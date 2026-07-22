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

@app.route("/api/stats")
def get_stats():
    try:
        from config_loader import load_config, get_path, get_opt
        from vault_stats import compute_stats, load_cache, save_cache
        cfg = load_config(str(CONFIG_PATH))
        base_vault = get_path(cfg, "base_vault")
        if not base_vault:
            return jsonify({"error": "base_vault no configurado"}), 400
        prj_name = get_opt(cfg, "prj_vault_name", "PRJ_VAULT")

        # Cache primero: lo escribe el paso 4 del pipeline. ?refresh=1 fuerza
        # recalculo (util tras tocar el vault a mano). Si el cache falta o
        # esta corrupto, se recalcula y se re-escribe: nadie se queda sin
        # dashboard, solo paga el escaneo completo una vez.
        if request.args.get("refresh") != "1":
            cached = load_cache(Path(base_vault))
            if cached is not None:
                return jsonify(cached)
        stats = compute_stats(Path(base_vault), prj_name)
        save_cache(Path(base_vault), stats)
        return jsonify(stats)
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

        raw_vault = base_vault / "RAW_VAULT"
        result = subprocess.run(
            [sys.executable, str(HERE / "patch_gizmo_map.py"), str(raw_vault), str(gizmo_map_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return jsonify({"ok": True, "patched": len(filled), "patch_output": result.stdout})
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
