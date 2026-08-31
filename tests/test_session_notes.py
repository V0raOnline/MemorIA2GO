# -*- coding: utf-8 -*-
"""Tests del generador de las tres notas de sesion (session_notes.py).

Lo que importa verificar, porque es lo que hace o rompe el diseño (CONTEXT 3y):
  - el enlace de la madre a las hijas es de BLOQUE (^tN) y el ancla de destino
    existe en la hija con el MISMO numero -- si divergen, el salto no funciona;
  - las hijas son condicionales: sin pensamiento no hay nota de razonamientos;
  - la verbosidad controla el output de herramientas sin tocar la conversacion;
  - la numeracion de turnos es consistente entre las tres notas.
"""
import re

import session_notes as sn


def _sesion(turns, **meta):
    base = {"provider": "claude-code", "session_id": "S1",
            "title": "Sesión de prueba", "project": "/repo",
            "git_branch": "main", "create_time": 1735732800.0,
            "update_time": 1735732900.0, "turns": turns}
    base.update(meta)
    return base


def _asis(text="respondo", thinking=None, tools=None):
    return {"role": "assistant", "text": text,
            "thinking": thinking or [], "tools": tools or []}


def _user(text="pregunto"):
    return {"role": "user", "text": text}


def _tool(name="Read", cmd="foo.py", result="ok"):
    return {"name": name, "input": {"file_path": cmd}, "result": result, "id": "x"}


def test_madre_siempre_hijas_condicionales(tmp_path):
    # Sesion sin pensamiento ni herramientas: solo madre.
    ses = _sesion([_user(), _asis()])
    esc = sn.generar_notas(ses, tmp_path, nivel=2)
    assert set(esc) == {"madre"}


def test_con_herramientas_aparece_su_nota(tmp_path):
    ses = _sesion([_user(), _asis(tools=[_tool()])])
    esc = sn.generar_notas(ses, tmp_path, nivel=2)
    assert set(esc) == {"madre", "herramientas"}


def test_con_pensamiento_aparece_su_nota(tmp_path):
    ses = _sesion([_user(), _asis(thinking=["lo pensé así"])])
    esc = sn.generar_notas(ses, tmp_path, nivel=2)
    assert set(esc) == {"madre", "razonamientos"}


def test_el_enlace_de_bloque_casa_con_su_ancla(tmp_path):
    """Turno 2 de asistente con herramientas: la madre enlaza ^t2 y la nota de
    herramientas tiene ^t2. Los numeros TIENEN que coincidir."""
    ses = _sesion([
        _user(), _asis("primera"),                      # turno asis 1, sin tools
        _user(), _asis("segunda", tools=[_tool()]),     # turno asis 2, con tools
    ])
    esc = sn.generar_notas(ses, tmp_path, nivel=2)
    madre = esc["madre"].read_text(encoding="utf-8")
    tools = esc["herramientas"].read_text(encoding="utf-8")

    # La madre enlaza al bloque ^t2 (no ^t1, que no tiene herramientas).
    assert "#^t2|1 herramienta(s)]]" in madre
    assert "^t1" not in madre
    # Y la nota de herramientas tiene ese ancla de destino.
    assert "## Turno 2 ^t2" in tools
    # El nombre de la hija en el enlace es exactamente el fichero escrito.
    nom = sn.nombres(ses)
    assert "[[%s#^t2" % nom["herramientas"] in madre
    assert esc["herramientas"].stem == nom["herramientas"]


def test_numeracion_consistente_en_las_tres_notas(tmp_path):
    ses = _sesion([
        _user(), _asis("a", thinking=["p1"], tools=[_tool()]),
        _user(), _asis("b", thinking=["p2"], tools=[_tool()]),
    ])
    esc = sn.generar_notas(ses, tmp_path, nivel=2)
    madre = esc["madre"].read_text(encoding="utf-8")
    raz = esc["razonamientos"].read_text(encoding="utf-8")
    tools = esc["herramientas"].read_text(encoding="utf-8")
    for n in (1, 2):
        assert ("#^t%d|pensó]]" % n) in madre
        assert ("## Turno %d ^t%d" % (n, n)) in raz
        assert ("## Turno %d ^t%d" % (n, n)) in tools


def test_verbosidad_0_no_escribe_herramientas(tmp_path):
    ses = _sesion([_user(), _asis(tools=[_tool()])])
    esc = sn.generar_notas(ses, tmp_path, nivel=0)
    assert "herramientas" not in esc
    # Y la madre no pone el ancla de herramientas.
    assert "herramienta(s)]]" not in esc["madre"].read_text(encoding="utf-8")


def test_verbosidad_1_es_traza_sin_resultado(tmp_path):
    ses = _sesion([_user(), _asis(tools=[_tool(result="RESULTADO_LARGO")])])
    esc = sn.generar_notas(ses, tmp_path, nivel=1)
    t = esc["herramientas"].read_text(encoding="utf-8")
    assert "**`Read`**" in t
    assert "RESULTADO_LARGO" not in t          # el resultado no se pinta
    assert "<details>" not in t


def test_verbosidad_2_pliega_el_resultado(tmp_path):
    ses = _sesion([_user(), _asis(tools=[_tool(result="RESULTADO_LARGO")])])
    t = sn.generar_notas(ses, tmp_path, nivel=2)["herramientas"].read_text(encoding="utf-8")
    assert "<details>" in t and "RESULTADO_LARGO" in t


def test_verbosidad_3_resultado_integro_sin_details(tmp_path):
    ses = _sesion([_user(), _asis(tools=[_tool(result="RESULTADO_LARGO")])])
    t = sn.generar_notas(ses, tmp_path, nivel=3)["herramientas"].read_text(encoding="utf-8")
    assert "RESULTADO_LARGO" in t and "<details>" not in t


def test_la_conversacion_no_depende_de_la_verbosidad(tmp_path):
    """Bajar la verbosidad recorta herramientas, nunca la conversacion."""
    ses = _sesion([_user("mi pregunta"), _asis("mi respuesta", tools=[_tool()])])
    for nivel in (0, 1, 2, 3):
        madre = sn.generar_notas(ses, tmp_path, nivel=nivel)["madre"].read_text(encoding="utf-8")
        assert "mi pregunta" in madre and "mi respuesta" in madre


def test_thinking_vacio_no_crea_nota_fantasma(tmp_path):
    """Un turno cuyo thinking es [] (no estaba visible) no debe crear la nota
    de razonamientos."""
    ses = _sesion([_user(), _asis("hola", thinking=[])])
    assert "razonamientos" not in sn.generar_notas(ses, tmp_path, nivel=2)


def test_dos_sesiones_mismo_titulo_y_dia_no_colisionan(tmp_path):
    """Bug real (2026-08-31): 4 sesiones de Codex del mismo dia sin titulo
    quedaban todas como 'sesion-de-agente' y se pisaban al escribir. El nombre
    deriva del session_id, asi que dos sesiones distintas dan nombres distintos
    aunque compartan titulo y fecha."""
    ses_a = _sesion([_user(), _asis()], session_id="aaaaaaaa-1111",
                    title=None, create_time=1735732800.0)
    ses_b = _sesion([_user(), _asis()], session_id="bbbbbbbb-2222",
                    title=None, create_time=1735732800.0)
    a = sn.generar_notas(ses_a, tmp_path, nivel=2)
    b = sn.generar_notas(ses_b, tmp_path, nivel=2)
    assert a["madre"].name != b["madre"].name
    # las dos madres sobreviven en disco
    assert a["madre"].exists() and b["madre"].exists()


def test_sesion_vacia_no_escribe_nada(tmp_path):
    assert sn.generar_notas({"turns": []}, tmp_path) == {}
    assert sn.generar_notas(None, tmp_path) == {}


def test_el_slug_no_produce_nombres_peligrosos():
    n = sn.nombres({"title": "Fix: /etc/passwd  ·  ¿roto?",
                    "create_time": 1735732800.0})
    assert "/" not in n["madre"] and "\\" not in n["madre"]
    # La fecha del prefijo sale de create_time; el punto es que el slug limpia
    # las barras y signos, no la fecha exacta (que depende de la zona horaria).
    assert re.match(r"20\d\d-\d\d-\d\d_fix-etc-passwd-roto", n["madre"])
