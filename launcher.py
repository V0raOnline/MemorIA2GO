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

    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)([A-Za-z_]+)\s*:", line)
        if not m:
            continue
        indent, key = m.group(1), m.group(2)
        if key not in updates:
            continue
        v = updates[key]
        if isinstance(v, bool):
            val_str = "true" if v else "false"
        elif v is None:
            val_str = "''"
        else:
            val_str = f"'{v}'"
        lines[i] = f"{indent}{key}: {val_str}"

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
                return jsonify(_con_suno(cached, cfg))
        stats = compute_stats(Path(base_vault), prj_name)
        save_cache(Path(base_vault), stats)
        return jsonify(_con_suno(stats, cfg))
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
             "--config", str(CONFIG_PATH), "--yes", "--reindex-only"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, env=env,
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
            cmd = [sys.executable, str(HERE / "MemorIA2GO.py"),
                   "--config", str(CONFIG_PATH), "--yes"]
            if from_merge:
                cmd.append("--from-merge")
            if reprocess_all:
                cmd.append("--reprocess-all")

            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
