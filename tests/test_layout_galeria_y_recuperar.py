# -*- coding: utf-8 -*-
"""La galeria y la recuperacion de imagenes con un layout que no es el de siempre.

Las dos se escribieron cuando el vault solo tenia una forma (MERGED_VAULT/Conversaciones, bancos en
CHATGPT/...). Con el preset «por proveedor» las conversaciones viven en una carpeta por proveedor, y
con el RAW externo la fuente esta fuera de la base. Si alguna siguiera mirando solo la carpeta de
siempre, no daria ningun error: la galeria saldria sin conversaciones y la recuperacion diria que no
hay nada que reparar. Por eso se prueba con el pipeline REAL y se compara contra el preset de siempre.
"""
import json
import os
from pathlib import Path

import pytest

import galeria as gal
import layout as lay
import recuperar_imagenes as rec
from test_presets_de_punta_a_punta import _montar_y_ejecutar
from test_recuperar_imagenes import (FECHA_VIEJA, JPG, PNG, _conv, _fusionar, _importar, _notas, _zip)


# ---- la galeria, con el pipeline entero -------------------------------------------------
@pytest.fixture(scope="module")
def vaults(tmp_path_factory):
    """El mismo material construido con el preset de siempre y con el que parte MERGED por proveedor."""
    hechos = {}
    for preset in ("proyectos", "proveedor"):
        _tmp, base, _cfg, r = _montar_y_ejecutar(tmp_path_factory, f"galeria_{preset}", preset)
        assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-800:]
        hechos[preset] = base
    return hechos


def _sin_entorno(monkeypatch):
    # La galeria la lanza el launcher o la consola: el layout sale del marcador del vault.
    monkeypatch.delenv(lay.ENV_LAYOUT, raising=False)


def test_por_proveedor_la_galeria_encuentra_las_mismas_imagenes_y_conversaciones(vaults, monkeypatch):
    _sin_entorno(monkeypatch)
    clasico, partido = gal.recoger(vaults["proyectos"]), gal.recoger(vaults["proveedor"])
    con_conv = [it for it in partido if it.get("conv")]
    assert con_conv, "el fixture tiene adjuntos enlazados desde sus notas: alguno tiene que tener conversacion"
    assert len(partido) == len(clasico)
    assert len(con_conv) == len([it for it in clasico if it.get("conv")])
    assert sorted(it["ruta"] for it in partido) == sorted(it["ruta"] for it in clasico)


def test_por_proveedor_la_nota_de_cada_imagen_es_la_de_la_carpeta_de_su_proveedor(vaults, monkeypatch):
    _sin_entorno(monkeypatch)
    base = vaults["proveedor"]
    for it in gal.recoger(base):
        if not it.get("conv"):
            continue
        nota = it["conv"]["nota"]
        carpeta = lay.carpeta_proveedor(it["conv"]["proveedor"])
        assert nota.startswith(f"MERGED_VAULT/{carpeta}/Conversaciones/"), nota
        assert (base / f"{nota}.md").is_file(), nota


def test_por_proveedor_la_galeria_se_genera_entera(vaults, monkeypatch, tmp_path):
    _sin_entorno(monkeypatch)
    r = gal.generar(vaults["proveedor"], tmp_path / "g", miniaturas=False, log=lambda *_: None)
    assert r["items"] == len(gal.recoger(vaults["proyectos"]))
    assert r["con_conversacion"] > 0
    assert (tmp_path / "g" / "index.html").is_file()


def test_la_galeria_usa_los_bancos_del_layout_y_no_los_de_siempre(tmp_path, monkeypatch):
    """Un vault con bancos renombrados: si la galeria tuviera un nombre a mano, no veria nada."""
    _sin_entorno(monkeypatch)
    otro = lay.Layout({"chatgpt.raiz": "OAI", "chatgpt.generadas": "{chatgpt.raiz}/hechas",
                       "merged": "FUSION", "conversaciones": "Charlas"}, preset="de-prueba")
    lay.escribir_marcador(tmp_path, otro)
    (tmp_path / "OAI" / "hechas").mkdir(parents=True)
    (tmp_path / "OAI" / "hechas" / "aaaa.png").write_bytes(PNG)
    nota = tmp_path / "FUSION" / "Charlas" / "n.md"
    nota.parent.mkdir(parents=True)
    nota.write_text('---\ntitle: "Con imagen"\ndate: 2026-10-01\n---\n\n### User\nhaz un faro\n\n'
                    "### Assistant\n![](OAI/hechas/aaaa.png)\n", encoding="utf-8")
    items = gal.recoger(tmp_path)
    assert [it["ruta"] for it in items] == ["OAI/hechas/aaaa.png"]
    assert items[0]["conv"]["titulo"] == "Con imagen"


# ---- la recuperacion -----------------------------------------------------------------
def _construir(tmp_path, monkeypatch, layout_, raw: Path):
    """Un vault construido por el pipeline REAL con `layout_`, a partir de un export sin los binarios
    de las imagenes (el bug que repara recuperar_imagenes), y el export completo."""
    base = tmp_path / "vault"
    base.mkdir()
    lay.escribir_marcador(base, layout_)
    monkeypatch.setenv(lay.ENV_LAYOUT, lay.entorno(layout_)[lay.ENV_LAYOUT])   # como el orquestador a sus hijos
    convs = [_conv([("sediment://file_aaa", False), ("file-service://file-bbb", True)])]
    completo = _zip(tmp_path / "completo.zip", convs, {"file_aaa.dat": PNG, "file-bbb.dat": JPG})
    sin_binarios = _zip(tmp_path / "sin_binarios.zip", convs, {})
    _importar(sin_binarios, raw / "Conversaciones", base)
    _fusionar(raw, layout_.ruta(base, "merged"))
    monkeypatch.delenv(lay.ENV_LAYOUT)                 # desde aqui, el layout sale del marcador
    for n in _notas(raw) + _notas(layout_.ruta(base, "merged")):
        os.utime(n, (FECHA_VIEJA, FECHA_VIEJA))
    return base, completo


def test_por_proveedor_recupera_las_notas_de_la_carpeta_de_su_proveedor(tmp_path, monkeypatch):
    partido = lay.Layout(preset="proveedor")
    base, completo = _construir(tmp_path, monkeypatch, partido, tmp_path / "vault" / "RAW_VAULT")
    fusionadas = _notas(base / "MERGED_VAULT" / "ChatGPT" / "Conversaciones")
    assert fusionadas, "con el preset por proveedor, la nota fusionada vive en la carpeta de ChatGPT"
    assert not (base / "MERGED_VAULT" / "Conversaciones").exists()

    r = rec.recuperar(completo, base, aplicar=True, carpeta_logs=tmp_path / "logs", log=lambda *_: None)
    assert r["notas_cambiadas"] == 2                  # la de RAW y la fusionada
    for n in fusionadas:
        t = n.read_text(encoding="utf-8")
        assert "imagen no disponible" not in t
        assert t.count("![](CHATGPT/") == 2


def test_con_el_raw_fuera_de_la_base_recupera_y_deshace_tambien_alli(tmp_path, monkeypatch):
    fuera = tmp_path / "fuente_externa"
    externo = lay.Layout(externas={"raw": str(fuera)})
    base, completo = _construir(tmp_path, monkeypatch, externo, fuera)
    nota_raw = _notas(fuera / "Conversaciones")[0]
    antes = nota_raw.read_bytes()
    assert b"imagen no disponible" in antes

    r = rec.recuperar(completo, base, aplicar=True, carpeta_logs=tmp_path / "logs", log=lambda *_: None)
    assert r["notas_cambiadas"] == 2
    assert b"imagen no disponible" not in nota_raw.read_bytes()
    diario = json.loads((Path(r["copia"]) / "diario.json").read_text(encoding="utf-8"))
    assert list(diario["externas"].values()) == [str(nota_raw)]

    assert rec.deshacer(Path(r["copia"]), log=lambda *_: None) == 2
    assert nota_raw.read_bytes() == antes
    assert int(nota_raw.stat().st_mtime) == FECHA_VIEJA
