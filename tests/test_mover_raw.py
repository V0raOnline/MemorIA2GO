# -*- coding: utf-8 -*-
"""mover_raw.py: llevar el RAW a otra carpeta sin perder nada.

La promesa es la del pacto del pipeline aplicada a una migracion: el original no
se toca, y una copia solo cuenta cuando se ha COMPROBADO -- no cuando "no ha dado
error". Por eso la mitad de estos tests rompen la copia a proposito (contenido
truncado, fecha perdida) y exigen que la herramienta lo vea y no deje marcador.
"""
import os
import shutil
from pathlib import Path

import pytest

import layout as lay
import mover_raw as mr

FECHA_VIEJA = 1_600_000_000    # 2020-09-13: distinta de "ahora", para detectar una fecha perdida


@pytest.fixture
def vault(tmp_path):
    """Un vault clasico con un RAW de verdad: notas en subcarpetas, el registro de
    exports y una nota con acentos, todo con fechas de modificacion antiguas."""
    base = tmp_path / "vault"
    raw = base / "RAW_VAULT"
    ficheros = {
        "Conversaciones/2026/06/una.md": "---\ntitle: Una\n---\nHola\n",
        "Conversaciones/2026/07/otra-h1234abcd.md": "---\ntitle: Otra\n---\nQué tal, ñandú\n",
        "_exports_procesados.json": '{"export.zip": "2026-06-01"}',
        "_last_import.json": '{"timestamp": "2026-06-01T10:00:00"}',
    }
    for i, (rel, cuerpo) in enumerate(ficheros.items()):
        p = raw / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(cuerpo, encoding="utf-8")
        os.utime(p, (FECHA_VIEJA + i * 1000, FECHA_VIEJA + i * 1000))
    return base


def _arbol(raiz: Path):
    return {p.relative_to(raiz).as_posix(): p.read_bytes() for p in raiz.rglob("*") if p.is_file()}


def _mtimes(raiz: Path):
    return {p.relative_to(raiz).as_posix(): p.stat().st_mtime for p in raiz.rglob("*") if p.is_file()}


def test_dry_run_no_escribe_nada(vault, tmp_path):
    destino = tmp_path / "fuente"
    antes = _arbol(vault)
    assert mr.mover(vault, destino, dry_run=True, log=lambda *_: None) == 0
    assert not destino.exists()
    assert lay.leer_marcador(vault) is None
    assert _arbol(vault) == antes


def test_copia_identica_y_deja_el_marcador(vault, tmp_path):
    destino = tmp_path / "fuente"
    original = _arbol(vault / "RAW_VAULT")
    fechas = _mtimes(vault / "RAW_VAULT")

    assert mr.mover(vault, destino, log=lambda *_: None) == 0

    assert _arbol(destino) == original
    # la fecha de modificacion sobrevive: el merge decide por ella que titulo prevalece
    for rel, m in _mtimes(destino).items():
        assert abs(m - fechas[rel]) <= mr.TOLERANCIA_MTIME, rel
    # el marcador apunta ya a la nueva ubicacion, y cualquier herramienta la encuentra
    assert lay.cargar(vault, usar_entorno=False).ruta(vault, "raw") == destino


def test_no_borra_el_original(vault, tmp_path):
    antes = _arbol(vault / "RAW_VAULT")
    mr.mover(vault, tmp_path / "fuente", log=lambda *_: None)
    assert _arbol(vault / "RAW_VAULT") == antes, "el original no se toca; lo borra el usuario"


def test_repetirlo_no_hace_dano(vault, tmp_path):
    destino = tmp_path / "fuente"
    mr.mover(vault, destino, log=lambda *_: None)
    # el marcador ya dice que el RAW esta alli: no hay nada que mover
    with pytest.raises(mr.ErrorDeMovimiento, match="ya esta"):
        mr.mover(vault, destino, log=lambda *_: None)


def test_reanuda_una_copia_interrumpida(vault, tmp_path):
    """Si se corto a la mitad, volver a lanzarlo completa lo que falta y salta lo ya bueno."""
    destino = tmp_path / "fuente"
    raw = vault / "RAW_VAULT"
    ya = "Conversaciones/2026/06/una.md"
    (destino / ya).parent.mkdir(parents=True)
    shutil.copy2(raw / ya, destino / ya)
    # un .part huerfano de la ejecucion cortada no es un fichero ajeno
    (destino / "Conversaciones/2026/07").mkdir(parents=True)
    (destino / "Conversaciones/2026/07/otra-h1234abcd.md.part").write_bytes(b"a medias")

    mr.mover(vault, destino, log=lambda *_: None)

    assert _arbol(destino) == _arbol(raw)
    assert not list(destino.rglob("*.part"))


def test_rechaza_un_destino_con_ficheros_ajenos(vault, tmp_path):
    destino = tmp_path / "fuente"
    destino.mkdir()
    (destino / "mis_cosas.txt").write_text("no es del RAW", encoding="utf-8")
    with pytest.raises(mr.ErrorDeMovimiento, match="no es una carpeta limpia|no estan en el RAW"):
        mr.mover(vault, destino, log=lambda *_: None)
    assert lay.leer_marcador(vault) is None


def test_no_sobrescribe_un_fichero_distinto_del_destino(vault, tmp_path):
    destino = tmp_path / "fuente"
    rel = "Conversaciones/2026/06/una.md"
    (destino / rel).parent.mkdir(parents=True)
    (destino / rel).write_text("OTRO CONTENIDO", encoding="utf-8")
    with pytest.raises(mr.ErrorDeMovimiento, match="DISTINTO"):
        mr.mover(vault, destino, log=lambda *_: None)
    assert (destino / rel).read_text(encoding="utf-8") == "OTRO CONTENIDO"


@pytest.mark.parametrize("donde", ["dentro_del_raw", "contiene_al_raw", "es_la_base", "dentro_de_merged"])
def test_rechaza_destinos_que_no_son_seguros(vault, donde):
    destino = {
        "dentro_del_raw": vault / "RAW_VAULT" / "sub",
        "contiene_al_raw": vault,
        "es_la_base": vault,
        "dentro_de_merged": vault / "MERGED_VAULT" / "fuente",
    }[donde]
    with pytest.raises(mr.ErrorDeMovimiento):
        mr.mover(vault, destino, log=lambda *_: None)


def test_sin_raw_no_hay_nada_que_mover(tmp_path):
    base = tmp_path / "vault"
    base.mkdir()
    with pytest.raises(mr.ErrorDeMovimiento, match="no existe"):
        mr.mover(base, tmp_path / "fuente", log=lambda *_: None)


def test_sin_espacio_no_empieza(vault, tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "_espacio_libre", lambda _d: 0)
    with pytest.raises(mr.ErrorDeMovimiento, match="no hay sitio"):
        mr.mover(vault, tmp_path / "fuente", log=lambda *_: None)
    assert not (tmp_path / "fuente").exists()


# ---- la verificacion tiene que ver una copia rota ---------------------------

def test_una_copia_truncada_se_detecta_y_no_deja_marcador(vault, tmp_path, monkeypatch):
    def copia_rota(src, dst, *a, **k):
        Path(dst).write_bytes(Path(src).read_bytes()[:-3])   # pierde los ultimos bytes
        return dst
    monkeypatch.setattr(mr.shutil, "copy2", copia_rota)
    with pytest.raises(mr.ErrorDeMovimiento, match="verificacion ha fallado"):
        mr.mover(vault, tmp_path / "fuente", log=lambda *_: None)
    assert lay.leer_marcador(vault) is None, "con la copia sin verificar, el vault sigue apuntando al original"


def test_una_copia_con_el_mismo_tamano_pero_otro_contenido_se_detecta(vault, tmp_path, monkeypatch):
    """El tamano solo no basta: por eso se compara tambien el SHA-1."""
    def copia_corrupta(src, dst, *a, **k):
        datos = bytearray(Path(src).read_bytes())
        datos[0] ^= 0x01
        Path(dst).write_bytes(bytes(datos))
        shutil.copystat(src, dst)
        return dst
    monkeypatch.setattr(mr.shutil, "copy2", copia_corrupta)
    with pytest.raises(mr.ErrorDeMovimiento, match="verificacion ha fallado"):
        mr.mover(vault, tmp_path / "fuente", log=lambda *_: None)
    assert lay.leer_marcador(vault) is None


def test_una_copia_que_pierde_la_fecha_se_detecta(vault, tmp_path, monkeypatch):
    """El contenido es identico, pero el merge desempata por fecha de modificacion."""
    def copia_sin_fecha(src, dst, *a, **k):
        shutil.copyfile(src, dst)      # copia el contenido, no la fecha
        return dst
    monkeypatch.setattr(mr.shutil, "copy2", copia_sin_fecha)
    with pytest.raises(mr.ErrorDeMovimiento, match="verificacion ha fallado"):
        mr.mover(vault, tmp_path / "fuente", log=lambda *_: None)
    assert lay.leer_marcador(vault) is None


# ---- linea de ordenes -------------------------------------------------------

def test_main_devuelve_0_y_2(vault, tmp_path, capsys):
    destino = tmp_path / "fuente"
    assert mr.main(["--base-vault", str(vault), "--hacia", str(destino)]) == 0
    assert "Copia verificada" in capsys.readouterr().out
    assert mr.main(["--base-vault", str(vault), "--hacia", str(destino)]) == 2
    assert "✗" in capsys.readouterr().out
    assert mr.main(["--base-vault", str(tmp_path / "no_existe"), "--hacia", str(destino)]) == 2
