# -*- coding: utf-8 -*-
"""Tests de los endpoints de Reconexion (backlog 2026-07-23): registrar un
pendiente de Grok descargado a mano via upload, y listar pendientes. Usa
Flask test_client con un vault temporal (monkeypatch de CONFIG_PATH) --
nunca contra el vault real, para no mutar los pendientes de verdad de V0ra."""
import json
from io import BytesIO

import pytest

import launcher
from pendientes import ref_pendiente


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


def test_registrar_grok_conserva_la_entrada_para_sobrevivir_al_reproceso(client, tmp_path):
    """Bug real (2026-07-28): registrar BORRABA la entrada, y el siguiente
    --reprocess-all la volvia a listar porque process_grok_media_posts la
    re-anade al no encontrar el binario en el zip (que sigue sin estar: por
    eso era un pendiente). Con 205 pendientes reales, un reproceso devolvia
    los 205 a la casilla de salida.

    Se conserva marcada como rescatada: la fusion de
    split_chatgpt_export.py la ve en `vistos` y no la duplica."""
    grok_dir = tmp_path / "vault" / "GROK"
    grok_dir.mkdir(parents=True)
    path = grok_dir / "_pendientes_descarga.json"
    path.write_text(json.dumps([
        {"id": "abc123", "prompt": "un gato", "media_type": "image"},
        {"id": "def456", "prompt": "un perro", "media_type": "image"},
    ]), encoding="utf-8")

    data = {"id": "abc123", "file": (BytesIO(PNG), "foto.png")}
    body = client.post("/api/pendientes/registrar", data=data,
                       content_type="multipart/form-data").get_json()
    assert body["ok"] is True
    assert body["restantes"] == 1

    guardado = json.loads(path.read_text(encoding="utf-8"))
    assert len(guardado) == 2, "la entrada no debe borrarse: el reproceso la re-anadiria"
    # Se busca por `ref`, no por `id`: al quedar triada pierde la credencial
    # (ver pendientes.py). En Grok el `id` ES la credencial -- basta para
    # construir la ruta al fichero -- asi que tambien se va.
    rescatada = next(p for p in guardado if p["ref"] == ref_pendiente("abc123"))
    assert rescatada["estado"] == "rescatada"
    assert rescatada["fichero"] == body["fname"]
    assert "id" not in rescatada and "link" not in rescatada, \
        "una entrada triada no puede seguir guardando con que abrirse"

    # La que sigue sin triar SI conserva su id: tiene que ser pulsable.
    sin_triar = next(p for p in guardado if p.get("id") == "def456")
    assert sin_triar["ref"] == ref_pendiente("def456")

    # Simula el merge del pipeline: lo ya presente no se re-anade, y ahora la
    # identidad con la que se reconoce es el hash, no la credencial.
    vistos = {p.get("ref") for p in guardado}
    assert ref_pendiente("abc123") in vistos

    # Y la lista de trabajo ya no la ofrece.
    datos = client.get("/api/pendientes").get_json()
    assert [p["id"] for p in datos["grok"]] == ["def456"]


def test_pendientes_sin_estado_se_tratan_como_sin_triar(client, tmp_path):
    """Retrocompatibilidad: los ficheros escritos antes de que existieran
    los estados no llevan el campo y deben seguir listandose."""
    grok_dir = tmp_path / "vault" / "GROK"
    grok_dir.mkdir(parents=True)
    (grok_dir / "_pendientes_descarga.json").write_text(
        json.dumps([{"id": "viejo", "media_type": "image"}]), encoding="utf-8")

    datos = client.get("/api/pendientes").get_json()
    assert [p["id"] for p in datos["grok"]] == ["viejo"]


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

    # Indexado por `ref`: la descartada ya no guarda su URL.
    guardado = {e["ref"]: e for e in _leer(path)}
    descartada = guardado[ref_pendiente("https://a.es/1.jpg")]
    assert descartada["estado"] == "descartada"
    assert "url" not in descartada, \
        "descartar tambien tiene que quitar el enlace: es una llave viva"

    # La que sigue sin triar conserva su URL, que es lo que la hace pulsable.
    intacta = guardado[ref_pendiente("https://b.es/2.jpg")]
    assert intacta["estado"] == "sin_triar"
    assert intacta["url"] == "https://b.es/2.jpg"

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

    # Antes este test afirmaba `== []`, codificando el bug de 2026-07-28
    # como comportamiento correcto: al borrar la entrada, el siguiente
    # reproceso la volvia a listar. Ahora se conserva marcada.
    pendientes_restantes = json.loads((grok_dir / "_pendientes_descarga.json").read_text(encoding="utf-8"))
    assert len(pendientes_restantes) == 1
    assert pendientes_restantes[0]["estado"] == "rescatada"


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
