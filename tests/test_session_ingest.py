# -*- coding: utf-8 -*-
"""Tests de la ingesta de sesiones locales (session_ingest.py, paso 3).

Todo contra un vault de prueba en tmp_path: NUNCA el vault real de V0ra. Lo que
se verifica es el reparto cerrado en CONTEXT 3y:
  - la fuente cruda .jsonl se preserva integra en el banco, por hash;
  - la madre cae en Conversaciones/Sesiones-Code/AAAA/MM con el frontmatter que
    el pipeline necesita (Project_name none, provider, source, conv_id);
  - las hijas caen en el banco, FUERA de Conversaciones/ (o contaminarian la
    nube de Cartografia);
  - es idempotente: reingerir no duplica ni pierde nada.
"""
import json
from pathlib import Path

import session_ingest as si
import session_notes as sn


def _escribir_jsonl(path: Path, eventos) -> Path:
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in eventos),
                    encoding="utf-8")
    return path


def _sesion_con_todo(sid="S1", cwd="/repo/MemorIA2GO"):
    """Una sesion con pensamiento visible y herramientas: genera las tres notas."""
    return [
        {"type": "user", "sessionId": sid, "cwd": cwd, "gitBranch": "release/es",
         "timestamp": "2026-08-27T10:00:00Z", "origin": {"kind": "human"},
         "message": {"role": "user", "content": "arregla el bug del parser"}},
        {"type": "assistant", "sessionId": sid,
         "timestamp": "2026-08-27T10:00:05Z",
         "message": {"role": "assistant", "content": [
             {"type": "thinking", "thinking": "el fallo esta en la linea 40",
              "signature": "x"},
             {"type": "text", "text": "Miro el fichero."}]}},
        {"type": "assistant", "sessionId": sid,
         "timestamp": "2026-08-27T10:00:06Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Read",
              "input": {"file_path": "parser.py"}}]}},
        {"type": "user", "sessionId": sid,
         "timestamp": "2026-08-27T10:00:07Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1",
              "content": "return None de mas"}]}},
        {"type": "assistant", "sessionId": sid,
         "timestamp": "2026-08-27T10:00:08Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "Arreglado."}]}},
        {"type": "ai-title", "sessionId": sid, "aiTitle": "Arreglo del parser"},
    ]


def test_ingesta_completa_reparte_bien(tmp_path):
    jsonl = _escribir_jsonl(tmp_path / "s.jsonl", _sesion_con_todo())
    vault = tmp_path / "vault"
    escritas = si.ingest_sesion(jsonl, vault, nivel=2)

    assert set(escritas) == {"madre", "razonamientos", "herramientas"}
    merged = vault / "MERGED_VAULT"

    # La madre en Conversaciones/Sesiones-Code/AAAA/MM
    madre = escritas["madre"]
    assert "Conversaciones" in madre.parts and "Sesiones-Code" in madre.parts
    assert "2026" in madre.parts and "08" in madre.parts

    # Las hijas en el banco, NO bajo Conversaciones
    for rol in ("razonamientos", "herramientas"):
        p = escritas[rol]
        assert "CLAUDE_CODE" in p.parts and "SESIONES" in p.parts
        assert "Conversaciones" not in p.parts

    # La fuente cruda, integra, en el banco
    banco = merged / "CLAUDE_CODE" / "SESIONES"
    fuentes = list(banco.glob("*.jsonl"))
    assert len(fuentes) == 1
    assert fuentes[0].read_bytes() == jsonl.read_bytes()


def test_frontmatter_de_la_madre_es_de_pipeline(tmp_path):
    jsonl = _escribir_jsonl(tmp_path / "s.jsonl", _sesion_con_todo(sid="ABC"))
    escritas = si.ingest_sesion(jsonl, tmp_path / "vault", nivel=2)
    fm = (escritas["madre"]).read_text(encoding="utf-8")
    # Los campos que Cartografia / project_organizer necesitan.
    assert 'Project_name: "none"' in fm
    assert 'provider: "claude-code"' in fm
    assert 'source: "claude_code_session"' in fm
    assert 'conv_id: "ABC"' in fm
    assert "date:" in fm and "title:" in fm


def test_la_madre_no_lleva_ruido_de_herramientas(tmp_path):
    """La conversacion (lo que Cartografia indexa) no debe contener el output
    tecnico: eso vive en la nota de herramientas, fuera de Conversaciones."""
    jsonl = _escribir_jsonl(tmp_path / "s.jsonl", _sesion_con_todo())
    escritas = si.ingest_sesion(jsonl, tmp_path / "vault", nivel=2)
    madre = escritas["madre"].read_text(encoding="utf-8")
    assert "return None de mas" not in madre     # el resultado del Read
    assert "arregla el bug del parser" in madre  # la conversacion, si
    # el enlace a las herramientas, si
    assert "herramienta(s)]]" in madre


def test_el_manifest_registra_la_sesion(tmp_path):
    jsonl = _escribir_jsonl(tmp_path / "s.jsonl", _sesion_con_todo(sid="XYZ"))
    si.ingest_sesion(jsonl, tmp_path / "vault", nivel=2)
    manifest = json.loads(
        (tmp_path / "vault" / "MERGED_VAULT" / "CLAUDE_CODE" / "SESIONES"
         / "_sesiones_manifest.json").read_text(encoding="utf-8"))
    entradas = list(manifest.values())
    assert len(entradas) == 1
    assert entradas[0]["session_id"] == "XYZ"
    assert entradas[0]["turnos"] == 2


def test_idempotente_reingerir_no_duplica(tmp_path):
    jsonl = _escribir_jsonl(tmp_path / "s.jsonl", _sesion_con_todo())
    vault = tmp_path / "vault"
    si.ingest_sesion(jsonl, vault, nivel=2)
    si.ingest_sesion(jsonl, vault, nivel=2)   # otra vez

    banco = vault / "MERGED_VAULT" / "CLAUDE_CODE" / "SESIONES"
    assert len(list(banco.glob("*.jsonl"))) == 1        # una sola fuente
    madres = list((vault / "MERGED_VAULT" / "Conversaciones").rglob("*.md"))
    # Una madre (mismo nombre -> se sobreescribe, no se duplica)
    nombres = {p.name for p in madres}
    assert len(nombres) == 1


def test_sesion_sin_pensamiento_no_crea_razonamientos(tmp_path):
    eventos = [
        {"type": "user", "sessionId": "S", "cwd": "/repo",
         "timestamp": "2026-08-27T10:00:00Z", "origin": {"kind": "human"},
         "message": {"role": "user", "content": "hola"}},
        {"type": "assistant", "sessionId": "S",
         "timestamp": "2026-08-27T10:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "thinking", "thinking": "", "signature": "solo-firma"},
             {"type": "text", "text": "hola, dime"}]}},
    ]
    jsonl = _escribir_jsonl(tmp_path / "s.jsonl", eventos)
    escritas = si.ingest_sesion(jsonl, tmp_path / "vault", nivel=2)
    assert "razonamientos" not in escritas
    assert set(escritas) == {"madre"}


def test_jsonl_sin_contenido_da_none(tmp_path):
    jsonl = _escribir_jsonl(tmp_path / "s.jsonl",
                            [{"type": "queue-operation", "sessionId": "S"}])
    assert si.ingest_sesion(jsonl, tmp_path / "vault") is None


def test_ingest_dir_recorre_todas(tmp_path):
    proyectos = tmp_path / "projects"
    (proyectos / "repoA").mkdir(parents=True)
    (proyectos / "repoB").mkdir(parents=True)
    _escribir_jsonl(proyectos / "repoA" / "s1.jsonl", _sesion_con_todo(sid="A1"))
    _escribir_jsonl(proyectos / "repoB" / "s2.jsonl", _sesion_con_todo(sid="B1"))
    _escribir_jsonl(proyectos / "repoB" / "vacia.jsonl",
                    [{"type": "queue-operation", "sessionId": "V"}])

    stats = si.ingest_dir(proyectos, tmp_path / "vault", nivel=2, log=lambda *a: None)
    assert stats["sesiones"] == 2
    assert stats["vacias"] == 1
    banco = tmp_path / "vault" / "MERGED_VAULT" / "CLAUDE_CODE" / "SESIONES"
    assert len(list(banco.glob("*.jsonl"))) == 2


def test_no_escribe_fuera_del_vault_indicado(tmp_path):
    """Salvaguarda: todo lo escrito cuelga del base_vault que se le pasa."""
    jsonl = _escribir_jsonl(tmp_path / "s.jsonl", _sesion_con_todo())
    vault = tmp_path / "vault"
    escritas = si.ingest_sesion(jsonl, vault, nivel=2)
    for p in escritas.values():
        assert str(p).startswith(str(vault))
