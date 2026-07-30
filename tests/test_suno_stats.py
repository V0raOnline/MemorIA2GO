# -*- coding: utf-8 -*-
"""Tests de suno_stats.py — tarjeta de la biblioteca de Suno en el
Observatorio.

Los fixtures reproducen la forma REAL de `_index.json` (verificada contra
las 2094 pistas de V0ra, 2026-07-30), no la que decia la documentacion.
Las dos diferencias que importan y que aqui quedan fijadas:

  - `duration` cuelga de `metadata`, no del nivel superior.
  - `metadata.task` NO sirve para clasificar: `gen` no aparece nunca en
    datos reales y 1151 de 2094 pistas lo traen a None. Por eso las
    cuentas se hacen por badge y por booleanos de nivel superior.
"""
import json
from pathlib import Path

import pytest

import launcher
import suno_stats


def _clip(**kw):
    """Pista con la forma real: lo que cuelga de metadata, en metadata."""
    meta = {
        "duration": kw.pop("duration", 120.0),
        "task": kw.pop("task", None),          # None es el caso MAYORITARIO
        "secondary_badges": kw.pop("badges", []),
        "prompt": "[Verse]\nletra",
        "tags": "synthwave",
    }
    clip = {
        "id": kw.pop("id", "abc"),
        "title": kw.pop("title", "Una cancion"),
        "is_liked": kw.pop("is_liked", False),
        "is_trashed": kw.pop("is_trashed", False),
        "project": kw.pop("project", None),
        "metadata": meta,
    }
    clip.update(kw)
    return clip


def _index(tmp_path: Path, clips: list) -> Path:
    backup = tmp_path / "suno_backup"
    backup.mkdir()
    (backup / "_index.json").write_text(json.dumps(clips), encoding="utf-8")
    return backup


def test_sin_backup_devuelve_none(tmp_path):
    """Sin backup, la tarjeta no se pinta -- no se pinta a cero, que seria
    mentir sobre una biblioteca que no se ha descargado."""
    assert suno_stats.compute_suno_stats(tmp_path / "no-existe") is None
    assert suno_stats.compute_suno_stats(None) is None


def test_index_corrupto_no_revienta(tmp_path):
    """El dashboard entero no puede caerse porque un JSON este a medias."""
    backup = tmp_path / "suno_backup"
    backup.mkdir()
    (backup / "_index.json").write_text("{ esto no es json", encoding="utf-8")

    assert suno_stats.compute_suno_stats(backup) is None


def test_cuenta_total_favoritas_y_completas(tmp_path):
    backup = _index(tmp_path, [
        _clip(id="1", is_liked=True, badges=[{"display_name": "Full Song"}]),
        _clip(id="2", is_liked=True),
        _clip(id="3", badges=[{"display_name": "Cover"}]),
        _clip(id="4"),
    ])

    s = suno_stats.compute_suno_stats(backup)

    assert s["total"] == 4
    assert s["favoritas"] == 2
    assert s["completas"] == 1


def test_duracion_se_lee_de_metadata_no_del_nivel_superior(tmp_path):
    """El bug que habria salido de fiarse de la documentacion, que listaba
    'duration' como campo de nivel superior. Cada pista lleva un 'duration'
    ARRIBA con un valor absurdo: si el codigo lee el de arriba la suma se
    dispara, si lee el de metadata sale la correcta. Un fixture que solo
    omitiera el campo de arriba no distinguiria 'lee el correcto' de 'no
    encuentra ninguno'."""
    def _con_senuelo(sid):
        c = _clip(id=sid, duration=1800.0)
        c["duration"] = 999999      # el campo que decia la documentacion
        return c

    backup = _index(tmp_path, [_con_senuelo("1"), _con_senuelo("2")])

    s = suno_stats.compute_suno_stats(backup)

    assert s["duracion_segundos"] == 3600
    assert s["duracion_legible"] == "1 h"


def test_duracion_ausente_o_basura_no_rompe_la_suma(tmp_path):
    backup = _index(tmp_path, [
        _clip(id="1", duration=60.0),
        _clip(id="2", duration=None),
        _clip(id="3", duration="no soy un numero"),
    ])

    s = suno_stats.compute_suno_stats(backup)

    assert s["total"] == 3
    assert s["duracion_segundos"] == 60


def test_la_papelera_no_cuenta_como_biblioteca(tmp_path):
    backup = _index(tmp_path, [
        _clip(id="1"),
        _clip(id="2", is_trashed=True, is_liked=True, duration=600.0),
    ])

    s = suno_stats.compute_suno_stats(backup)

    assert s["total"] == 1
    assert s["favoritas"] == 0
    assert s["duracion_segundos"] == 120


def test_proyectos_se_cuentan_por_nombre_distinto(tmp_path):
    backup = _index(tmp_path, [
        _clip(id="1", project={"id": "p1", "name": "Glitch"}),
        _clip(id="2", project={"id": "p1", "name": "Glitch"}),
        _clip(id="3", project={"id": "p2", "name": "Koru"}),
        _clip(id="4"),
    ])

    s = suno_stats.compute_suno_stats(backup)

    assert s["proyectos"] == 2
    assert s["sin_proyecto"] == 1


def test_proyecto_sin_nombre_no_cuenta_como_proyecto(tmp_path):
    """Pasa de verdad en los datos de V0ra: hay objetos project sin name.
    Un proyecto sin nombre no es un proyecto -- va a 'sin proyecto', que es
    lo que hace cuadrar la cuenta con los 29 que ella ya tenia contados."""
    backup = _index(tmp_path, [
        _clip(id="1", project={"id": "p1", "name": ""}),
        _clip(id="2", project={"id": "p2", "name": "Koru"}),
    ])

    s = suno_stats.compute_suno_stats(backup)

    assert s["proyectos"] == 1
    assert s["sin_proyecto"] == 1


def test_task_no_influye_en_ninguna_cuenta(tmp_path):
    """Fija la decision: task esta documentado como gen/cover/mashup pero
    en datos reales trae None, cadena vacia y seis valores mas. No se usa
    para clasificar nada, para que anadir un valor nuevo en Suno no
    desajuste la tarjeta en silencio."""
    backup = _index(tmp_path, [
        _clip(id="1", task=None, is_liked=True),
        _clip(id="2", task="", is_liked=True),
        _clip(id="3", task="artist_consistency", is_liked=True),
        _clip(id="4", task="un_task_que_suno_invente_manana", is_liked=True),
    ])

    s = suno_stats.compute_suno_stats(backup)

    assert s["total"] == 4
    assert s["favoritas"] == 4


def test_biblioteca_vacia_devuelve_ceros_no_none(tmp_path):
    """Distinto de 'no hay backup': un backup vacio SI es informacion."""
    backup = _index(tmp_path, [])

    s = suno_stats.compute_suno_stats(backup)

    assert s is not None
    assert s["total"] == 0
    assert s["duracion_legible"] == "0 min"


def test_duracion_corta_se_muestra_en_minutos(tmp_path):
    backup = _index(tmp_path, [_clip(id="1", duration=900.0)])

    assert suno_stats.compute_suno_stats(backup)["duracion_legible"] == "15 min"


# ─────────────────────────────────────────
# Integracion con /api/stats
# ─────────────────────────────────────────

def _config(tmp_path, suno_backup=""):
    cfg = tmp_path / "memoria_config.yaml"
    vault = tmp_path / "vault"
    (vault / "MERGED_VAULT").mkdir(parents=True, exist_ok=True)
    cfg.write_text(f"""
paths:
  base_vault: '{vault}'
  exports_dir: '{tmp_path}'
  gizmo_map: ''
  suno_backup: '{suno_backup}'
options:
  prj_vault_name: 'PRJ_VAULT'
""", encoding="utf-8")
    return cfg


@pytest.fixture
def client(tmp_path, monkeypatch):
    def _build(suno_backup=""):
        monkeypatch.setattr(launcher, "CONFIG_PATH", _config(tmp_path, suno_backup))
        launcher.app.config["TESTING"] = True
        return launcher.app.test_client()
    return _build


def test_stats_sin_suno_configurado_no_manda_la_clave(client):
    """Sin ruta configurada, 'suno' no viaja -- la tarjeta no se pinta."""
    data = client().get("/api/stats?refresh=1").get_json()

    assert "suno" not in data


def test_stats_con_backup_incluye_la_biblioteca(client, tmp_path):
    backup = _index(tmp_path, [
        _clip(id="1", is_liked=True, duration=1800.0,
              badges=[{"display_name": "Full Song"}],
              project={"id": "p", "name": "Koru"}),
        _clip(id="2", duration=1800.0),
    ])

    data = client(str(backup)).get("/api/stats?refresh=1").get_json()

    assert data["suno"]["total"] == 2
    assert data["suno"]["favoritas"] == 1
    assert data["suno"]["completas"] == 1
    assert data["suno"]["duracion_legible"] == "1 h"


def test_stats_con_ruta_que_no_existe_no_revienta(client, tmp_path):
    """Ruta configurada pero backup borrado/movido: el dashboard sigue
    sirviendo el resto."""
    data = client(str(tmp_path / "no-existe")).get("/api/stats?refresh=1").get_json()

    assert "error" not in data
    assert "suno" not in data


def test_las_stats_de_suno_no_entran_en_el_cache_del_vault(client, tmp_path):
    """El cache lo escribe el paso 4 del pipeline; la biblioteca de Suno
    cambia por su cuenta, con otra herramienta y en otro momento. Si se
    cachearan, quedarian rancias justo despues de un backup -- que es
    cuando mas quieres mirarlas. Este test lo fija: se anaden DESPUES de
    leer el cache, asi que un backup nuevo se ve sin --refresh."""
    backup_dir = tmp_path / "suno_backup"
    c = client(str(backup_dir))

    backup_dir.mkdir()
    (backup_dir / "_index.json").write_text(json.dumps([_clip(id="1")]), encoding="utf-8")
    primera = c.get("/api/stats?refresh=1").get_json()      # escribe cache
    assert primera["suno"]["total"] == 1

    # Llega un backup nuevo. El cache del vault sigue siendo el de antes.
    (backup_dir / "_index.json").write_text(
        json.dumps([_clip(id="1"), _clip(id="2")]), encoding="utf-8")
    segunda = c.get("/api/stats").get_json()                # SIN refresh

    assert segunda["suno"]["total"] == 2
