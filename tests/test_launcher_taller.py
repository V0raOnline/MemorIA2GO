# -*- coding: utf-8 -*-
"""Herramientas → Taller: los endpoints de su estado y de Recuperar imagenes de ChatGPT.

Configuracion temporal y, sobre todo, LOGS_DIR temporal: "Deshacer la ultima" restaura notas desde la
copia mas reciente de esa carpeta, y la real tiene las copias de V0ra. Ningun test puede verlas.
Los vaults se hacen con el pipeline real, con los ayudantes de test_recuperar_imagenes.py."""
import json
import os
import time

import pytest

import launcher
from test_recuperar_imagenes import JPG, PNG, PNG2, _conv, _importar, _notas, _zip

CONVS = [_conv([("sediment://file_aaa", False), ("file-service://file-bbb", True)])]


def _config(tmp_path, **rutas):
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text("paths:\n" + "".join(f"  {k}: '{v}'\n" for k, v in rutas.items()) + "options: {}\n",
                   encoding="utf-8")
    return cfg


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Un vault con avisos (importado de un export sin binarios) y, en la carpeta de exports, el export
    completo. Devuelve (cliente, base, exports, logs)."""
    base, exports, logs = tmp_path / "vault", tmp_path / "exports", tmp_path / "logs"
    exports.mkdir()
    _importar(_zip(tmp_path / "sin.zip", CONVS, {}), base / "RAW_VAULT" / "Conversaciones", base)
    _zip(exports / "chatgpt-2026-10-18.zip", CONVS, {"file_aaa.dat": PNG, "file-bbb.dat": JPG})
    monkeypatch.setattr(launcher, "CONFIG_PATH", _config(tmp_path, base_vault=base, exports_dir=exports))
    monkeypatch.setattr(launcher, "LOGS_DIR", logs)
    launcher._avisos_cache.clear()
    launcher.app.config["TESTING"] = True
    yield launcher.app.test_client(), base, exports, logs
    launcher._avisos_cache.clear()


def _nota(base):
    return _notas(base / "RAW_VAULT" / "Conversaciones")[0]


def test_sin_rutas_cada_herramienta_dice_lo_que_le_falta(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "CONFIG_PATH", _config(tmp_path))
    monkeypatch.setattr(launcher, "LOGS_DIR", tmp_path / "logs")
    cliente = launcher.app.test_client()
    d = cliente.get("/api/taller").get_json()
    assert "base_vault" in d["recuperar"]["falta"] and d["recuperar"]["exports"] == []
    assert d["indices"] == {"fecha": None} and "substack_vault" in d["tintero"]["falta"]
    assert "base_vault" in cliente.get("/api/taller/avisos").get_json()["falta"]


def test_la_lista_de_exports_solo_trae_los_de_chatgpt(entorno):
    cliente, base, exports, _ = entorno
    _zip(exports / "otro.zip", [], {})                                   # conversations vacio: tambien ChatGPT
    import zipfile
    with zipfile.ZipFile(exports / "grok.zip", "w") as z:
        z.writestr("ttl/30d/export_data/x/prod-grok-backend.json", "{}")
    with zipfile.ZipFile(exports / "frames-000.zip", "w") as z:          # de Claude, pero parece ChatGPT en HTML
        z.writestr("frame.html", "<html></html>")
    nombres = [e["nombre"] for e in cliente.get("/api/taller").get_json()["recuperar"]["exports"]]
    assert "grok.zip" not in nombres and "frames-000.zip" not in nombres and "chatgpt-2026-10-18.zip" in nombres


def test_los_avisos_se_cuentan_y_se_recuerdan(entorno):
    cliente, base, _, _ = entorno
    assert cliente.get("/api/taller/avisos").get_json() == {"avisos": 2, "imagenes": 2}
    nota = _nota(base)
    nota.write_text(nota.read_text(encoding="utf-8").replace("imagen no disponible", "otra cosa"), encoding="utf-8")
    assert cliente.get("/api/taller/avisos").get_json()["avisos"] == 2, "de memoria: no se vuelve a leer"


def test_simular_no_escribe_nada_y_no_habla_de_opciones_de_consola(entorno):
    cliente, base, exports, logs = entorno
    antes = _nota(base).read_bytes()
    res = cliente.post("/api/taller/recuperar", json={"export": str(exports / "chatgpt-2026-10-18.zip")})
    texto = res.get_data(as_text=True)
    assert res.status_code == 200 and "SIMULACION" in texto and texto.rstrip().endswith("__DONE__ 0")
    assert "--aplicar" not in texto and "--deshacer" not in texto
    assert _nota(base).read_bytes() == antes and not logs.exists()


def test_solo_acepta_un_export_de_la_lista(entorno, tmp_path):
    cliente, _, _, _ = entorno
    fuera = _zip(tmp_path / "fuera.zip", CONVS, {"file_aaa.dat": PNG})
    assert cliente.post("/api/taller/recuperar", json={"export": str(fuera)}).status_code == 400
    assert cliente.post("/api/taller/recuperar", json={}).status_code == 400


def test_aplicar_repara_guarda_la_copia_en_su_carpeta_y_vuelve_a_contar(entorno):
    cliente, base, exports, logs = entorno
    assert cliente.get("/api/taller/avisos").get_json()["avisos"] == 2
    texto = cliente.post("/api/taller/recuperar", json={"export": str(exports / "chatgpt-2026-10-18.zip"),
                                                        "aplicar": True}).get_data(as_text=True)
    assert texto.rstrip().endswith("__DONE__ 0") and "--deshacer" not in texto
    assert "imagen no disponible" not in _nota(base).read_text(encoding="utf-8")
    assert [c.name.startswith("recuperar_imagenes_") for c in logs.iterdir()] == [True]
    assert cliente.get("/api/taller/avisos").get_json()["avisos"] == 0
    d = cliente.get("/api/taller").get_json()["recuperar"]["deshacer"]
    assert d["tipo"] == "avisos" and d["fecha"][:4].isdigit()


def test_deshacer_restaura_marca_la_copia_y_la_siguiente_vez_no_la_repite(entorno):
    cliente, base, exports, logs = entorno
    original = _nota(base).read_bytes()
    assert cliente.post("/api/taller/recuperar/deshacer").status_code == 404
    cliente.post("/api/taller/recuperar", json={"export": str(exports / "chatgpt-2026-10-18.zip"),
                                                "aplicar": True}).get_data()
    r = cliente.post("/api/taller/recuperar/deshacer").get_json()
    assert r["ok"] and r["notas"] == 1 and _nota(base).read_bytes() == original
    (copia,) = list(logs.iterdir())
    assert (copia / "deshecho.json").is_file() and (copia / "diario.json").is_file(), "se marca, no se borra"
    assert cliente.post("/api/taller/recuperar/deshacer").status_code == 404
    assert cliente.get("/api/taller").get_json()["recuperar"]["deshacer"] is None


def test_con_biblioteca_se_deshace_primero_la_de_la_biblioteca(entorno, tmp_path):
    """Avisos y biblioteca en la misma pasada dejan dos copias: la de la biblioteca se hace despues y es
    la que "Deshacer la ultima" toma primero. Pulsar dos veces deja la nota como estaba."""
    cliente, base, exports, logs = entorno
    from test_biblioteca_generadas import _entrada
    _zip(exports / "chatgpt-2026-10-18.zip", CONVS, {"file_aaa.dat": PNG, "file-bbb.dat": JPG, "file_gen1.dat": PNG2},
         [_entrada("file_gen1", "Generada.png")])
    original = _nota(base).read_bytes()
    cliente.post("/api/taller/recuperar", json={"export": str(exports / "chatgpt-2026-10-18.zip"),
                                                "aplicar": True, "biblioteca": True}).get_data()
    assert len(list(logs.iterdir())) == 2                                  # una copia por cada trabajo
    assert cliente.get("/api/taller").get_json()["recuperar"]["deshacer"]["tipo"] == "biblioteca"
    cliente.post("/api/taller/recuperar/deshacer")
    cliente.post("/api/taller/recuperar/deshacer")
    assert _nota(base).read_bytes() == original


def test_los_indices_dicen_su_fecha_y_si_una_recuperacion_los_dejo_viejos(entorno):
    cliente, base, exports, logs = entorno
    arbol = base / "MERGED_VAULT" / "_tree_index.md"
    arbol.parent.mkdir(parents=True)
    arbol.write_text("indice", encoding="utf-8")
    os.utime(arbol, (time.time() - 3600, time.time() - 3600))
    ix = cliente.get("/api/taller").get_json()["indices"]
    assert ix["fecha"][:4].isdigit() and ix["viejos"] is False
    cliente.post("/api/taller/recuperar", json={"export": str(exports / "chatgpt-2026-10-18.zip"),
                                                "aplicar": True}).get_data()
    assert cliente.get("/api/taller").get_json()["indices"]["viejos"] is True


def test_mover_lo_antiguo_de_tintero_solo_hace_falta_con_layout_antiguo_y_varias_publicaciones(tmp_path, monkeypatch):
    sv, exports = tmp_path / "tintero", tmp_path / "exports"
    (sv / "Posts").mkdir(parents=True)
    exports.mkdir()
    monkeypatch.setattr(launcher, "CONFIG_PATH", _config(tmp_path, substack_vault=sv, exports_dir=exports))
    monkeypatch.setattr(launcher, "LOGS_DIR", tmp_path / "logs")
    cliente = launcher.app.test_client()
    assert cliente.get("/api/taller").get_json()["tintero"]["hace_falta"] is False      # sin publicaciones
    (sv / "_publicaciones.md").write_text("indice", encoding="utf-8")                  # ya por publicaciones
    t = cliente.get("/api/taller").get_json()["tintero"]
    assert t["hace_falta"] is True and t["legado"] == ["Posts"]


def test_no_se_lanza_si_ya_hay_algo_en_marcha(entorno):
    cliente, _, exports, _ = entorno
    assert launcher.run_lock.acquire(blocking=False)
    try:
        assert cliente.post("/api/taller/recuperar", json={"export": str(exports / "chatgpt-2026-10-18.zip")}).status_code == 409
        assert cliente.post("/api/taller/recuperar/deshacer").status_code in (404, 409)
    finally:
        launcher.run_lock.release()
