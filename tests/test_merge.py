# -*- coding: utf-8 -*-
"""Test de regresion de vault_merge.py (backlog CONTEXT.md #1).

Cubre la resolucion de renombrados de hilo: dos notas RAW con el mismo
conv_id pero titulos distintos deben fusionarse en UNA sola nota MERGED,
con el titulo mas reciente y el viejo conservado en titulo_original.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import vault_merge as vm

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_raw_note(path: Path, *, conv_id, title, date, suffix, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    front = (
        "---\n"
        f'title: "{title}"\n'
        f"date: {date}\n"
        "source: chatgpt_export\n"
        f"conv_id: {conv_id}\n"
        "---\n\n"
    )
    body = (
        f"### User\n\nPregunta {suffix}\n\n"
        f"### Assistant\n\nRespuesta {suffix}\n"
    )
    path.write_text(front + body, encoding="utf-8", newline="")
    os.utime(path, (mtime, mtime))


def test_merge_resuelve_renombrado_y_conserva_titulo_original(tmp_path):
    raw_conv = tmp_path / "RAW_VAULT" / "Conversations"
    merged_dir = tmp_path / "MERGED_VAULT"

    now = time.time()
    _write_raw_note(
        raw_conv / "2026-06-01_titulo-viejo.md",
        conv_id="abc123", title="Titulo viejo", date="2026-06-01",
        suffix="uno", mtime=now - 1000,
    )
    _write_raw_note(
        raw_conv / "2026-06-01_titulo-nuevo.md",
        conv_id="abc123", title="Titulo nuevo", date="2026-06-01",
        suffix="dos", mtime=now - 500,
    )

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "vault_merge.py"),
         str(tmp_path / "RAW_VAULT"), str(merged_dir), "--merge"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    out_dir = merged_dir / "Conversations"
    notas = list(out_dir.glob("*.md"))
    assert len(notas) == 1, f"se esperaba 1 nota fusionada, hay: {[n.name for n in notas]}"

    front, messages = vm.read_note(str(notas[0]))
    assert front.get("title", "").strip('"') == "Titulo nuevo"
    assert front.get("titulo_original", "").strip('"') == "Titulo viejo"

    contenido = " ".join(m["content"] for m in messages)
    assert "Pregunta uno" in contenido
    assert "Pregunta dos" in contenido
