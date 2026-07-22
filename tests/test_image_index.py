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

    link_re = ii.make_link_re("IMAGE_BANK")
    entries = ii.collect_entries(vault, "Conversaciones", manifest={}, link_re=link_re)

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
    link_re = ii.make_link_re("IMAGE_BANK")
    entries = ii.collect_entries(vault, "Conversaciones", manifest={}, link_re=link_re)
    md = ii.render_markdown(entries, "IMAGE_BANK", "Índice de Imágenes")
    assert "IMAGE_BANK/real.png" in md
    assert "falsa.png" not in md


def test_bank_prefix_distinto_no_mezcla_bancos(tmp_path):
    """Un enlace CHATGPT/GENERADAS/ no debe aparecer en el indice de
    CHATGPT/ADJUNTOS y viceversa -- son bancos separados (decision V0ra
    2026-07-22, taxonomia por proveedor y tipo)."""
    vault = tmp_path
    conv_dir = vault / "Conversaciones"
    _write_note(
        conv_dir / "nota.md", title="Nota", date="2026-07-01",
        body="![](CHATGPT/GENERADAS/gen.png)\n\n![](CHATGPT/ADJUNTOS/adj.png)\n",
    )
    entries_generadas = ii.collect_entries(vault, "Conversaciones", manifest={},
                                            link_re=ii.make_link_re("CHATGPT/GENERADAS"))
    entries_adjuntos = ii.collect_entries(vault, "Conversaciones", manifest={},
                                           link_re=ii.make_link_re("CHATGPT/ADJUNTOS"))
    assert entries_generadas[0]["images"] == [("gen.png", {})]
    assert entries_adjuntos[0]["images"] == [("adj.png", {})]
