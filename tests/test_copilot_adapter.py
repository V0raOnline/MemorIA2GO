# -*- coding: utf-8 -*-
"""Tests de la importacion del export CSV de Copilot: adaptador, preflight y
la carga de punta a punta por load_conversations.

El CSV real lleva BOM UTF-8, CRLF y mensajes con saltos de linea dentro de
comillas; los tests de punta a punta lo reproducen a proposito.
"""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from providers import copilot_adapter as ca
import preflight
import split_chatgpt_export as sce

CABECERA = "Conversation,Time,Author,Message\r\n"


def _fila(conv="C1", time="2026-09-19T06:48:20", author="User", msg="hola"):
    return {"Conversation": conv, "Time": time, "Author": author, "Message": msg}


def _csv(tmp_path, cuerpo, cabecera=CABECERA, nombre="copilot.csv"):
    p = tmp_path / nombre
    p.write_bytes(("﻿" + cabecera + cuerpo).encode("utf-8"))
    return p


# ---------------------------------------------------------------- detect

def test_detect_reconoce_filas_de_copilot():
    assert ca.detect([_fila()]) is True


@pytest.mark.parametrize("data", [None, [], {}, "x", [{"Conversation": "a"}], ["no dict"],
                                   [{"title": "t", "mapping": {}}]])
def test_detect_rechaza_lo_que_no_es_copilot(data):
    assert ca.detect(data) is False


# ----------------------------------------------------------------- parse

def test_parse_agrupa_por_conversacion_y_mapea_roles():
    convs = ca.parse([
        _fila("A", author="User", msg="pregunta"),
        _fila("A", author="AI", msg="respuesta"),
        _fila("B", author="ai", msg="otra"),
    ])
    assert [c["title"] for c in convs] == ["A", "B"]
    assert convs[0]["messages"] == [{"role": "user", "content": "pregunta"},
                                    {"role": "assistant", "content": "respuesta"}]
    assert convs[1]["messages"][0]["role"] == "assistant"


def test_parse_cumple_el_contrato_del_modelo_intermedio():
    c = ca.parse([_fila()])[0]
    assert set(c) == {"title", "create_time", "update_time", "messages", "gizmo_id", "provider"}
    assert c["provider"] == "copilot" and c["gizmo_id"] is None
    assert set(c["messages"][0]) == {"role", "content"}


def test_parse_create_y_update_son_el_primer_y_ultimo_mensaje_aunque_vengan_desordenados():
    c = ca.parse([_fila(time="2026-09-19T10:00:00"), _fila(time="2026-09-19T08:00:00"),
                  _fila(time="2026-09-19T09:00:00")])[0]
    assert c["update_time"] - c["create_time"] == 2 * 3600
    assert isinstance(c["create_time"], float)


def test_parse_ignora_mensajes_vacios_y_conversaciones_que_se_quedan_sin_nada():
    convs = ca.parse([_fila("A", msg="   "), _fila("B", msg="vale"), _fila("", msg="sin nombre")])
    assert [c["title"] for c in convs] == ["B"]


def test_parse_con_fecha_ilegible_no_revienta_y_deja_none():
    c = ca.parse([_fila(time="ayer por la tarde")])[0]
    assert c["create_time"] is None and c["update_time"] is None
    assert c["messages"][0]["content"] == "hola"


def test_parse_conserva_saltos_de_linea_del_mensaje():
    c = ca.parse([_fila(msg="linea 1\nlinea 2\n\n```py\nx = 1\n```")])[0]
    assert c["messages"][0]["content"] == "linea 1\nlinea 2\n\n```py\nx = 1\n```"


def test_epoch_acepta_z_final():
    assert ca._epoch("2026-09-19T06:48:20Z") == ca._epoch("2026-09-19T06:48:20+00:00")


def test_parse_de_entrada_invalida_devuelve_lista_vacia():
    assert ca.parse(None) == [] and ca.parse([]) == [] and ca.parse("x") == []


# ------------------------------------------------------------- preflight

def test_preflight_acepta_un_csv_de_copilot(tmp_path):
    r = preflight.validate_export_file(_csv(tmp_path, "C,2026-09-19T06:48:20,User,hola\r\n"))
    assert r["valido"] is True and r["tipo"] == "copilot_csv"


def test_preflight_acepta_el_csv_vacio_solo_con_cabeceras(tmp_path):
    # Dos de los tres ficheros del export real vienen asi.
    assert preflight.validate_export_file(_csv(tmp_path, ""))["valido"] is True


def test_preflight_rechaza_un_csv_que_no_es_de_copilot_y_dice_que_cabeceras_hay(tmp_path):
    r = preflight.validate_export_file(_csv(tmp_path, "1,2\r\n", cabecera="a,b\r\n"))
    assert r["valido"] is False and "a, b" in r["mensaje"]


def test_preflight_ya_no_menciona_solo_zip_json_html():
    r = preflight.validate_export_file(RAIZ / "README.md")
    assert ".csv" in r["mensaje"]


# --------------------------------------------------- de punta a punta

def test_load_conversations_lee_el_csv_con_bom_crlf_y_multilinea(tmp_path):
    cuerpo = ('Charla,2026-09-19T06:48:20,User,"hola\r\ncomo estas"\r\n'
              'Charla,2026-09-19T06:48:30,AI,"bien, gracias"\r\n')
    convs, zf = sce.load_conversations(str(_csv(tmp_path, cuerpo)))
    assert zf is None and len(convs) == 1
    assert convs[0]["provider"] == "copilot"
    assert convs[0]["messages"][0]["content"].replace("\r\n", "\n") == "hola\ncomo estas"
    assert convs[0]["messages"][1] == {"role": "assistant", "content": "bien, gracias"}


def test_load_conversations_de_un_csv_vacio_da_cero_conversaciones(tmp_path):
    convs, _ = sce.load_conversations(str(_csv(tmp_path, "")))
    assert convs == []


def test_un_export_de_chatgpt_no_es_secuestrado_por_el_adaptador_de_copilot():
    assert ca.detect([{"title": "t", "mapping": {}, "create_time": 1}]) is False
