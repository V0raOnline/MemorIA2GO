# -*- coding: utf-8 -*-
"""Herramientas → Galerias: los endpoints que lanzan las dos galerias desde la app. Flask test_client con
una configuracion temporal (nunca la real de V0ra) y el navegador sustituido por un falso: los tests
no abren nada en la pantalla de nadie."""
import json

import pytest
from PIL import Image

import launcher


def _config(tmp_path, **rutas):
    cfg = tmp_path / "memoria_config.yaml"
    lineas = "".join(f"  {k}: '{v}'\n" for k, v in rutas.items())
    cfg.write_text(f"paths:\n{lineas}  exports_dir: '{tmp_path}'\noptions: {{}}\n", encoding="utf-8")
    return cfg


@pytest.fixture
def abiertas(monkeypatch):
    lista = []
    monkeypatch.setattr(launcher, "_abrir_en_navegador", lambda p: lista.append(p))
    return lista


def _cliente(monkeypatch, cfg):
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)
    launcher.app.config["TESTING"] = True
    return launcher.app.test_client()


def _vault_con_una_imagen(tmp_path):
    base = tmp_path / "vault"
    gen = base / "CHATGPT" / "GENERADAS"
    gen.mkdir(parents=True)
    Image.new("RGB", (300, 200), (10, 200, 10)).save(gen / "aaaa.png")
    return base


def _vault_tintero(tmp_path):
    v = tmp_path / "tintero"
    nota = v / "Posts" / "2026" / "10" / "post.md"
    nota.parent.mkdir(parents=True)
    nota.write_text('---\ntitle: "Un post"\ndate: 2026-10-01\nsource: substack_export\npublication: "mipub"\n'
                    'post_id: "1"\nslug: "un-post"\nstatus: "published"\ntype: "newsletter"\n---\n\n# Un post\n\nTexto.\n',
                    encoding="utf-8")
    return v


def test_sin_rutas_cada_galeria_dice_que_le_falta(tmp_path, monkeypatch):
    res = _cliente(monkeypatch, _config(tmp_path)).get("/api/galerias").get_json()
    assert "base_vault" in res["imagenes"]["falta"] and "substack_vault" in res["tintero"]["falta"]


def test_sin_generar_dice_que_no_existe(tmp_path, monkeypatch):
    cfg = _config(tmp_path, base_vault=_vault_con_una_imagen(tmp_path))
    res = _cliente(monkeypatch, cfg).get("/api/galerias").get_json()
    assert res["imagenes"] == {"existe": False}


def test_generar_ensena_el_log_la_abre_y_deja_su_estado(tmp_path, monkeypatch, abiertas):
    base = _vault_con_una_imagen(tmp_path)
    cliente = _cliente(monkeypatch, _config(tmp_path, base_vault=base))
    res = cliente.post("/api/galerias/imagenes/generar")
    texto = res.get_data(as_text=True)
    assert res.status_code == 200 and "1 imagenes y videos" in texto and texto.rstrip().endswith("__DONE__ 0")
    assert "Abierta en tu navegador." in texto and abiertas == [base / ".galeria" / "index.html"]
    estado = cliente.get("/api/galerias").get_json()["imagenes"]
    assert estado["existe"] is True and estado["items"] == 1 and estado["generada"][:4].isdigit()


def test_la_de_tintero_sin_red_no_sale_a_internet(tmp_path, monkeypatch, abiertas):
    v = _vault_tintero(tmp_path)
    cliente = _cliente(monkeypatch, _config(tmp_path, substack_vault=v))
    texto = cliente.post("/api/galerias/tintero/generar", json={"sin_red": True}).get_data(as_text=True)
    assert "sin red" in texto and "1 posts" in texto and texto.rstrip().endswith("__DONE__ 0")
    assert cliente.get("/api/galerias").get_json()["tintero"]["posts"] == 1


def test_si_falla_no_abre_nada(tmp_path, monkeypatch, abiertas):
    base = tmp_path / "vacio"
    base.mkdir()
    texto = _cliente(monkeypatch, _config(tmp_path, base_vault=base)).post("/api/galerias/imagenes/generar").get_data(as_text=True)
    assert "[error]" in texto and texto.rstrip().endswith("__DONE__ 2") and abiertas == []


def test_abrir_la_ultima(tmp_path, monkeypatch, abiertas):
    base = _vault_con_una_imagen(tmp_path)
    cliente = _cliente(monkeypatch, _config(tmp_path, base_vault=base))
    assert cliente.post("/api/galerias/imagenes/abrir").status_code == 404
    cliente.post("/api/galerias/imagenes/generar").get_data()
    abiertas.clear()
    assert cliente.post("/api/galerias/imagenes/abrir").get_json() == {"ok": True}
    assert abiertas == [base / ".galeria" / "index.html"]


def test_una_galeria_desconocida_o_sin_ruta(tmp_path, monkeypatch, abiertas):
    cliente = _cliente(monkeypatch, _config(tmp_path))
    assert cliente.post("/api/galerias/otra/generar").status_code == 404
    assert cliente.post("/api/galerias/imagenes/generar").status_code == 400


def test_no_se_lanza_si_ya_hay_algo_en_marcha(tmp_path, monkeypatch, abiertas):
    cliente = _cliente(monkeypatch, _config(tmp_path, base_vault=_vault_con_una_imagen(tmp_path)))
    assert launcher.run_lock.acquire(blocking=False)
    try:
        assert cliente.post("/api/galerias/imagenes/generar").status_code == 409
    finally:
        launcher.run_lock.release()


def test_una_galeria_de_antes_del_estado_da_su_fecha_y_ningun_recuento(tmp_path, monkeypatch):
    base = _vault_con_una_imagen(tmp_path)
    (base / ".galeria").mkdir()
    (base / ".galeria" / "index.html").write_text("<html></html>", encoding="utf-8")
    res = _cliente(monkeypatch, _config(tmp_path, base_vault=base)).get("/api/galerias").get_json()["imagenes"]
    assert res["existe"] is True and res["generada"][:4].isdigit() and "items" not in res
