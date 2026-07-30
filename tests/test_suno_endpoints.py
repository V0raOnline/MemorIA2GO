# -*- coding: utf-8 -*-
"""Tests de los endpoints de MUSIC·0LOGY (pestaña de Suno, 2026-07-30).

El foco está en el token. Es un Bearer de Clerk: mientras dura da acceso a
la cuenta entera de V0ra, y esta es la única parte de la aplicación que
maneja una credencial. Las tres reglas que estos tests fijan:

  - No viaja por la URL (query string -> historial del navegador y logs).
  - No viaja por argv (visible en la lista de procesos del sistema para
    cualquiera que mire).
  - No se persiste en ningún sitio.

Lo que sí viaja es el cuerpo del POST y el entorno del proceso hijo.
"""
import json

import pytest

import launcher


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    backup = tmp_path / "suno_backup"
    backup.mkdir()
    (backup / "_index.json").write_text("[]", encoding="utf-8")
    vault = tmp_path / "SUNO_VAULT"
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(f"""
paths:
  base_vault: '{tmp_path / "vault"}'
  exports_dir: '{tmp_path}'
  gizmo_map: ''
  suno_backup: '{backup}'
  suno_vault: '{vault}'
options:
  prj_vault_name: 'PRJ_VAULT'
""", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)
    launcher.app.config["TESTING"] = True
    return launcher.app.test_client(), backup, vault


def test_backup_sin_token_no_lanza_nada(entorno):
    client, _, _ = entorno

    res = client.post("/api/suno/backup", json={})

    assert res.status_code == 400
    assert "token" in res.get_json()["error"].lower()


def test_el_token_va_por_entorno_nunca_por_argv(entorno, monkeypatch):
    """La regla dura: argv es visible en tasklist/ps para cualquier proceso
    del sistema. El entorno del hijo, no."""
    client, _, _ = entorno
    capturado = {}

    class _FakeProc:
        def __init__(self, *a, **kw):
            capturado["argv"] = a[0]
            capturado["env"] = kw.get("env") or {}
            self.stdout = iter(["[info] listando biblioteca...\n"])
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(launcher.subprocess, "Popen", _FakeProc)

    res = client.post("/api/suno/backup",
                      json={"token": "SECRETO-JWT", "browser_token": "SECRETO-BT"})
    cuerpo = res.get_data(as_text=True)

    assert capturado["env"]["SUNO_TOKEN"] == "SECRETO-JWT"
    assert capturado["env"]["SUNO_BROWSER_TOKEN"] == "SECRETO-BT"
    assert not any("SECRETO" in str(a) for a in capturado["argv"]), \
        "el token acabo en la linea de comandos del proceso"
    assert "SECRETO" not in cuerpo, "el token se devolvio en la respuesta"


def test_el_token_no_aparece_en_el_log_que_se_manda_al_navegador(entorno, monkeypatch):
    """El log va en vivo a la pantalla. Si el script llegara a imprimir el
    token, se veria ahi -- y de ahi a una captura de pantalla compartida hay
    un paso."""
    client, _, _ = entorno

    class _FakeProc:
        def __init__(self, *a, **kw):
            self.stdout = iter(["[info] usando token SECRETO-JWT\n"])
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(launcher.subprocess, "Popen", _FakeProc)
    res = client.post("/api/suno/backup", json={"token": "SECRETO-JWT"})
    cuerpo = res.get_data(as_text=True)

    # El script simulado escupe el token a proposito. El endpoint lo censura
    # en la frontera, en vez de confiar en que ningun print de depuracion se
    # cuele nunca. Escrito primero, y se puso rojo hasta implementar la
    # censura -- que es como se sabe que sirve para algo.
    assert "SECRETO-JWT" not in cuerpo
    assert "[token oculto]" in cuerpo


def test_backup_sin_carpeta_configurada_avisa(tmp_path, monkeypatch):
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(f"""
paths:
  base_vault: '{tmp_path}'
  exports_dir: '{tmp_path}'
  gizmo_map: ''
  suno_backup: ''
  suno_vault: ''
options:
  prj_vault_name: 'PRJ_VAULT'
""", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)
    launcher.app.config["TESTING"] = True

    res = launcher.app.test_client().post("/api/suno/backup", json={"token": "x"})

    assert res.status_code == 400
    assert "suno_backup" in res.get_json()["error"]


def test_verify_llama_al_script_con_la_carpeta_configurada(entorno, monkeypatch):
    client, backup, _ = entorno
    visto = {}

    def _fake_run(cmd, **kw):
        visto["cmd"] = cmd
        class R:
            returncode = 0
            stdout = "Total en indice: 0"
            stderr = ""
        return R()

    monkeypatch.setattr(launcher.subprocess, "run", _fake_run)
    data = client.post("/api/suno/verify").get_json()

    assert data["ok"] is True
    assert "verify_backup.py" in " ".join(visto["cmd"])
    assert str(backup) in visto["cmd"]


def test_build_exige_las_dos_rutas(tmp_path, monkeypatch):
    """Construir necesita origen Y destino. Sin destino no se inventa uno."""
    backup = tmp_path / "suno_backup"
    backup.mkdir()
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(f"""
paths:
  base_vault: '{tmp_path}'
  exports_dir: '{tmp_path}'
  gizmo_map: ''
  suno_backup: '{backup}'
  suno_vault: ''
options:
  prj_vault_name: 'PRJ_VAULT'
""", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)
    launcher.app.config["TESTING"] = True

    res = launcher.app.test_client().post("/api/suno/build")

    assert res.status_code == 400
    assert "suno_vault" in res.get_json()["error"]


def test_build_pasa_origen_y_destino(entorno, monkeypatch):
    client, backup, vault = entorno
    visto = {}

    def _fake_run(cmd, **kw):
        visto["cmd"] = cmd
        class R:
            returncode = 0
            stdout = "Vault construido"
            stderr = ""
        return R()

    monkeypatch.setattr(launcher.subprocess, "run", _fake_run)
    data = client.post("/api/suno/build").get_json()

    assert data["ok"] is True
    assert str(backup) in visto["cmd"]
    assert str(vault) in visto["cmd"]


def test_build_fallido_devuelve_error_no_ok(entorno, monkeypatch):
    client, _, _ = entorno

    def _fake_run(cmd, **kw):
        class R:
            returncode = 1
            stdout = ""
            stderr = "algo se rompio"
        return R()

    monkeypatch.setattr(launcher.subprocess, "run", _fake_run)
    res = client.post("/api/suno/build")

    assert res.status_code == 500
    assert "algo se rompio" in res.get_json()["error"]
