# -*- coding: utf-8 -*-
"""Tests del cablado del nuevo export de Claude al pipeline (Fase B).

Fija tres cosas que preflight y load_conversations tienen que garantizar
para que el resto del pipeline no se entere de que hay un formato nuevo:
  - el manifiesto se reconoce (informativamente, no como export importable);
  - el zip fragmentado conversations-NNN.zip se reconoce con etiqueta
    propia, pero solo por su nombre canonico -- renombrarlo lo hace caer
    en la rama chatgpt_zip, que sigue funcionando porque _dispatch
    despacha por estructura, no por etiqueta;
  - la carpeta descomprimida se reconoce como layout, aparece en
    list_pending_exports, tiene fingerprint estable, y load_conversations
    la ingesta delegando en newclaude_adapter.parse_conversations.
"""
import json
import zipfile
from pathlib import Path

import pytest

import preflight
import split_chatgpt_export as sce


# ─────────────────────────────────────────
# Fixtures minimos
# ─────────────────────────────────────────

def _manifest_payload():
    """Manifiesto valido con las 5 categorias del export real."""
    cats = ["light_metadata", "projects", "memories", "frames", "conversations"]
    return {
        "instructions": "Download each file using the export_url. Note: Each export URL can only be used once.",
        "created_at": "2026-09-20T20:17:00.878412+00:00",
        "total_files": len(cats),
        "data_files": [
            {"batch_index": i, "export_url": f"https://x/download/{i}",
             "category": c, "part": 0, "filename": f"{c}-000.zip"}
            for i, c in enumerate(cats)
        ],
        "version": "1.0",
    }


def _payload_conversations_claude():
    """Una conversacion minima con la forma exacta del export de Claude
    (usada para meter dentro de un zip fragmentado sintetico)."""
    return json.dumps([{
        "uuid": "abc-def",
        "name": "Hola",
        "summary": "",
        "created_at": "2026-09-01T10:00:00+00:00",
        "updated_at": "2026-09-01T10:00:00+00:00",
        "account": {"uuid": "usr-1"},
        "chat_messages": [
            {"uuid": "m1", "text": "hola",
             "content": [{"type": "text", "text": "hola"}],
             "sender": "human", "created_at": "2026-09-01T10:00:00+00:00",
             "updated_at": "2026-09-01T10:00:00+00:00",
             "attachments": [], "files": [], "parent_message_uuid": None},
        ],
    }], ensure_ascii=False).encode("utf-8")


def _crear_layout(base: Path, conversations: bytes | None = None) -> Path:
    """Crea una carpeta con la marca minima del layout NewClaude:
    conversations-000/conversations.json. Devuelve la carpeta raiz."""
    layout = base / "NewClaude"
    layout.mkdir()
    conv_dir = layout / "conversations-000"
    conv_dir.mkdir()
    (conv_dir / "conversations.json").write_bytes(
        conversations if conversations is not None else b"[]"
    )
    return layout


# ─────────────────────────────────────────
# Manifiesto JSON
# ─────────────────────────────────────────

def test_manifiesto_reconocido_como_no_importable(tmp_path):
    """El manifiesto en si no lleva conversaciones. Lo importante: el
    usuario recibe un mensaje que le dice que bajar los 5 zips, no un
    'JSON invalido' que le confunda."""
    m = tmp_path / "manifest-uuid-2026-09-20-20-17-00.json"
    m.write_text(json.dumps(_manifest_payload()), encoding="utf-8")
    result = preflight.validate_export_file(m)
    assert result["valido"] is False
    assert result["tipo"] == "newclaude_manifest"
    assert "Manifiesto" in result["mensaje"]
    assert "5 zips" in result["mensaje"] or "5" in result["mensaje"]


def test_manifiesto_con_categoria_desconocida_lanza_aviso(tmp_path):
    m = tmp_path / "manifest-x.json"
    payload = _manifest_payload()
    payload["data_files"].append({
        "batch_index": 5, "export_url": "https://x/download/5",
        "category": "categoria_nueva", "part": 0, "filename": "categoria_nueva-000.zip"
    })
    m.write_text(json.dumps(payload), encoding="utf-8")
    result = preflight.validate_export_file(m)
    assert result["tipo"] == "newclaude_manifest"
    assert "categoria_nueva" in result["mensaje"]


# ─────────────────────────────────────────
# conversations-NNN.zip
# ─────────────────────────────────────────

def test_conversations_zip_reconocido_por_nombre_canonico(tmp_path):
    z = tmp_path / "conversations-000.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("conversations.json", _payload_conversations_claude())
    result = preflight.validate_export_file(z)
    assert result["valido"] is True
    assert result["tipo"] == "newclaude_conversations_zip"


def test_conversations_zip_renombrado_cae_en_chatgpt_zip(tmp_path):
    """Si alguien renombra el zip, la etiqueta cambia pero SIGUE siendo
    importable: _dispatch despachara al adaptador de Claude por
    estructura, no por etiqueta. Este test defiende explicitamente esa
    red -- no queremos ser estrictos con el nombre y perder el export."""
    z = tmp_path / "algo_random.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("conversations.json", _payload_conversations_claude())
    result = preflight.validate_export_file(z)
    assert result["valido"] is True
    assert result["tipo"] == "chatgpt_zip"  # fallback correcto


# ─────────────────────────────────────────
# Layout de carpeta
# ─────────────────────────────────────────

def test_layout_carpeta_reconocido_por_validate_export_directory(tmp_path):
    layout = _crear_layout(tmp_path, _payload_conversations_claude())
    result = preflight.validate_export_directory(layout)
    assert result["valido"] is True
    assert result["tipo"] == "newclaude_layout"
    assert "conversations" in result["categorias_presentes"]


def test_layout_incompleto_sigue_siendo_valido_con_solo_conversations(tmp_path):
    """El usuario puede haber bajado solo el zip de conversations y no
    los otros. El layout parcial se acepta -- solo se procesara lo que
    haya. El mensaje lo indica en 'categorias_presentes'."""
    layout = _crear_layout(tmp_path)
    result = preflight.validate_export_directory(layout)
    assert result["valido"] is True
    assert result["categorias_presentes"] == ["conversations"]


def test_layout_rechaza_carpetas_ajenas(tmp_path):
    (tmp_path / "cualquier_carpeta").mkdir()
    (tmp_path / "cualquier_carpeta" / "no_hay_conversations_aqui.txt").write_text("x")
    result = preflight.validate_export_directory(tmp_path / "cualquier_carpeta")
    assert result["valido"] is False


# ─────────────────────────────────────────
# Enumeracion en exports_dir (files + directorios)
# ─────────────────────────────────────────

def test_list_pending_incluye_layouts_como_carpetas(tmp_path):
    """El export nuevo llega como CARPETA. list_pending_exports tiene que
    enumerarlas junto a los .zip/.json de siempre para que MemorIA2GO.py
    (paso 1) las procese como cualquier otro export."""
    exports = tmp_path / "exports"
    exports.mkdir()
    raw = tmp_path / "RAW"
    raw.mkdir()

    _crear_layout(exports, _payload_conversations_claude())

    pending = preflight.list_pending_exports(exports, raw)
    assert len(pending) == 1
    assert pending[0].is_dir()
    assert pending[0].name == "NewClaude"


def test_list_pending_mezcla_ficheros_y_carpetas(tmp_path):
    """En el mismo exports_dir puede coexistir un zip clasico y una
    carpeta del nuevo formato. Los dos aparecen como pendientes."""
    exports = tmp_path / "exports"
    exports.mkdir()
    raw = tmp_path / "RAW"
    raw.mkdir()

    # Un zip clasico de ChatGPT
    zpath = exports / "chatgpt.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("conversations.json", b'[{"title":"x","mapping":{}}]')
    # Y una carpeta layout
    _crear_layout(exports, _payload_conversations_claude())

    pending = preflight.list_pending_exports(exports, raw)
    nombres = sorted(p.name for p in pending)
    assert nombres == ["NewClaude", "chatgpt.zip"]


def test_export_fingerprint_de_carpeta_usa_tamano_de_conversations_json(tmp_path):
    """La huella tiene que cambiar cuando cambia el contenido, no cuando
    cambian metadatos irrelevantes (mtime). Para directorios, el tamano
    de conversations.json es el proxy usado."""
    layout = _crear_layout(tmp_path, b'[{"chat_messages":[]}]')
    fp1 = preflight.export_fingerprint(layout)
    assert "|dir|" in fp1
    # Cambia el contenido -> cambia la huella
    (layout / "conversations-000" / "conversations.json").write_bytes(
        b'[{"chat_messages":[]}, {"chat_messages":[]}]'
    )
    fp2 = preflight.export_fingerprint(layout)
    assert fp1 != fp2


# ─────────────────────────────────────────
# split_chatgpt_export.load_conversations desde carpeta
# ─────────────────────────────────────────

def test_load_conversations_desde_carpeta_produce_convs_de_claude(tmp_path):
    """Punto a punto: load_conversations en una carpeta layout devuelve
    conversaciones con provider='claude' y conv_id -- las dos piezas que
    hacen que write_md las escriba con el mismo source que el export
    viejo y que vault_merge las agrupe por conv_id (dedup gratis)."""
    layout = _crear_layout(tmp_path, _payload_conversations_claude())
    convs, zf = sce.load_conversations(str(layout))
    assert zf is None  # no hay zip asociado al layout
    assert len(convs) == 1
    assert convs[0]["provider"] == "claude"
    assert convs[0]["conv_id"] == "abc-def"


def test_load_conversations_carpeta_sin_layout_grita(tmp_path):
    """Una carpeta ajena tiene que fallar RUIDOSAMENTE, mismo criterio
    que un zip corrupto: si el usuario apunta al sitio equivocado, mejor
    que se entere ya que perder conversaciones en silencio."""
    (tmp_path / "cualquier_cosa").mkdir()
    with pytest.raises(RuntimeError):
        sce.load_conversations(str(tmp_path / "cualquier_cosa"))
