# -*- coding: utf-8 -*-
"""Tests de regresion de preflight.validate_export_file (backlog CONTEXT.md #1).

Cubre los 4 tipos de export soportados (por estructura, no por nombre de
archivo) y los dos casos de fallo explicito que el modulo esta pensado para
gritar: zip corrupto y estructura desconocida.
"""
import zipfile
from pathlib import Path

import preflight

FIXTURES = Path(__file__).parent / "fixtures"


def _make_zip(tmp_path, name, entries: dict) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for arcname, content in entries.items():
            zf.writestr(arcname, content)
    return path


def test_chatgpt_zip_clasico(tmp_path):
    data = (FIXTURES / "chatgpt_classic.json").read_bytes()
    zpath = _make_zip(tmp_path, "chatgpt_classic.zip", {"conversations.json": data})
    result = preflight.validate_export_file(zpath)
    assert result["valido"] is True
    assert result["tipo"] == "chatgpt_zip"


def test_chatgpt_zip_fragmentado(tmp_path):
    frag_dir = FIXTURES / "chatgpt_fragmentado"
    entries = {f.name: f.read_bytes() for f in sorted(frag_dir.glob("conversations-*.json"))}
    zpath = _make_zip(tmp_path, "chatgpt_frag.zip", entries)
    result = preflight.validate_export_file(zpath)
    assert result["valido"] is True
    assert result["tipo"] == "chatgpt_zip_fragmentado"


def test_claude_zip():
    result = preflight.validate_export_file(FIXTURES / "claude_export.zip")
    assert result["valido"] is True
    assert result["tipo"] == "claude_zip"


def test_grok_zip():
    result = preflight.validate_export_file(FIXTURES / "grok_export.zip")
    assert result["valido"] is True
    assert result["tipo"] == "grok_zip"


def test_zip_corrupto(tmp_path):
    bad = tmp_path / "corrupto.zip"
    bad.write_bytes(b"esto no es un zip valido, son bytes cualquiera" * 5)
    result = preflight.validate_export_file(bad)
    assert result["valido"] is False
    assert "CORRUPT" in result["mensaje"]


def test_zip_estructura_desconocida(tmp_path):
    zpath = _make_zip(tmp_path, "raro.zip", {"readme.txt": "esto no es un export de nada reconocible"})
    result = preflight.validate_export_file(zpath)
    assert result["valido"] is False
    assert "UNKNOWN STRUCTURE" in result["mensaje"]


# ─────────────────────────────────────────
# Substack: reconocido y RECHAZADO a proposito (CONTEXT.md seccion 3j).
# Fixture sintetico inline, sin datos reales: el export de V0ra lleva emails
# de suscriptores y no tiene por que existir una copia en tests/.
# ─────────────────────────────────────────

def _substack_entries() -> dict:
    return {
        "posts.csv": "post_id,post_date,is_published,type,title\n"
                     "1.hola,2026-01-01T00:00:00.000Z,true,newsletter,Hola\n",
        "posts/1.hola.html": "<p>Un parrafo cualquiera.</p><p>Y otro.</p>",
        "posts/1.delivers.csv": "post_id,timestamp,email\n1,2026-01-01T00:00:00.000Z,alguien@ejemplo.test\n",
        "email_list.publicacion.csv": "email,active_subscription\nalguien@ejemplo.test,true\n",
    }


def test_substack_zip_reconocido_y_rechazado(tmp_path):
    zpath = _make_zip(tmp_path, "substack.zip", _substack_entries())
    result = preflight.validate_export_file(zpath)
    assert result["valido"] is False
    assert result["tipo"] == "substack_zip"
    assert "SUBSTACK EXPORT" in result["mensaje"]
    # Los CSV con datos de suscriptores se cuentan y se nombran en voz alta;
    # posts.csv no cuenta, que es indice de publicaciones y no lleva PII.
    assert "2 CSV" in result["mensaje"]


def test_substack_no_llega_a_importarse(tmp_path):
    """Lo que de verdad importa no es el dict que devuelve la validacion,
    sino que el zip NO entre en la cola de importacion (criterio de hecho:
    comprobar el efecto en el pipeline, no solo el retorno de la funcion)."""
    exports = tmp_path / "exports"
    exports.mkdir()
    _make_zip(exports, "substack.zip", _substack_entries())
    raw_vault = tmp_path / "RAW_VAULT"
    raw_vault.mkdir()
    assert preflight.list_pending_exports(exports, raw_vault) == []


def test_zip_con_html_suelto_sigue_cayendo_en_la_rama_degradada(tmp_path):
    """Senuelo deliberado: el MISMO zip sin posts.csv debe seguir entrando
    como chatgpt_zip_html. Si este test se pone verde por el motivo
    equivocado (p.ej. alguien amplia el guard a cualquier posts/*.html),
    el de arriba deja de estar probando lo que cree probar."""
    zpath = _make_zip(tmp_path, "solo_html.zip", {"posts/1.hola.html": "<p>Un parrafo.</p>"})
    result = preflight.validate_export_file(zpath)
    assert result["valido"] is True
    assert result["tipo"] == "chatgpt_zip_html"
