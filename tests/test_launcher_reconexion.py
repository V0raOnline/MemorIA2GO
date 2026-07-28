# -*- coding: utf-8 -*-
"""Tests de los endpoints de Reconexion (backlog 2026-07-23): registrar un
pendiente de Grok descargado a mano via upload, y listar pendientes. Usa
Flask test_client con un vault temporal (monkeypatch de CONFIG_PATH) --
nunca contra el vault real, para no mutar los pendientes de verdad de V0ra."""
import json
from io import BytesIO

import pytest

import launcher


def _make_config(tmp_path, base_vault):
    cfg_path = tmp_path / "memoria_config.yaml"
    cfg_path.write_text(f"""
paths:
  base_vault: '{base_vault}'
  exports_dir: '{tmp_path}'
  gizmo_map: ''
options:
  prj_vault_name: 'PRJ_VAULT'
""", encoding="utf-8")
    return cfg_path


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "CONFIG_PATH", _make_config(tmp_path, tmp_path / "vault"))
    launcher.app.config["TESTING"] = True
    return launcher.app.test_client()


def test_pendientes_sin_fichero_devuelve_vacio_por_proveedor(client):
    res = client.get("/api/pendientes")
    assert res.get_json() == {"grok": [], "chatgpt": []}


def test_pendientes_lista_lo_que_hay_en_disco(client, tmp_path):
    grok_dir = tmp_path / "vault" / "GROK"
    grok_dir.mkdir(parents=True)
    pendientes = [{"id": "abc123", "prompt": "un gato", "link": "https://grok.com/x",
                   "media_type": "image", "create_time": "2026-06-01T00:00:00Z"}]
    (grok_dir / "_pendientes_descarga.json").write_text(json.dumps(pendientes), encoding="utf-8")

    res = client.get("/api/pendientes")
    assert res.get_json()["grok"] == pendientes


# ---------- imagenes de busqueda web de ChatGPT (triaje) ----------

def _pendientes_chatgpt(tmp_path, entradas):
    d = tmp_path / "vault" / "CHATGPT"
    d.mkdir(parents=True, exist_ok=True)
    (d / "_pendientes_descarga.json").write_text(json.dumps(entradas), encoding="utf-8")
    return d / "_pendientes_descarga.json"


def _leer(path):
    return json.loads(path.read_text(encoding="utf-8"))


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def test_listado_separa_los_dos_proveedores(client, tmp_path):
    grok_dir = tmp_path / "vault" / "GROK"
    grok_dir.mkdir(parents=True)
    (grok_dir / "_pendientes_descarga.json").write_text(
        json.dumps([{"id": "g1", "media_type": "image"}]), encoding="utf-8")
    _pendientes_chatgpt(tmp_path, [{"url": "https://a.es/1.jpg", "estado": "sin_triar"}])

    datos = client.get("/api/pendientes").get_json()
    assert [p["id"] for p in datos["grok"]] == ["g1"]
    assert [p["url"] for p in datos["chatgpt"]] == ["https://a.es/1.jpg"]


def test_listado_oculta_lo_ya_triado(client, tmp_path):
    """Lo rescatado y lo descartado no vuelve a la lista de trabajo, pero
    sigue en el fichero: el paso 1 lo necesita para pintar la nota."""
    path = _pendientes_chatgpt(tmp_path, [
        {"url": "https://a.es/1.jpg", "estado": "sin_triar"},
        {"url": "https://b.es/2.jpg", "estado": "rescatada", "fichero": "x.jpg"},
        {"url": "https://c.es/3.jpg", "estado": "descartada"},
    ])
    datos = client.get("/api/pendientes").get_json()
    assert [p["url"] for p in datos["chatgpt"]] == ["https://a.es/1.jpg"]
    assert len(_leer(path)) == 3


def test_registrar_imagen_web_va_al_banco_chatgpt_web(client, tmp_path):
    """Banco propio: no GENERADAS (no la genero la IA) ni ADJUNTOS (no la
    subio V0ra) -- es una referencia web de terceros."""
    path = _pendientes_chatgpt(tmp_path, [
        {"url": "https://a.es/1.jpg", "estado": "sin_triar",
         "queries": ["iglesia siruela"], "conversaciones": ["Olor"]},
    ])
    data = {"proveedor": "chatgpt", "url": "https://a.es/1.jpg",
            "file": (BytesIO(PNG), "foto.png")}
    body = client.post("/api/pendientes/registrar", data=data,
                       content_type="multipart/form-data").get_json()

    assert body["ok"] is True and body["restantes"] == 0
    fname = body["fname"]
    assert fname.endswith(".png")
    assert (tmp_path / "vault" / "CHATGPT" / "WEB" / fname).exists()

    manifest = json.loads((tmp_path / "vault" / "CHATGPT" / "WEB" /
                           "_image_manifest.json").read_text(encoding="utf-8"))
    assert manifest[fname]["origen"] == "web"
    assert manifest[fname]["url_original"] == "https://a.es/1.jpg"
    assert manifest[fname]["queries"] == ["iglesia siruela"]


def test_registrar_imagen_web_conserva_la_entrada_con_estado(client, tmp_path):
    """Diferencia clave con Grok: la entrada NO se borra. El paso 1 lee
    `fichero` en cada reproceso para pintar la imagen; si se borrara, el
    siguiente reproceso la volveria a listar sin triar y se perderia el
    rescate."""
    path = _pendientes_chatgpt(tmp_path, [{"url": "https://a.es/1.jpg", "estado": "sin_triar"}])
    data = {"proveedor": "chatgpt", "url": "https://a.es/1.jpg",
            "file": (BytesIO(PNG), "foto.png")}
    body = client.post("/api/pendientes/registrar", data=data,
                       content_type="multipart/form-data").get_json()

    guardado = _leer(path)
    assert len(guardado) == 1
    assert guardado[0]["estado"] == "rescatada"
    assert guardado[0]["fichero"] == body["fname"]


def test_descartar_marca_estado_y_lo_saca_de_la_lista(client, tmp_path):
    path = _pendientes_chatgpt(tmp_path, [
        {"url": "https://a.es/1.jpg", "estado": "sin_triar"},
        {"url": "https://b.es/2.jpg", "estado": "sin_triar"},
    ])
    body = client.post("/api/pendientes/descartar",
                       json={"url": "https://a.es/1.jpg"}).get_json()
    assert body["ok"] is True and body["restantes"] == 1

    guardado = {e["url"]: e["estado"] for e in _leer(path)}
    assert guardado["https://a.es/1.jpg"] == "descartada"
    assert guardado["https://b.es/2.jpg"] == "sin_triar"

    datos = client.get("/api/pendientes").get_json()
    assert [p["url"] for p in datos["chatgpt"]] == ["https://b.es/2.jpg"]


def test_descartar_url_inexistente_da_error(client, tmp_path):
    _pendientes_chatgpt(tmp_path, [])
    res = client.post("/api/pendientes/descartar", json={"url": "https://no.es/x.jpg"})
    assert res.status_code == 404


def test_descartar_sin_url_da_error(client, tmp_path):
    _pendientes_chatgpt(tmp_path, [])
    assert client.post("/api/pendientes/descartar", json={}).status_code == 400


def test_registrar_imagen_web_inexistente_da_error(client, tmp_path):
    _pendientes_chatgpt(tmp_path, [])
    data = {"proveedor": "chatgpt", "url": "https://no.es/x.jpg",
            "file": (BytesIO(PNG), "foto.png")}
    res = client.post("/api/pendientes/registrar", data=data,
                      content_type="multipart/form-data")
    assert res.status_code == 404


def test_registrar_pendiente_sube_archiva_y_da_de_alta(client, tmp_path):
    grok_dir = tmp_path / "vault" / "GROK"
    grok_dir.mkdir(parents=True)
    pendientes = [{"id": "abc123", "prompt": "un gato", "link": "https://grok.com/x",
                   "media_type": "image", "create_time": "2026-06-01T00:00:00Z"}]
    (grok_dir / "_pendientes_descarga.json").write_text(json.dumps(pendientes), encoding="utf-8")

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 20  # cabecera real de PNG, sniff_ext la reconoce
    data = {"id": "abc123", "file": (BytesIO(png_bytes), "foto.png")}
    res = client.post("/api/pendientes/registrar", data=data, content_type="multipart/form-data")

    body = res.get_json()
    assert body["ok"] is True
    assert body["restantes"] == 0

    fname = body["fname"]
    assert fname.endswith(".png")
    assert (grok_dir / "GENERADAS_IMAGEN" / fname).exists()

    manifest = json.loads((grok_dir / "GENERADAS_IMAGEN" / "_image_manifest.json").read_text(encoding="utf-8"))
    assert manifest[fname]["prompt"] == "un gato"
    assert manifest[fname]["create_time"] == "2026-06-01T00:00:00Z"
    assert manifest[fname]["origen"] == "generada"

    pendientes_restantes = json.loads((grok_dir / "_pendientes_descarga.json").read_text(encoding="utf-8"))
    assert pendientes_restantes == []


def test_registrar_video_va_a_generadas_video(client, tmp_path):
    grok_dir = tmp_path / "vault" / "GROK"
    grok_dir.mkdir(parents=True)
    pendientes = [{"id": "vid1", "prompt": "un perro corriendo", "link": "https://grok.com/y",
                   "media_type": "video", "create_time": "2026-06-02T00:00:00Z"}]
    (grok_dir / "_pendientes_descarga.json").write_text(json.dumps(pendientes), encoding="utf-8")

    mp4_bytes = b"\x00\x00\x00\x18ftypmp42" + b"0" * 20  # firma real de mp4
    data = {"id": "vid1", "file": (BytesIO(mp4_bytes), "video.mp4")}
    res = client.post("/api/pendientes/registrar", data=data, content_type="multipart/form-data")

    body = res.get_json()
    assert body["ok"] is True
    fname = body["fname"]
    assert (grok_dir / "GENERADAS_VIDEO" / fname).exists()
    assert not (grok_dir / "GENERADAS_IMAGEN" / fname).exists()


def test_registrar_pendiente_inexistente_da_error(client, tmp_path):
    grok_dir = tmp_path / "vault" / "GROK"
    grok_dir.mkdir(parents=True)
    (grok_dir / "_pendientes_descarga.json").write_text("[]", encoding="utf-8")

    data = {"id": "no-existe", "file": (BytesIO(b"\x89PNG\r\n\x1a\n0000"), "foto.png")}
    res = client.post("/api/pendientes/registrar", data=data, content_type="multipart/form-data")
    assert res.status_code == 404
    assert "error" in res.get_json()


def test_registrar_sin_fichero_da_error(client, tmp_path):
    grok_dir = tmp_path / "vault" / "GROK"
    grok_dir.mkdir(parents=True)
    (grok_dir / "_pendientes_descarga.json").write_text("[]", encoding="utf-8")

    res = client.post("/api/pendientes/registrar", data={"id": "abc123"}, content_type="multipart/form-data")
    assert res.status_code == 400
