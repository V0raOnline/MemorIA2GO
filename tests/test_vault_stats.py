# -*- coding: utf-8 -*-
"""Tests de compute_asset_stats (backlog 2026-07-23: la tarjeta del
dashboard media IMAGE_BANK, vacio a proposito desde la migracion de
taxonomia -- ahora cuenta los bancos reales por proveedor, incluyendo
artefactos de Claude y videos de Grok, no solo imagenes)."""
from pathlib import Path

from vault_stats import compute_asset_stats


def _write(path: Path, content: bytes = b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_banco_vacio_no_revienta(tmp_path):
    stats = compute_asset_stats(tmp_path)
    assert stats["total_items"] == 0
    assert stats["tamano_legible"] == "0 B"
    assert stats["por_proveedor"]["chatgpt"]["items"] == 0
    assert stats["por_proveedor"]["claude"]["items"] == 0


def test_cuenta_por_proveedor_y_tipo(tmp_path):
    _write(tmp_path / "CHATGPT" / "GENERADAS" / "a.png")
    _write(tmp_path / "CHATGPT" / "GENERADAS" / "b.png")
    _write(tmp_path / "CHATGPT" / "ADJUNTOS" / "c.png")
    _write(tmp_path / "GROK" / "ADJUNTOS" / "d.jpg")
    _write(tmp_path / "GROK" / "GENERADAS_VIDEO" / "e.mp4")
    _write(tmp_path / "CLAUDE" / "ARTEFACTOS" / "markdown" / "f.md")
    _write(tmp_path / "CLAUDE" / "ARTEFACTOS" / "codigo" / "g.py")

    stats = compute_asset_stats(tmp_path)

    assert stats["total_items"] == 7
    assert stats["por_proveedor"]["chatgpt"]["items"] == 3
    assert stats["por_proveedor"]["grok"]["items"] == 2
    assert stats["por_proveedor"]["claude"]["items"] == 2

    chatgpt_detalle = {d["etiqueta"]: d["items"] for d in stats["por_proveedor"]["chatgpt"]["detalle"]}
    assert chatgpt_detalle["generadas"] == 2
    assert chatgpt_detalle["adjuntos"] == 1

    claude_detalle = {d["etiqueta"]: d["items"] for d in stats["por_proveedor"]["claude"]["detalle"]}
    assert claude_detalle["markdown"] == 1
    assert claude_detalle["codigo"] == 1


def test_ignora_manifests_y_ficheros_ocultos(tmp_path):
    _write(tmp_path / "CHATGPT" / "GENERADAS" / "a.png")
    _write(tmp_path / "CHATGPT" / "GENERADAS" / "_image_manifest.json", b"{}")

    stats = compute_asset_stats(tmp_path)
    assert stats["por_proveedor"]["chatgpt"]["items"] == 1


def test_claude_sin_subtipos_con_items_no_aparece_en_detalle(tmp_path):
    """Solo se lista un tipo en el detalle si tiene al menos 1 item --
    evita ramas vacias tipo '0 svg' ensuciando la tarjeta."""
    _write(tmp_path / "CLAUDE" / "ARTEFACTOS" / "markdown" / "a.md")
    (tmp_path / "CLAUDE" / "ARTEFACTOS" / "html").mkdir(parents=True)

    stats = compute_asset_stats(tmp_path)
    etiquetas = [d["etiqueta"] for d in stats["por_proveedor"]["claude"]["detalle"]]
    assert etiquetas == ["markdown"]
