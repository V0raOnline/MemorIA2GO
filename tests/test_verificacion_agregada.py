# -*- coding: utf-8 -*-
"""Test del semaforo agregado de exports_dir (backlog CONTEXT.md #2,
verificaciones colapsables, diseno confirmado con V0ra 2026-07-21):
- "err" mientras no haya ni un export valido.
- "warn" si hay validos pero alguno esta invalido o tiene aviso de deriva.
- "ok" solo si todos los candidatos estan limpios -- tener pendientes NO
  baja el semaforo, es el estado normal antes de un import.
"""
import zipfile
from pathlib import Path

import preflight

FIXTURES = Path(__file__).parent / "fixtures"


def test_sin_ningun_export_valido_es_err(tmp_path):
    (tmp_path / "no_es_un_export.txt").write_text("nada que ver", encoding="utf-8")
    report = preflight.validate_config(None, str(tmp_path))
    export_check = next(c for c in report["checks"] if c["campo"] == "exports_dir")
    assert export_check["estado"] == "err"
    assert export_check["validos"] == 0


def test_todos_limpios_sin_pendientes_es_ok(tmp_path):
    zpath = tmp_path / "claude_export.zip"
    zpath.write_bytes((FIXTURES / "claude_export.zip").read_bytes())
    report = preflight.validate_config(None, str(tmp_path))
    export_check = next(c for c in report["checks"] if c["campo"] == "exports_dir")
    assert export_check["estado"] == "ok"
    assert export_check["validos"] == 1


def test_pendientes_sin_problemas_sigue_siendo_ok(tmp_path):
    """Sin base_vault no se puede calcular 'pendientes' (requiere el
    registro en RAW_VAULT), pero el punto del test es que el semaforo no
    depende de esa cifra en absoluto -- solo de candidatos invalidos/aviso."""
    zpath = tmp_path / "claude_export.zip"
    zpath.write_bytes((FIXTURES / "claude_export.zip").read_bytes())
    base_vault = tmp_path / "vault"
    base_vault.mkdir()
    report = preflight.validate_config(str(base_vault), str(tmp_path))
    export_check = next(c for c in report["checks"] if c["campo"] == "exports_dir")
    assert export_check["pendientes"] == 1  # nada procesado todavia: 1 pendiente
    assert export_check["estado"] == "ok"  # pero sigue en verde: pendiente no es problema


def test_un_candidato_invalido_mezclado_baja_a_warn(tmp_path):
    zpath = tmp_path / "claude_export.zip"
    zpath.write_bytes((FIXTURES / "claude_export.zip").read_bytes())
    roto = tmp_path / "roto.zip"
    with zipfile.ZipFile(roto, "w") as zf:
        zf.writestr("readme.txt", "esto no es un export")

    report = preflight.validate_config(None, str(tmp_path))
    export_check = next(c for c in report["checks"] if c["campo"] == "exports_dir")
    assert export_check["validos"] == 1
    assert export_check["estado"] == "warn"


def test_deriva_de_formato_baja_a_warn(tmp_path):
    frag_dir = FIXTURES / "chatgpt_fragmentado"
    zpath = tmp_path / "chatgpt_frag.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in sorted(frag_dir.glob("conversations-*.json")):
            zf.writestr(f.name, f.read_bytes())

    report = preflight.validate_config(None, str(tmp_path), deep=True)
    export_check = next(c for c in report["checks"] if c["campo"] == "exports_dir")
    assert export_check["estado"] == "warn"
