# -*- coding: utf-8 -*-
"""El selector de organizacion del vault, del lado del servidor.

  GET  /api/layout/presets -> los tres presets y, de cada uno, por que NO se puede elegir ahora;
  POST /api/config         -> un `layout_preset` que el vault no admite no se guarda.

Contra un vault temporal: nunca el real de V0ra.
"""
import pytest

import launcher
import layout as lay


def _config(tmp_path, preset=None):
    cfg = tmp_path / "memoria_config.yaml"
    opciones = "options:\n  prj_vault_name: 'PRJ_VAULT'\n"
    if preset:
        opciones += f"  layout_preset: '{preset}'\n"
    cfg.write_text(f"paths:\n  base_vault: '{(tmp_path / 'vault').as_posix()}'\n"
                   f"  exports_dir: '{tmp_path.as_posix()}'\n  gizmo_map: ''\n" + opciones, encoding="utf-8")
    return cfg


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    (tmp_path / "vault").mkdir()
    monkeypatch.setattr(launcher, "CONFIG_PATH", _config(tmp_path))
    launcher.app.config["TESTING"] = True
    return launcher.app.test_client()


def _con_notas(tmp_path, preset):
    base = tmp_path / "vault"
    lay.escribir_marcador(base, lay.Layout(preset=preset))
    carpeta = base / "MERGED_VAULT" / lay.Layout(preset=preset).conv_rel("grok")
    carpeta.mkdir(parents=True)
    (carpeta / "a.md").write_text("---\ntitle: a\n---\n", encoding="utf-8")


def test_presets_de_un_vault_nuevo_se_pueden_elegir_todos(cliente):
    d = cliente.get("/api/layout/presets").get_json()
    assert [p["id"] for p in d["presets"]] == ["unico", "proveedor", "proyectos"]
    assert all(p["conflictos"] == [] for p in d["presets"])
    assert d["configurado"] == "proyectos" and d["del_vault"] is None


def test_presets_dicen_las_dos_cosas_que_fija_cada_uno(cliente):
    d = {p["id"]: p for p in cliente.get("/api/layout/presets").get_json()["presets"]}
    assert (d["unico"]["particion"], d["unico"]["proyectos"]) == ("unico", False)
    assert (d["proveedor"]["particion"], d["proveedor"]["proyectos"]) == ("proveedor", False)
    assert (d["proyectos"]["particion"], d["proyectos"]["proyectos"]) == ("unico", True)


def test_un_vault_con_notas_no_admite_cambiar_la_particion(cliente, tmp_path):
    _con_notas(tmp_path, "unico")
    d = cliente.get("/api/layout/presets").get_json()
    por_id = {p["id"]: p for p in d["presets"]}
    assert por_id["proveedor"]["conflictos"], "partir un vault con notas deberia bloquearse"
    assert por_id["unico"]["conflictos"] == [] and por_id["proyectos"]["conflictos"] == []
    assert d["del_vault"] == "unico"


def test_el_vault_de_antes_de_los_presets_es_proyectos(cliente, tmp_path):
    """Sin marcador y con notas en MERGED_VAULT/Conversations, como el vault real de V0ra."""
    carpeta = tmp_path / "vault" / "MERGED_VAULT" / "Conversations"
    carpeta.mkdir(parents=True)
    (carpeta / "a.md").write_text("---\ntitle: a\n---\n", encoding="utf-8")
    por_id = {p["id"]: p for p in cliente.get("/api/layout/presets").get_json()["presets"]}
    assert por_id["proveedor"]["conflictos"]
    assert por_id["unico"]["conflictos"] == [] and por_id["proyectos"]["conflictos"] == []


def test_guardar_un_preset_que_el_vault_no_admite_da_400_y_no_escribe(cliente, tmp_path):
    _con_notas(tmp_path, "unico")
    antes = launcher.CONFIG_PATH.read_text(encoding="utf-8")
    r = cliente.post("/api/config", json={"options": {"layout_preset": "proveedor"}})
    assert r.status_code == 400
    assert "layout_preset" in r.get_json()["error"]
    assert launcher.CONFIG_PATH.read_text(encoding="utf-8") == antes


def test_guardar_un_preset_valido_lo_escribe_en_la_config(cliente):
    r = cliente.post("/api/config", json={"options": {"layout_preset": "proveedor"}})
    assert r.status_code == 200
    assert "layout_preset: 'proveedor'" in launcher.CONFIG_PATH.read_text(encoding="utf-8")
    assert cliente.get("/api/layout/presets").get_json()["configurado"] == "proveedor"


def test_guardar_un_preset_desconocido_da_400_con_los_validos(cliente):
    r = cliente.post("/api/config", json={"options": {"layout_preset": "por-colores"}})
    assert r.status_code == 400
    assert "unico, proveedor, proyectos" in r.get_json()["error"]


def test_guardar_sin_preset_no_lo_toca(cliente):
    r = cliente.post("/api/config", json={"options": {"by_year": False}})
    assert r.status_code == 200
    assert "layout_preset" not in launcher.CONFIG_PATH.read_text(encoding="utf-8")


def test_guardar_el_mismo_preset_que_ya_tiene_el_vault_es_libre(cliente, tmp_path):
    _con_notas(tmp_path, "proveedor")
    r = cliente.post("/api/config", json={"options": {"layout_preset": "proveedor"}})
    assert r.status_code == 200


def test_el_launcher_lee_el_layout_del_marcador_no_de_la_config(cliente, tmp_path):
    """Las estadisticas del vault tienen que recorrer las carpetas de proveedor."""
    _con_notas(tmp_path, "proveedor")
    s = cliente.get("/api/stats?refresh=1").get_json()
    assert s["layout"]["particion"] == "proveedor"
    assert s["vaults"]["MERGED_VAULT"]["notas"] == 1


def test_un_vault_sin_marcador_adopta_el_preset_de_la_config_en_cada_peticion(tmp_path, monkeypatch):
    """Antes del primer import no hay marcador: el layout con el que trabajan las
    peticiones y sus procesos hijos tiene que ser el que pide la config."""
    (tmp_path / "vault").mkdir()
    monkeypatch.setattr(launcher, "CONFIG_PATH", _config(tmp_path, "proveedor"))
    launcher.app.config["TESTING"] = True
    launcher.app.test_client().get("/api/config")
    L = lay.cargar()                      # lee el entorno que dejo la peticion
    assert (L.particion, L.proyectos) == ("proveedor", False)


def test_con_marcador_la_peticion_usa_el_del_marcador_aunque_la_config_pida_otro(tmp_path, monkeypatch):
    (tmp_path / "vault").mkdir()
    lay.escribir_marcador(tmp_path / "vault", lay.Layout(preset="unico"))
    monkeypatch.setattr(launcher, "CONFIG_PATH", _config(tmp_path, "proveedor"))
    launcher.app.config["TESTING"] = True
    launcher.app.test_client().get("/api/config")
    assert lay.cargar().particion == "unico"
