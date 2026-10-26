#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py — Servidor local (Flask) que sirve la interfaz web de MemorIA2GO
y ejecuta los scripts del pipeline por debajo.

Uso:
  python launcher.py                     # puerto 8765, abre el navegador
  python launcher.py --port 80           # para http://m3m0ria/ sin puerto (con entrada en hosts)
  python launcher.py --no-browser        # no abre el navegador (servicio / tarea programada)

Abre el navegador solo en http://127.0.0.1:8765 (salvo --no-browser)

Endpoints:
  GET  /                      -> interfaz web
  GET  /api/config            -> config actual (memoria_config.yaml)
  POST /api/config            -> guarda config (parche in-place, preserva comentarios)
  GET  /api/stats             -> estadisticas del base_vault configurado
  GET  /api/gizmos-pendientes -> gizmos sin nombrar del ultimo import
  POST /api/gizmos            -> guarda nombres, parchea RAW_VAULT in-place
  GET  /api/run                -> SSE, lanza el pipeline completo con log en vivo
  GET  /api/run?from_merge=1  -> SSE, salta el paso 1 (usado tras /api/gizmos)
  GET  /api/pendientes         -> pendientes de descarga por proveedor (Herramientas → Taller)
  POST /api/pendientes/registrar -> da de alta un pendiente descargado a mano (upload)
  POST /api/pendientes/descartar -> marca un pendiente (web o generación) como descartado
  POST /api/reindex            -> relanza paso4_indices sin reprocesar (Herramientas → Taller)
  POST /api/substack/verify    -> qué trae el export de Substack y qué NO (Tintero)
  POST /api/substack/build     -> construye el vault de Tintero desde el export
  GET  /api/galerias           -> estado de las dos galerias (Herramientas → Galerias)
  POST /api/galerias/<cual>/generar -> genera la galeria con log en vivo y la abre en el navegador
  POST /api/galerias/<cual>/abrir   -> abre la ultima galeria generada
  GET  /api/taller             -> estado de las herramientas del Taller (Herramientas → Taller)
  GET  /api/taller/avisos      -> avisos de "imagen no disponible" que quedan (lento la 1a vez)
  POST /api/taller/recuperar   -> recuperar_imagenes.py con log en vivo (simular o aplicar)
  POST /api/taller/recuperar/deshacer -> deshace la ultima pasada aplicada
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, Response, send_from_directory

# Identidad de un pendiente separada de su llave -- ver pendientes.py.
from pendientes import ref_pendiente, ref_de_entrada, sanear
import layout

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"
CONFIG_PATH = HERE / "memoria_config.yaml"
PORT = 8765

sys.path.insert(0, str(HERE))

app = Flask(__name__)
run_lock = threading.Lock()


@app.before_request
def _fijar_layout_activo():
    """Deja el layout del vault en el entorno del proceso antes de CADA peticion.

    Los modulos que el launcher importa (orphan_cloud, vault_stats...) y los
    procesos que lanza leen el layout de ahi. Se recalcula cada vez y SIN mirar
    el entorno que dejo la peticion anterior (usar_entorno=False): si el layout
    del vault cambia en disco -- una migracion --, la siguiente peticion ya lo
    ve, sin reiniciar. Sin config o sin vault, queda el clasico."""
    try:
        from config_loader import load_config, get_path, get_opt
        cfg = load_config(str(CONFIG_PATH))
        base = get_path(cfg, "base_vault")
        raw_cfg = get_path(cfg, "raw_vault")
        lay = layout.cargar(base, get_opt(cfg, "prj_vault_name", None), usar_entorno=False,
                            raw_vault=str(raw_cfg) if raw_cfg else None,
                            preset=get_opt(cfg, "layout_preset", None))
        os.environ.update(layout.entorno(lay))
    except Exception:
        os.environ.pop(layout.ENV_LAYOUT, None)

# ─────────────────────────────────────────
# Config: lectura via config_loader, escritura como parche in-place
# (yaml.dump normal destruiria los comentarios que ya tiene el archivo)
# ─────────────────────────────────────────

def read_config() -> dict:
    from config_loader import load_config
    if not CONFIG_PATH.exists():
        return {"paths": {"base_vault": "", "exports_dir": "", "gizmo_map": ""},
                "options": {"prj_vault_name": layout.CLASICO.rel("prj"), "by_year": True, "by_month": True,
                            "make_index": True, "keep_hashes": False, "dry_run": False,
                            "theme": "warm"}}
    cfg = load_config(str(CONFIG_PATH))
    # Convierte Path a str para que sea serializable en JSON
    return json.loads(json.dumps(cfg, default=str))


def patch_config_yaml(updates: dict) -> None:
    """Reescribe solo el valor de las claves conocidas, preservando comentarios
    y el resto del archivo. Mismo principio que patch_gizmo_map.py: parche
    in-place, no reescritura completa."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"No existe {CONFIG_PATH}")

    text = CONFIG_PATH.read_text(encoding="utf-8-sig")
    lines = text.split("\n")

    def _yaml_val(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "''"
        return f"'{v}'"

    vistas = set()
    ultima_de_paths = None
    ultima_de_options = None
    en_paths = False
    en_options = False
    for i, line in enumerate(lines):
        if re.match(r"^paths\s*:", line):
            en_paths, en_options = True, False
            continue
        if re.match(r"^options\s*:", line):
            en_paths, en_options = False, True
            continue
        if re.match(r"^[A-Za-z_]+\s*:", line):
            en_paths, en_options = False, False
        m = re.match(r"^(\s*)([A-Za-z_]+)\s*:", line)
        if not m:
            continue
        indent, key = m.group(1), m.group(2)
        if en_paths:
            ultima_de_paths = i
        if en_options:
            ultima_de_options = i
        if key not in updates:
            continue
        vistas.add(key)
        lines[i] = f"{indent}{key}: {_yaml_val(updates[key])}"

    # Claves que el archivo todavia no tiene. Sin esto la interfaz guardaba
    # en silencio: el bucle de arriba solo reescribe lineas EXISTENTES, asi
    # que una ruta nueva (substack_vault en una config anterior a Tintero) se
    # perdia sin un solo aviso. Se añaden al final del bloque adecuado
    # preservando el resto del archivo. Reglas:
    #   - claves *_vault/_dir/_map/_backup -> bloque `paths:`
    #   - resto de claves no vistas -> bloque `options:` (theme, y cualquier
    #     opcion futura que se añada por la UI antes de tocar la plantilla).
    nuevas_paths = [k for k in updates if k not in vistas and k.endswith(("_vault", "_dir", "_map", "_backup"))]
    if nuevas_paths and ultima_de_paths is not None:
        bloque = [f"  {k}: {_yaml_val(updates[k])}" for k in nuevas_paths]
        lines[ultima_de_paths + 1:ultima_de_paths + 1] = bloque
        # ultima_de_options se corre hacia abajo tantas lineas como acabamos
        # de insertar, si estaba mas abajo que ultima_de_paths.
        if ultima_de_options is not None and ultima_de_options > ultima_de_paths:
            ultima_de_options += len(bloque)

    nuevas_opts = [k for k in updates if k not in vistas and k not in nuevas_paths]
    if nuevas_opts and ultima_de_options is not None:
        bloque = [f"  {k}: {_yaml_val(updates[k])}" for k in nuevas_opts]
        lines[ultima_de_options + 1:ultima_de_options + 1] = bloque

    CONFIG_PATH.write_text("\n".join(lines), encoding="utf-8", newline="")


# ─────────────────────────────────────────
# Rutas estaticas
# ─────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEB_DIR, filename)


# ─────────────────────────────────────────
# API: configuracion
# ─────────────────────────────────────────

@app.route("/api/browse")
def api_browse():
    """Devuelve subdirectorios del path indicado, para autocompletar rutas
    en la configuracion desde el navegador via <datalist>. Solo lectura,
    solo listado, jamas contenidos: no expone ningun archivo del disco.

    Comportamiento estilo "Ejecutar" de Windows:
    - path='' o inexistente -> raices (letras de unidad en Windows,
      '/' en Linux)
    - path que existe y es carpeta -> sus subdirectorios inmediatos
    - path que existe pero no es carpeta -> subdirectorios del padre
      (permite seguir tecleando tras una ruta a fichero)
    - path que no existe pero su padre si -> subdirectorios del padre
      filtrados por el prefijo (el completado en vivo mientras escribes)
    """
    q = (request.args.get("path") or "").strip()
    # Extensiones de fichero a incluir, si el campo lo pide (ej. gizmo_map).
    # Sin este parametro, solo se sugieren directorios (comportamiento por defecto).
    ext_filter = (request.args.get("ext") or "").strip().lower()
    ext_incluidas = [e if e.startswith(".") else "." + e
                     for e in ext_filter.split(",") if e.strip()]
    try:
        # Raices del sistema
        if not q:
            if os.name == "nt":
                import string
                raices = [f"{L}:\\" for L in string.ascii_uppercase
                          if Path(f"{L}:\\").exists()]
            else:
                raices = ["/"]
            return jsonify({"opciones": raices})

        p = Path(q)
        if p.is_dir():
            base, prefijo = p, ""
        elif p.parent.is_dir():
            # Ruta a medio escribir: sugerir dentro del padre filtrando
            base, prefijo = p.parent, p.name.lower()
        else:
            return jsonify({"opciones": []})

        opciones = []
        for child in base.iterdir():
            try:
                if child.name.startswith("."):
                    continue
                if child.is_dir():
                    if not prefijo or child.name.lower().startswith(prefijo):
                        opciones.append(str(child))
                elif ext_incluidas and child.is_file():
                    if child.suffix.lower() in ext_incluidas:
                        if not prefijo or child.name.lower().startswith(prefijo):
                            opciones.append(str(child))
            except OSError:
                continue
        opciones.sort(key=str.lower)
        return jsonify({"opciones": opciones[:50]})
    except Exception as e:
        return jsonify({"opciones": [], "error": str(e)}), 200


def _conflictos_de_preset(preset: str, updates: dict | None = None) -> list:
    """Por que el vault de la config NO admite `preset` (vacia = se puede). Los
    valores de `updates`, si vienen, mandan sobre los de la config guardada: es la
    config que se esta a punto de escribir."""
    from config_loader import load_config, get_path, get_opt
    cfg = load_config(str(CONFIG_PATH)) if CONFIG_PATH.exists() else {"paths": {}, "options": {}}
    updates = updates or {}
    base = updates.get("base_vault") or get_path(cfg, "base_vault")
    if not base:
        return []
    raw = updates.get("raw_vault") if "raw_vault" in updates else get_path(cfg, "raw_vault")
    prj = updates.get("prj_vault_name") or get_opt(cfg, "prj_vault_name", None)
    pedido = layout.pedido(base, prj, str(raw) if raw else None, preset)
    return layout.conflictos(base, pedido)


@app.route("/api/layout/presets")
def layout_presets():
    """Los presets de organizacion del vault y, de cada uno, por que NO se puede
    elegir ahora (vacio = se puede). Un vault con notas fusionadas no cambia de
    organizacion sin migrarlo, y la interfaz lo dice en vez de dejar elegir y
    fallar despues."""
    try:
        from config_loader import load_config, get_path, get_opt
        cfg = load_config(str(CONFIG_PATH)) if CONFIG_PATH.exists() else {"paths": {}, "options": {}}
        base = get_path(cfg, "base_vault")
        marcador = layout.leer_marcador(base) if base and Path(base).is_dir() else None
        presets = []
        for nombre, (particion, proyectos) in layout.PRESETS.items():
            motivo = _conflictos_de_preset(nombre) if base and Path(base).is_dir() else []
            presets.append({"id": nombre, "particion": particion, "proyectos": proyectos,
                            "conflictos": motivo})
        return jsonify({
            "presets": presets,
            "configurado": layout.normalizar_preset(get_opt(cfg, "layout_preset", None)),
            "del_vault": layout.normalizar_preset(marcador.preset) if marcador and marcador.preset in
                         (*layout.PRESETS, "clasico") else None,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["GET"])
def get_config():
    try:
        return jsonify(read_config())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["POST"])
def set_config():
    # silent=True: sin el, un cuerpo vacio o un JSON roto lanzaba y salia
    # por el except generico como 500. Con el, llega {} y lo rechaza la
    # validacion de cada endpoint con su mensaje. Un 400 que explica vale
    # mas que un 500 que no.
    data = request.get_json(force=True, silent=True) or {}
    updates = {}
    updates.update(data.get("paths", {}))
    updates.update(data.get("options", {}))
    # Un preset que el vault no admite no se guarda: el pipeline se negaria a
    # arrancar despues, y es mejor decirlo aqui, junto al campo, que en un log.
    if updates.get("layout_preset"):
        try:
            motivo = _conflictos_de_preset(updates["layout_preset"], updates)
        except layout.LayoutError as e:
            motivo = [str(e)]
        if motivo:
            return jsonify({"error": " ".join(motivo)}), 400
    try:
        patch_config_yaml(updates)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: estadisticas
# ─────────────────────────────────────────

# ─────────────────────────────────────────
# API: MUSIC·0LOGY — herramienta hermana, pipeline propio, misma casa.
#
# Es el UNICO sitio de la app que sale a Internet, y lo hace solo cuando le
# pones un token en la mano y pulsas. La regla de producto ("el pipeline
# nunca hace peticiones de red salientes") sigue en pie: no es el pipeline,
# y no es por iniciativa propia.
# ─────────────────────────────────────────

def _suno_script(nombre: str) -> Path:
    return HERE / "suno" / nombre


@app.route("/api/suno/backup", methods=["POST"])
def suno_backup():
    """Descarga la biblioteca. POST con streaming (no SSE por GET) porque el
    token viaja en el cuerpo: en una query string acabaria en el historial
    del navegador y en cualquier log de acceso.

    Los tokens se pasan al hijo por ENTORNO, no por argv. Un Bearer de Clerk
    da acceso a la cuenta entera mientras dura, y argv es visible en la
    lista de procesos del sistema para cualquiera que mire.
    """
    data = request.get_json(force=True, silent=True) or {}
    token = (data.get("token") or "").strip()
    # browser-token: la API de Suno lo pedia cuando se escribio el script,
    # pero en la practica (verificado por V0ra sobre su biblioteca entera) el
    # Bearer basta. Se retiro de la interfaz para no doblar la dificultad del
    # paso mas dificil; el endpoint lo sigue aceptando y backup_suno.py lo
    # sigue soportando por CLI, como via de escape si Suno vuelve a exigirlo.
    browser_token = (data.get("browser_token") or "").strip()
    if not token:
        return jsonify({"error": "Falta el Bearer token"}), 400

    from config_loader import load_config, get_path
    cfg = load_config(str(CONFIG_PATH))
    backup = get_path(cfg, "suno_backup")
    if not backup:
        return jsonify({"error": "Configura primero la carpeta del backup (suno_backup)"}), 400

    if not run_lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una ejecucion en curso"}), 409

    def generate():
        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "SUNO_TOKEN": token}
            if browser_token:
                env["SUNO_BROWSER_TOKEN"] = browser_token
            proc = subprocess.Popen(
                [sys.executable, str(_suno_script("backup_suno.py")), "--out", str(backup)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
            )
            # Censura de salida: el log va EN VIVO a la pantalla, y de ahi a
            # una captura compartida hay un paso. Hoy backup_suno.py no
            # imprime los tokens, pero un print de depuracion anadido con
            # prisa manana si podria -- esto lo ataja en la frontera en vez
            # de confiar en que nadie se equivoque nunca. Hay un test que lo
            # comprueba simulando un script que los escupe.
            secretos = [s for s in (token, browser_token) if s and len(s) > 8]
            for line in proc.stdout:
                limpia = line.rstrip()
                for s in secretos:
                    limpia = limpia.replace(s, "[token oculto]")
                yield limpia + "\n"
            proc.wait()
            yield f"__DONE__ {proc.returncode}\n"
        except Exception as e:
            yield f"__ERROR__ {e}\n"
        finally:
            run_lock.release()

    return Response(generate(), mimetype="text/plain",
                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _suno_run(script: str, args: list) -> tuple:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(_suno_script(script))] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=1800, env=env,
    )
    salida = (result.stdout or "") + (result.stderr or "")
    return result.returncode, salida.strip()


@app.route("/api/suno/verify", methods=["POST"])
def suno_verify():
    """Cruza los IDs de _index.json contra los ficheros reales. La pasada que
    confirma que el backup esta integro ANTES de construir el vault."""
    try:
        from config_loader import load_config, get_path
        backup = get_path(load_config(str(CONFIG_PATH)), "suno_backup")
        if not backup:
            return jsonify({"error": "Configura primero la carpeta del backup (suno_backup)"}), 400
        code, salida = _suno_run("verify_backup.py", ["--backup-dir", str(backup)])
        return jsonify({"ok": code == 0, "salida": salida[-4000:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/suno/build", methods=["POST"])
def suno_build():
    try:
        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        backup = get_path(cfg, "suno_backup")
        vault = get_path(cfg, "suno_vault")
        if not backup:
            return jsonify({"error": "Configura primero la carpeta del backup (suno_backup)"}), 400
        if not vault:
            return jsonify({"error": "Configura primero el vault de musica (suno_vault)"}), 400
        code, salida = _suno_run("build_suno_vault.py",
                                  ["--backup-dir", str(backup), "--vault-dir", str(vault)])
        if code != 0:
            return jsonify({"error": salida[-500:] or "fallo al construir el vault"}), 500
        return jsonify({"ok": True, "salida": salida[-4000:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: MUSIC·0LOGY / Flow Music — la segunda fuente de musica.
#
# Mismo pipeline que Suno (capturar, verificar, construir) contra otra API,
# la de Riffusion. Endpoints separados en vez de un parametro `fuente` en
# los de Suno: los scripts son distintos, las rutas de configuracion son
# distintas, y meter un if por proveedor en un endpoint que hoy funciona es
# como se rompen las cosas que ya iban bien.
# ─────────────────────────────────────────

def _flowmusic_script(nombre: str) -> Path:
    return HERE / "flowmusic" / nombre


@app.route("/api/flowmusic/backup", methods=["POST"])
def flowmusic_backup():
    """Descarga la biblioteca de Flow Music. Igual que la de Suno: POST con
    streaming porque el token viaja en el cuerpo, y al hijo se le pasa por
    ENTORNO, nunca por argv (argv se ve en la lista de procesos).

    Flow Music necesita UNA sola cabecera, `Authorization`. Confirmado por
    ablacion sobre las 16 que manda el navegador. No hay equivalente al
    browser-token de Suno.
    """
    data = request.get_json(force=True, silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"error": "Falta el Bearer token"}), 400
    # Chrome trunca los valores largos del panel Headers con una elipsis. Si
    # el token la trae, las cabeceras HTTP (latin-1) revientan dentro de
    # http.client con un traceback que no dice nada. Mejor atajarlo aqui.
    if "…" in token:
        return jsonify({"error": "El token viene cortado (contiene «…»). Copialo "
                                  "con «Copy as cURL», no del panel Headers."}), 400

    from config_loader import load_config, get_path
    cfg = load_config(str(CONFIG_PATH))
    backup = get_path(cfg, "flowmusic_backup")
    if not backup:
        return jsonify({"error": "Configura primero la carpeta del backup (flowmusic_backup)"}), 400

    formatos = (data.get("formatos") or "m4a,wav").strip()

    if not run_lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una ejecucion en curso"}), 409

    def generate():
        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "FLOWMUSIC_TOKEN": token}
            proc = subprocess.Popen(
                [sys.executable, str(_flowmusic_script("backup_flowmusic.py")),
                 "--out", str(backup), "--formats", formatos],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
            )
            # Misma censura que en Suno: el log va en vivo a la pantalla y de
            # ahi a una captura compartida hay un paso.
            for line in proc.stdout:
                limpia = line.rstrip()
                if len(token) > 8:
                    limpia = limpia.replace(token, "[token oculto]")
                yield limpia + "\n"
            proc.wait()
            yield f"__DONE__ {proc.returncode}\n"
        except Exception as e:
            yield f"__ERROR__ {e}\n"
        finally:
            run_lock.release()

    return Response(generate(), mimetype="text/plain",
                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/copilot_images/backup", methods=["POST"])
def copilot_images_backup():
    """Descarga la biblioteca de imagenes de Copilot, con su prompt y fechas.
    Mismo patron que Flow Music: token en el cuerpo, al hijo por ENTORNO
    (nunca argv) y censurado en el log en vivo. Solo hace falta la cabecera
    `Authorization` de la peticion `Artifact.ashx` (ver el script)."""
    data = request.get_json(force=True, silent=True) or {}
    token = (data.get("token") or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        return jsonify({"error": "Falta el Bearer token"}), 400
    if "…" in token:
        return jsonify({"error": "El token viene cortado (contiene «…»). Copialo "
                                  "con «Copy as cURL», no del panel Headers."}), 400

    from config_loader import load_config, get_path
    cfg = load_config(str(CONFIG_PATH))
    backup = get_path(cfg, "copilot_images_backup")
    if not backup:
        return jsonify({"error": "Configura primero la carpeta del backup (copilot_images_backup)"}), 400

    if not run_lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una ejecucion en curso"}), 409

    def generate():
        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "COPILOT_TOKEN": token}
            proc = subprocess.Popen(
                [sys.executable, str(HERE / "copilot_images" / "backup_copilot_images.py"),
                 "--out", str(backup)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
            )
            for line in proc.stdout:
                limpia = line.rstrip()
                if len(token) > 8:
                    limpia = limpia.replace(token, "[token oculto]")
                yield limpia + "\n"
            proc.wait()
            yield f"__DONE__ {proc.returncode}\n"
        except Exception as e:
            yield f"__ERROR__ {e}\n"
        finally:
            run_lock.release()

    return Response(generate(), mimetype="text/plain",
                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _copilot_images_run(script: str, args: list) -> tuple:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(HERE / "copilot_images" / script)] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=1800, env=env,
    )
    return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()


@app.route("/api/copilot_images/verify", methods=["POST"])
def copilot_images_verify():
    try:
        from config_loader import load_config, get_path
        backup = get_path(load_config(str(CONFIG_PATH)), "copilot_images_backup")
        if not backup:
            return jsonify({"error": "Configura primero la carpeta del backup (copilot_images_backup)"}), 400
        code, salida = _copilot_images_run("verify_copilot_images.py", ["--backup-dir", str(backup)])
        return jsonify({"ok": code == 0, "salida": salida[-4000:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/copilot_images/build", methods=["POST"])
def copilot_images_build():
    try:
        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        backup = get_path(cfg, "copilot_images_backup")
        vault = get_path(cfg, "copilot_images_vault")
        if not backup:
            return jsonify({"error": "Configura primero la carpeta del backup (copilot_images_backup)"}), 400
        if not vault:
            return jsonify({"error": "Configura primero el vault de imagenes de Copilot (copilot_images_vault)"}), 400
        code, salida = _copilot_images_run("build_copilot_images_vault.py",
                                            ["--backup-dir", str(backup), "--vault-dir", str(vault)])
        if code != 0:
            return jsonify({"error": salida[-500:] or "fallo al construir el vault"}), 500
        return jsonify({"ok": True, "salida": salida[-4000:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _grok_dir():
    """Carpeta GROK del vault, derivada de base_vault igual que rescue_pending.py."""
    from config_loader import load_config, get_path
    base = get_path(load_config(str(CONFIG_PATH)), "base_vault")
    return layout.cargar(base).ruta(base, "grok.raiz") if base else None


@app.route("/api/grok_imagine/backup", methods=["POST"])
def grok_imagine_backup():
    """Baja la biblioteca de Grok Imagine al banco GROK/IMAGINE. Mismo patron
    que el resto de capturas, pero la credencial es la COOKIE de sesion de
    grok.com, no un Bearer que caduca: da acceso completo a la cuenta. Va en
    el cuerpo, al hijo por ENTORNO (nunca argv) y se censura en el log en
    vivo."""
    data = request.get_json(force=True, silent=True) or {}
    cookie = (data.get("cookie") or "").strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()
    if not cookie:
        return jsonify({"error": "Falta la cookie de grok.com"}), 400
    if "…" in cookie:
        return jsonify({"error": "La cookie viene cortada (contiene «…»). Copia el valor "
                                  "entero de la cabecera Cookie."}), 400
    try:
        cookie.encode("latin-1")
    except UnicodeEncodeError:
        return jsonify({"error": "La cookie tiene caracteres que no caben en una cabecera HTTP."}), 400

    grok = _grok_dir()
    if not grok:
        return jsonify({"error": "Configura primero la carpeta base del vault (base_vault)"}), 400
    if not grok.is_dir():
        return jsonify({"error": f"No existe la carpeta GROK: {grok}"}), 400

    if not run_lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una ejecucion en curso"}), 409

    def generate():
        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "GROK_COOKIE": cookie}
            proc = subprocess.Popen(
                [sys.executable, str(HERE / "grok_imagine" / "backup_grok_imagine.py"),
                 "--grok-dir", str(grok)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
            )
            for line in proc.stdout:
                limpia = line.rstrip()
                if len(cookie) > 8:
                    limpia = limpia.replace(cookie, "[cookie oculta]")
                yield limpia + "\n"
            proc.wait()
            yield f"__DONE__ {proc.returncode}\n"
        except Exception as e:
            yield f"__ERROR__ {e}\n"
        finally:
            run_lock.release()

    return Response(generate(), mimetype="text/plain",
                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/grok_imagine/verify", methods=["POST"])
def grok_imagine_verify():
    try:
        grok = _grok_dir()
        if not grok:
            return jsonify({"error": "Configura primero la carpeta base del vault (base_vault)"}), 400
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        result = subprocess.run(
            [sys.executable, str(HERE / "grok_imagine" / "verify_grok_imagine.py"),
             "--grok-dir", str(grok)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, env=env,
        )
        salida = ((result.stdout or "") + (result.stderr or "")).strip()
        return jsonify({"ok": result.returncode == 0, "salida": salida[-4000:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _flowmusic_run(script: str, args: list) -> tuple:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(_flowmusic_script(script))] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=1800, env=env,
    )
    salida = (result.stdout or "") + (result.stderr or "")
    return result.returncode, salida.strip()


@app.route("/api/flowmusic/verify", methods=["POST"])
def flowmusic_verify():
    try:
        from config_loader import load_config, get_path
        backup = get_path(load_config(str(CONFIG_PATH)), "flowmusic_backup")
        if not backup:
            return jsonify({"error": "Configura primero la carpeta del backup (flowmusic_backup)"}), 400
        code, salida = _flowmusic_run("verify_flowmusic.py", ["--backup-dir", str(backup)])
        return jsonify({"ok": code == 0, "salida": salida[-4000:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/flowmusic/build", methods=["POST"])
def flowmusic_build():
    try:
        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        backup = get_path(cfg, "flowmusic_backup")
        vault = get_path(cfg, "flowmusic_vault")
        if not backup:
            return jsonify({"error": "Configura primero la carpeta del backup (flowmusic_backup)"}), 400
        if not vault:
            return jsonify({"error": "Configura primero el vault de Flow Music (flowmusic_vault)"}), 400
        code, salida = _flowmusic_run("build_flowmusic_vault.py",
                                       ["--backup-dir", str(backup), "--vault-dir", str(vault)])
        if code != 0:
            return jsonify({"error": salida[-500:] or "fallo al construir el vault"}), 500
        return jsonify({"ok": True, "salida": salida[-4000:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: Tintero — la otra herramienta hermana.
#
# A diferencia de MUSIC·0LOGY, esta NO sale a Internet: Substack SI tiene
# export, y el zip entra por exports_dir como cualquier otro fichero quieto.
# Lo que pasa es que el pipeline conversacional lo RECHAZA a proposito (un
# post no es un dialogo, ver el guard en preflight.validate_export_file) y
# esta puerta lo recoge. Misma carpeta de entrada, dos puertas distintas.
# ─────────────────────────────────────────

def _substack_script(nombre: str) -> Path:
    return HERE / "substack" / nombre


def _substack_run(script: str, args: list) -> tuple:
    # PYTHONIOENCODING a la fuerza: la consola de Windows viene en cp1252 y
    # los titulos de V0ra llevan acentos y simbolos. Mismo patron que _suno_run.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(_substack_script(script))] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=1800, env=env,
    )
    salida = (result.stdout or "") + (result.stderr or "")
    return result.returncode, salida.strip()


# El CSV de estadisticas de cada publicacion lo localiza el propio constructor
# (substack/build_substack_vault.py: localizar_stats), emparejandolo por el slug
# que lleva el nombre. Aqui ya no se elige UNO: con varias publicaciones eso
# daba el CSV de una a todas.


@app.route("/api/substack/verify", methods=["POST"])
def substack_verify():
    """Lo que hay, lo que cruza, lo que se ignora y lo que NO viene.

    No lanza subproceso: lee del zip y devuelve numeros, que es lo que la
    tarjeta necesita. El subproceso se reserva para construir."""
    try:
        from config_loader import load_config, get_path
        from substack_stats import verificar_export
        cfg = load_config(str(CONFIG_PATH))
        exports = get_path(cfg, "exports_dir")
        if not exports:
            return jsonify({"error": "Configura primero la carpeta de exports"}), 400
        datos = verificar_export(exports, vault=get_path(cfg, "substack_vault"))
        if not datos.get("encontrado"):
            return jsonify({"error": "No hay ningun export de Substack en la carpeta de exports. "
                                     "Descargalo desde los ajustes de tu publicacion y dejalo ahi."}), 404
        return jsonify(datos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/substack/build", methods=["POST"])
def substack_build():
    try:
        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        exports = get_path(cfg, "exports_dir")
        vault = get_path(cfg, "substack_vault")
        if not exports:
            return jsonify({"error": "Configura primero la carpeta de exports"}), 400
        if not vault:
            return jsonify({"error": "Configura primero el vault de Tintero (substack_vault)"}), 400
        args = ["--exports-dir", str(exports), "--vault-dir", str(vault)]
        cuerpo = request.get_json(silent=True) or {}
        if cuerpo.get("dry_run"):
            args.append("--dry-run")
        if cuerpo.get("permitir_legado"):
            args.append("--permitir-legado")
        code, salida = _substack_run("build_substack_vault.py", args)
        if code != 0:
            return jsonify({"error": salida[-800:] or "fallo al construir el vault"}), 500
        return jsonify({"ok": True, "salida": salida[-4000:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/substack/migrar", methods=["POST"])
def substack_migrar():
    """Mueve el layout antiguo (un solo export) de la raiz del vault a la carpeta de su
    publicacion. Sin `aplicar` solo devuelve el plan: es lo que ve el usuario antes de
    confirmar. No borra nada; la publicacion se deduce de los post_id de las notas."""
    try:
        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        exports = get_path(cfg, "exports_dir")
        vault = get_path(cfg, "substack_vault")
        if not exports:
            return jsonify({"error": "Configura primero la carpeta de exports"}), 400
        if not vault:
            return jsonify({"error": "Configura primero el vault de Tintero (substack_vault)"}), 400
        cuerpo = request.get_json(silent=True) or {}
        aplicar = bool(cuerpo.get("aplicar"))
        args = ["--migrar-legado", "--exports-dir", str(exports), "--vault-dir", str(vault)]
        if aplicar:
            args.append("--aplicar")
        if cuerpo.get("publicacion"):
            args += ["--publicacion", str(cuerpo["publicacion"])]
        code, salida = _substack_run("build_substack_vault.py", args)
        if code != 0:
            return jsonify({"error": salida[-800:] or "fallo al migrar"}), 400
        return jsonify({"ok": True, "aplicado": aplicar, "salida": salida[-4000:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: Herramientas → Galerias
# ─────────────────────────────────────────
# Las dos galerias son complementos (galeria.py, galeria_tintero.py): la app solo las lanza, ensena su
# log en vivo y, al terminar, las abre en el navegador predeterminado -- una pagina servida por la app
# no puede abrir un fichero local, y el lanzador corre en el mismo equipo (decision de V0ra 2026-10-23).
GALERIAS = {
    # cual: (script, ruta de la configuracion de la que cuelga, opcion del script para esa ruta)
    "imagenes": ("galeria.py", "base_vault", "--base-vault"),
    "tintero": ("galeria_tintero.py", "substack_vault", "--vault"),
}
CARPETA_GALERIA = ".galeria"


def _carpeta_galeria(cual: str):
    """(carpeta de la galeria, None) o (None, mensaje de error) si falta su ruta en la configuracion."""
    from config_loader import load_config, get_path
    ruta = get_path(load_config(str(CONFIG_PATH)), GALERIAS[cual][1])
    if not ruta:
        return None, f"Configura primero {GALERIAS[cual][1]}"
    return Path(ruta) / CARPETA_GALERIA, None


def _abrir_en_navegador(pagina: Path) -> None:
    webbrowser.open(Path(pagina).resolve().as_uri())


@app.route("/api/galerias")
def galerias_estado():
    """El estado de cada galeria para su titulo plegado: si se puede generar, si existe y lo que dice su
    estado.json (cuando se genero y cuanto lleva). Nunca abre la pagina, que pesa cientos de MB."""
    out = {}
    for cual in GALERIAS:
        try:
            carpeta, falta = _carpeta_galeria(cual)
        except Exception as e:
            out[cual] = {"error": str(e)}
            continue
        if falta:
            out[cual] = {"falta": falta}
            continue
        pagina = carpeta / "index.html"
        info = {"existe": pagina.is_file()}
        try:
            info.update(json.loads((carpeta / "estado.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            # Una galeria de antes de que existiera estado.json: la fecha de la pagina, y sin
            # recuentos -- mejor no decir cuantas lleva que decir cero.
            if info["existe"]:
                info["generada"] = datetime.fromtimestamp(pagina.stat().st_mtime).isoformat(timespec="seconds")
        out[cual] = info
    return jsonify(out)


@app.route("/api/galerias/<cual>/generar", methods=["POST"])
def galerias_generar(cual):
    if cual not in GALERIAS:
        return jsonify({"error": "galeria desconocida"}), 404
    try:
        carpeta, falta = _carpeta_galeria(cual)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if falta:
        return jsonify({"error": falta}), 400
    script, clave, opcion = GALERIAS[cual]
    args = [sys.executable, str(HERE / script), opcion, str(carpeta.parent)]
    if cual == "tintero" and (request.get_json(silent=True) or {}).get("sin_red"):
        args.append("--sin-red")
    if not run_lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una ejecucion en curso"}), 409

    def generate():
        try:
            # MEMORIA_CONFIG: la misma configuracion que usa la app (el vault de Copilot sale de ahi).
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "MEMORIA_CONFIG": str(CONFIG_PATH)}
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1, env=env)
            for line in proc.stdout:
                yield line.rstrip() + "\n"
            proc.wait()
            if proc.returncode == 0 and (carpeta / "index.html").is_file():
                _abrir_en_navegador(carpeta / "index.html")
                yield "Abierta en tu navegador.\n"
            yield f"__DONE__ {proc.returncode}\n"
        except Exception as e:
            yield f"__ERROR__ {e}\n"
        finally:
            run_lock.release()

    return Response(generate(), mimetype="text/plain",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/galerias/<cual>/abrir", methods=["POST"])
def galerias_abrir(cual):
    if cual not in GALERIAS:
        return jsonify({"error": "galeria desconocida"}), 404
    try:
        carpeta, falta = _carpeta_galeria(cual)
        if falta:
            return jsonify({"error": falta}), 400
        pagina = carpeta / "index.html"
        if not pagina.is_file():
            return jsonify({"error": "Todavia no la has generado"}), 404
        _abrir_en_navegador(pagina)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: Herramientas → Taller
# ─────────────────────────────────────────
# Reparaciones y puestas al dia que no piden reprocesar. Cada herramienta es un plegable con su estado
# en el titulo; aqui se calcula ese estado. El de "Recuperar imagenes" va aparte (/api/taller/avisos):
# contar los avisos es leer todas las notas (55 s en el vault real), asi que se calcula una vez, se
# recuerda, y solo se vuelve a contar tras aplicar o deshacer, que es cuando cambia.
_avisos_cache: dict = {}
_avisos_lock = threading.Lock()
# Donde recuperar_imagenes.py deja sus copias de seguridad, y donde "deshacer" las busca. Variable de
# modulo a proposito: los tests la apuntan a una carpeta temporal y nunca ven las copias reales.
LOGS_DIR = HERE / "logs"
PREFIJO_COPIA_RECUPERAR = "recuperar_imagenes_"
MARCA_DESHECHA = "deshecho.json"          # dentro de una copia ya deshecha: "deshacer la ultima" la salta


def _cfg_rutas():
    from config_loader import load_config, get_path
    cfg = load_config(str(CONFIG_PATH))
    return {k: get_path(cfg, k) for k in ("base_vault", "exports_dir", "substack_vault")}


def _exports_chatgpt(exports_dir) -> list:
    """Los zips de ChatGPT de la carpeta de exports, el mas reciente primero. Se reconocen con la misma
    deteccion que la Verificacion (solo lee el indice del zip, no lo descomprime)."""
    from preflight import validate_export_file
    if not exports_dir or not Path(exports_dir).is_dir():
        return []
    salida = []
    for z in Path(exports_dir).glob("*.zip"):
        # Solo los dos formatos de ChatGPT que traen imagenes. "chatgpt_zip_html" (el degradado, solo
        # HTML) no las trae, y ademas es como se clasifica hoy el frames-000.zip del export nuevo de Claude.
        if validate_export_file(z).get("tipo") not in ("chatgpt_zip", "chatgpt_zip_fragmentado"):
            continue
        m = re.search(r"(\d{4}-\d{2}-\d{2})", z.name)
        fecha = m.group(1) if m else datetime.fromtimestamp(z.stat().st_mtime).strftime("%Y-%m-%d")
        salida.append({"ruta": str(z), "nombre": z.name, "fecha": fecha, "mb": round(z.stat().st_size / 1048576)})
    return sorted(salida, key=lambda e: (e["fecha"], e["nombre"]), reverse=True)


def _copias_recuperar() -> list:
    """Las copias de seguridad de recuperar_imagenes.py que aun se pueden deshacer, la mas reciente primero."""
    if not LOGS_DIR.is_dir():
        return []
    copias = [c for c in LOGS_DIR.iterdir() if c.is_dir() and c.name.startswith(PREFIJO_COPIA_RECUPERAR)
              and (c / "diario.json").is_file() and not (c / MARCA_DESHECHA).exists()]
    return sorted(copias, key=lambda c: c.name, reverse=True)


def _describir_copia(copia: Path) -> dict:
    """Que desharia "Deshacer la ultima": su fecha (del nombre) y de que pasada es."""
    m = re.match(PREFIJO_COPIA_RECUPERAR + r"(\d{8})_(\d{6})(_\w+)?$", copia.name)
    fecha = (datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").isoformat(timespec="seconds")
             if m else None)
    tipo = {"_biblioteca": "biblioteca", "_metadatos": "metadatos"}.get(m.group(3) if m else None, "avisos")
    return {"nombre": copia.name, "fecha": fecha, "tipo": tipo}


@app.route("/api/taller")
def taller_estado():
    """El estado de cada herramienta del Taller para su titulo plegado (menos los avisos, que van aparte)."""
    try:
        rutas = _cfg_rutas()
        base, exports, sv = rutas["base_vault"], rutas["exports_dir"], rutas["substack_vault"]
        copias = _copias_recuperar()
        out = {"recuperar": {"exports": _exports_chatgpt(exports),
                             "deshacer": _describir_copia(copias[0]) if copias else None}}
        if not base:
            out["recuperar"]["falta"] = "Configura primero base_vault"
        # Indices: la fecha de _tree_index.md, que el paso 4 reescribe siempre. Si una recuperacion de
        # imagenes cambio notas despues, los indices se han quedado viejos.
        arbol = layout.cargar(base).ruta(base, "merged") / "_tree_index.md" if base else None
        if arbol and arbol.is_file():
            fecha = arbol.stat().st_mtime
            ultima_rep = max((c.stat().st_mtime for c in copias), default=0)
            out["indices"] = {"fecha": datetime.fromtimestamp(fecha).isoformat(timespec="seconds"),
                              "viejos": ultima_rep > fecha}
        else:
            out["indices"] = {"fecha": None}
        # Tintero: la misma regla que el aviso de la verificacion (layout de un solo export en la raiz
        # y varias publicaciones, o el vault ya organizado por publicaciones).
        if sv and exports:
            from substack_stats import bsv
            legado = bsv.layout_antiguo(sv)
            pubs, _ = bsv.exports_por_publicacion(Path(exports))
            out["tintero"] = {"hace_falta": bool(legado) and (len(pubs) > 1 or bsv.ya_por_publicaciones(sv)),
                              "legado": legado}
        else:
            out["tintero"] = {"falta": "Configura primero substack_vault"}
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/taller/avisos")
def taller_avisos():
    """{avisos, imagenes}: los avisos de 'imagen no disponible en el export' que quedan en las notas.
    Lento la primera vez (lee todas las notas); despues, de memoria hasta que algo los cambie."""
    try:
        base = _cfg_rutas()["base_vault"]
        if not base:
            return jsonify({"falta": "Configura primero base_vault"})
        with _avisos_lock:
            if _avisos_cache.get("base") != str(base):
                import recuperar_imagenes as rec
                por_puntero, _, _ = rec.buscar_avisos(Path(base))
                _avisos_cache.update(base=str(base), avisos=sum(len(v) for v in por_puntero.values()),
                                     imagenes=len(por_puntero))
            return jsonify({"avisos": _avisos_cache["avisos"], "imagenes": _avisos_cache["imagenes"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/taller/recuperar", methods=["POST"])
def taller_recuperar():
    """recuperar_imagenes.py con su log en vivo. Sin `aplicar`, simulacion (no escribe nada)."""
    cuerpo = request.get_json(silent=True) or {}
    rutas = _cfg_rutas()
    base = rutas["base_vault"]
    if not base:
        return jsonify({"error": "Configura primero base_vault"}), 400
    # Solo un export de la lista: la ruta no se acepta tal cual del cliente.
    validos = {e["ruta"]: e for e in _exports_chatgpt(rutas["exports_dir"])}
    export = str(cuerpo.get("export") or "")
    if export not in validos:
        return jsonify({"error": "Elige un export de ChatGPT de tu carpeta de exports"}), 400
    aplicar = bool(cuerpo.get("aplicar"))
    args = [sys.executable, str(HERE / "recuperar_imagenes.py"), "--export", export, "--base-vault", str(base),
            "--logs", str(LOGS_DIR)]
    if cuerpo.get("biblioteca"):
        args.append("--biblioteca")
    if aplicar:
        args.append("--aplicar")
    if not run_lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una ejecucion en curso"}), 409

    def generate():
        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "MEMORIA_CONFIG": str(CONFIG_PATH)}
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1, env=env)
            for line in proc.stdout:
                # La ultima linea habla de --aplicar y de --deshacer (linea de ordenes): aqui estan los botones.
                if "--aplicar." in line or "python recuperar_imagenes.py --deshacer" in line:
                    continue
                yield line.rstrip() + "\n"
            proc.wait()
            if aplicar:
                _avisos_cache.clear()          # las notas han cambiado: se vuelven a contar
            yield f"__DONE__ {proc.returncode}\n"
        except Exception as e:
            yield f"__ERROR__ {e}\n"
        finally:
            run_lock.release()

    return Response(generate(), mimetype="text/plain",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/taller/recuperar/deshacer", methods=["POST"])
def taller_recuperar_deshacer():
    """Deshace la ultima pasada con --aplicar: restaura sus notas desde su copia y la marca como deshecha
    (no la borra). Pulsar otra vez deshace la anterior, en orden inverso, que es el orden correcto."""
    copias = _copias_recuperar()
    if not copias:
        return jsonify({"error": "No hay nada que deshacer"}), 404
    if not run_lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una ejecucion en curso"}), 409
    try:
        import recuperar_imagenes as rec
        copia = copias[0]
        n = rec.deshacer(copia, log=lambda *_: None)
        (copia / MARCA_DESHECHA).write_text(json.dumps({"deshecho": datetime.now().isoformat(timespec="seconds"),
                                                        "notas": n}), encoding="utf-8")
        _avisos_cache.clear()
        return jsonify({"ok": True, "copia": copia.name, "notas": n})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        run_lock.release()


def _con_substack(stats: dict, cfg: dict) -> dict:
    """Añade la tarjeta de Tintero al payload del dashboard.

    Lee del EXPORT, nunca del vault construido: tiene que funcionar justo
    despues de descargar el zip y antes de construir nada. Si no hay export
    en la carpeta, la clave no viaja y la tarjeta no se pinta -- no se pinta
    a cero, misma regla que la de musica.
    """
    try:
        from config_loader import get_path
        from substack_stats import compute_substack_stats
        exports = get_path(cfg, "exports_dir")
        if not exports:
            return stats
        datos = compute_substack_stats(exports)
        if datos:
            stats = {**stats, "substack": datos}
    except Exception:
        pass  # el dashboard entero no puede caerse por una tarjeta
    return stats


def _con_suno(stats: dict, cfg: dict) -> dict:
    """Añade las stats de MUSIC·0LOGY al payload del dashboard.

    Se calculan EN VIVO, deliberadamente fuera del cache de vault_stats.
    Ese cache lo escribe el paso 4 del pipeline, y la biblioteca de Suno
    cambia por su cuenta -- se descarga con otra herramienta, en otro
    momento. Cachearla ahí la dejaría rancia justo cuando más quieres
    mirarla: recién terminado un backup.

    Medido sobre la biblioteca real de V0ra (2094 pistas, _index.json de
    12 MB): 120 ms. Barato de sobra frente a montar una segunda capa de
    cache con su propia invalidación, que es donde se cuelan los errores
    que no avisan.

    Si no hay ruta configurada o no hay backup, la clave sencillamente no
    viaja y la tarjeta no se pinta -- no se pinta a cero, que sería mentir
    sobre una biblioteca que no se ha descargado.
    """
    try:
        from config_loader import get_path
        from suno_stats import compute_suno_stats
        backup = get_path(cfg, "suno_backup")
        if not backup:
            return stats
        suno = compute_suno_stats(backup)
        if suno:
            stats = {**stats, "suno": suno}
    except Exception:
        pass  # el dashboard entero no puede caerse por la tarjeta de música
    return stats


def _con_flowmusic(stats: dict, cfg: dict) -> dict:
    """Añade las stats de Flow Music al payload, misma regla que _con_suno.

    En vivo y fuera del cache por lo mismo: la biblioteca cambia por su
    cuenta, con otra herramienta y en otro momento. Aquí es aún más barato
    que en Suno — el _index.json son 174 pistas, no 2094.

    Si no hay ruta o no hay backup, la clave no viaja y la sección no se
    pinta. No se pinta a cero: eso sería mentir sobre una biblioteca que no
    se ha descargado.
    """
    try:
        from config_loader import get_path
        from flowmusic_stats import compute_flowmusic_stats
        backup = get_path(cfg, "flowmusic_backup")
        if not backup:
            return stats
        flow = compute_flowmusic_stats(backup)
        if flow:
            stats = {**stats, "flowmusic": flow}
    except Exception:
        pass  # el dashboard entero no puede caerse por una tarjeta
    return stats


def _con_musica(stats: dict, cfg: dict) -> dict:
    """Las dos fuentes de MUSIC·0LOGY. Envoltorio para no repetir el par en
    los dos puntos de salida de get_stats()."""
    return _con_flowmusic(_con_suno(stats, cfg), cfg)


@app.route("/api/stats")
def get_stats():
    try:
        from config_loader import load_config, get_path, get_opt
        from vault_stats import compute_stats, load_cache, save_cache
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault no configurado"}), 400
        # Configurado pero inexistente NO es lo mismo que sin configurar, y
        # hasta hoy se notaba en que este endpoint reventaba con un 500 y un
        # errno crudo: el calculo de estadisticas intenta escribir su cache
        # DENTRO del vault. Quien acaba de instalar y aun no ha creado la
        # carpeta, o la escribio mal, veia "[Errno 2] No such file or
        # directory: ...\.m3m0ria_stats.json.tmp" en el Observatorio.
        if not Path(base_vault).is_dir():
            return jsonify({"error": f"la carpeta base no existe: {base_vault}"}), 400
        prj_name = get_opt(cfg, "prj_vault_name", None)

        # Cache primero: lo escribe el paso 4 del pipeline. ?refresh=1 fuerza
        # recalculo (util tras tocar el vault a mano). Si el cache falta o
        # esta corrupto, se recalcula y se re-escribe: nadie se queda sin
        # dashboard, solo paga el escaneo completo una vez.
        if request.args.get("refresh") != "1":
            cached = load_cache(Path(base_vault))
            if cached is not None:
                return jsonify(_con_substack(_con_musica(cached, cfg), cfg))
        stats = compute_stats(Path(base_vault), prj_name)  # None = el del layout
        save_cache(Path(base_vault), stats)
        return jsonify(_con_substack(_con_musica(stats, cfg), cfg))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: nube de huerfanas (Fase 1, solo lectura)
# ─────────────────────────────────────────

@app.route("/api/orphan-cloud")
def orphan_cloud_api():
    try:
        from config_loader import load_config, get_path, get_opt
        from orphan_cloud import build_cloud
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault no configurado"}), 400
        prj_name = get_opt(cfg, "prj_vault_name", None)
        # Las tres fuentes de siembra del vocabulario de proyectos:
        # carpetas de PRJ_VAULT + gizmo_map.json + projects de los exports
        gizmo_map = get_path(cfg, "gizmo_map")
        exports_dir = get_path(cfg, "exports_dir")
        return jsonify(build_cloud(
            Path(base_vault), prj_name,
            gizmo_map_path=Path(gizmo_map) if gizmo_map else None,
            exports_dir=Path(exports_dir) if exports_dir else None,
        ))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orphan-cloud/notes")
def orphan_cloud_notes_api():
    try:
        from config_loader import load_config, get_path
        from orphan_cloud import notes_for_term
        term = (request.args.get("term") or "").strip()
        if not term:
            return jsonify({"error": "falta el parametro term"}), 400
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault no configurado"}), 400
        return jsonify(notes_for_term(Path(base_vault), term))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/topics", methods=["GET"])
def get_topics():
    try:
        from orphan_cloud import load_topic_map
        return jsonify({"temas": load_topic_map(HERE / "topic_map.json")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/topics", methods=["POST"])
def save_topics():
    try:
        data = request.get_json(force=True, silent=True) or {}
        # La clave tiene que venir. Sin esto, un POST malformado -- o un
        # cuerpo vacio -- escribia {} y se llevaba por delante todos los
        # temas curados a mano, respondiendo "ok". La interfaz manda siempre
        # {temas}, asi que exigirlo no quita nada: solo distingue "no quedan
        # temas" de "la peticion venia rota".
        if "temas" not in data:
            return jsonify({"error": "falta 'temas' en la peticion"}), 400
        temas = data.get("temas") or {}
        limpio = {
            str(k).strip(): [str(w).strip() for w in v if str(w).strip()]
            for k, v in temas.items()
            if isinstance(v, list) and str(k).strip()
        }
        p = HERE / "topic_map.json"
        # Copia antes de pisar. Este fichero es curaduria pura, de meses, y
        # no lo reconstruye ningun reproceso: si se pierde, se perdio. El
        # pacto de la casa vale tambien para lo que escribe la interfaz.
        if p.exists():
            try:
                shutil.copy2(p, p.with_name(p.name + ".bak"))
            except OSError:
                pass
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(limpio, ensure_ascii=False, indent=2),
                       encoding="utf-8", newline="\n")
        tmp.replace(p)
        return jsonify({"ok": True, "temas": len(limpio)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/topics/generate", methods=["POST"])
def generate_topics():
    try:
        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault no configurado"}), 400
        # Subproceso en vez de import: el generador se relee del disco en
        # cada pulsacion. Mata la clase entera de bugs de "launcher con
        # modulo cacheado tras actualizar el codigo", que ya mordio tres
        # veces en este proyecto.
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        result = subprocess.run(
            [sys.executable, str(HERE / "orphan_cloud.py"), str(base_vault),
             "--generate-topics", "--topic-map", str(HERE / "topic_map.json")],
            capture_output=True, text=True, encoding="utf-8",
            timeout=600, env=env,
        )
        if result.returncode != 0:
            detalle = (result.stderr or "").strip()[-400:] or "fallo el generador (sin stderr)"
            return jsonify({"error": detalle}), 500
        return jsonify(json.loads(result.stdout))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: gizmos huerfanos
# ─────────────────────────────────────────

@app.route("/api/gizmos-pendientes")
def get_gizmos_pendientes():
    try:
        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({})
        path = layout.cargar(base_vault).ruta(base_vault, "raw") / "_gizmos_pendientes.json"
        if not path.exists():
            return jsonify({})
        with open(path, "r", encoding="utf-8-sig") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/gizmos", methods=["POST"])
def post_gizmos():
    """Recibe {gizmo_id_normalizado: nombre, ...} (solo los que el usuario
    rellen\u00f3), actualiza gizmo_map.json y parchea RAW_VAULT in-place.
    No relanza el pipeline aqui -- eso lo hace el front llamando a
    /api/run?from_merge=1 despues, para que el log en vivo sea uno solo."""
    data = request.get_json(force=True, silent=True) or {}
    filled = {gid: name.strip() for gid, name in data.items() if name and name.strip()}
    if not filled:
        return jsonify({"ok": True, "patched": 0, "note": "nada que guardar"})

    try:
        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        gizmo_map_path = get_path(cfg, "gizmo_map") or (HERE / "gizmo_map.json")

        existing = {}
        if gizmo_map_path.exists():
            with open(gizmo_map_path, "r", encoding="utf-8-sig") as f:
                existing = json.load(f)
        for gid, name in filled.items():
            existing[f"g-{gid}"] = name
        gizmo_map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(gizmo_map_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        raw_vault = layout.cargar(base_vault).ruta(base_vault, "raw")
        result = subprocess.run(
            [sys.executable, str(HERE / "patch_gizmo_map.py"), str(raw_vault), str(gizmo_map_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return jsonify({"ok": True, "patched": len(filled), "patch_output": result.stdout})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: Taller — pendientes de descarga de Grok + regenerar índices
# ─────────────────────────────────────────

def _ruta_pendientes(base_vault, proveedor: str):
    """Cada proveedor tiene su propia lista de pendientes, con forma
    distinta -- ver _leer_pendientes."""
    clave = "grok.pendientes" if proveedor == "grok" else "chatgpt.pendientes"
    return layout.cargar(base_vault).ruta(base_vault, clave)


def _leer_pendientes(base_vault, proveedor: str) -> list:
    """Tolerante: sin fichero o corrupto, lista vacia. No poder listar
    pendientes no debe tumbar la pestaña entera."""
    path = _ruta_pendientes(base_vault, proveedor)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            datos = json.load(f)
        return datos if isinstance(datos, list) else []
    except Exception:
        return []


def _buscar_pendiente(pendientes: list, proveedor: str, credencial: str):
    """La entrada cuya identidad corresponde a esa credencial.

    Se compara por `ref` (ver pendientes.py): las entradas ya triadas no
    guardan su credencial, asi que buscarlas por ella no las encontraria. El
    navegador manda la credencial porque es lo que tiene a mano en la lista de
    las SIN triar, que si la conservan; aqui se hashea para buscar.
    """
    r = ref_pendiente(credencial)
    return next((p for p in pendientes
                 if (p.get("ref") or ref_de_entrada(p, proveedor)) == r), None)


def _escribir_pendientes(base_vault, proveedor: str, datos: list) -> None:
    """Escritura atomica via tmp+replace: un corte a mitad no deja el
    triaje de V0ra en un JSON roto.

    Sanea antes de escribir: toda salida de aqui lleva `ref` y ninguna entrada
    triada conserva su enlace de descarga."""
    sanear(datos, proveedor)
    path = _ruta_pendientes(base_vault, proveedor)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                   encoding="utf-8", newline="\n")
    tmp.replace(path)


@app.route("/api/pendientes")
def get_pendientes():
    """Pendientes de los dos proveedores, agrupados. Ojo: NO tienen la
    misma forma, porque son cosas distintas:

    - grok    -- generaciones propias de V0ra en Imagine cuyo binario no
                 viaja en el zip. Clave `id`.
    - chatgpt -- imagenes de busqueda web (de terceros) que ChatGPT mostro
                 en la conversacion. Clave `url`.

    Los dos usan el mismo modelo de estados: las entradas ya triadas se
    quedan en el fichero (el pipeline las necesita) pero no se listan aqui.
    Sin `estado` = sin triar, para no romper ficheros ya existentes.
    """
    try:
        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"grok": [], "chatgpt": []})
        sin_triar = lambda ps: [p for p in ps
                                if (p.get("estado") or "sin_triar") == "sin_triar"]
        return jsonify({
            "grok": sin_triar(_leer_pendientes(base_vault, "grok")),
            "chatgpt": sin_triar(_leer_pendientes(base_vault, "chatgpt")),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/pendientes/descartar", methods=["POST"])
def descartar_pendiente():
    """Marca un pendiente como irrelevante SIN borrarlo. El descarte se guarda
    como `estado` en el JSON (no en la nota) para que sobreviva a los
    reprocesos: la nota se regenera y el paso 1 vuelve a leer este estado para
    dejar la marca discreta en su sitio.

    Vale para los dos proveedores, con el mismo modelo de estados desde b8a9c82
    (la entrada se CONSERVA marcada, nunca se borra), pero por motivos
    distintos: en ChatGPT descarta ruido de busqueda ajeno; en Grok,
    generaciones propias de V0ra que ya no quiere ver en la lista. La credencial
    llega por `url` (ChatGPT) o `id` (Grok) segun cual sea la clave del
    proveedor -- ver get_pendientes()."""
    try:
        datos_req = request.get_json(force=True, silent=True) or {}
        proveedor = (datos_req.get("proveedor") or "chatgpt").strip().lower()
        if proveedor not in ("chatgpt", "grok"):
            return jsonify({"error": "proveedor desconocido"}), 400
        credencial = (datos_req.get("url") or datos_req.get("id") or "").strip()
        if not credencial:
            return jsonify({"error": "falta la credencial del pendiente"}), 400

        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault no configurado"}), 400

        pendientes = _leer_pendientes(base_vault, proveedor)
        entrada = _buscar_pendiente(pendientes, proveedor, credencial)
        if entrada is None:
            return jsonify({"error": "ese pendiente ya no esta en la lista"}), 404

        entrada["estado"] = "descartada"
        _escribir_pendientes(base_vault, proveedor, pendientes)
        restantes = sum(1 for p in pendientes
                        if (p.get("estado") or "sin_triar") == "sin_triar")
        return jsonify({"ok": True, "restantes": restantes})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/pendientes/registrar", methods=["POST"])
def registrar_pendiente():
    """Da de alta a mano un pendiente de Grok que V0ra descargó fuera de la
    app (el pipeline nunca descarga solo). Recibe el fichero por upload en
    vez de una ruta a mano: evita mal-archivar en el banco equivocado.
    Mismo esquema hash+extension que usa la extraccion automatica
    (split_chatgpt_export.py) para que el resultado sea indistinguible."""
    try:
        proveedor = (request.form.get("proveedor") or "grok").strip().lower()
        archivo = request.files.get("file")
        if not archivo:
            return jsonify({"error": "falta file"}), 400

        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault no configurado"}), 400

        if proveedor == "chatgpt":
            return _registrar_imagen_web(base_vault, request.form.get("url"), archivo)

        pendiente_id = request.form.get("id")
        if not pendiente_id:
            return jsonify({"error": "falta id"}), 400

        pendientes = _leer_pendientes(base_vault, "grok")
        if not pendientes:
            return jsonify({"error": "no hay pendientes registrados"}), 404

        pendiente = _buscar_pendiente(pendientes, "grok", pendiente_id)
        if pendiente is None:
            return jsonify({"error": "ese pendiente ya no existe (¿ya se registró?)"}), 404

        data = archivo.read()
        if not data:
            return jsonify({"error": "el fichero subido está vacío"}), 400

        import hashlib
        from split_chatgpt_export import sniff_ext

        media_type = pendiente.get("media_type")
        clave_banco = "grok.generadas_video" if media_type == "video" else "grok.generadas_imagen"
        bank_dir = layout.cargar(base_vault).ruta(base_vault, clave_banco)
        bank_dir.mkdir(parents=True, exist_ok=True)

        fname = f"{hashlib.sha1(data).hexdigest()[:16]}{sniff_ext(data)}"
        dest = bank_dir / fname
        if not dest.exists():
            dest.write_bytes(data)

        manifest_path = bank_dir / "_image_manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
        manifest[fname] = {
            "origen": "generada",
            "prompt": pendiente.get("prompt"),
            "media_type": media_type,
            "create_time": pendiente.get("create_time"),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        # La entrada se CONSERVA marcada como rescatada, no se borra.
        # Bug real (2026-07-28): borrarla hacia que el siguiente
        # --reprocess-all la volviera a listar, porque
        # process_grok_media_posts la re-anade al no encontrar el binario
        # en el zip (que sigue sin estar: por eso era un pendiente). Con la
        # entrada presente, la fusion de split_chatgpt_export.py la ve en
        # `vistos` y no la duplica. Mismo modelo de estados que ChatGPT.
        pendiente["estado"] = "rescatada"
        pendiente["fichero"] = fname
        # _escribir_pendientes sanea: al quedar triada, esta entrada pierde su
        # `id` y su `link` y conserva solo el `ref`.
        _escribir_pendientes(base_vault, "grok", pendientes)

        restantes = sum(1 for p in pendientes
                        if (p.get("estado") or "sin_triar") == "sin_triar")
        return jsonify({"ok": True, "fname": fname, "restantes": restantes})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _registrar_imagen_web(base_vault, url: str, archivo) -> "Response":
    """Rescata una imagen de busqueda web de ChatGPT al banco CHATGPT/WEB.

    Banco propio a proposito (decision V0ra 2026-07-27): no encaja en
    GENERADAS (no la genero la IA) ni en ADJUNTOS (no la subio V0ra) --
    son referencias web de terceros, categoria distinta.

    A diferencia de Grok, la entrada NO se borra de la lista: se marca
    `rescatada` con el nombre de fichero, porque el paso 1 lee ese dato en
    cada reproceso para pintar la imagen real en la nota. Borrarla haria
    que el siguiente reproceso la volviera a listar como sin triar y se
    perderia el rescate."""
    url = (url or "").strip()
    if not url:
        return jsonify({"error": "falta url"}), 400

    pendientes = _leer_pendientes(base_vault, "chatgpt")
    entrada = _buscar_pendiente(pendientes, "chatgpt", url)
    if entrada is None:
        return jsonify({"error": "esa imagen ya no esta en la lista"}), 404

    data = archivo.read()
    if not data:
        return jsonify({"error": "el fichero subido está vacío"}), 400

    import hashlib
    from split_chatgpt_export import sniff_ext

    bank_dir = layout.cargar(base_vault).ruta(base_vault, "chatgpt.web")
    bank_dir.mkdir(parents=True, exist_ok=True)
    # Mismo esquema hash+extension que la extraccion automatica, para que
    # el resultado sea indistinguible de un asset extraido del export.
    fname = f"{hashlib.sha1(data).hexdigest()[:16]}{sniff_ext(data)}"
    dest = bank_dir / fname
    if not dest.exists():
        dest.write_bytes(data)

    manifest_path = bank_dir / "_image_manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    manifest[fname] = {
        "origen": "web",
        "url_original": url,
        "queries": entrada.get("queries") or [],
        "conversaciones": entrada.get("conversaciones") or [],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    entrada["estado"] = "rescatada"
    entrada["fichero"] = fname
    _escribir_pendientes(base_vault, "chatgpt", pendientes)

    restantes = sum(1 for p in pendientes
                    if (p.get("estado") or "sin_triar") == "sin_triar")
    return jsonify({"ok": True, "fname": fname, "restantes": restantes})


@app.route("/api/reindex", methods=["POST"])
def reindex():
    """Relanza paso4_indices via subprocess (no import: el codigo se relee
    del disco en cada pulsacion, mismo criterio que /api/topics/generate).
    Barato frente a un reproceso completo -- solo toca MERGED_VAULT/PRJ_VAULT
    ya existentes, no re-importa desde los exports."""
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        result = subprocess.run(
            [sys.executable, str(HERE / "MemorIA2GO.py"),
             "--config", str(CONFIG_PATH), "--yes", "--no-wizard", "--reindex-only"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, env=env, stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            detalle = (result.stderr or result.stdout or "").strip()[-500:] or "fallo la regeneracion (sin salida)"
            return jsonify({"error": detalle}), 500
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: sesiones locales de Claude Code / Codex (herramienta hermana, a mano)
# ─────────────────────────────────────────

@app.route("/api/sessions/status")
def sessions_status():
    """Cuantas sesiones de agente hay ya en el vault. Para la tarjeta del
    Observatorio. Barato: cuenta los .jsonl crudos de los dos bancos, que es
    lo que la ingesta preserva (uno por sesion ingerida)."""
    try:
        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"claude_code": 0, "codex": 0, "total": 0})
        lay = layout.cargar(base_vault)
        d_cc = lay.ruta(base_vault, "sesiones.claude_code")
        d_cx = lay.ruta(base_vault, "sesiones.codex")
        cc = len(list(d_cc.glob("*.jsonl"))) if d_cc.exists() else 0
        cx = len(list(d_cx.glob("*.jsonl"))) if d_cx.exists() else 0
        return jsonify({"claude_code": cc, "codex": cx, "total": cc + cx})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/ingest", methods=["POST"])
def sessions_ingest():
    """Ingesta las sesiones locales de Claude Code y Codex al vault. A mano:
    el pipeline no lo hace. `nivel` (0-3) es el detalle del output de
    herramientas en las notas; la fuente cruda se preserva igual sea cual sea.
    La sesion en curso se omite (su captura seria parcial)."""
    try:
        datos = request.get_json(force=True, silent=True) or {}
        try:
            nivel = int(datos.get("nivel", 2))
        except (TypeError, ValueError):
            nivel = 2
        nivel = max(0, min(3, nivel))

        from config_loader import load_config, get_path
        import session_ingest as si
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault no configurado"}), 400

        total = {"sesiones": 0, "vacias": 0, "notas": 0, "activa_omitida": 0}
        for carpeta in si._carpetas_por_defecto():
            st = si.ingest_dir(carpeta, base_vault, nivel=nivel, log=lambda *a: None)
            for k in total:
                total[k] += st.get(k, 0)
        return jsonify({"ok": True, **total})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: ejecutar pipeline (SSE, log en vivo)
# ─────────────────────────────────────────

# ───────────────────────────────────
# API: verificación previa (evita errores tipo conversations.json ausente,
# descubiertos hasta ahora en mitad del paso 1)
# ───────────────────────────────────

@app.route("/api/verificar")
def get_verificar():
    try:
        from config_loader import load_config, get_path
        from preflight import validate_config
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        exports_dir = get_path(cfg, "exports_dir")
        gizmo_map = get_path(cfg, "gizmo_map")
        # deep=1 activa el muestreo de deriva de formato (detect_new_keys),
        # que parsea el JSON completo de cada export -- caro en exports
        # grandes. Solo se pide explicitamente desde el boton "Verificar
        # ahora", nunca desde el poll automatico del badge al cambiar de tab.
        deep = request.args.get("deep") == "1"
        report = validate_config(
            str(base_vault) if base_vault else None,
            str(exports_dir) if exports_dir else None,
            str(gizmo_map) if gizmo_map else None,
            deep=deep,
        )
        return jsonify(report)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/run")
def run_pipeline():
    from_merge = request.args.get("from_merge") == "1"
    reprocess_all = request.args.get("reprocess_all") == "1"

    if not run_lock.acquire(blocking=False):
        return jsonify({"error": "Ya hay una ejecucion en curso"}), 409

    def generate():
        try:
            # --no-wizard y stdin cerrado: nada lanzado desde aqui puede
            # quedarse esperando a que alguien escriba en una consola que no
            # existe. Con DEVNULL, un input() perdido da EOF y muere; sin el,
            # se cuelga para siempre y la web solo muestra un log que no
            # avanza.
            cmd = [sys.executable, str(HERE / "MemorIA2GO.py"),
                   "--config", str(CONFIG_PATH), "--yes", "--no-wizard"]
            if from_merge:
                cmd.append("--from-merge")
            if reprocess_all:
                cmd.append("--reprocess-all")

            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
            )
            for line in proc.stdout:
                yield f"data: {line.rstrip()}\n\n"
            proc.wait()
            yield f"event: done\ndata: {proc.returncode}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {str(e)}\n\n"
        finally:
            run_lock.release()

    return Response(generate(), mimetype="text/event-stream",
                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def main():
    ap = argparse.ArgumentParser(description="Servidor local de M3M0R.IA (MemorIA2GO).")
    ap.add_argument("--port", type=int, default=PORT,
                    help=f"Puerto de escucha (por defecto {PORT}; usa 80 para URL sin puerto)")
    ap.add_argument("--no-browser", action="store_true",
                    help="No abrir el navegador al arrancar (uso como servicio o tarea programada)")
    args = ap.parse_args()

    sufijo = "" if args.port == 80 else f":{args.port}"
    url = f"http://127.0.0.1{sufijo}"
    print(f"M3M0R.IA corriendo en {url}")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
