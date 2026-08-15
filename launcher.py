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
  GET  /api/pendientes         -> pendientes de descarga por proveedor (Reconexión)
  POST /api/pendientes/registrar -> da de alta un pendiente descargado a mano (upload)
  POST /api/pendientes/descartar -> marca una imagen web como irrelevante
  POST /api/reindex            -> relanza paso4_indices sin reprocesar (Reconexión)
  GET  /api/layout             -> ¿el vault usa el layout español? (pinta la card o no)
  POST /api/layout/migrate     -> renombra el layout al inglés y reengancha enlaces
  POST /api/substack/verify    -> qué trae el export de Substack y qué NO (Inkwell)
  POST /api/substack/build     -> construye el vault de Inkwell desde el export
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, Response, send_from_directory

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"
CONFIG_PATH = HERE / "memoria_config.yaml"
PORT = 8765

sys.path.insert(0, str(HERE))

app = Flask(__name__)
run_lock = threading.Lock()

# ─────────────────────────────────────────
# Config: lectura via config_loader, escritura como parche in-place
# (yaml.dump normal destruiria los comentarios que ya tiene el archivo)
# ─────────────────────────────────────────

def read_config() -> dict:
    from config_loader import load_config
    if not CONFIG_PATH.exists():
        return {"paths": {"base_vault": "", "exports_dir": "", "gizmo_map": ""},
                "options": {"prj_vault_name": "PRJ_VAULT", "by_year": True, "by_month": True,
                            "make_index": True, "keep_hashes": False, "dry_run": False}}
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
    en_paths = False
    for i, line in enumerate(lines):
        if re.match(r"^paths\s*:", line):
            en_paths = True
            continue
        if re.match(r"^[A-Za-z_]+\s*:", line):
            en_paths = False
        m = re.match(r"^(\s*)([A-Za-z_]+)\s*:", line)
        if not m:
            continue
        indent, key = m.group(1), m.group(2)
        if en_paths:
            ultima_de_paths = i
        if key not in updates:
            continue
        vistas.add(key)
        lines[i] = f"{indent}{key}: {_yaml_val(updates[key])}"

    # Claves que el archivo todavia no tiene. Sin esto la interfaz guardaba
    # en silencio: el bucle de arriba solo reescribe lineas EXISTENTES, asi
    # que una ruta nueva (substack_vault en una config anterior a Tintero) se
    # perdia sin un solo aviso. Se añaden al final del bloque `paths:`, que es
    # donde viven todas las rutas, preservando el resto del archivo.
    nuevas = [k for k in updates if k not in vistas and k.endswith(("_vault", "_dir", "_map", "_backup"))]
    if nuevas and ultima_de_paths is not None:
        bloque = [f"  {k}: {_yaml_val(updates[k])}" for k in nuevas]
        lines[ultima_de_paths + 1:ultima_de_paths + 1] = bloque

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


@app.route("/api/config", methods=["GET"])
def get_config():
    try:
        return jsonify(read_config())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.get_json(force=True) or {}
    updates = {}
    updates.update(data.get("paths", {}))
    updates.update(data.get("options", {}))
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
    data = request.get_json(force=True) or {}
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
            return jsonify({"error": salida[-500:] or "failed to build the vault"}), 500
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
    data = request.get_json(force=True) or {}
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


# ─────────────────────────────────────────
# API: Inkwell — la otra herramienta hermana.
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


def _stats_csv_en(exports_dir) -> Path:
    """Localiza el CSV de estadisticas dentro de la carpeta de exports. Se
    coge el mas reciente por nombre: el fichero lleva la fecha dentro
    (v0raonline_email_stats_AAAA-MM-DD.csv) y cada descarga sobreescribe la
    foto anterior, asi que el ultimo es el bueno.

    Se busca por contenido de cabecera, no por nombre a secas: en esa
    carpeta puede haber otros CSV y meter uno equivocado daria un cruce
    silencioso de 0 filas, que es peor que no encontrarlo."""
    if not exports_dir:
        return None
    candidatos = []
    for p in sorted(Path(exports_dir).glob("*.csv"), reverse=True):
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                cabecera = f.readline()
        except OSError:
            continue
        if "title" in cabecera and "post_date" in cabecera and "section_name" in cabecera:
            candidatos.append(p)
    return candidatos[0] if candidatos else None


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
            return jsonify({"error": "Configure the exports folder first"}), 400
        datos = verificar_export(exports, _stats_csv_en(exports))
        if not datos.get("encontrado"):
            return jsonify({"error": "No Substack export found in the exports folder. "
                                     "Download it from your publication settings and drop it there."}), 404
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
            return jsonify({"error": "Configure the exports folder first"}), 400
        if not vault:
            return jsonify({"error": "Configure the Inkwell vault first (substack_vault)"}), 400
        args = ["--exports-dir", str(exports), "--vault-dir", str(vault)]
        csv_stats = _stats_csv_en(exports)
        if csv_stats:
            args += ["--stats", str(csv_stats)]
        if (request.get_json(silent=True) or {}).get("dry_run"):
            args.append("--dry-run")
        code, salida = _substack_run("build_substack_vault.py", args)
        if code != 0:
            return jsonify({"error": salida[-500:] or "failed to build the vault"}), 500
        return jsonify({"ok": True, "salida": salida[-4000:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _con_substack(stats: dict, cfg: dict) -> dict:
    """Añade la tarjeta de Inkwell al payload del dashboard.

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
            return jsonify({"error": "base_vault is not configured"}), 400
        prj_name = get_opt(cfg, "prj_vault_name", "PRJ_VAULT")

        # Cache primero: lo escribe el paso 4 del pipeline. ?refresh=1 fuerza
        # recalculo (util tras tocar el vault a mano). Si el cache falta o
        # esta corrupto, se recalcula y se re-escribe: nadie se queda sin
        # dashboard, solo paga el escaneo completo una vez.
        if request.args.get("refresh") != "1":
            cached = load_cache(Path(base_vault))
            if cached is not None:
                return jsonify(_con_substack(_con_musica(cached, cfg), cfg))
        stats = compute_stats(Path(base_vault), prj_name)
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
            return jsonify({"error": "base_vault is not configured"}), 400
        prj_name = get_opt(cfg, "prj_vault_name", "PRJ_VAULT")
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
            return jsonify({"error": "missing term parameter"}), 400
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault is not configured"}), 400
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
        data = request.get_json(force=True) or {}
        temas = data.get("temas") or {}
        limpio = {
            str(k).strip(): [str(w).strip() for w in v if str(w).strip()]
            for k, v in temas.items()
            if isinstance(v, list) and str(k).strip()
        }
        p = HERE / "topic_map.json"
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
            return jsonify({"error": "base_vault is not configured"}), 400
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
            detalle = (result.stderr or "").strip()[-400:] or "the generator failed (no stderr)"
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
        path = base_vault / "RAW_VAULT" / "_gizmos_pendientes.json"
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
    data = request.get_json(force=True) or {}
    filled = {gid: name.strip() for gid, name in data.items() if name and name.strip()}
    if not filled:
        return jsonify({"ok": True, "patched": 0, "note": "nothing to save"})

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

        raw_vault = base_vault / "RAW_VAULT"
        result = subprocess.run(
            [sys.executable, str(HERE / "patch_gizmo_map.py"), str(raw_vault), str(gizmo_map_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return jsonify({"ok": True, "patched": len(filled), "patch_output": result.stdout})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# API: Reconexión — pendientes de descarga de Grok + regenerar índices
# ─────────────────────────────────────────

def _ruta_pendientes(base_vault, proveedor: str):
    """Cada proveedor tiene su propia lista de pendientes, con forma
    distinta -- ver _leer_pendientes."""
    carpeta = "GROK" if proveedor == "grok" else "CHATGPT"
    return base_vault / carpeta / "_pendientes_descarga.json"


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


def _escribir_pendientes(base_vault, proveedor: str, datos: list) -> None:
    """Escritura atomica via tmp+replace: un corte a mitad no deja el
    triaje de V0ra en un JSON roto."""
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
    """Marca una imagen de busqueda web como irrelevante. El descarte se
    guarda en el JSON (no en la nota) para que sobreviva a los reprocesos:
    la nota se regenera y el paso 1 vuelve a leer este estado para dejar
    la marca discreta en su sitio.

    Solo ChatGPT: los pendientes de Grok son generaciones propias de V0ra,
    no resultados de busqueda ajenos, y el descarte se diseño para el ruido
    de estos ultimos."""
    try:
        datos_req = request.get_json(force=True) or {}
        url = (datos_req.get("url") or "").strip()
        if not url:
            return jsonify({"error": "missing url"}), 400

        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault is not configured"}), 400

        pendientes = _leer_pendientes(base_vault, "chatgpt")
        entrada = next((p for p in pendientes if p.get("url") == url), None)
        if entrada is None:
            return jsonify({"error": "that image is no longer in the list"}), 404

        entrada["estado"] = "descartada"
        _escribir_pendientes(base_vault, "chatgpt", pendientes)
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
            return jsonify({"error": "missing file"}), 400

        from config_loader import load_config, get_path
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault is not configured"}), 400

        if proveedor == "chatgpt":
            return _registrar_imagen_web(base_vault, request.form.get("url"), archivo)

        pendiente_id = request.form.get("id")
        if not pendiente_id:
            return jsonify({"error": "missing id"}), 400

        pend_path = base_vault / "GROK" / "_pendientes_descarga.json"
        if not pend_path.exists():
            return jsonify({"error": "no pending downloads recorded"}), 404
        with open(pend_path, "r", encoding="utf-8-sig") as f:
            pendientes = json.load(f)

        pendiente = next((p for p in pendientes if p.get("id") == pendiente_id), None)
        if pendiente is None:
            return jsonify({"error": "that pending item no longer exists (already registered?)"}), 404

        data = archivo.read()
        if not data:
            return jsonify({"error": "the uploaded file is empty"}), 400

        import hashlib
        from split_chatgpt_export import sniff_ext

        media_type = pendiente.get("media_type")
        bank_name = "GENERATED_VIDEO" if media_type == "video" else "GENERATED_IMAGE"
        bank_dir = base_vault / "GROK" / bank_name
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
        tmp = pend_path.with_name(pend_path.name + ".tmp")
        tmp.write_text(json.dumps(pendientes, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        tmp.replace(pend_path)

        restantes = sum(1 for p in pendientes
                        if (p.get("estado") or "sin_triar") == "sin_triar")
        return jsonify({"ok": True, "fname": fname, "restantes": restantes})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _registrar_imagen_web(base_vault, url: str, archivo) -> "Response":
    """Rescata una imagen de busqueda web de ChatGPT al banco CHATGPT/WEB.

    Banco propio a proposito (decision V0ra 2026-07-27): no encaja en
    GENERATED (no la genero la IA) ni en ATTACHMENTS (no la subio V0ra) --
    son referencias web de terceros, categoria distinta.

    A diferencia de Grok, la entrada NO se borra de la lista: se marca
    `rescatada` con el nombre de fichero, porque el paso 1 lee ese dato en
    cada reproceso para pintar la imagen real en la nota. Borrarla haria
    que el siguiente reproceso la volviera a listar como sin triar y se
    perderia el rescate."""
    url = (url or "").strip()
    if not url:
        return jsonify({"error": "missing url"}), 400

    pendientes = _leer_pendientes(base_vault, "chatgpt")
    entrada = next((p for p in pendientes if p.get("url") == url), None)
    if entrada is None:
        return jsonify({"error": "that image is no longer in the list"}), 404

    data = archivo.read()
    if not data:
        return jsonify({"error": "the uploaded file is empty"}), 400

    import hashlib
    from split_chatgpt_export import sniff_ext

    bank_dir = base_vault / "CHATGPT" / "WEB"
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


@app.route("/api/layout")
def get_layout():
    """Estado del layout del vault: si esta construido con los nombres de
    carpeta de la edicion espanola, hace falta migrarlo. La card de
    Reconexion solo se pinta si esto dice que si, para que un usuario nuevo
    no vea un boton que no le sirve para nada (decision V0ra 2026-07-30).

    Barato a proposito -- solo stat de rutas -- porque se llama en cada
    carga de la pestana."""
    try:
        from config_loader import load_config, get_path
        import layout_migration
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault or not Path(base_vault).is_dir():
            return jsonify({"necesaria": False})
        return jsonify(layout_migration.detectar(Path(base_vault)))
    except Exception as e:
        # No poder comprobar el layout no debe tumbar la pestana entera:
        # el resto de Reconexion (pendientes, reindexar) sigue siendo util.
        return jsonify({"necesaria": False, "error": str(e)})


@app.route("/api/layout/migrate", methods=["POST"])
def post_layout_migrate():
    """Renombra el layout y reengancha los enlaces. Import directo (no
    subprocess como /api/reindex) porque devuelve un informe estructurado
    que la UI pinta, no un log."""
    try:
        from config_loader import load_config, get_path
        import layout_migration
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault or not Path(base_vault).is_dir():
            return jsonify({"error": "base_vault is not configured or does not exist"}), 400
        return jsonify({"ok": True, **layout_migration.migrar(Path(base_vault))})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
            detalle = (result.stderr or result.stdout or "").strip()[-500:] or "index rebuild failed (no output)"
            return jsonify({"error": detalle}), 500
        return jsonify({"ok": True})
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
        return jsonify({"error": "A run is already in progress"}), 409

    def generate():
        try:
            # --no-wizard y stdin cerrado: nada lanzado desde aqui puede
            # quedarse esperando a que alguien escriba en una consola que no
            # existe. Con DEVNULL un input() perdido da EOF y muere; sin el,
            # se cuelga para siempre y la web solo muestra un log parado.
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
    ap = argparse.ArgumentParser(description="Local server for M3M0R.IA (MemorIA2GO).")
    ap.add_argument("--port", type=int, default=PORT,
                    help=f"Listening port (default {PORT}; use 80 for a URL without a port)")
    ap.add_argument("--no-browser", action="store_true",
                    help="Do not open the browser on start (for service or scheduled-task use)")
    args = ap.parse_args()

    sufijo = "" if args.port == 80 else f":{args.port}"
    url = f"http://127.0.0.1{sufijo}"
    print(f"M3M0R.IA corriendo en {url}")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
