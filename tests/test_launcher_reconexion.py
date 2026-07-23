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


def test_pendientes_sin_fichero_devuelve_lista_vacia(client):
    res = client.get("/api/pendientes")
    assert res.get_json() == []


def test_pendientes_lista_lo_que_hay_en_disco(client, tmp_path):
    grok_dir = tmp_path / "vault" / "GROK"
    grok_dir.mkdir(parents=True)
    pendientes = [{"id": "abc123", "prompt": "un gato", "link": "https://grok.com/x",
                   "media_type": "image", "create_time": "2026-06-01T00:00:00Z"}]
    (grok_dir / "_pendientes_descarga.json").write_text(json.dumps(pendientes), encoding="utf-8")

    res = client.get("/api/pendientes")
    assert res.get_json() == pendientes


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
