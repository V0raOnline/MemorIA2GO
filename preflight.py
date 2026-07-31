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
import re
import zipfile
from pathlib import Path
from typing import Optional

REGISTRY_FILENAME = "_exports_procesados.json"

# Formato fragmentado de ChatGPT (2026+): conversations-000.json,
# conversations-001.json... Definido aqui como constante del modulo para
# que preflight y el lector puedan coincidir en la misma deteccion.
SHARD_RX = re.compile(r"conversations-\d+\.json$", re.IGNORECASE)


def validate_export_file(path) -> dict:
    """Comprueba que un archivo concreto sea un export reconocible de alguno
    de los proveedores soportados (ChatGPT, Claude, Grok), sin llegar a parsear
    las conversaciones completas. La distincion entre proveedores es
    informativa (campo 'tipo'); el despacho real al adaptador correcto lo
    hace split_chatgpt_export._dispatch por estructura del JSON."""
    p = Path(path)
    if not p.exists():
        return {"valido": False, "mensaje": f"File does not exist: {p}"}

    ext = p.suffix.lower()

    if ext == ".zip":
        try:
            with zipfile.ZipFile(p, "r") as zf:
                names = zf.namelist()
        except (zipfile.BadZipFile, OSError) as e:
            # GRITAR, no susurrar: un zip ilegible es exactamente la noticia
            # que hay que recibir el dia que ocurre, no el mes que se descubre
            # (incidente real: exports corruptos silenciosamente ignorados y
            # conversaciones "desaparecidas" durante semanas).
            return {"valido": False,
                    "mensaje": f"CORRUPT OR UNREADABLE ZIP ({type(e).__name__}: {e}). "
                               "Any conversations inside are NOT being imported. "
                               "Try repairing it (7-Zip often can) or re-download the export."}

        has_conv = any(n.lower().endswith("conversations.json") for n in names)
        shards = [n for n in names if SHARD_RX.search(n)]
        has_html = any(n.lower().endswith(".html") for n in names)
        # El zip de Claude tambien trae conversations.json; se distingue por
        # los acompanantes que ChatGPT nunca incluye (users.json, projects/).
        looks_claude = any(n.lower() == "users.json" for n in names) or \
                       any(n.lower().startswith("projects/") for n in names)

        if shards:
            return {"valido": True,
                    "mensaje": f"Fragmented ChatGPT export recognized ({len(shards)} conversations-NNN.json shards).",
                    "tipo": "chatgpt_zip_fragmentado"}
        if has_conv and looks_claude:
            return {"valido": True, "mensaje": "Claude export recognized (conversations.json + users.json/projects).", "tipo": "claude_zip"}
        if has_conv:
            return {"valido": True, "mensaje": "conversations.json found inside the ZIP (ChatGPT export).", "tipo": "chatgpt_zip"}
        if any(n.lower().endswith("prod-grok-backend.json") for n in names):
            return {"valido": True, "mensaje": "Grok export recognized (prod-grok-backend.json).", "tipo": "grok_zip"}
        # Export de Substack. Se evalua ANTES que has_html porque cae justo en
        # esa rama: sus 109 .html la disparan, el zip se acepta como
        # 'chatgpt_zip_html' degradado y load_conversations lee UN solo .html
        # fabricando una conversacion falsa que alterna user/assistant con los
        # parrafos de un unico post (medido contra el export real de V0ra
        # 2026-07-31: 109 posts -> 1 "conversacion" de 108 mensajes, los otros
        # 108 posts desaparecidos, sin conv_id ni provider ni fecha). Es el
        # mismo fallo silencioso que motivo la deteccion por estructura del
        # conversations.json de Claude, pero sin red debajo.
        # No es un proveedor de este pipeline y no debe serlo (decision de V0ra
        # 2026-07-31: un post no es un dialogo, ver CONTEXT.md seccion 3j). Al
        # pipeline conversacional no se le ensena un supuesto nuevo, solo a
        # RECONOCER y RECHAZAR: eso es lo que cierra el agujero.
        if any(n.lower() == "posts.csv" for n in names) and \
           any(n.lower().startswith("posts/") and n.lower().endswith(".html") for n in names):
            # Los CSV de posts/ (delivers/opens) y email_list.*.csv llevan
            # emails de suscriptores, y los de opens ademas pais/ciudad/
            # dispositivo/user-agent: datos personales de TERCEROS. Se nombran
            # en voz alta a proposito, mismo criterio que gritar ante un zip
            # corrupto -- que nadie los descubra el dia que reprocese esto con
            # otra herramienta.
            csv_pii = [n for n in names if n.lower().endswith(".csv") and n.lower() != "posts.csv"]
            return {
                "valido": False,
                "mensaje": "SUBSTACK EXPORT: recognized, and deliberately NOT imported here. "
                           "Posts are publications, not conversations: this pipeline would turn "
                           "them into degraded fake dialogue. They have their own tool. "
                           f"Heads-up: this ZIP also carries {len(csv_pii)} CSV files with "
                           "subscriber personal data (emails; the 'opens' ones also include "
                           "country, city, device and user agent). They are never imported.",
                "tipo": "substack_zip",
            }

        if has_html:
            # Valido pero con aviso de deriva: si solo hay HTML, o es un export
            # muy antiguo o el proveedor cambio de formato y no lo reconocemos.
            return {"valido": True,
                    "mensaje": "WARNING: only conversation HTML found — unusual format. "
                               "If this export is recent, the provider may have changed format "
                               "and the parser would need updating; HTML import is degraded.",
                    "tipo": "chatgpt_zip_html"}

        muestra = names[:8]
        return {
            "valido": False,
            "mensaje": "UNKNOWN STRUCTURE: this ZIP does not match any supported format "
                       "(ChatGPT classic or fragmented, Claude, Grok). If it is a recent export, "
                       "the provider probably changed format: the parser needs updating. "
                       "A sample of the contents is attached for diagnosis.",
            "contenido_encontrado": muestra,
        }

    if ext == ".json":
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return {"valido": False, "mensaje": f"The file is not valid JSON: {e}"}
        except Exception as e:
            return {"valido": False, "mensaje": f"Could not read the file: {e}"}

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
            "mensaje": "The JSON does not have the expected shape of a supported export "
                       "(ChatGPT: list with 'mapping'/'title' or object with 'conversations'; "
                       "Claude: list with 'chat_messages').",
        }

    if ext in (".html", ".htm"):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return {"valido": False, "mensaje": f"Could not read the HTML: {e}"}
        if len(txt) < 100:
            return {"valido": False, "mensaje": "The HTML looks empty or too small to be an export."}
        return {"valido": True, "mensaje": "HTML file accepted (shallow validation, does not guarantee valid content).", "tipo": "html"}

    return {"valido": False, "mensaje": f"Unsupported extension: {ext or '(no extension)'}. Use .zip, .json or .html."}


def list_export_candidates(exports_dir, deep: bool = False) -> list:
    """Lista TODOS los .zip/.json/.html de la carpeta, mas recientes primero,
    cada uno ya validado. Con deep=True, ademas muestrea cada candidato
    valido con detect_new_keys y anexa el aviso al mensaje (ver su
    docstring: es una lectura completa del JSON, deliberadamente NO
    automatica en cada poll de la UI)."""
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
        mensaje = result["mensaje"]
        aviso = False  # deriva de formato detectada (deep=True): valido sigue en True, solo es aviso
        if deep and result["valido"]:
            drift = detect_new_keys(f)
            claves = drift.get("claves_nuevas") or []
            if claves:
                aviso = True
                mensaje += (
                    f" ⚠ AVISO: {len(claves)} clave(s) nueva(s) nunca vistas en "
                    f"conversaciones de {drift.get('provider')}: {', '.join(claves)}. "
                    "El proveedor puede haber cambiado de formato; revisa si el "
                    "adaptador necesita actualizarse."
                )
        out.append({
            "nombre": f.name,
            "ruta": str(f),
            "valido": result["valido"],
            "tipo": result.get("tipo"),
            "mensaje": mensaje,
            "aviso": aviso,
        })
    return out


# ─────────────────────────────────────────
# Deteccion de deriva de formato (detect_strict): avisa si un export trae
# claves de conversacion nunca vistas por el adaptador correspondiente.
# ─────────────────────────────────────────

def _load_raw_json_for_sampling(p: Path):
    """Carga cruda del JSON de un export, SOLO para muestreo de claves.
    Duplica deliberadamente (en pequeno) el sniffing de zip que ya hace
    validate_export_file en vez de reutilizar split_chatgpt_export.load_conversations:
    ese loader hace parseo+render completos (mapping, imagenes, hilos) y es
    codigo sensible con historial de incidentes (Nido_Delta); esta funcion
    es de solo lectura y, si falla, el peor caso es un aviso que no aparece
    -- nunca afecta a la importacion real."""
    ext = p.suffix.lower()
    if ext == ".zip":
        with zipfile.ZipFile(p, "r") as zf:
            names = zf.namelist()
            shards = sorted(n for n in names if SHARD_RX.search(n))
            if shards:
                combinado = []
                for name in shards:
                    with zf.open(name) as f:
                        parte = json.load(f)
                    if isinstance(parte, list):
                        combinado.extend(parte)
                return combinado
            json_name = next((n for n in names if n.lower().endswith("conversations.json")), None)
            if not json_name:
                json_name = next((n for n in names if n.lower().endswith("prod-grok-backend.json")), None)
            if not json_name:
                return None
            with zf.open(json_name) as f:
                return json.load(f)
        return None
    if ext == ".json":
        with open(p, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return None  # HTML u otro formato degradado: no hay JSON que muestrear


def _sample_items_for_schema(data):
    """Decide el proveedor por estructura (mismo criterio que _dispatch en
    split_chatgpt_export.py) y devuelve los dicts de nivel 'conversacion'
    sobre los que se comparan claves."""
    from providers import claude_adapter, grok_adapter

    if claude_adapter.detect(data):
        return "claude", claude_adapter.KNOWN_KEYS, list(data)
    if grok_adapter.detect(data):
        metas = [
            (cw.get("conversation") or {})
            for cw in (data.get("conversations") or [])
            if isinstance(cw, dict)
        ]
        return "grok", grok_adapter.KNOWN_KEYS, metas

    import split_chatgpt_export as sce
    if isinstance(data, dict) and isinstance(data.get("conversations"), list):
        raw = data["conversations"]
    elif isinstance(data, list):
        raw = data
    else:
        raw = []
    return "chatgpt", sce.CHATGPT_KNOWN_KEYS, raw


def detect_new_keys(path, sample_size: int = 20) -> dict:
    """Muestrea hasta `sample_size` conversaciones de un export y compara
    sus claves de nivel superior contra las que el adaptador correspondiente
    declara conocer (KNOWN_KEYS). No bloquea nada -- es un aviso (pensado
    para pintarse en amarillo en la UI) de que el proveedor pudo haber
    cambiado de formato, la misma familia de bug que conversation_template_id
    (Nido_Delta, 2026-07-20): una clave nueva que el parser todavia no conoce
    y que hoy viajaria invisible al resto del pipeline.

    A diferencia de validate_export_file (deliberadamente barata, no parsea),
    esta funcion SI carga el JSON completo -- es cara en exports grandes y no
    debe llamarse en cada poll automatico de la UI, solo ante una accion
    explicita del usuario (o en CLI/tests)."""
    p = Path(path)
    try:
        data = _load_raw_json_for_sampling(p)
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        return {"muestreado": False, "motivo": f"No se pudo leer para muestreo: {type(e).__name__}: {e}"}

    if data is None:
        return {"muestreado": False, "motivo": "Formato sin JSON muestreable (HTML u otro no reconocido)."}

    provider, known_keys, items = _sample_items_for_schema(data)
    muestra = items[:sample_size]
    claves_nuevas = set()
    for it in muestra:
        if isinstance(it, dict):
            claves_nuevas.update(k for k in it.keys() if k not in known_keys)

    return {
        "muestreado": True,
        "provider": provider,
        "total_items": len(items),
        "muestra_size": len(muestra),
        "claves_nuevas": sorted(claves_nuevas),
    }


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

def validate_config(base_vault, exports_dir, gizmo_map_path=None, deep: bool = False) -> dict:
    """Informe completo: cada campo de la config con su estado, la lista de
    candidatos en exports_dir (validos o no), y cuantos de los validos estan
    ya procesados frente a pendientes (si base_vault existe, para poder
    consultar su registro). deep=True activa ademas el muestreo de deriva de
    formato (detect_new_keys) por candidato -- ver list_export_candidates."""
    checks = []

    if not base_vault:
        checks.append({"campo": "base_vault", "ok": False, "mensaje": "Not configured."})
    else:
        bv = Path(base_vault)
        parent_ok = bv.exists() or bv.parent.exists()
        checks.append({
            "campo": "base_vault", "ok": parent_ok,
            "mensaje": "OK." if parent_ok else f"Neither the folder nor its parent exist: {bv.parent}",
        })

    # estado: semaforo agregado para la UI (caja nivel-1 colapsable de
    # exports_dir). "err" mientras no haya ni un export valido (nada que
    # importar); "warn" si hay validos pero alguno esta invalido/sin
    # reconocer o tiene aviso de deriva de formato; "ok" solo si todos los
    # candidatos estan limpios. Tener "pendientes" NO baja el semaforo --
    # es el estado normal antes de un import, no un problema (decision
    # V0ra 2026-07-21).
    export_check = {"campo": "exports_dir", "ok": False, "estado": "err", "mensaje": "", "candidatos": [],
                     "validos": 0, "pendientes": 0, "ya_procesados": 0}
    if not exports_dir:
        export_check["mensaje"] = "No configurado."
    else:
        ed = Path(exports_dir)
        if not ed.is_dir():
            export_check["mensaje"] = f"The folder does not exist: {ed}"
        else:
            candidatos = list_export_candidates(ed, deep=deep)
            export_check["candidatos"] = candidatos
            validos = [c for c in candidatos if c["valido"]]
            export_check["validos"] = len(validos)

            if not validos:
                export_check["mensaje"] = "No hay ningun export valido en esta carpeta."
            else:
                hay_problema = any((not c["valido"]) or c.get("aviso") for c in candidatos)
                export_check["estado"] = "warn" if hay_problema else "ok"
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
                            "mensaje": "Does not exist yet -- it will be created when saving gizmos. Not blocking."})
        else:
            try:
                with open(gp, "r", encoding="utf-8-sig") as f:
                    json.load(f)
                checks.append({"campo": "gizmo_map", "ok": True, "mensaje": "Valid JSON."})
            except Exception as e:
                checks.append({"campo": "gizmo_map", "ok": False, "mensaje": f"Invalid JSON: {e}"})

    todo_ok = all(c["ok"] for c in checks)
    return {"ok": todo_ok, "checks": checks}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Valida la configuracion de MemorIA2GO antes de ejecutar.")
    ap.add_argument("--base-vault", default=None)
    ap.add_argument("--exports-dir", required=True)
    ap.add_argument("--gizmo-map", default=None)
    ap.add_argument("--deep", action="store_true",
                     help="Muestrea el contenido de cada export y avisa de claves nuevas "
                          "nunca vistas (deriva de formato). Mas lento: parsea el JSON completo.")
    args = ap.parse_args()

    report = validate_config(args.base_vault, args.exports_dir, args.gizmo_map, deep=args.deep)
    for c in report["checks"]:
        estado = "OK " if c["ok"] else "FALLO"
        print(f"[{estado}] {c['campo']}: {c['mensaje']}")
    print(f"\nGlobal: {'OK' if report['ok'] else 'HAY PROBLEMAS'}")
