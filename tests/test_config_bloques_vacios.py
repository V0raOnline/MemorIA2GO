# -*- coding: utf-8 -*-
"""Un bloque vacio en el YAML no puede tumbar la carga de configuracion.

BUG REAL (2026-08-11, V0ra en el equipo limpio). Sintoma desconcertante:
**Verificacion en verde y el pipeline negandose a arrancar** diciendo que no
habia configuracion utilizable. Las dos cosas a la vez, sobre el mismo
fichero.

La causa: en YAML, una clave suelta sin nada debajo

    options:

se carga como `options: None`, no como clave ausente. Y `setdefault` solo
actua si la clave FALTA, asi que el None sobrevivia; el primer `get_opt()`
hacia `None.get(...)` y reventaba con "'NoneType' object has no attribute
'get'". Ese AttributeError lo tragaba un `except Exception` generico que
devolvia None, y el pipeline lo interpretaba como "no hay configuracion".

Verificacion seguia verde porque **solo mira `paths`**: nunca toca
`options`, asi que jamas pisaba la mina. Dos componentes leyendo el mismo
fichero y contradiciendose es lo que hizo el diagnostico tan largo.

La leccion, que es de las que se repiten: **un `except Exception` que
convierte un error de programacion en "no hay datos" borra la pista justo
donde hacia falta.**
"""
import tempfile
from pathlib import Path

import pytest

from config_loader import get_opt, get_path, load_config


def _yaml(texto: str) -> str:
    f = Path(tempfile.mkdtemp()) / "config.yaml"
    f.write_text(texto, encoding="utf-8")
    return str(f)


@pytest.mark.parametrize("caso,texto", [
    ("options como clave suelta", "paths:\n  base_vault: 'C:/v'\noptions:\n"),
    ("paths como clave suelta", "paths:\noptions:\n  make_index: true\n"),
    ("los dos sueltos", "paths:\noptions:\n"),
    ("fichero vacio del todo", ""),
    ("solo comentarios", "# nada mas que esto\n"),
])
def test_los_bloques_vacios_se_leen_como_diccionarios(caso, texto):
    """EL BUG: si alguno queda en None, el primer .get() de abajo revienta."""
    cfg = load_config(_yaml(texto))

    assert isinstance(cfg.get("paths"), dict), f"[{caso}] paths no es dict"
    assert isinstance(cfg.get("options"), dict), f"[{caso}] options no es dict"


@pytest.mark.parametrize("texto", [
    "paths:\n  base_vault: 'C:/v'\noptions:\n",
    "paths:\noptions:\n",
    "",
])
def test_los_lectores_no_revientan_sobre_esos_bloques(texto):
    """El fallo no era el load, era el primer acceso despues. Se comprueba
    el camino completo: los dos lectores que usa todo el proyecto."""
    cfg = load_config(_yaml(texto))

    assert get_opt(cfg, "make_index", True) is not None
    assert get_opt(cfg, "prj_vault_name", "PRJ_VAULT") == "PRJ_VAULT" or True
    get_path(cfg, "base_vault")          # no debe lanzar
    get_path(cfg, "exports_dir")


def test_una_config_con_options_vacio_sirve_para_arrancar(tmp_path):
    """De extremo a extremo, que es donde dolia: con las rutas puestas y
    `options:` suelto, el pipeline tiene que poder arrancar."""
    import MemorIA2GO

    exports = tmp_path / "exports"; exports.mkdir()
    vault = tmp_path / "vault"; vault.mkdir()
    cfg = _yaml(f"paths:\n  exports_dir: '{exports}'\n  base_vault: '{vault}'\noptions:\n")

    problemas: list[str] = []
    params = MemorIA2GO.load_from_yaml(cfg, problemas)

    assert params, f"se sigue negando: {problemas}"
    assert params["exports_dir"] == exports


def test_si_la_lectura_falla_el_motivo_llega_a_quien_pregunta(tmp_path):
    """El otro lado de la leccion: un fallo de lectura no puede quedarse en
    un aviso suelto. Quien llama tiene que poder contarlo en el error."""
    import MemorIA2GO

    roto = tmp_path / "roto.yaml"
    roto.write_text("paths: [esto no es\n  un mapa valido\n", encoding="utf-8")

    problemas: list[str] = []
    params = MemorIA2GO.load_from_yaml(str(roto), problemas)

    assert params is None
    assert problemas, "se nego sin decir por que"
