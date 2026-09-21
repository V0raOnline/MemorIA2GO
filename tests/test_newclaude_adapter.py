# -*- coding: utf-8 -*-
"""Tests del adaptador del NUEVO formato de export de Claude.

Que se prueba, en orden de importancia:
  - detect_manifest reconoce un manifiesto y rechaza cualquier otro JSON;
  - detect_layout reconoce la carpeta descomprimida por su marca minima
    (conversations-NNN/conversations.json), sobrevive a NNN != 000, y
    rechaza carpetas que no son un export;
  - parse_conversations delega correctamente en claude_adapter (mismo
    contrato de salida: el nuevo formato NO es un modelo nuevo);
  - categorias_del_manifiesto separa conocidas de desconocidas (la
    señal de deriva de formato que preflight consumira en la Fase A/4).
"""
import json
from pathlib import Path

import pytest

from providers import newclaude_adapter as nc


# ─────────────────────────────────────────
# Fixtures: manifiesto sintetico minimo y variantes
# ─────────────────────────────────────────

def _manifiesto_valido(categorias=None):
    """Manifiesto minimo con las 5 categorias del export real. Si el
    caller pasa `categorias`, se usan esas (para simular derivas)."""
    cats = categorias if categorias is not None else [
        "light_metadata", "projects", "memories", "frames", "conversations",
    ]
    return {
        "instructions": "Download each file using the export_url. Note: Each export URL can only be used once.",
        "created_at": "2026-09-20T20:17:00.878412+00:00",
        "total_files": len(cats),
        "data_files": [
            {"batch_index": i,
             "export_url": f"https://claude.ai/export/x/download/{i:08x}",
             "category": c,
             "part": 0,
             "filename": f"{c}-000.zip"}
            for i, c in enumerate(cats)
        ],
        "version": "1.0",
    }


# ─────────────────────────────────────────
# detect_manifest
# ─────────────────────────────────────────

def test_detect_manifest_reconoce_el_manifiesto_de_5_categorias():
    assert nc.detect_manifest(_manifiesto_valido()) is True


def test_detect_manifest_admite_falta_de_alguna_categoria_conocida():
    """Si el usuario ha exportado un subconjunto o Anthropic quita una
    categoria, mientras haya AL MENOS UNA conocida, sigue siendo el
    manifiesto nuevo. La disciplina es reconocer, no exigir."""
    assert nc.detect_manifest(_manifiesto_valido(["conversations"])) is True
    assert nc.detect_manifest(_manifiesto_valido(["memories", "frames"])) is True


def test_detect_manifest_rechaza_manifiesto_sin_ninguna_categoria_conocida():
    """Si nada del data_files cae en el conjunto conocido, no es este
    export -- puede ser otro tipo de manifiesto (Anthropic tiene mas de
    uno; el pipeline no debe atribuirse cosas ajenas)."""
    m = _manifiesto_valido(["cosa_rara", "otra_cosa"])
    assert nc.detect_manifest(m) is False


def test_detect_manifest_rechaza_lo_que_no_es_manifiesto():
    """Rechazos duros: cualquier otra cosa que caiga en preflight (lista
    de conversaciones, dict de Grok, string, None) tiene que dar False
    sin explotar. Es el papel del detector: separar, no consumir."""
    assert nc.detect_manifest([{"chat_messages": []}]) is False       # export viejo de Claude
    assert nc.detect_manifest({"conversations": [{"responses": []}]}) is False  # Grok
    assert nc.detect_manifest({"data_files": "no_es_lista"}) is False
    assert nc.detect_manifest({"data_files": []}) is False            # lista vacia
    assert nc.detect_manifest({}) is False
    assert nc.detect_manifest(None) is False
    assert nc.detect_manifest("cadena") is False


def test_detect_manifest_no_exige_que_TODAS_las_entradas_tengan_todas_las_claves():
    """`data_files[*]` debe tener al menos category y filename; el resto
    (batch_index, export_url, part) son metadatos que pueden faltar en
    un manifiesto experimental sin invalidar el reconocimiento."""
    m = {"data_files": [{"category": "conversations", "filename": "conversations-000.zip"}]}
    assert nc.detect_manifest(m) is True


# ─────────────────────────────────────────
# detect_layout
# ─────────────────────────────────────────

def test_detect_layout_reconoce_carpeta_con_conversations_000(tmp_path):
    """Escenario canonico: descomprimir el zip crea conversations-000/
    con conversations.json dentro."""
    (tmp_path / "conversations-000").mkdir()
    (tmp_path / "conversations-000" / "conversations.json").write_text("[]", encoding="utf-8")
    assert nc.detect_layout(tmp_path) is True


def test_detect_layout_admite_NNN_distinto_de_000(tmp_path):
    """Si algun dia el export llega troceado en conversations-001,
    conversations-002... la carpeta sigue siendo reconocible. La deteccion
    es por prefijo, no por sufijo exacto."""
    (tmp_path / "conversations-013").mkdir()
    (tmp_path / "conversations-013" / "conversations.json").write_text("[]", encoding="utf-8")
    assert nc.detect_layout(tmp_path) is True


def test_detect_layout_rechaza_carpetas_ajenas(tmp_path):
    (tmp_path / "cualquier_cosa").mkdir()
    (tmp_path / "conversations-000").mkdir()  # subdir presente...
    # ...pero sin el conversations.json dentro: no cuenta
    assert nc.detect_layout(tmp_path) is False


def test_detect_layout_rechaza_lo_que_no_es_directorio(tmp_path):
    # un fichero suelto no es un layout
    (tmp_path / "manifiesto.json").write_text("{}", encoding="utf-8")
    assert nc.detect_layout(tmp_path / "manifiesto.json") is False
    # una ruta inexistente
    assert nc.detect_layout(tmp_path / "no_existe") is False


# ─────────────────────────────────────────
# parse_conversations
# ─────────────────────────────────────────

def test_parse_conversations_delega_en_claude_adapter(tmp_path):
    """El nuevo formato ES el viejo por dentro: el mismo conversations.json
    parseado con este adaptador debe dar exactamente lo mismo que si se
    parsea directo con claude_adapter. Sin sorpresas semanticas."""
    from providers import claude_adapter as viejo

    # Una conversacion minima con la forma exacta del export real.
    payload = [{
        "uuid": "aaaa-bbbb-cccc-dddd",
        "name": "Hola mundo",
        "summary": "",
        "created_at": "2026-09-01T10:00:00+00:00",
        "updated_at": "2026-09-01T10:05:00+00:00",
        "account": {"uuid": "usr-1"},
        "chat_messages": [
            {"uuid": "m1", "text": "hola", "content": [{"type": "text", "text": "hola"}],
             "sender": "human", "created_at": "2026-09-01T10:00:00+00:00",
             "updated_at": "2026-09-01T10:00:00+00:00",
             "attachments": [], "files": [], "parent_message_uuid": None},
            {"uuid": "m2", "text": "qué tal", "content": [{"type": "text", "text": "qué tal"}],
             "sender": "assistant", "created_at": "2026-09-01T10:01:00+00:00",
             "updated_at": "2026-09-01T10:01:00+00:00",
             "attachments": [], "files": [], "parent_message_uuid": "m1"},
        ],
    }]
    conv_dir = tmp_path / "conversations-000"
    conv_dir.mkdir()
    (conv_dir / "conversations.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    via_nuevo = nc.parse_conversations(tmp_path)
    via_viejo = viejo.parse(payload)
    assert via_nuevo == via_viejo
    assert len(via_nuevo) == 1
    assert via_nuevo[0]["conv_id"] == "aaaa-bbbb-cccc-dddd"
    assert via_nuevo[0]["provider"] == "claude"


def test_parse_conversations_devuelve_vacio_si_no_hay_carpeta_de_conversaciones(tmp_path):
    """Si el layout no tiene conversations-NNN/, no hay conversaciones
    que parsear -- lista vacia, no excepcion. Los otros pases (memories,
    frames, projects) siguen su camino."""
    assert nc.parse_conversations(tmp_path) == []


# ─────────────────────────────────────────
# categorias_del_manifiesto
# ─────────────────────────────────────────

def test_categorias_separa_conocidas_de_desconocidas():
    m = _manifiesto_valido(["conversations", "frames", "cosa_nueva"])
    resultado = nc.categorias_del_manifiesto(m)
    assert resultado["conocidas"] == ["conversations", "frames"]
    assert resultado["desconocidas"] == ["cosa_nueva"]


def test_categorias_preserva_el_orden_del_manifiesto():
    """El orden importa porque los avisos de preflight lo citan; si sale
    barajado por set() lo hara ver ruidoso en la UI."""
    m = _manifiesto_valido(["memories", "conversations", "frames"])
    assert nc.categorias_del_manifiesto(m)["conocidas"] == \
        ["memories", "conversations", "frames"]


# ─────────────────────────────────────────
# Prueba contra el export REAL (si esta disponible en bck/NewClaude/)
# ─────────────────────────────────────────
# Este es el corolario del contrato interno: la disciplina de V0ra dice
# "diagnostico antes que codigo, y prueba contra datos reales antes de
# dar por hecho". Si esta el export descomprimido, se ejerce -- si no,
# el test se salta silenciosamente en CI.

_BCK = Path(__file__).resolve().parent.parent / "bck" / "NewClaude"


@pytest.mark.skipif(not _BCK.is_dir(), reason="bck/NewClaude/ no disponible")
def test_export_real_es_reconocido_como_layout():
    assert nc.detect_layout(_BCK) is True


@pytest.mark.skipif(not (_BCK / "conversations-000" / "conversations.json").is_file(),
                    reason="conversations.json real no disponible")
def test_export_real_parsea_todas_las_conversaciones_con_conv_id():
    convs = nc.parse_conversations(_BCK)
    assert len(convs) > 0
    # Cada conversacion parseada tiene que llevar conv_id (identidad
    # canonica del pipeline) y provider "claude" (no "newclaude") para
    # que vault_merge las fusione con las del export viejo.
    for c in convs:
        assert c["conv_id"], f"conversacion sin conv_id: {c.get('title')!r}"
        assert c["provider"] == "claude"


def _manifiestos_reales():
    """El manifest real puede estar dentro de bck/NewClaude/ o al lado
    (bck/), segun donde lo haya dejado el usuario tras descargarlo."""
    return list(_BCK.glob("manifest-*.json")) + list(_BCK.parent.glob("manifest-*.json"))


@pytest.mark.skipif(not _manifiestos_reales(), reason="manifest real no disponible")
def test_manifiesto_real_es_reconocido():
    m_path = _manifiestos_reales()[0]
    with m_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert nc.detect_manifest(data) is True
    cats = nc.categorias_del_manifiesto(data)
    # El manifiesto real trae las 5 categorias esperadas.
    assert set(cats["conocidas"]) == set(nc.KNOWN_CATEGORIES)
    assert cats["desconocidas"] == []
