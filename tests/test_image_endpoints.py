# -*- coding: utf-8 -*-
"""Tests de los endpoints de image.ia (Copilot y Grok Imagine).

Mismas reglas que test_suno_endpoints.py. La credencial es lo que importa:
el Bearer de Copilot y, sobre todo, la COOKIE de grok.com, que da acceso a la
cuenta entera mientras dure.

  - No viaja por la URL ni por argv (visible en la lista de procesos).
  - Va al proceso hijo por el entorno.
  - Se censura en el log que se manda en vivo al navegador.
"""
import pytest

import launcher


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    base = tmp_path / "vault"
    (base / "GROK").mkdir(parents=True)
    backup = tmp_path / "copilot_backup"
    backup.mkdir()
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(f"""
paths:
  base_vault: '{base}'
  exports_dir: '{tmp_path}'
  gizmo_map: ''
  copilot_images_backup: '{backup}'
  copilot_images_vault: '{tmp_path / "COPILOT_VAULT"}'
options:
  prj_vault_name: 'PRJ_VAULT'
""", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)
    launcher.app.config["TESTING"] = True
    return launcher.app.test_client(), base, backup


def _falso_popen(capturado, salida):
    class _FakeProc:
        def __init__(self, *a, **kw):
            capturado["argv"] = a[0]
            capturado["env"] = kw.get("env") or {}
            self.stdout = iter(salida)
            self.returncode = 0

        def wait(self):
            return 0
    return _FakeProc


def _falso_run(visto, stdout="TODO OK", code=0):
    def _run(cmd, **kw):
        visto["cmd"] = cmd

        class R:
            returncode = code
        R.stdout, R.stderr = stdout, ""
        return R()
    return _run


# -------------------------------------------------------------- Copilot

def test_copilot_backup_sin_token_no_lanza_nada(entorno):
    client, _, _ = entorno
    res = client.post("/api/copilot_images/backup", json={})
    assert res.status_code == 400 and "token" in res.get_json()["error"].lower()


def test_copilot_rechaza_un_token_cortado(entorno):
    client, _, _ = entorno
    res = client.post("/api/copilot_images/backup", json={"token": "eyJab…cd"})
    assert res.status_code == 400 and "cortado" in res.get_json()["error"]


def test_copilot_token_por_entorno_sin_argv_ni_prefijo_bearer(entorno, monkeypatch):
    client, _, backup = entorno
    capturado = {}
    monkeypatch.setattr(launcher.subprocess, "Popen", _falso_popen(capturado, ["[info] ok\n"]))
    res = client.post("/api/copilot_images/backup", json={"token": "Bearer SECRETO-JWT"})
    assert capturado["env"]["COPILOT_TOKEN"] == "SECRETO-JWT"
    assert not any("SECRETO" in str(a) for a in capturado["argv"])
    assert str(backup) in capturado["argv"]
    assert "SECRETO" not in res.get_data(as_text=True)


def test_copilot_censura_el_token_en_el_log(entorno, monkeypatch):
    client, _, _ = entorno
    monkeypatch.setattr(launcher.subprocess, "Popen",
                        _falso_popen({}, ["[info] usando SECRETO-JWT\n"]))
    cuerpo = client.post("/api/copilot_images/backup", json={"token": "SECRETO-JWT"}).get_data(as_text=True)
    assert "SECRETO-JWT" not in cuerpo and "[token oculto]" in cuerpo


def test_copilot_verify_y_build_llaman_a_sus_scripts(entorno, monkeypatch):
    client, _, backup = entorno
    visto = {}
    monkeypatch.setattr(launcher.subprocess, "run", _falso_run(visto))
    assert client.post("/api/copilot_images/verify").get_json()["ok"] is True
    assert "verify_copilot_images.py" in " ".join(visto["cmd"]) and str(backup) in visto["cmd"]
    assert client.post("/api/copilot_images/build").get_json()["ok"] is True
    assert "build_copilot_images_vault.py" in " ".join(visto["cmd"])


def test_copilot_verify_con_problemas_devuelve_ok_false(entorno, monkeypatch):
    client, _, _ = entorno
    monkeypatch.setattr(launcher.subprocess, "run", _falso_run({}, "faltan", code=1))
    assert client.post("/api/copilot_images/verify").get_json()["ok"] is False


# ----------------------------------------------------------------- Grok

def test_grok_backup_sin_cookie_no_lanza_nada(entorno):
    client, _, _ = entorno
    res = client.post("/api/grok_imagine/backup", json={})
    assert res.status_code == 400 and "cookie" in res.get_json()["error"].lower()


def test_grok_rechaza_una_cookie_cortada_o_no_latin1(entorno):
    client, _, _ = entorno
    assert client.post("/api/grok_imagine/backup", json={"cookie": "a=b…"}).status_code == 400
    assert client.post("/api/grok_imagine/backup", json={"cookie": "a=日本"}).status_code == 400


def test_grok_cookie_por_entorno_sin_argv_y_sin_prefijo(entorno, monkeypatch):
    client, base, _ = entorno
    capturado = {}
    monkeypatch.setattr(launcher.subprocess, "Popen", _falso_popen(capturado, ["[info] ok\n"]))
    res = client.post("/api/grok_imagine/backup", json={"cookie": "Cookie: sso=SECRETA; x=1"})
    assert capturado["env"]["GROK_COOKIE"] == "sso=SECRETA; x=1"
    assert not any("SECRETA" in str(a) for a in capturado["argv"])
    assert str(base / "GROK") in capturado["argv"]
    assert "SECRETA" not in res.get_data(as_text=True)


def test_grok_censura_la_cookie_en_el_log(entorno, monkeypatch):
    client, _, _ = entorno
    monkeypatch.setattr(launcher.subprocess, "Popen",
                        _falso_popen({}, ["[info] cabecera sso=SECRETA; x=1\n"]))
    cuerpo = client.post("/api/grok_imagine/backup", json={"cookie": "sso=SECRETA; x=1"}).get_data(as_text=True)
    assert "SECRETA" not in cuerpo and "[cookie oculta]" in cuerpo


def test_grok_sin_carpeta_grok_existente_avisa_en_vez_de_crearla(tmp_path, monkeypatch):
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(f"""
paths:
  base_vault: '{tmp_path / "no_existe"}'
  exports_dir: '{tmp_path}'
  gizmo_map: ''
options:
  prj_vault_name: 'PRJ_VAULT'
""", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)
    launcher.app.config["TESTING"] = True
    res = launcher.app.test_client().post("/api/grok_imagine/backup", json={"cookie": "a=b"})
    assert res.status_code == 400 and "GROK" in res.get_json()["error"]
    assert not (tmp_path / "no_existe").exists()


def test_grok_verify_llama_al_script_con_la_carpeta_grok(entorno, monkeypatch):
    client, base, _ = entorno
    visto = {}
    monkeypatch.setattr(launcher.subprocess, "run", _falso_run(visto))
    assert client.post("/api/grok_imagine/verify").get_json()["ok"] is True
    assert "verify_grok_imagine.py" in " ".join(visto["cmd"])
    assert str(base / "GROK") in visto["cmd"]
