# -*- coding: utf-8 -*-
"""`topic_map.json` no se puede vaciar por accidente desde la interfaz.

Cazado el 2026-08-11 barriendo los POST en busca de minas, no por un fallo
reportado: `POST /api/topics` con el cuerpo vacio escribia `{}` sobre el
mapa de temas y respondia **`{"ok": true, "temas": 0}`**. Los catorce temas
de V0ra, curados a mano durante meses, fuera y sin copia.

Lo que lo hace grave no es la probabilidad, es que **no lo reconstruye
ningun reproceso**: los exports son la fuente de verdad de las
conversaciones, pero de los temas no hay fuente ninguna. Es exactamente lo
que el pacto de la casa promete no hacer, y estaba en la interfaz.

El contraste que lo delata: `/api/gizmos`, su hermano de al lado, fusiona
con lo existente y corta con "nada que guardar" si le llega vacio. Dos
endpoints escritos con criterios opuestos.

Dos capas: la peticion tiene que traer la clave `temas` (una malformada ya
no puede vaciar), y antes de pisar se deja copia (un vaciado legitimo sigue
siendo reversible).
"""
import json

import pytest

import launcher


@pytest.fixture
def app_con_temas(tmp_path, monkeypatch):
    """El launcher apuntando a un topic_map con temas de verdad."""
    monkeypatch.setattr(launcher, "HERE", tmp_path)
    mapa = tmp_path / "topic_map.json"
    mapa.write_text(json.dumps({
        "organoides": ["organoide", "cerebro"],
        "promptologia": ["prompt", "instruccion"],
    }, ensure_ascii=False), encoding="utf-8")
    launcher.app.config["TESTING"] = True
    return launcher.app.test_client(), mapa


def test_un_cuerpo_vacio_ya_no_borra_los_temas(app_con_temas):
    """EL BUG. Antes: 200 'ok' y el fichero a {}."""
    cliente, mapa = app_con_temas
    antes = mapa.read_text(encoding="utf-8")

    r = cliente.post("/api/topics", json={})

    assert r.status_code == 400, "un cuerpo sin 'temas' no puede darse por bueno"
    assert mapa.read_text(encoding="utf-8") == antes, "se toco el fichero igualmente"


def test_una_peticion_sin_json_tampoco(app_con_temas):
    cliente, mapa = app_con_temas
    antes = mapa.read_text(encoding="utf-8")

    r = cliente.post("/api/topics", data=b"", content_type="application/json")

    assert r.status_code == 400
    assert mapa.read_text(encoding="utf-8") == antes


def test_guardar_temas_de_verdad_sigue_funcionando(app_con_temas):
    """La proteccion no puede estorbar al uso normal."""
    cliente, mapa = app_con_temas

    r = cliente.post("/api/topics", json={"temas": {"musica": ["suno", "riff"]}})

    assert r.status_code == 200
    assert json.loads(mapa.read_text(encoding="utf-8")) == {"musica": ["suno", "riff"]}


def test_vaciar_a_proposito_se_permite_pero_deja_copia(app_con_temas):
    """Borrar el ultimo tema es una accion legitima. Lo que no puede ser es
    que sea irreversible: de los temas no hay fuente de verdad en ninguna
    parte, a diferencia de las conversaciones."""
    cliente, mapa = app_con_temas

    r = cliente.post("/api/topics", json={"temas": {}})

    assert r.status_code == 200
    assert json.loads(mapa.read_text(encoding="utf-8")) == {}
    copia = mapa.with_name(mapa.name + ".bak")
    assert copia.exists(), "no quedo copia de lo que se acaba de borrar"
    assert "organoides" in json.loads(copia.read_text(encoding="utf-8"))


def test_cada_guardado_deja_copia_del_estado_anterior(app_con_temas):
    cliente, mapa = app_con_temas
    cliente.post("/api/topics", json={"temas": {"uno": ["a"]}})
    cliente.post("/api/topics", json={"temas": {"dos": ["b"]}})

    copia = json.loads(mapa.with_name(mapa.name + ".bak").read_text(encoding="utf-8"))

    assert copia == {"uno": ["a"]}, "la copia deberia ser el estado inmediatamente anterior"
