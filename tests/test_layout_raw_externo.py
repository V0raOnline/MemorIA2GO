# -*- coding: utf-8 -*-
"""RAW en ubicacion propia, y la validacion de nombres para Windows.

Lo que se protege es un fallo que no da error: con la fuente RAW en un sitio
distinto del que el vault ya tiene, el pipeline escribiria las notas nuevas en un
RAW vacio, el merge solo veria esas y las anteriores quedarian fuera de la fusion.
Por eso `conflictos` es lo importante de este fichero.
"""
import json
import os
from pathlib import Path

import pytest

import layout as lay
from layout import Layout, LayoutError


# ---- nombres que Windows recorta o reserva -------------------------------

@pytest.mark.parametrize("nombre,fragmento", [
    ("MERGED.", "ends in a dot or a space"),
    ("carpeta /sub", "ends in a dot or a space"),
    ("NUL", "reserved"),
    ("com3.txt", "reserved"),
    ("bien/aux", "reserved"),
    ("con\x07trol", "not valid on Windows"),
])
def test_nombres_que_windows_recorta_o_reserva_se_rechazan(nombre, fragmento):
    malos = Layout({"merged": nombre}).problemas()
    assert any(fragmento in m for m in malos), malos


@pytest.mark.parametrize("nombre", [".fuente", "a.b", "NULL", "COM10", "console", "LPT0", "x/.oculta"])
def test_nombres_validos_que_se_parecen_a_los_prohibidos_pasan(nombre):
    """Un validador demasiado celoso es peor que ninguno: rechazaria nombres buenos."""
    assert Layout({"merged": nombre}).problemas() == []


def test_un_punto_al_principio_es_valido_en_todas_las_plataformas():
    # La pregunta de V0ra: el punto delante no es un problema; si lo es al final.
    assert Layout({"merged": ".M3M0RIA"}).problemas() == []
    assert Layout({"merged": "M3M0RIA."}).problemas() != []


# ---- ubicacion externa del RAW -------------------------------------------

def test_solo_se_pueden_externalizar_las_claves_permitidas(tmp_path):
    with pytest.raises(LayoutError, match="cannot live outside"):
        Layout(externas={"merged": str(tmp_path / "x")})


def test_ruta_da_la_externa_y_rel_sigue_dando_el_nombre_interno(tmp_path):
    ext = tmp_path / "fuera" / "fuente"
    L = Layout(externas={"raw": str(ext)})
    assert L.ruta(tmp_path / "vault", "raw") == ext
    assert L.es_externa("raw") and not L.es_externa("merged")
    assert L.rel("raw") == "RAW_VAULT"   # sigue sirviendo de etiqueta (estadisticas, mensajes)
    assert L.ruta(tmp_path / "vault", "merged") == tmp_path / "vault" / "MERGED_VAULT"


def test_vacio_o_none_no_cuenta_como_externo():
    assert Layout(externas={"raw": ""}).externas == {}
    assert Layout(externas={"raw": None}).externas == {}


def test_la_externa_tiene_que_ser_absoluta():
    assert any("absolute path" in m for m in Layout(externas={"raw": "relativa/fuente"}).problemas())


def test_la_externa_se_valida_contra_el_vault(tmp_path):
    base = tmp_path / "vault"
    base.mkdir()
    ok = Layout(externas={"raw": str(tmp_path / "fuera")})
    assert ok.problemas(base) == []

    # igual a la propia carpeta base
    assert any("base folder itself" in m for m in Layout(externas={"raw": str(base)}).problemas(base))
    # contiene la base: recorreria todo el vault como si fuera la fuente
    assert any("contains the base folder" in m for m in Layout(externas={"raw": str(tmp_path)}).problemas(base))
    # dentro de un vault o de un banco: mezclaria la fuente con otra cosa
    for dentro in (base / "MERGED_VAULT" / "fuente", base / "GROK" / "ATTACHMENTS", base / "PRJ_VAULT"):
        malos = Layout(externas={"raw": str(dentro)}).problemas(base)
        assert any("would mix" in m for m in malos), (dentro, malos)
    # dentro de la base pero en carpeta libre: es decision de quien configura (p.ej. .fuente)
    assert Layout(externas={"raw": str(base / ".fuente")}).problemas(base) == []


def test_dos_layouts_se_distinguen_por_su_ubicacion_externa(tmp_path):
    a = Layout(externas={"raw": str(tmp_path / "a")})
    assert a != Layout()
    assert a != Layout(externas={"raw": str(tmp_path / "b")})
    assert a == Layout(externas={"raw": str(tmp_path / "a")})


# ---- marcador y entorno conservan la ubicacion ----------------------------

def test_el_marcador_guarda_y_devuelve_la_ubicacion_externa(tmp_path):
    L = Layout(externas={"raw": str(tmp_path / "fuente")}, preset="mio")
    lay.escribir_marcador(tmp_path, L)
    leido = lay.leer_marcador(tmp_path)
    assert leido == L and leido.ruta(tmp_path, "raw") == tmp_path / "fuente"
    assert json.loads((tmp_path / lay.MARCADOR).read_text(encoding="utf-8"))["version"] == lay.VERSION_MARCADOR


def test_un_marcador_antiguo_sin_externas_se_sigue_leyendo(tmp_path):
    viejo = {"version": 1, "preset": "clasico", "nombres": lay.CLASICO.a_dict()}
    (tmp_path / lay.MARCADOR).write_text(json.dumps(viejo), encoding="utf-8")
    assert lay.leer_marcador(tmp_path) == lay.CLASICO


def test_el_entorno_lleva_la_ubicacion_a_los_procesos_hijos(tmp_path, monkeypatch):
    L = Layout(externas={"raw": str(tmp_path / "fuente")})
    monkeypatch.setenv(lay.ENV_LAYOUT, lay.entorno(L)[lay.ENV_LAYOUT])
    assert lay.cargar().ruta(tmp_path, "raw") == tmp_path / "fuente"


# ---- cargar / pedido -------------------------------------------------------

def test_cargar_usa_raw_vault_solo_si_el_vault_no_tiene_marcador(tmp_path):
    ext = tmp_path / "fuera"
    base = tmp_path / "vault"
    base.mkdir()
    assert lay.cargar(base, raw_vault=str(ext)).ruta(base, "raw") == ext
    # con marcador, manda el marcador: la config discrepante la para `conflictos`
    lay.escribir_marcador(base, lay.CLASICO)
    assert lay.cargar(base, raw_vault=str(ext)).ruta(base, "raw") == base / "RAW_VAULT"


def test_pedido_manda_la_config_sobre_la_ubicacion_pero_conserva_la_tabla(tmp_path):
    base = tmp_path / "vault"
    base.mkdir()
    lay.escribir_marcador(base, Layout({"merged": "FUSION"}, externas={"raw": str(tmp_path / "a")}))
    p = lay.pedido(base, raw_vault=None)
    assert p.rel("merged") == "FUSION"            # la tabla del vault
    assert not p.es_externa("raw")                 # la ubicacion, la de la config (vacia)
    assert lay.pedido(base, raw_vault=str(tmp_path / "b")).ruta(base, "raw") == tmp_path / "b"


# ---- conflictos ------------------------------------------------------------

def _vault_clasico_con_raw(tmp_path):
    base = tmp_path / "vault"
    (base / "RAW_VAULT" / "Conversations").mkdir(parents=True)
    (base / "RAW_VAULT" / "Conversations" / "n.md").write_text("x", encoding="utf-8")
    return base


def test_un_vault_nuevo_adopta_lo_que_pida_la_config(tmp_path):
    base = tmp_path / "vault"
    base.mkdir()
    assert lay.conflictos(base, lay.pedido(base, raw_vault=str(tmp_path / "fuera"))) == []


def test_un_vault_con_raw_clasico_no_acepta_en_silencio_un_raw_en_otro_sitio(tmp_path):
    base = _vault_clasico_con_raw(tmp_path)
    malos = lay.conflictos(base, lay.pedido(base, raw_vault=str(tmp_path / "fuera")))
    assert len(malos) == 1
    assert "mover_raw.py" in malos[0] and "RAW_VAULT" in malos[0]


def test_el_mismo_sitio_no_es_conflicto(tmp_path):
    base = _vault_clasico_con_raw(tmp_path)
    assert lay.conflictos(base, lay.pedido(base, raw_vault=None)) == []
    # y la comparacion no se deja engañar por mayusculas ni por barras
    interno = str(base / "raw_vault").replace("\\", "/")
    if os.name == "nt":
        assert lay.conflictos(base, lay.pedido(base, raw_vault=interno)) == []


def test_marcador_externo_y_config_vacia_es_conflicto(tmp_path):
    base = tmp_path / "vault"
    base.mkdir()
    ext = tmp_path / "fuente"
    ext.mkdir()
    lay.escribir_marcador(base, Layout(externas={"raw": str(ext)}))
    malos = lay.conflictos(base, lay.pedido(base, raw_vault=None))
    assert len(malos) == 1 and str(ext) in malos[0]


def test_marcador_externo_y_config_igual_es_via_libre(tmp_path):
    base = tmp_path / "vault"
    base.mkdir()
    ext = tmp_path / "fuente"
    ext.mkdir()
    lay.escribir_marcador(base, Layout(externas={"raw": str(ext)}))
    assert lay.conflictos(base, lay.pedido(base, raw_vault=str(ext))) == []


def test_fuente_externa_que_ha_desaparecido_no_se_recrea_en_silencio(tmp_path):
    """Disco desconectado: crear un RAW nuevo vacio aqui partiria la fuente en dos."""
    base = tmp_path / "vault"
    base.mkdir()
    ext = tmp_path / "unidad_desconectada" / "fuente"     # no existe
    lay.escribir_marcador(base, Layout(externas={"raw": str(ext)}))
    malos = lay.conflictos(base, lay.pedido(base, raw_vault=str(ext)))
    assert len(malos) == 1 and "does not exist" in malos[0] and "not connected" in malos[0]
