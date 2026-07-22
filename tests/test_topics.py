# -*- coding: utf-8 -*-
"""Test de regresion de orphan_cloud.generate_topic_index (backlog CONTEXT.md #1).

Cubre las tres formas de regla del topic_map (palabra suelta, frase, campo=valor
estructural) y las dos capas de puntos ciegos de _sin-tema.md: sin ningun tema
vs. solo pescada por redes estructurales.
"""
import json
from pathlib import Path

import orphan_cloud as oc


def _write_note(path: Path, *, project, provider, title, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    front = (
        "---\n"
        f'title: "{title}"\n'
        "date: 2026-06-01\n"
        f"Project_name: {project}\n"
        f"provider: {provider}\n"
        "---\n\n"
    )
    path.write_text(front + body, encoding="utf-8", newline="\n")


def test_generate_topic_index_reglas_palabra_frase_y_estructural(tmp_path):
    base_vault = tmp_path
    conv_dir = base_vault / "MERGED_VAULT" / "Conversaciones"

    _write_note(
        conv_dir / "pan-casero.md", project="none", provider="chatgpt",
        title="Pan casero",
        body="### User\n\n¿Como hago una receta de pan sencilla?\n\n"
             "### Assistant\n\nAqui tienes la receta paso a paso.\n",
    )
    _write_note(
        conv_dir / "plan-deportivo.md", project="none", provider="chatgpt",
        title="Plan deportivo",
        body="### User\n\nQuiero una rutina de ejercicios para el gimnasio.\n\n"
             "### Assistant\n\nTe propongo una rutina de ejercicios de tres dias.\n",
    )
    _write_note(
        conv_dir / "consulta-clima.md", project="none", provider="claude",
        title="Consulta cualquiera",
        body="### User\n\n¿Que opinas del clima en Madrid?\n\n"
             "### Assistant\n\nNo tengo datos meteorologicos en tiempo real.\n",
    )
    _write_note(
        conv_dir / "capital-francia.md", project="none", provider="grok",
        title="Nada que ver",
        body="### User\n\n¿Cual es la capital de Francia?\n\n"
             "### Assistant\n\nParis es la capital de Francia.\n",
    )

    topic_map_path = tmp_path / "topic_map.json"
    topic_map_path.write_text(
        json.dumps({
            "Cocina": ["receta"],
            "Entrenamiento": ["rutina de ejercicios"],
            "Fuente Claude": ["provider=claude"],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    stats = oc.generate_topic_index(base_vault, topic_map_path)
    assert stats["temas"] == 3

    temas_dir = base_vault / "MERGED_VAULT" / "_Temas"

    cocina = (temas_dir / "cocina.md").read_text(encoding="utf-8")
    assert "[[pan-casero]]" in cocina
    assert "plan-deportivo" not in cocina

    entrenamiento = (temas_dir / "entrenamiento.md").read_text(encoding="utf-8")
    assert "[[plan-deportivo]]" in entrenamiento

    fuente_claude = (temas_dir / "fuente-claude.md").read_text(encoding="utf-8")
    assert "[[consulta-clima]]" in fuente_claude

    sin_tema = (temas_dir / "_sin-tema.md").read_text(encoding="utf-8")
    assert "## Sin ningun tema" in sin_tema
    assert "[[capital-francia]]" in sin_tema
    assert "## Solo pescadas por redes estructurales" in sin_tema
    assert "[[consulta-clima]]" in sin_tema
    # pan-casero y plan-deportivo tienen tema de contenido: no deben aparecer
    # en ninguna de las dos secciones de puntos ciegos.
    assert "pan-casero" not in sin_tema
    assert "plan-deportivo" not in sin_tema
