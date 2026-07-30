# -*- coding: utf-8 -*-
"""Tests de project_organizer.py — la vista PRJ_VAULT (conversaciones
organizadas por proyecto/anio/mes) derivada de MERGED_VAULT.

Motivados por un bug real de 2026-07-28: el organizador recorria el vault
ENTERO, asi que arrastraba tambien las notas generadas (indices y notas de
tema) a un cajon `none/0000/00`, refrescandolas en cada corrida.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def _nota(path: Path, *, titulo, proyecto=None, fecha=None, cuerpo="texto"):
    path.parent.mkdir(parents=True, exist_ok=True)
    front = ["---", f'title: "{titulo}"']
    if fecha:
        front.append(f"date: {fecha}")
    if proyecto:
        front.append(f'Project_name: "{proyecto}"')
    front += ["---", "", cuerpo]
    path.write_text("\n".join(front), encoding="utf-8")


def _organizar(src: Path, dst: Path):
    return subprocess.run(
        [sys.executable, str(HERE / "project_organizer.py"), str(src), str(dst), "--by-date"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_organiza_conversaciones_por_proyecto_y_fecha(tmp_path):
    src, dst = tmp_path / "MERGED", tmp_path / "PRJ"
    _nota(src / "Conversations" / "2026" / "03" / "a.md",
          titulo="Con proyecto", proyecto="Arkinesis", fecha="2026-03-15")
    _organizar(src, dst)
    assert (dst / "Arkinesis" / "2026" / "03" / "a.md").exists()


def test_conversacion_sin_proyecto_va_a_none(tmp_path):
    src, dst = tmp_path / "MERGED", tmp_path / "PRJ"
    _nota(src / "Conversations" / "2026" / "03" / "b.md",
          titulo="Sin proyecto", fecha="2026-03-15")
    _organizar(src, dst)
    assert (dst / "none" / "2026" / "03" / "b.md").exists()


def test_no_arrastra_indices_ni_notas_de_tema(tmp_path):
    """Bug real 2026-07-28: los indices y las notas de _Topics/ no tienen
    Project_name ni date, asi que acababan en none/0000/00 -- 24 ficheros
    y 1353 KB duplicados en el vault real, con sus enlaces contando doble
    en el grafo de Obsidian. PRJ_VAULT es una vista de CONVERSACIONES."""
    src, dst = tmp_path / "MERGED", tmp_path / "PRJ"
    _nota(src / "Conversations" / "2026" / "03" / "real.md",
          titulo="Conversacion de verdad", proyecto="Arkinesis", fecha="2026-03-15")

    # Notas generadas, tal como las escribe el paso 4 (sin frontmatter util)
    for nombre in ("_tree_index.md", "scaffolding_index.md", "_index_chatgpt.md",
                   "_index_grok.md", "_grok_pending.md"):
        (src / nombre).write_text("# indice generado\n", encoding="utf-8")
    (src / "_Topics").mkdir(parents=True, exist_ok=True)
    for tema in ("arkinesis.md", "organoides.md"):
        (src / "_Topics" / tema).write_text("# tema\n", encoding="utf-8")

    _organizar(src, dst)

    assert (dst / "Arkinesis" / "2026" / "03" / "real.md").exists()
    assert not (dst / "none" / "0000").exists(), "el cajon de basura no debe crearse"
    copiados = {p.name for p in dst.rglob("*.md")}
    assert copiados == {"real.md"}


def test_los_indices_originales_no_se_tocan(tmp_path):
    """El fix filtra la lectura, no borra nada del vault fuente."""
    src, dst = tmp_path / "MERGED", tmp_path / "PRJ"
    _nota(src / "Conversations" / "2026" / "03" / "a.md",
          titulo="X", proyecto="P", fecha="2026-03-01")
    idx = src / "_tree_index.md"
    idx.write_text("# indice\n", encoding="utf-8")
    _organizar(src, dst)
    assert idx.exists() and idx.read_text(encoding="utf-8") == "# indice\n"


def test_sin_carpeta_conversaciones_aborta_con_mensaje(tmp_path):
    """Guarda ya existente: sin Conversations/ no hay nada que organizar."""
    src, dst = tmp_path / "MERGED", tmp_path / "PRJ"
    src.mkdir(parents=True)
    res = _organizar(src, dst)
    assert res.returncode != 0
    assert "Conversations" in (res.stdout + res.stderr)
