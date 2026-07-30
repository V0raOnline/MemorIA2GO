# -*- coding: utf-8 -*-
"""Tests de regresion de relink_assets.py (backlog CONTEXT.md seccion 3,
paso 6/6): herramienta reutilizable para reescribir enlaces cuando un
banco de assets cambia de nombre/carpeta. Diseño confirmado con V0ra
2026-07-22: reescritura masiva en las notas existentes, no symlinks de
compatibilidad, porque este tipo de reorganizacion ya es recurrente.
"""
import subprocess
import sys
from pathlib import Path

import pytest

import relink_assets as ra


def _write_note(path: Path, body: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_relink_file_reescribe_solo_los_enlaces_del_mapa(tmp_path):
    nota = tmp_path / "nota.md"
    _write_note(nota, (
        "### Assistant\n\n"
        "![](IMAGE_BANK/abc123.png)\n\n"
        "![](IMAGE_BANK/sindestino.png)\n\n"
        "texto normal sin enlaces\n"
    ))
    mapa = {"IMAGE_BANK/abc123.png": "CHATGPT/GENERADAS/abc123.png"}

    cambios = ra.relink_file(nota, mapa)

    assert cambios == 1
    texto = nota.read_text(encoding="utf-8")
    assert "![](CHATGPT/GENERADAS/abc123.png)" in texto
    assert "![](IMAGE_BANK/sindestino.png)" in texto  # sin mapeo, se queda igual


def test_relink_file_no_toca_wikilinks(tmp_path):
    nota = tmp_path / "nota.md"
    _write_note(nota, "Ver [[IMAGE_BANK/abc123.png]] y ![](IMAGE_BANK/abc123.png)\n")
    mapa = {"IMAGE_BANK/abc123.png": "CHATGPT/GENERADAS/abc123.png"}

    ra.relink_file(nota, mapa)

    texto = nota.read_text(encoding="utf-8")
    assert "[[IMAGE_BANK/abc123.png]]" in texto  # wikilink intacto
    assert "![](CHATGPT/GENERADAS/abc123.png)" in texto  # embed reescrito


def test_relink_file_sin_cambios_no_reescribe_el_archivo(tmp_path):
    nota = tmp_path / "nota.md"
    _write_note(nota, "sin ningun enlace de imagen\n")
    mtime_antes = nota.stat().st_mtime

    cambios = ra.relink_file(nota, {"IMAGE_BANK/x.png": "CHATGPT/GENERADAS/x.png"})

    assert cambios == 0
    assert nota.stat().st_mtime == mtime_antes


def test_relink_vault_recorre_recursivamente_y_suma_stats(tmp_path):
    _write_note(tmp_path / "Conversaciones" / "2026" / "07" / "a.md",
                "![](IMAGE_BANK/uno.png)\n![](IMAGE_BANK/dos.png)\n")
    _write_note(tmp_path / "Conversaciones" / "2026" / "07" / "b.md",
                "sin enlaces\n")
    mapa = {"IMAGE_BANK/uno.png": "CHATGPT/GENERADAS/uno.png",
            "IMAGE_BANK/dos.png": "CHATGPT/ADJUNTOS/dos.png"}

    stats = ra.relink_vault(tmp_path, mapa)

    assert stats["archivos_escaneados"] == 2
    assert stats["archivos_tocados"] == 1
    assert stats["enlaces_reescritos"] == 2


def test_relink_vault_no_revienta_con_junction_colgando(tmp_path):
    """Bug real 2026-07-22: un junction legado (RAW_VAULT/_assets ->
    IMAGE_BANK) quedo apuntando a una carpeta ya borrada tras mover su
    contenido a la taxonomia nueva -- Path.rglob('*.md') reventaba con
    FileNotFoundError en cuanto lo pisaba, matando el escaneo entero antes
    de llegar a las notas reales. Reproduce el junction roto de verdad
    (mklink /J, la tecnica que en su dia usaba MemorIA2GO.py para el
    junction _assets, ya retirado del pipeline) en vez de mockear -- si el
    entorno no permite crear junctions, se salta."""
    if sys.platform != "win32":
        pytest.skip("junctions son un concepto especifico de Windows")

    _write_note(tmp_path / "Conversaciones" / "real.md", "![](IMAGE_BANK/uno.png)\n")

    destino_inexistente = tmp_path / "no_existe" / "IMAGE_BANK"
    junction = tmp_path / "_assets"
    resultado = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(destino_inexistente)],
        capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        pytest.skip(f"no se pudo crear el junction de prueba: {resultado.stderr.strip()}")

    mapa = {"IMAGE_BANK/uno.png": "CHATGPT/GENERADAS/uno.png"}
    stats = ra.relink_vault(tmp_path, mapa)  # no debe lanzar FileNotFoundError

    assert stats["archivos_escaneados"] == 1
    assert stats["enlaces_reescritos"] == 1


def test_relink_vault_dry_run_no_escribe_nada(tmp_path):
    nota = tmp_path / "a.md"
    _write_note(nota, "![](IMAGE_BANK/uno.png)\n")
    mapa = {"IMAGE_BANK/uno.png": "CHATGPT/GENERADAS/uno.png"}

    stats = ra.relink_vault(tmp_path, mapa, dry_run=True)

    assert stats["enlaces_reescritos"] == 1
    assert "IMAGE_BANK/uno.png" in nota.read_text(encoding="utf-8")  # intacto


def test_relink_reescribe_enlaces_de_fichero_no_solo_imagenes(tmp_path):
    """Bug real (cazado 2026-07-30 preparando el renombrado de carpetas):
    la herramienta nacio cuando los bancos solo tenian imagenes, asi que su
    patron era ![](ruta) y solo eso. Despues llegaron CLAUDE/ARTEFACTOS
    (SIEMPRE [texto](ruta), nunca imagen) y los adjuntos no-imagen de Grok.
    Contra el vault real: los 16 artefactos y 4 de los 16 adjuntos de Grok
    usan la forma de enlace -- al mover un banco se quedaban apuntando a la
    carpeta vieja SIN aviso, que es la peor manera de fallar."""
    nota = tmp_path / "a.md"
    _write_note(nota, (
        "![](CLAUDE/ARTEFACTOS/codigo/script.py)\n\n"
        "🧩 Artefacto: **Mi script** → [script.py](CLAUDE/ARTEFACTOS/codigo/script.py)\n"
    ))
    mapa = {"CLAUDE/ARTEFACTOS/codigo/script.py": "CLAUDE/ARTIFACTS/code/script.py"}

    stats = ra.relink_vault(tmp_path, mapa)
    texto = nota.read_text(encoding="utf-8")

    assert stats["enlaces_reescritos"] == 2, "la forma [texto](ruta) se quedo sin reescribir"
    assert "CLAUDE/ARTEFACTOS" not in texto
    assert "[script.py](CLAUDE/ARTIFACTS/code/script.py)" in texto
    assert "![](CLAUDE/ARTIFACTS/code/script.py)" in texto


def test_relink_no_toca_wikilinks(tmp_path):
    """El contrato de la herramienta: nunca [[wikilinks]] ni texto normal.
    Ampliar el patron a [texto](ruta) no debe romper esa promesa."""
    nota = tmp_path / "a.md"
    _write_note(nota, "[[CLAUDE/ARTEFACTOS/codigo/script.py]]\n\nCLAUDE/ARTEFACTOS suelto\n")
    mapa = {"CLAUDE/ARTEFACTOS/codigo/script.py": "CLAUDE/ARTIFACTS/code/script.py"}

    stats = ra.relink_vault(tmp_path, mapa)

    assert stats["enlaces_reescritos"] == 0
    assert "[[CLAUDE/ARTEFACTOS/codigo/script.py]]" in nota.read_text(encoding="utf-8")


def test_relink_dry_run_cuenta_las_dos_formas(tmp_path):
    nota = tmp_path / "a.md"
    _write_note(nota, "![](GROK/ADJUNTOS/foto.jpg)\n\n[informe.pdf](GROK/ADJUNTOS/informe.pdf)\n")
    mapa = {
        "GROK/ADJUNTOS/foto.jpg": "GROK/ATTACHMENTS/foto.jpg",
        "GROK/ADJUNTOS/informe.pdf": "GROK/ATTACHMENTS/informe.pdf",
    }

    stats = ra.relink_vault(tmp_path, mapa, dry_run=True)

    assert stats["enlaces_reescritos"] == 2
    assert "GROK/ADJUNTOS" in nota.read_text(encoding="utf-8")  # intacto
