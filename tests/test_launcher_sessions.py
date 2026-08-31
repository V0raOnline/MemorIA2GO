# -*- coding: utf-8 -*-
"""Tests de los endpoints de sesiones locales (/api/sessions/*).

Flask test_client con un vault temporal y una carpeta de sesiones falsa: nunca
toca ~/.claude ni ~/.codex ni el vault real de V0ra.
"""
import json

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
    monkeypatch.setattr(launcher, "CONFIG_PATH",
                        _make_config(tmp_path, tmp_path / "vault"))
    launcher.app.config["TESTING"] = True
    return launcher.app.test_client()


def _sesion_code(sid="S1"):
    return [
        {"type": "user", "sessionId": sid, "cwd": "/repo",
         "timestamp": "2026-08-27T10:00:00Z", "origin": {"kind": "human"},
         "message": {"role": "user", "content": "arregla el bug"}},
        {"type": "assistant", "sessionId": sid,
         "timestamp": "2026-08-27T10:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Read",
              "input": {"file_path": "x.py"}}]}},
        {"type": "user", "sessionId": sid,
         "timestamp": "2026-08-27T10:00:02Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        {"type": "assistant", "sessionId": sid,
         "timestamp": "2026-08-27T10:00:03Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "hecho"}]}},
    ]


def test_status_sin_vault_da_cero(client):
    data = client.get("/api/sessions/status").get_json()
    assert data == {"claude_code": 0, "codex": 0, "total": 0}


def test_ingest_y_status_extremo_a_extremo(client, tmp_path, monkeypatch):
    # Carpeta de sesiones falsa con una sesion de Claude Code.
    proyectos = tmp_path / "fake-claude"
    proyectos.mkdir()
    (proyectos / "s.jsonl").write_text(
        "\n".join(json.dumps(e) for e in _sesion_code()), encoding="utf-8")

    # La ingesta mira las carpetas por defecto: se apuntan a la falsa.
    import session_ingest as si
    monkeypatch.setattr(si, "_carpetas_por_defecto", lambda: [proyectos])
    # Sin sessionId de entorno para que no se omita nada como "activa".
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_HOST_SESSION_ID", raising=False)

    res = client.post("/api/sessions/ingest", json={"nivel": 2}).get_json()
    assert res["ok"] is True
    assert res["sesiones"] == 1
    assert res["notas"] >= 2

    # Y el status ya cuenta la sesion ingerida.
    data = client.get("/api/sessions/status").get_json()
    assert data["claude_code"] == 1
    assert data["total"] == 1


def test_ingest_nivel_se_acota_a_0_3(client, tmp_path, monkeypatch):
    proyectos = tmp_path / "fake"
    proyectos.mkdir()
    (proyectos / "s.jsonl").write_text(
        "\n".join(json.dumps(e) for e in _sesion_code()), encoding="utf-8")
    import session_ingest as si
    monkeypatch.setattr(si, "_carpetas_por_defecto", lambda: [proyectos])
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

    # nivel fuera de rango no revienta: se acota.
    res = client.post("/api/sessions/ingest", json={"nivel": 99}).get_json()
    assert res["ok"] is True
    # nivel 3 (acotado desde 99) -> la nota de herramientas existe
    banco = tmp_path / "vault" / "MERGED_VAULT" / "CLAUDE_CODE" / "SESSIONS"
    assert any(p.name.endswith("tools.md") for p in banco.glob("*.md"))


def test_ingest_nivel_invalido_no_revienta(client, tmp_path, monkeypatch):
    proyectos = tmp_path / "fake"
    proyectos.mkdir()
    import session_ingest as si
    monkeypatch.setattr(si, "_carpetas_por_defecto", lambda: [proyectos])
    res = client.post("/api/sessions/ingest", json={"nivel": "abc"})
    assert res.get_json()["ok"] is True   # nivel no numerico -> por defecto 2
