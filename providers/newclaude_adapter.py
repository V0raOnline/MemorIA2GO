# -*- coding: utf-8 -*-
"""providers/newclaude_adapter.py -- Adaptador del NUEVO formato de export
de Claude (claude.ai) al modelo intermedio de MemorIA2GO.

Anthropic cambio silenciosamente el formato del export en agosto/septiembre
de 2026 (unificacion de memoria entre chat y Cowork, ver
https://support.claude.com/en/articles/12123587). Lo que antes era UN zip
con conversations.json + users.json + projects.json ahora es un
MANIFIESTO JSON + 5 ZIPS DE UN SOLO USO, cada uno con su categoria:

    manifest-<uuid>-<ts>-<sig>-<AAAA-MM-DD-HH-MM-SS>.json
    ├── light_metadata-000.zip  (users.json + login_history.json)
    ├── projects-000.zip        (projects/<uuid>.json, uno por proyecto)
    ├── memories-000.zip        (memories/<user_uuid>.json, memoria persistente)
    ├── frames-000.zip          (artifacts/<uuid>/... versiones + comentarios)
    └── conversations-000.zip   (conversations.json monolitico, mismo formato)

No hay anuncio oficial (comprobado en el Privacy Center y en changelogs
publicos, 2026-09-21). El unico rastro publico es un issue de terceros:
https://github.com/ukogan/claude-migration-assistant/issues/4

DECISIONES DE DISEÑO (ver bck/NewClaude/PLAN.md):

- `conversations.json` interno TIENE la misma forma que el export viejo.
  Verificado contra el export real de V0ra 2026-09-20 (264 convs, 13.935
  mensajes): claves de conversacion y de mensaje identicas a KNOWN_KEYS
  del claude_adapter. Este adaptador delega en `claude_adapter.parse`
  para las conversaciones y no re-implementa nada.
- El `source` que se emite es `claude_export`, NO `newclaude_export`.
  Motivo: el pipeline usa `conv_id` como identidad de conversacion en
  vault_merge (verificado en vault_merge.py:199, `key = f"id:{cid}"`);
  si el `source` divergiera, las variantes del mismo `conv_id` de dos
  exports (viejo y nuevo) no se fusionarian coherentemente. Con el
  mismo `source`, vault_merge las fusiona y recupera mensajes nuevos.
- `memories`, `frames`, `projects` y `light_metadata` NO se ingestan en
  esta version del adaptador. Se preservan en su banco crudo y se
  atacan por fases (ver plan).

Este adaptador NO se conecta al detector automatico
(split_chatgpt_export._dispatch) todavia: la Fase A del plan es
fundacional (parseo + tests), la Fase B lo cablea al pipeline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from providers import claude_adapter

# Las cinco categorias que el manifiesto debe listar. Si aparece una
# categoria fuera de este conjunto, o si falta alguna esperada, es señal
# de que Anthropic volvio a mover el formato -- preflight avisa, no
# bloquea (misma disciplina que KNOWN_KEYS en el adaptador viejo).
KNOWN_CATEGORIES = frozenset({
    "light_metadata", "projects", "memories", "frames", "conversations",
})

# Claves esperadas en el manifiesto JSON. `version` puede subir sin
# romper compatibilidad; se mira, no se exige valor concreto.
MANIFEST_KEYS = frozenset({
    "instructions", "created_at", "total_files", "data_files", "version",
})

# Claves esperadas en cada entrada de `data_files` del manifiesto.
DATA_FILE_KEYS = frozenset({
    "batch_index", "export_url", "category", "part", "filename",
})


def detect_manifest(data: Any) -> bool:
    """True si `data` (JSON ya cargado) es el manifiesto del nuevo export.

    Se identifica por la combinacion: dict raiz con `data_files` (lista),
    cada entrada un dict con `category` y `filename`, y por lo menos una
    categoria del conjunto conocido. Deliberadamente PERMISIVO en las
    claves opcionales (`instructions`, `version`, `total_files`,
    `created_at`) para que un cambio menor del formato no rompa la
    deteccion; el aviso de deriva es responsabilidad del que llame."""
    if not isinstance(data, dict):
        return False
    dfs = data.get("data_files")
    if not isinstance(dfs, list) or not dfs:
        return False
    if not all(isinstance(d, dict) and "category" in d and "filename" in d
               for d in dfs):
        return False
    cats = {d.get("category") for d in dfs}
    return bool(cats & KNOWN_CATEGORIES)


def detect_layout(carpeta: Any) -> bool:
    """True si `carpeta` (Path o str) es una carpeta descomprimida del
    nuevo export.

    Reconoce la estructura resultante de descomprimir los 5 zips: cinco
    subcarpetas hermanas `<categoria>-NNN/` (habitualmente `-000`), cada
    una con el contenido de su zip. Se admite que falte alguna categoria
    (por ejemplo, si el usuario solo descomprimio conversations-000.zip
    para probar): la señal minima es que exista `conversations-NNN/` con
    un `conversations.json` dentro."""
    p = Path(carpeta)
    if not p.is_dir():
        return False
    # Buscar la subcarpeta de conversaciones (el minimo viable).
    for sub in p.iterdir():
        if not sub.is_dir():
            continue
        nombre = sub.name.lower()
        if nombre.startswith("conversations-") and (sub / "conversations.json").is_file():
            return True
    return False


def _find_subdir(carpeta: Path, categoria: str) -> Optional[Path]:
    """Busca la subcarpeta `<categoria>-NNN/` dentro de `carpeta`. Devuelve
    la primera que encuentre (habitualmente `-000`); None si no existe."""
    prefijo = categoria.lower() + "-"
    for sub in carpeta.iterdir():
        if sub.is_dir() and sub.name.lower().startswith(prefijo):
            return sub
    return None


def parse_conversations(carpeta: Any) -> List[Dict[str, Any]]:
    """Lee conversations.json de una carpeta descomprimida del nuevo
    export y lo devuelve ya parseado por `claude_adapter.parse`.

    Delega TODO el trabajo semantico al adaptador viejo: el formato
    interno de conversations.json no cambio, y re-implementarlo aqui
    seria duplicar 230 lineas de logica (threading por
    parent_message_uuid, resolucion de artefactos, attachments,
    rendering...) que ya estan probadas."""
    p = Path(carpeta)
    conv_dir = _find_subdir(p, "conversations")
    if conv_dir is None:
        return []
    conv_json = conv_dir / "conversations.json"
    if not conv_json.is_file():
        return []
    import json
    with conv_json.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return claude_adapter.parse(data)


def categorias_del_manifiesto(data: Dict[str, Any]) -> Dict[str, List[str]]:
    """Dado un manifiesto valido (`detect_manifest(data)` True), devuelve
    `{"conocidas": [...], "desconocidas": [...]}` en el orden en que
    aparecen en `data_files`. Util para que preflight avise si Anthropic
    añade una categoria nueva (misma señal que las claves nuevas)."""
    conocidas, desconocidas = [], []
    for d in data.get("data_files") or []:
        cat = d.get("category")
        if cat in KNOWN_CATEGORIES:
            conocidas.append(cat)
        elif cat:
            desconocidas.append(cat)
    return {"conocidas": conocidas, "desconocidas": desconocidas}
