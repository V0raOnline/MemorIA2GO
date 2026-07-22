# -*- coding: utf-8 -*-
"""Test de regresion de image_index.py (bug real 2026-07-21): contenido
pegado/citado dentro de una conversacion (URLs externas, ejemplos de sintaxis
markdown) que use "![](...)" se contaba como imagen real del pipeline y
aparecia como icono roto en el indice -- se leyo como "hemos perdido los
indices" cuando el indice en si era correcto. El fix exige el prefijo
IMAGE_BANK/ que es el que este pipeline realmente usa al incrustar imagenes.
"""
from pathlib import Path

import image_index as ii


def _write_note(path: Path, *, title, date, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    front = f'---\ntitle: "{title}"\ndate: {date}\n---\n\n'
    path.write_text(front + body, encoding="utf-8")


def test_ignora_enlaces_pegados_sin_prefijo_image_bank(tmp_path):
    vault = tmp_path
    conv_dir = vault / "Conversaciones"

    _write_note(
        conv_dir / "con-imagen-real.md", title="Con imagen real", date="2026-07-01",
        body="### Assistant\n\nAqui tienes la captura.\n\n![](IMAGE_BANK/abc123.png)\n",
    )
    _write_note(
        conv_dir / "solo-ruido.md", title="Ejemplos de markdown", date="2026-07-02",
        body="### User\n\nAsi se referencia una imagen en markdown: "
             "![](imagenes/nombre_imagen.png) o pegando una URL externa "
             "![](https://miro.medium.com/v2/resize:fit:840/1*abc.png)\n",
    )

    bank = vault / "IMAGE_BANK"
    bank.mkdir()
    (bank / "abc123.png").write_bytes(b"fake-png-bytes")
    # nombre_imagen.png / 1*abc.png NO existen en IMAGE_BANK a proposito.

    entries = ii.collect_entries(vault, "Conversaciones", manifest={})

    assert len(entries) == 1, f"solo la nota con imagen real deberia quedar, hay: {[e['title'] for e in entries]}"
    assert entries[0]["title"] == "Con imagen real"
    assert entries[0]["images"] == [("abc123.png", {})]


def test_render_markdown_sin_referencias_rotas(tmp_path):
    vault = tmp_path
    conv_dir = vault / "Conversaciones"
    _write_note(
        conv_dir / "nota.md", title="Nota", date="2026-07-01",
        body="![](IMAGE_BANK/real.png)\n\n"
             "texto citado con ![](otra-carpeta/falsa.png) de por medio\n",
    )
    entries = ii.collect_entries(vault, "Conversaciones", manifest={})
    md = ii.render_markdown(entries)
    assert "IMAGE_BANK/real.png" in md
    assert "falsa.png" not in md
