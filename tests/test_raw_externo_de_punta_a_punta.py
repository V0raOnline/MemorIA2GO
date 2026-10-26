# -*- coding: utf-8 -*-
"""El RAW fuera del vault, con el pipeline REAL (subproceso, como el launcher).

Tres cosas que ningun test unitario ve:

  1. Con `raw_vault` puesto, el RAW nace en esa carpeta y NO en base_vault: ni
     una carpeta RAW_VAULT a la vista de Obsidian.
  2. El ciclo de V0ra: vault ya construido -> mover_raw -> seguir importando. El
     merge tiene que seguir viendo las conversaciones anteriores (si no, la
     fusion se partiria sin un solo error) y no se reimporta nada.
  3. El pipeline se NIEGA a seguir cuando config y vault discrepan, y cuando la
     fuente ha desaparecido, y en ambos casos no escribe nada.
"""
import json
import shutil
import zipfile
from pathlib import Path

import pytest

import layout as lay
import mover_raw
import vault_stats

from test_layout_de_punta_a_punta import (USER, U_ADJ, U_IMG, PNG, PNG2, _enlaces_a_ficheros,
                                            _ejecutar, _export_grok)


def _export_grok_2(destino: Path) -> Path:
    """Un segundo export con OTRA conversacion: llega despues, en otra importacion."""
    cuerpo = {
        "conversations": [{
            "conversation": {"id": "c2", "title": "Segunda conversacion",
                              "create_time": "2026-07-10T08:00:00Z",
                              "modify_time": "2026-07-10T08:10:00Z", "leaf_response_id": None},
            "responses": [
                {"response": {"_id": "q1", "parent_response_id": None, "sender": "human",
                              "message": "Otra cosa distinta",
                              "create_time": {"$date": {"$numberLong": "1773000000000"}},
                              "model": ""}, "share_link": None},
                {"response": {"_id": "q2", "parent_response_id": "q1", "sender": "ASSISTANT",
                              "message": "De acuerdo.",
                              "create_time": {"$date": {"$numberLong": "1773000300000"}},
                              "model": "grok-4"}, "share_link": None},
            ],
        }],
        "projects": [], "tasks": [], "media_posts": [],
    }
    z = destino / "grok_export_2.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(f"ttl/30d/export_data/{USER}/prod-grok-backend.json", json.dumps(cuerpo))
    return z


def _cfg(tmp_path: Path, base: Path, exports: Path, raw_vault=None) -> Path:
    cfg = tmp_path / "memoria_config.yaml"
    raw = f"  raw_vault: '{Path(raw_vault).as_posix()}'\n" if raw_vault else ""
    cfg.write_text(
        "paths:\n"
        f"  base_vault: '{base.as_posix()}'\n"
        f"  exports_dir: '{exports.as_posix()}'\n"
        f"{raw}"
        "options:\n  by_year: true\n  by_month: true\n  make_index: true\n",
        encoding="utf-8")
    return cfg


def _salida(r) -> str:
    return (r.stdout or "") + (r.stderr or "")


def _notas(carpeta: Path):
    return sorted(p.name for p in carpeta.rglob("*.md"))


@pytest.fixture
def entorno(tmp_path):
    exports = tmp_path / "exports"
    base = tmp_path / "vault"
    exports.mkdir()
    base.mkdir()
    _export_grok(exports)
    return tmp_path, base, exports


def test_con_raw_vault_la_fuente_nace_fuera_del_vault(entorno):
    tmp, base, exports = entorno
    fuera = tmp / "fuera" / "fuente"
    r = _ejecutar(_cfg(tmp, base, exports, raw_vault=fuera))
    assert r.returncode == 0, _salida(r)[-2500:]

    # la fuente esta donde se pidio, con sus notas y su estado
    assert _notas(fuera / "Conversaciones"), "no hay notas en la fuente externa"
    assert (fuera / "_exports_procesados.json").is_file()
    # y NADA de RAW a la vista del vault
    assert not (base / "RAW_VAULT").exists(), "ha nacido un RAW_VAULT dentro del vault"
    # el resto del pipeline funciona igual: fusion, proyectos, indices
    assert _notas(base / "MERGED_VAULT" / "Conversaciones")
    assert (base / "MERGED_VAULT" / "_index_grok.md").is_file()
    # y el marcador deja constancia de donde esta la fuente
    assert lay.leer_marcador(base).ruta(base, "raw") == fuera


def test_los_enlaces_de_las_notas_siguen_resolviendo(entorno):
    tmp, base, exports = entorno
    r = _ejecutar(_cfg(tmp, base, exports, raw_vault=tmp / "fuera" / "fuente"))
    assert r.returncode == 0, _salida(r)[-2000:]
    enlaces = _enlaces_a_ficheros(base, base / "MERGED_VAULT")
    assert enlaces, "no hay enlaces a assets: el test no probaria nada"
    rotos = [f"{n.name} -> {x}" for n, x in enlaces if not (base / x).is_file()]
    assert not rotos, rotos


def test_una_segunda_pasada_no_reimporta_ni_crea_otro_raw(entorno):
    tmp, base, exports = entorno
    cfg = _cfg(tmp, base, exports, raw_vault=tmp / "fuera" / "fuente")
    assert _ejecutar(cfg).returncode == 0
    antes = _notas(tmp / "fuera" / "fuente" / "Conversaciones")
    r = _ejecutar(cfg)
    assert r.returncode == 0, _salida(r)[-1500:]
    assert "al d" in _salida(r), "deberia decir que no hay exports nuevos (el registro vive en la fuente)"
    assert _notas(tmp / "fuera" / "fuente" / "Conversaciones") == antes
    assert not (base / "RAW_VAULT").exists()


def test_las_estadisticas_encuentran_la_fuente_externa(entorno):
    tmp, base, exports = entorno
    assert _ejecutar(_cfg(tmp, base, exports, raw_vault=tmp / "fuera" / "fuente")).returncode == 0
    s = vault_stats.compute_stats(base)
    assert s["vaults"]["RAW_VAULT"]["existe"] is True and s["vaults"]["RAW_VAULT"]["notas"] >= 1
    assert s["ultima_importacion"] is not None, "el estado de la ultima importacion vive en la fuente"


# ---- el ciclo de V0ra: vault ya construido -> mover -> seguir --------------

def test_ciclo_completo_vault_existente_mover_y_seguir_importando(entorno):
    tmp, base, exports = entorno
    # 1. un vault construido como siempre, con su RAW dentro
    assert _ejecutar(_cfg(tmp, base, exports)).returncode == 0
    raw_dentro = base / "RAW_VAULT"
    notas_antes = _notas(raw_dentro / "Conversaciones")
    assert notas_antes

    # 2. se mueve la fuente (copia + verificacion; el original no se toca)
    fuera = tmp / "fuera" / "fuente"
    assert mover_raw.mover(base, fuera, log=lambda *_: None) == 0
    assert raw_dentro.exists(), "mover_raw no borra el original"

    # 3. el usuario pone raw_vault en su config; el pipeline sigue y no reimporta nada
    cfg = _cfg(tmp, base, exports, raw_vault=fuera)
    r = _ejecutar(cfg)
    assert r.returncode == 0, _salida(r)[-2000:]
    assert "al d" in _salida(r), "el registro de exports debia viajar con la fuente"
    assert _notas(fuera / "Conversaciones") == notas_antes

    # 4. llega un export NUEVO: va a la fuente externa y el merge sigue viendo las conversaciones anteriores
    _export_grok_2(exports)
    r = _ejecutar(cfg)
    assert r.returncode == 0, _salida(r)[-2000:]
    assert len(_notas(fuera / "Conversaciones")) == len(notas_antes) + 1
    assert len(_notas(base / "MERGED_VAULT" / "Conversaciones")) == 2, \
        "la fusion deberia contener las DOS conversaciones: la anterior y la nueva"
    # y el RAW antiguo no ha recibido nada: la fuente ya es la externa
    assert _notas(raw_dentro / "Conversaciones") == notas_antes


# ---- el pipeline se niega, y no escribe nada --------------------------------

def test_config_con_otro_raw_que_el_vault_se_niega_y_no_escribe_nada(entorno):
    tmp, base, exports = entorno
    assert _ejecutar(_cfg(tmp, base, exports)).returncode == 0
    fuera = tmp / "fuera" / "fuente"
    raw_antes = _notas(base / "RAW_VAULT" / "Conversaciones")
    _export_grok_2(exports)                       # hay algo nuevo que importar: tentacion de seguir

    r = _ejecutar(_cfg(tmp, base, exports, raw_vault=fuera))

    assert r.returncode == 2, _salida(r)[-1500:]
    assert "mover_raw.py" in _salida(r)
    assert not fuera.exists(), "se ha creado la fuente nueva pese al conflicto"
    assert _notas(base / "RAW_VAULT" / "Conversaciones") == raw_antes, "se ha importado a medias"


def test_quitar_raw_vault_de_la_config_con_el_marcador_externo_se_niega(entorno):
    tmp, base, exports = entorno
    fuera = tmp / "fuera" / "fuente"
    assert _ejecutar(_cfg(tmp, base, exports, raw_vault=fuera)).returncode == 0
    _export_grok_2(exports)

    r = _ejecutar(_cfg(tmp, base, exports))       # config SIN raw_vault

    assert r.returncode == 2, _salida(r)[-1500:]
    assert not (base / "RAW_VAULT").exists(), "ha creado un RAW nuevo dentro del vault"
    assert len(_notas(fuera / "Conversaciones")) == 1


def test_fuente_desconectada_no_se_recrea_en_silencio(entorno):
    tmp, base, exports = entorno
    fuera = tmp / "unidad" / "fuente"
    cfg = _cfg(tmp, base, exports, raw_vault=fuera)
    assert _ejecutar(cfg).returncode == 0
    _export_grok_2(exports)

    oculta = tmp / "unidad_desenchufada"
    shutil.move(str(tmp / "unidad"), str(oculta))          # "se desconecta el disco"
    r = _ejecutar(cfg)
    assert r.returncode == 2, _salida(r)[-1500:]
    assert "no existe" in _salida(r)
    assert not (tmp / "unidad").exists(), "ha recreado la fuente en el disco desconectado"

    shutil.move(str(oculta), str(tmp / "unidad"))          # "se vuelve a conectar"
    assert _ejecutar(cfg).returncode == 0
    assert len(_notas(fuera / "Conversaciones")) == 2


def test_una_fuente_invalida_se_rechaza_antes_de_empezar(entorno):
    tmp, base, exports = entorno
    r = _ejecutar(_cfg(tmp, base, exports, raw_vault=base / "MERGED_VAULT" / "fuente"))
    assert r.returncode == 2, _salida(r)[-1500:]
    assert not (base / "MERGED_VAULT").exists(), "ha escrito algo pese a ser un destino invalido"
