# -*- coding: utf-8 -*-
"""Tests de backup_copilot_images.py.

Como en los de Suno, se comprueba el estado del DISCO y no solo el valor de
retorno: un .part huerfano o una imagen truncada que "existe" son fallos
silenciosos que la suite no vería.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "copilot_images"))

import backup_copilot_images as bci

SECRETO = "TOKEN-QUE-NO-DEBE-FILTRARSE"


class _Resp:
    def __init__(self, status=200, content=b"", headers=None, datos=None):
        self.status_code = status
        self._content = content
        self.headers = headers or {}
        self._datos = datos

    def json(self):
        if self._datos is None:
            raise ValueError("no json")
        return self._datos

    def iter_content(self, chunk_size=1):
        if self._content:
            yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Sesion:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.posts = []

    def post(self, url, data=None, timeout=None):
        self.posts.append(json.loads(data))
        return self.respuestas.pop(0)

    def get(self, url, stream=False, timeout=None):
        return self.respuestas.pop(0)


def _item(id_, prompt="un submarino", fecha="2025-05-04T11:55:26+00:00",
          nombre="x 15.jpeg", url="https://cdn/x?tempauth=SECRETO", size=5):
    return {
        "ID": id_, "Name": nombre, "CreatedDateTime": fecha,
        "LastModifiedDateTime": fecha, "MimeType": "", "SizeInBytes": size,
        "DownloadUrl": url, "Thumbnail": [{"large": {"Url": "https://t?tempauth=SECRETO"}}],
        "ArtifactCustomMetadata": {"ArtifactType": "Image", "Prompt": prompt,
                                   "CreationIndex": 1, "CreationId": "c1"},
    }


def _no_dormir(monkeypatch):
    monkeypatch.setattr(bci.time, "sleep", lambda s: None)


# ------------------------------------------------------------- metadata

def test_metadata_conserva_prompt_y_quita_urls_con_token():
    meta = bci.extraer_metadata(_item("A1"))
    assert meta["prompt"] == "un submarino"
    assert meta["created_at"].startswith("2025-05-04")
    volcado = json.dumps(meta)
    assert "SECRETO" not in volcado
    assert "DownloadUrl" not in meta["raw"] and "Thumbnail" not in meta["raw"]


def test_prompt_vacio_queda_none_no_cadena_vacia():
    assert bci.extraer_metadata(_item("A1", prompt=""))["prompt"] is None


def test_nombre_base_lleva_fecha_prompt_e_id():
    base = bci.nombre_base(_item("A1", prompt="Un submarino / en el mar?"))
    assert base == "2025-05-04_Un submarino en el mar_A1"


def test_extension_prefiere_el_nombre_y_normaliza_jpeg():
    assert bci.extension(_item("A", nombre="foo.jpeg")) == ".jpg"
    assert bci.extension(_item("A", nombre="foo.png")) == ".png"
    assert bci.extension(_item("A", nombre="sin_ext")) == ".jpg"


# -------------------------------------------------------------- listado

def test_listado_pagina_hasta_que_no_hay_siguiente(monkeypatch):
    _no_dormir(monkeypatch)
    p1 = {"Items": [_item("A"), _item("B")],
          "NextLinkInfo": {"NextLink": "n1", "NextLinkSignature": "s1"}}
    p2 = {"Items": [_item("C")], "NextLinkInfo": {"NextLink": "", "NextLinkSignature": ""}}
    s = _Sesion([_Resp(datos=p1), _Resp(datos=p2)])
    items, error = bci.listar_imagenes(s)
    assert [i["ID"] for i in items] == ["A", "B", "C"] and error is None
    assert s.posts[1]["NextLink"] == "n1" and s.posts[1]["NextLinkSignature"] == "s1"


def test_listado_no_cuenta_dos_veces_lo_repetido(monkeypatch):
    _no_dormir(monkeypatch)
    p1 = {"Items": [_item("A")], "NextLinkInfo": {"NextLink": "n1", "NextLinkSignature": "s"}}
    p2 = {"Items": [_item("A")], "NextLinkInfo": {"NextLink": "n2", "NextLinkSignature": "s"}}
    items, error = bci.listar_imagenes(_Sesion([_Resp(datos=p1), _Resp(datos=p2)]))
    assert [i["ID"] for i in items] == ["A"] and error is None


def test_listado_con_token_caducado_lo_dice(monkeypatch):
    _no_dormir(monkeypatch)
    items, error = bci.listar_imagenes(_Sesion([_Resp(status=401)]))
    assert items == [] and error == "caducado"


# ------------------------------------------------------------ descargas

def test_descarga_completa_deja_la_imagen_y_ningun_part(tmp_path, monkeypatch):
    _no_dormir(monkeypatch)
    destino = tmp_path / "a.jpg"
    r = _Resp(content=b"12345", headers={"content-length": "5"})
    assert bci.descargar(_Sesion([r]), "http://x", destino) == "ok"
    assert destino.read_bytes() == b"12345"
    assert not list(tmp_path.glob("*.part"))


def test_descarga_truncada_no_deja_imagen_que_parezca_completa(tmp_path, monkeypatch):
    _no_dormir(monkeypatch)
    destino = tmp_path / "a.jpg"
    cortas = [_Resp(content=b"123", headers={"content-length": "5"}) for _ in range(bci.MAX_REINTENTOS)]
    assert bci.descargar(_Sesion(cortas), "http://x", destino) == "error"
    assert not destino.exists()
    assert not list(tmp_path.glob("*.part"))


def test_descarga_con_403_se_marca_caducada(tmp_path, monkeypatch):
    _no_dormir(monkeypatch)
    assert bci.descargar(_Sesion([_Resp(status=403)]), "http://x", tmp_path / "a.jpg") == "caducado"


# ------------------------------------------------------ guardar / reanudar

def test_guardar_baja_la_imagen_y_escribe_su_json(tmp_path, monkeypatch):
    _no_dormir(monkeypatch)
    r = _Resp(content=b"12345", headers={"content-length": "5"})
    assert bci.guardar_imagen(_Sesion([r]), _item("A1"), tmp_path) == "nueva"
    base = "2025-05-04_un submarino_A1"
    assert (tmp_path / f"{base}.jpg").read_bytes() == b"12345"
    meta = json.loads((tmp_path / f"{base}.json").read_text(encoding="utf-8"))
    assert meta["prompt"] == "un submarino" and "SECRETO" not in json.dumps(meta)


def test_imagen_bajada_a_mano_se_reconoce_y_solo_gana_su_json(tmp_path):
    previa = tmp_path / "001_A1.jpg"
    previa.write_bytes(b"x")
    sesion = _Sesion([])  # si intentara bajar algo, pop() sobre lista vacia fallaria
    assert bci.guardar_imagen(sesion, _item("A1"), tmp_path) == "ya"
    assert previa.read_bytes() == b"x"
    assert (tmp_path / "001_A1.json").is_file()
    assert not list(tmp_path.glob("*.part")) and len(list(tmp_path.glob("*.jpg"))) == 1


def test_solo_metadata_no_baja_imagenes(tmp_path):
    assert bci.guardar_imagen(_Sesion([]), _item("A1"), tmp_path, solo_metadata=True) == "ya"
    assert not list(tmp_path.glob("*.jpg")) and len(list(tmp_path.glob("*.json"))) == 1


def test_el_token_no_viaja_en_la_sesion_de_descarga():
    api = bci.sesion_api(SECRETO)
    cdn = bci.sesion_cdn()
    assert SECRETO in api.headers["Authorization"]
    assert "Authorization" not in cdn.headers
