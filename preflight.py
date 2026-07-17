#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preflight.py — Validaciones previas a lanzar el pipeline, para dar errores
legibles ANTES de que algo falle a mitad de un subprocess con un traceback
crudo. Reutilizable desde MemorIA2GO.py (CLI) y desde launcher.py (web).

Incidente real que motiva este modulo: exports_dir contenia un .zip que no
era un export de ChatGPT (no tiene conversations.json dentro), y el fallo
solo aparecia dentro de split_chatgpt_export.py, muchas capas mas adentro
de lo necesario para diagnosticarlo.

Tambien resuelve un segundo problema real, descubierto despues: exports_dir
puede contener VARIOS exports validos de distintas fechas -- procesar solo
"el mas reciente" pierde silenciosamente conversaciones que existian en un
export viejo pero fueron borradas en la cuenta antes del export nuevo (un
export es un volcado completo, no un incremental). La solucion es procesar
TODOS los exports validos pendientes, llevando un registro de los ya
importados para que sea incremental por defecto.
"""
import json
import zipfile
from pathlib import Path
from typing import Optional

REGISTRY_FILENAME = "_exports_procesados.json"


def validate_export_file(path) -> dict:
    """Comprueba que un archivo concreto sea un export reconocible de alguno
    de los proveedores soportados (ChatGPT, Claude, Grok), sin llegar a parsear
    las conversaciones completas. La distincion entre proveedores es
    informativa (campo 'tipo'); el despacho real al adaptador correcto lo
    hace split_chatgpt_export._dispatch por estructura del JSON."""
    p = Path(path)
    if not p.exists():
        return {"valido": False, "mensaje": f"No existe el archivo: {p}"}

    ext = p.suffix.lower()

    if ext == ".zip":
        try:
            with zipfile.ZipFile(p, "r") as zf:
                names = zf.namelist()
        except zipfile.BadZipFile:
            return {"valido": False, "mensaje": "El archivo no es un ZIP valido (¿esta corrupto o incompleto?)."}

        has_conv = any(n.lower().endswith("conversations.json") for n in names)
        has_html = any(n.lower().endswith(".html") for n in names)
        # El zip de Claude tambien trae conversations.json; se distingue por
        # los acompanantes que ChatGPT nunca incluye (users.json, projects/).
        looks_claude = any(n.lower() == "users.json" for n in names) or \
                       any(n.lower().startswith("projects/") for n in names)

        if has_conv and looks_claude:
            return {"valido": True, "mensaje": "Export de Claude reconocido (conversations.json + users.json/projects).", "tipo": "claude_zip"}
        if has_conv:
            return {"valido": True, "mensaje": "conversations.json encontrado dentro del ZIP (export de ChatGPT).", "tipo": "chatgpt_zip"}
        if any(n.lower().endswith("prod-grok-backend.json") for n in names):
            return {"valido": True, "mensaje": "Export de Grok reconocido (prod-grok-backend.json).", "tipo": "grok_zip"}
        if has_html:
            return {"valido": True, "mensaje": "HTML de conversacion encontrado dentro del ZIP (formato antiguo).", "tipo": "chatgpt_zip_html"}

        muestra = names[:8]
        return {
            "valido": False,
            "mensaje": "Este ZIP no contiene conversations.json ni un HTML de conversacion -- no parece un export de ChatGPT.",
            "contenido_encontrado": muestra,
        }

    if ext == ".json":
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return {"valido": False, "mensaje": f"El archivo no es JSON valido: {e}"}
        except Exception as e:
            return {"valido": False, "mensaje": f"No pude leer el archivo: {e}"}

        looks_like_export = False
        tipo = "chatgpt_json"
        mensaje_ok = "Estructura de conversaciones de ChatGPT reconocida."
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if "chat_messages" in data[0]:
                looks_like_export = True
                tipo = "claude_json"
                mensaje_ok = "Estructura de conversaciones de Claude reconocida."
            elif "mapping" in data[0] or "title" in data[0]:
                looks_like_export = True
        elif isinstance(data, dict) and "conversations" in data:
            convs = data.get("conversations")
            # Grok tambien usa raiz {conversations: [...]}: sus items son
            # wrappers {conversation, responses}. Evaluar antes que ChatGPT.
            if isinstance(convs, list) and convs and isinstance(convs[0], dict) and "responses" in convs[0]:
                looks_like_export = True
                tipo = "grok_json"
                mensaje_ok = "Estructura de conversaciones de Grok reconocida."
            else:
                looks_like_export = True

        if looks_like_export:
            return {"valido": True, "mensaje": mensaje_ok, "tipo": tipo}
        return {
            "valido": False,
            "mensaje": "El JSON no tiene la forma esperada de un export soportado "
                       "(ChatGPT: lista con 'mapping'/'title' u objeto con 'conversations'; "
                       "Claude: lista con 'chat_messages').",
        }

    if ext in (".html", ".htm"):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return {"valido": False, "mensaje": f"No pude leer el HTML: {e}"}
        if len(txt) < 100:
            return {"valido": False, "mensaje": "El HTML parece vacio o demasiado pequeno para ser un export."}
        return {"valido": True, "mensaje": "Archivo HTML aceptado (validacion superficial, no garantiza contenido valido).", "tipo": "html"}

    return {"valido": False, "mensaje": f"Extension no soportada: {ext or '(sin extension)'}. Usa .zip, .json o .html."}


def list_export_candidates(exports_dir) -> list:
    """Lista TODOS los .zip/.json/.html de la carpeta, mas recientes primero,
    cada uno ya validado."""
    p = Path(exports_dir)
    if not p.is_dir():
        return []
    all_files = []
    for ext in ("*.zip", "*.json", "*.html", "*.htm"):
        all_files.extend(p.glob(ext))
    all_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    out = []
    for f in all_files:
        result = validate_export_file(f)
        out.append({"nombre": f.name, "ruta": str(f), "valido": result["valido"], "mensaje": result["mensaje"]})
    return out


# ─────────────────────────────────────────
# Registro de exports ya procesados (para importacion incremental)
# ─────────────────────────────────────────

def export_fingerprint(path: Path) -> str:
    """Identificador barato (nombre + tamano) para saber si un archivo ya se
    proceso. No usa hash de contenido a proposito: reprocesar por error no
    tiene coste real (--keep-versions + merge por huella ya lo protegen),
    y hashear archivos de ~1GB en cada ejecucion solo para comprobar si son
    'nuevos' seria caro sin necesidad."""
    st = path.stat()
    return f"{path.name}|{st.st_size}"


def load_registry(raw_vault) -> dict:
    path = Path(raw_vault) / REGISTRY_FILENAME
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def save_registry(raw_vault, registry: dict) -> None:
    raw_vault = Path(raw_vault)
    raw_vault.mkdir(parents=True, exist_ok=True)
    path = raw_vault / REGISTRY_FILENAME
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def list_pending_exports(exports_dir, raw_vault, reprocess_all: bool = False) -> list:
    """Devuelve la lista de archivos VALIDOS que aun no estan en el registro
    (o todos los validos, si reprocess_all=True), ordenados del mas antiguo
    al mas reciente -- asi el orden de importacion sigue la linea temporal
    real de tus exports."""
    p = Path(exports_dir)
    if not p.is_dir():
        return []

    registry = {} if reprocess_all else load_registry(raw_vault)

    all_files = []
    for ext in ("*.zip", "*.json", "*.html", "*.htm"):
        all_files.extend(p.glob(ext))
    all_files.sort(key=lambda x: x.stat().st_mtime)  # mas antiguo primero

    pending = []
    for f in all_files:
        if not validate_export_file(f)["valido"]:
            continue
        if export_fingerprint(f) in registry:
            continue
        pending.append(f)
    return pending


def mark_processed(raw_vault, files: list) -> None:
    """Anade estos archivos al registro tras procesarlos con exito."""
    registry = load_registry(raw_vault)
    for f in files:
        f = Path(f)
        registry[export_fingerprint(f)] = {
            "nombre": f.name,
            "procesado_en": __import__("datetime").datetime.now().isoformat(),
        }
    save_registry(raw_vault, registry)


# ─────────────────────────────────────────
# Informe de configuracion completo
# ─────────────────────────────────────────

def validate_config(base_vault, exports_dir, gizmo_map_path=None) -> dict:
    """Informe completo: cada campo de la config con su estado, la lista de
    candidatos en exports_dir (validos o no), y cuantos de los validos estan
    ya procesados frente a pendientes (si base_vault existe, para poder
    consultar su registro)."""
    checks = []

    if not base_vault:
        checks.append({"campo": "base_vault", "ok": False, "mensaje": "No configurado."})
    else:
        bv = Path(base_vault)
        parent_ok = bv.exists() or bv.parent.exists()
        checks.append({
            "campo": "base_vault", "ok": parent_ok,
            "mensaje": "OK." if parent_ok else f"Ni la carpeta ni su carpeta padre existen: {bv.parent}",
        })

    export_check = {"campo": "exports_dir", "ok": False, "mensaje": "", "candidatos": [],
                     "validos": 0, "pendientes": 0, "ya_procesados": 0}
    if not exports_dir:
        export_check["mensaje"] = "No configurado."
    else:
        ed = Path(exports_dir)
        if not ed.is_dir():
            export_check["mensaje"] = f"La carpeta no existe: {ed}"
        else:
            candidatos = list_export_candidates(ed)
            export_check["candidatos"] = candidatos
            validos = [c for c in candidatos if c["valido"]]
            export_check["validos"] = len(validos)

            if not validos:
                export_check["mensaje"] = "No hay ningun export valido en esta carpeta."
            else:
                raw_vault = (Path(base_vault) / "RAW_VAULT") if base_vault else None
                if raw_vault is not None:
                    pending = list_pending_exports(ed, raw_vault)
                    export_check["pendientes"] = len(pending)
                    export_check["ya_procesados"] = len(validos) - len(pending)
                    if pending:
                        export_check["mensaje"] = f"{len(pending)} export(s) nuevo(s) por importar de {len(validos)} valido(s)."
                    else:
                        export_check["mensaje"] = f"Todo al dia -- los {len(validos)} export(s) validos ya estan importados."
                    export_check["ok"] = True
                else:
                    export_check["mensaje"] = f"{len(validos)} export(s) valido(s) encontrados (configura base_vault para saber cuantos ya se importaron)."
                    export_check["ok"] = True
    checks.append(export_check)

    if gizmo_map_path:
        gp = Path(gizmo_map_path)
        if not gp.exists():
            checks.append({"campo": "gizmo_map", "ok": True,
                            "mensaje": "No existe todavia -- se creara al guardar gizmos. No bloqueante."})
        else:
            try:
                with open(gp, "r", encoding="utf-8-sig") as f:
                    json.load(f)
                checks.append({"campo": "gizmo_map", "ok": True, "mensaje": "JSON valido."})
            except Exception as e:
                checks.append({"campo": "gizmo_map", "ok": False, "mensaje": f"JSON invalido: {e}"})

    todo_ok = all(c["ok"] for c in checks)
    return {"ok": todo_ok, "checks": checks}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Valida la configuracion de MemorIA2GO antes de ejecutar.")
    ap.add_argument("--base-vault", default=None)
    ap.add_argument("--exports-dir", required=True)
    ap.add_argument("--gizmo-map", default=None)
    args = ap.parse_args()

    report = validate_config(args.base_vault, args.exports_dir, args.gizmo_map)
    for c in report["checks"]:
        estado = "OK " if c["ok"] else "FALLO"
        print(f"[{estado}] {c['campo']}: {c['mensaje']}")
    print(f"\nGlobal: {'OK' if report['ok'] else 'HAY PROBLEMAS'}")
