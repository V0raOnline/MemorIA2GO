# -*- coding: utf-8 -*-
"""Tests de backup_grok_imagine.py y verify_grok_imagine.py.

Se comprueba el estado del DISCO (ficheros, estado, manifest), no solo lo que
devuelven las funciones. Y que la cookie, que da acceso a toda la cuenta, no
se filtra.
"""
import json
import sys
from pathlib import Path

CARPETA = Path(__file__).resolve().parent.parent / "grok_imagine"
sys.path.insert(0, str(CARPETA))

import backup_grok_imagine as bg
import verify_grok_imagine as vg

PNG = b"\x89PNG\r\n\x1a\n" + b"contenido-a"
PNG2 = b"\x89PNG\r\n\x1a\n" + b"contenido-b"


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

    def iter_content(self, n=1):
        if self._content:
            yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Sesion:
    """Sirve respuestas por URL (listas = una por llamada) o en orden."""

    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.visitadas = []

    def get(self, url, timeout=None, stream=False):
        self.visitadas.append(url)
        r = self.respuestas
        if isinstance(r, dict):
            for clave, val in r.items():
                if clave in url:
                    return val.pop(0) if isinstance(val, list) else val
            return _Resp(404)
        return r.pop(0)


def _asset(aid, key=None, **extra):
    a = {"assetId": aid, "key": key if key is not None else f"users/u/{aid}/content",
         "mimeType": "image/png", "createTime": "2026-01-01T00:00:00Z",
         "width": 10, "height": 10, "isPublic": False}
    a.update(extra)
    return a


def _no_dormir(monkeypatch):
    monkeypatch.setattr(bg.time, "sleep", lambda s: None)


# --------------------------------------------------------------- cookie

def test_cookie_se_limpia_del_prefijo_cookie():
    assert bg.limpiar_cookie("  Cookie: a=b; c=d ") == "a=b; c=d"


def test_cookie_truncada_o_vacia_o_no_latin1_se_rechaza():
    assert bg.cookie_valida("") is not None
    assert "«…»" in bg.cookie_valida("a=b…c")
    assert bg.cookie_valida("a=ñ") is None
    assert bg.cookie_valida("a=日本") is not None
    assert bg.cookie_valida("a=b; c=d") is None


def test_la_cookie_va_en_la_cabecera_de_la_sesion():
    assert bg.crear_sesion("a=b").headers["Cookie"] == "a=b"
    assert "Cookie" not in bg.crear_sesion("").headers


# -------------------------------------------------------------- listado

def test_listado_pagina_por_page_token_y_deduplica(monkeypatch):
    _no_dormir(monkeypatch)
    s = _Sesion([_Resp(datos={"assets": [_asset("A"), _asset("B")], "nextPageToken": "t1"}),
                 _Resp(datos={"assets": [_asset("C")]})])
    assets, error = bg.listar_assets(s)
    assert [a["assetId"] for a in assets] == ["A", "B", "C"] and error is None
    assert "pageToken=t1" in s.visitadas[1] and "pageToken" not in s.visitadas[0]


def test_listado_para_si_la_pagina_siguiente_repite_lo_anterior(monkeypatch):
    _no_dormir(monkeypatch)
    pag = {"assets": [_asset("A")], "nextPageToken": "t"}
    assets, error = bg.listar_assets(_Sesion([_Resp(datos=pag), _Resp(datos=pag)]))
    assert [a["assetId"] for a in assets] == ["A"] and error == "fallo"


def test_listado_con_403_dice_que_la_cookie_caduco(monkeypatch):
    _no_dormir(monkeypatch)
    assets, error = bg.listar_assets(_Sesion([_Resp(status=403)]))
    assert assets == [] and error == "caducada"


# ---------------------------------------------------------- descargas

def test_descargar_ok_devuelve_los_bytes():
    assert bg.descargar(_Sesion([_Resp(content=PNG)]), "users/u/x/content") == ("ok", PNG)


def test_descargar_distingue_cookie_caducada_de_ausente(monkeypatch):
    _no_dormir(monkeypatch)
    assert bg.descargar(_Sesion([_Resp(status=403)]), "k")[0] == "caducada"
    assert bg.descargar(_Sesion([_Resp(status=404)]), "k")[0] == "ausente"


def test_descargar_rechaza_html_y_json_haciendose_pasar_por_activo(monkeypatch):
    _no_dormir(monkeypatch)
    assert bg.descargar(_Sesion([_Resp(content=b"<!DOCTYPE html><html>login")]), "k")[0] == "error"
    assert bg.descargar(_Sesion([_Resp(content=b'{"error": "x"}')]), "k")[0] == "error"


def test_descargar_incompleta_reintenta_y_acaba_en_error(monkeypatch):
    _no_dormir(monkeypatch)
    cortas = [_Resp(content=PNG, headers={"content-length": str(len(PNG) + 5)})
              for _ in range(bg.MAX_REINTENTOS)]
    estado, motivo = bg.descargar(_Sesion(cortas), "k")
    assert estado == "error" and "incompleta" in motivo


# ------------------------------------------------------------ procesar

def _entorno(tmp_path):
    grok = tmp_path / "GROK"
    banco = grok / "IMAGINE"
    banco.mkdir(parents=True)
    return grok, banco


def test_procesar_archiva_con_nombre_por_hash_y_manifest_con_linaje(tmp_path, monkeypatch):
    _no_dormir(monkeypatch)
    _, banco = _entorno(tmp_path)
    a = _asset("A", auxKeys={"original-image": "PADRE", "image_edit_is_root_user_uploaded": "true"})
    estado, manifest = {}, {}
    s = _Sesion({"users/u/A": _Resp(content=PNG)})
    c = bg.procesar(s, [a], banco, {}, estado, manifest)
    assert c["nuevas"] == 1 and estado["A"] == "ok"
    fichero = next(f for f in banco.iterdir() if f.suffix == ".png")
    assert (banco / fichero.name).read_bytes() == PNG and len(fichero.stem) == 16
    assert manifest[fichero.name]["edicion_de"] == "PADRE"
    assert manifest[fichero.name]["assetId"] == "A"
    assert json.loads((banco / "_estado.json").read_text(encoding="utf-8"))["A"] == "ok"
    assert not list(banco.glob("*.part"))


def test_procesar_deduplica_por_contenido_contra_otros_bancos(tmp_path, monkeypatch):
    _no_dormir(monkeypatch)
    grok, banco = _entorno(tmp_path)
    otro = grok / "GENERADAS_IMAGEN"
    otro.mkdir()
    (otro / "ya.png").write_bytes(PNG)
    ya = bg.indexar_bancos(grok)
    estado, manifest = {}, {}
    c = bg.procesar(_Sesion({"users/u/A": _Resp(content=PNG)}), [_asset("A")], banco, ya, estado, manifest)
    assert c["repetidas"] == 1 and estado["A"] == "repetida"
    assert not [f for f in banco.iterdir() if f.suffix == ".png"] and manifest == {}


def test_indexar_bancos_ignora_los_ficheros_de_trabajo(tmp_path):
    grok, banco = _entorno(tmp_path)
    (banco / "_inventario.json").write_text("[]", encoding="utf-8")
    (banco / "real.png").write_bytes(PNG)
    assert list(bg.indexar_bancos(grok).values()) == ["IMAGINE/real.png"]


def test_procesar_no_repite_lo_terminado_pero_si_reintenta_los_errores(tmp_path, monkeypatch):
    _no_dormir(monkeypatch)
    _, banco = _entorno(tmp_path)
    estado = {"A": "ok", "B": "repetida", "C": "ausente", "D": "error"}
    s = _Sesion({"users/u/D": _Resp(content=PNG2)})
    c = bg.procesar(s, [_asset(x) for x in "ABCD"], banco, {}, estado, {})
    assert len(s.visitadas) == 1 and "users/u/D" in s.visitadas[0]
    assert c["nuevas"] == 1 and estado["D"] == "ok"


def test_procesar_se_para_si_la_cookie_caduca_y_conserva_lo_bajado(tmp_path, monkeypatch):
    _no_dormir(monkeypatch)
    _, banco = _entorno(tmp_path)
    estado, manifest = {}, {}
    s = _Sesion({"users/u/A": _Resp(content=PNG), "users/u/B": _Resp(status=403)})
    c = bg.procesar(s, [_asset("A"), _asset("B"), _asset("C")], banco, {}, estado, manifest)
    assert c["caducada"] is True and c["nuevas"] == 1
    assert estado == {"A": "ok"}
    assert len(s.visitadas) == 2
    assert len(json.loads((banco / "_image_manifest.json").read_text(encoding="utf-8"))) == 1


def test_procesar_anota_el_404_como_terminal_y_el_asset_sin_key_como_fallo(tmp_path, monkeypatch):
    _no_dormir(monkeypatch)
    _, banco = _entorno(tmp_path)
    estado = {}
    c = bg.procesar(_Sesion({}), [_asset("A"), _asset("B", key="")], banco, {}, estado, {})
    assert estado == {"A": "ausente", "B": "sin key"}
    assert c["ausentes"] == 1 and c["errores"] == 1


def test_la_cookie_nunca_aparece_en_los_ficheros_de_trabajo(tmp_path, monkeypatch):
    _no_dormir(monkeypatch)
    _, banco = _entorno(tmp_path)
    secreto = "sso=COOKIE-SECRETA"
    sesion = bg.crear_sesion(secreto)
    sesion.get = _Sesion({"users/u/A": _Resp(content=PNG)}).get
    bg.procesar(sesion, [_asset("A")], banco, {}, {}, {})
    ficheros = list(banco.iterdir())
    assert len(ficheros) >= 3
    assert all(b"COOKIE-SECRETA" not in f.read_bytes() for f in ficheros)


# --------------------------------------------------------------- verify

def _montar_verify(tmp_path, inventario, estado, manifest, ficheros=()):
    grok, banco = _entorno(tmp_path)
    (banco / "_inventario.json").write_text(json.dumps(inventario), encoding="utf-8")
    (banco / "_estado.json").write_text(json.dumps(estado), encoding="utf-8")
    (banco / "_image_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for f in ficheros:
        (banco / f).write_bytes(PNG)
    return grok


def test_verify_sin_inventario_lo_dice(tmp_path):
    assert vg.verificar(tmp_path)["sin_inventario"] is True


def test_verify_todo_correcto(tmp_path):
    grok = _montar_verify(tmp_path, [_asset("A"), _asset("B")], {"A": "ok", "B": "repetida"},
                          {"a.png": {"assetId": "A"}}, ["a.png"])
    r = vg.verificar(grok)
    assert not (r["nunca"] or r["fallidos"] or r["ok_sin_manifest"] or r["faltan_en_disco"])


def test_verify_detecta_nunca_intentados_fallidos_y_ficheros_perdidos(tmp_path):
    grok = _montar_verify(
        tmp_path, [_asset("A"), _asset("B"), _asset("C"), _asset("D")],
        {"A": "ok", "B": "error", "C": "ausente"},
        {"a.png": {"assetId": "A"}}, [])
    r = vg.verificar(grok)
    assert r["nunca"] == ["D"] and r["fallidos"] == ["B"] and r["ausentes"] == ["C"]
    assert r["faltan_en_disco"] == ["a.png"]


def test_verify_ok_sin_manifest_es_un_problema_y_ausente_no(tmp_path):
    grok = _montar_verify(tmp_path, [_asset("A"), _asset("C")], {"A": "ok", "C": "ausente"}, {})
    r = vg.verificar(grok)
    assert r["ok_sin_manifest"] == ["A"]
