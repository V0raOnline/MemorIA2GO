# -*- coding: utf-8 -*-
"""Herramientas → Taller → REParsea·me: estado, simular, aplicar y deshacer desde la app.

Configuracion y LOGS_DIR temporales, como en test_launcher_taller.py: «Deshacer la ultima» restaura
desde la copia mas reciente de esa carpeta, y la real tiene las de V0ra. Ningun test puede verlas."""
import json

import pytest

import launcher
from test_launcher_taller import CONVS, _config
from test_recuperar_imagenes import _importar, _notas, _zip


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Un vault importado de verdad, con una nota de RAW escrita a la antigua (un bloque en JSON
    crudo). Devuelve (cliente, base, logs, nota)."""
    base, exports, logs = tmp_path / "vault", tmp_path / "exports", tmp_path / "logs"
    exports.mkdir()
    _importar(_zip(tmp_path / "sin.zip", CONVS, {}), base / "RAW_VAULT" / "Conversaciones", base)
    nota = _notas(base / "RAW_VAULT" / "Conversaciones")[0]
    texto = nota.read_text(encoding="utf-8").rstrip("\n")
    nota.write_text(texto + '\n\n### Assistant\n\n{"content_type": "code", "language": "python", "text": "1+1"}\n',
                    encoding="utf-8", newline="")
    monkeypatch.setattr(launcher, "CONFIG_PATH", _config(tmp_path, base_vault=base, exports_dir=exports))
    monkeypatch.setattr(launcher, "LOGS_DIR", logs)
    launcher._reparseame_cache.clear()
    launcher._avisos_cache.clear()
    launcher.app.config["TESTING"] = True
    yield launcher.app.test_client(), base, logs, nota
    launcher._reparseame_cache.clear()
    launcher._avisos_cache.clear()


def _correr(cliente, aplicar):
    salida = cliente.post("/api/taller/reparseame", json={"aplicar": aplicar}).get_data(as_text=True)
    assert "__DONE__ 0" in salida, salida[-1500:]
    resumen = [json.loads(l[11:]) for l in salida.splitlines() if l.startswith("__RESUMEN__")]
    assert len(resumen) == 1
    return salida, resumen[0]


def test_estado_sin_pasadas_cuenta_el_json_crudo(entorno):
    cliente, *_ = entorno
    e = cliente.get("/api/taller/reparseame").get_json()
    assert e == {"ultima": None, "deshacer": None, "json_crudo": 1}


def test_sin_base_lo_dice(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "CONFIG_PATH", _config(tmp_path))
    launcher._reparseame_cache.clear()
    assert "falta" in launcher.app.test_client().get("/api/taller/reparseame").get_json()
    assert launcher.app.test_client().post("/api/taller/reparseame", json={}).status_code == 400


def test_simular_no_escribe_y_no_habla_de_la_consola(entorno):
    cliente, base, logs, nota = entorno
    antes = nota.read_bytes()
    salida, r = _correr(cliente, aplicar=False)
    assert r["aplicado"] is False and r["reescritas"] == 1
    assert nota.read_bytes() == antes
    assert not logs.exists() or not any(c.name.startswith("reparseame_") for c in logs.iterdir())
    assert "python reparseame.py --deshacer" not in salida


def test_aplicar_y_deshacer(entorno):
    cliente, base, logs, nota = entorno
    antes = nota.read_bytes()
    assert cliente.post("/api/taller/reparseame/deshacer").status_code == 404
    _, r = _correr(cliente, aplicar=True)
    assert r["aplicado"] is True and r["reescritas"] == 1
    assert not any(b'{"content_type"' in p.read_bytes() for p in _notas(base / "RAW_VAULT" / "Conversaciones"))
    e = cliente.get("/api/taller/reparseame").get_json()
    assert e["json_crudo"] == 0 and e["ultima"] and e["deshacer"]["nombre"].startswith("reparseame_")
    d = cliente.post("/api/taller/reparseame/deshacer").get_json()
    assert d["ok"] and nota.read_bytes() == antes
    (copia,) = [c for c in logs.iterdir() if c.name.startswith("reparseame_")]
    assert (copia / "deshecho.json").is_file(), "se marca, no se borra"
    assert cliente.post("/api/taller/reparseame/deshacer").status_code == 404
    e = cliente.get("/api/taller/reparseame").get_json()
    assert e["deshacer"] is None and e["ultima"] and e["json_crudo"] == 1


def test_no_se_lanza_si_ya_hay_algo_en_marcha(entorno):
    cliente, *_ = entorno
    assert launcher.run_lock.acquire(blocking=False)
    try:
        assert cliente.post("/api/taller/reparseame", json={}).status_code == 409
    finally:
        launcher.run_lock.release()
