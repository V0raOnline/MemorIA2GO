# -*- coding: utf-8 -*-
"""«Última importación: hace 0 día(s)», siempre.

BUG REAL (V0ra, 2026-10-20): el Observatorio decía "hace 0 día(s)" con la última
importacion hecha el 2026-09-19, 31 dias antes. La causa no estaba en el calculo
sino en CUANDO se calcula: el paso 4 del pipeline escribe la cache de estadisticas
justo despues de importar, y ahi `dias_transcurridos` vale 0. El launcher sirve esa
cache tal cual, asi que el 0 se quedaba grabado para siempre. Los dias son un valor
derivado de "ahora"; guardarlo ya calculado es guardar una mentira que caduca.

Ningun test lo vio porque `compute_last_import` es correcto: el fallo solo existe
en el camino escribir-cache -> leer-cache-mas-tarde, que nadie ejercitaba.
Estos tests ejercitan ESE camino, con el dato real: una cache escrita un dia y
leida semanas despues.
"""
import datetime
import json

import pytest

import launcher
import vault_stats as vs

# El caso real: importacion el 19 de septiembre, cache escrita 20 minutos despues.
IMPORTACION = "2026-09-19T10:10:49.972103"
HOY = datetime.datetime(2026, 10, 20, 12, 56, 37)     # 31 dias despues


def _escribir_cache_congelada(base, dias_guardados=0):
    """Una cache tal como la dejo el pipeline: dias ya calculados en el momento de escribirla."""
    (base / vs.CACHE_FILENAME).write_text(json.dumps({
        "base_vault": str(base),
        "ultima_importacion": {"timestamp": IMPORTACION, "dias_transcurridos": dias_guardados,
                               "export_path": None},
        "calculado": "2026-09-19T10:30:56",
    }), encoding="utf-8")


# ---- el calculo ------------------------------------------------------------

def test_dias_desde_cuenta_dias_enteros():
    assert vs.dias_desde(IMPORTACION, HOY) == 31
    assert vs.dias_desde("2026-10-20T00:00:00", HOY) == 0
    assert vs.dias_desde("2026-10-19T13:00:00", HOY) == 0    # menos de 24 h: aun no es 1


def test_un_reloj_adelantado_no_pinta_dias_negativos():
    assert vs.dias_desde("2026-10-25T00:00:00", HOY) == 0


def test_compute_last_import_y_la_cache_calculan_igual(tmp_path):
    (tmp_path / "_last_import.json").write_text(json.dumps({"timestamp": IMPORTACION}), encoding="utf-8")
    ui = vs.compute_last_import(tmp_path)
    assert ui["dias_transcurridos"] == vs.dias_desde(IMPORTACION)


# ---- EL bug: la cache congela el valor -------------------------------------

def test_una_cache_escrita_tras_importar_no_congela_los_dias(tmp_path):
    _escribir_cache_congelada(tmp_path, dias_guardados=0)
    stats = vs.load_cache(tmp_path, ahora=HOY)
    assert stats["ultima_importacion"]["dias_transcurridos"] == 31


def test_los_dias_siguen_avanzando_con_la_misma_cache(tmp_path):
    """Leida a las 3 semanas, a los 2 meses... la cache es la misma; los dias no."""
    _escribir_cache_congelada(tmp_path)
    assert vs.load_cache(tmp_path, ahora=datetime.datetime(2026, 9, 20, 9, 0))["ultima_importacion"]["dias_transcurridos"] == 0
    assert vs.load_cache(tmp_path, ahora=datetime.datetime(2026, 10, 3, 9, 0))["ultima_importacion"]["dias_transcurridos"] == 13
    assert vs.load_cache(tmp_path, ahora=datetime.datetime(2026, 12, 19, 12, 0))["ultima_importacion"]["dias_transcurridos"] == 91


def test_el_ciclo_completo_escribir_hoy_leer_mas_tarde(tmp_path):
    """Lo que hace el pipeline de verdad: compute_stats + save_cache el dia de la
    importacion; el Observatorio lo lee despues."""
    (tmp_path / "RAW_VAULT").mkdir()
    ayer = datetime.datetime.now()
    (tmp_path / "RAW_VAULT" / "_last_import.json").write_text(
        json.dumps({"timestamp": ayer.isoformat()}), encoding="utf-8")
    vs.save_cache(tmp_path, vs.compute_stats(tmp_path))
    assert vs.load_cache(tmp_path)["ultima_importacion"]["dias_transcurridos"] == 0   # el dia de importar

    leida_despues = vs.load_cache(tmp_path, ahora=ayer + datetime.timedelta(days=40, hours=2))
    assert leida_despues["ultima_importacion"]["dias_transcurridos"] == 40


# ---- tolerancia: la cache nunca es fuente unica de verdad --------------------

def test_sin_importacion_registrada_la_cache_queda_como_estaba(tmp_path):
    (tmp_path / vs.CACHE_FILENAME).write_text(json.dumps({"ultima_importacion": None, "x": 1}), encoding="utf-8")
    assert vs.load_cache(tmp_path, ahora=HOY) == {"ultima_importacion": None, "x": 1}
    (tmp_path / vs.CACHE_FILENAME).write_text(json.dumps({"x": 1}), encoding="utf-8")
    assert vs.load_cache(tmp_path, ahora=HOY) == {"x": 1}


@pytest.mark.parametrize("ts", ["no es una fecha", "", None, 12345, "2026-09-19T10:10:49+02:00"])
def test_un_timestamp_ilegible_no_rompe_la_lectura(tmp_path, ts):
    """Mejor un valor viejo que un Observatorio que no carga. (El ultimo caso trae zona
    horaria: restar fechas con y sin zona lanza TypeError.)"""
    (tmp_path / vs.CACHE_FILENAME).write_text(json.dumps(
        {"ultima_importacion": {"timestamp": ts, "dias_transcurridos": 7}}), encoding="utf-8")
    stats = vs.load_cache(tmp_path, ahora=HOY)
    assert stats is not None and stats["ultima_importacion"]["dias_transcurridos"] == 7


def test_cache_ausente_o_corrupta_sigue_devolviendo_none(tmp_path):
    assert vs.load_cache(tmp_path) is None
    (tmp_path / vs.CACHE_FILENAME).write_text("{ no es json", encoding="utf-8")
    assert vs.load_cache(tmp_path) is None


# ---- por el endpoint que usa la interfaz ------------------------------------

def test_el_endpoint_del_observatorio_ya_no_sirve_el_cero_congelado(tmp_path, monkeypatch):
    base = tmp_path / "vault"
    base.mkdir()
    exports = tmp_path / "exports"
    exports.mkdir()
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(f"paths:\n  base_vault: '{base.as_posix()}'\n  exports_dir: '{exports.as_posix()}'\n"
                   "options:\n  by_month: true\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)

    hace_31 = datetime.datetime.now() - datetime.timedelta(days=31, hours=1)
    (base / vs.CACHE_FILENAME).write_text(json.dumps({
        "base_vault": str(base),
        "ultima_importacion": {"timestamp": hace_31.isoformat(), "dias_transcurridos": 0},
        "vaults": {}, "assets": {"total_items": 0, "por_proveedor": {}},
    }), encoding="utf-8")

    r = launcher.app.test_client().get("/api/stats")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["ultima_importacion"]["dias_transcurridos"] == 31
