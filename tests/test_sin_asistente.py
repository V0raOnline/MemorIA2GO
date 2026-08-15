# -*- coding: utf-8 -*-
"""El pipeline no puede quedarse esperando a alguien que no esta.

(Edicion inglesa: se comprueban las cadenas que imprime ESTA rama. Es otro
par escritor<->lector, con el mismo riesgo de siempre.)

BUG REAL (2026-08-11, V0ra probando el paquete en un equipo limpio): tras
configurar las rutas en la web, pulsar Construccion dejaba el log parado
para siempre. Por dentro, `MemorIA2GO.py` habia caido en su asistente
interactivo y estaba en un `input()` esperando una respuesta que nadie iba
a escribir, porque no habia consola al otro lado.

Tres fallos encadenados:
  1. `load_from_yaml` devolvia None EN SILENCIO si `exports_dir` no existia
     como carpeta (o si faltaba `base_vault`). Basta con configurar una ruta
     que aun no se ha creado.
  2. Con params en None, el flujo llamaba al asistente. Como subproceso de un
     servidor web, eso es un cuelgue eterno y mudo.
  3. `--no-wizard` hacia lo CONTRARIO de su ayuda: se saltaba la carga del
     YAML y aterrizaba igualmente en el asistente. Ponerselo al launcher no
     habria arreglado nada.

Lo que se protege aqui es una propiedad, no un formato: **nada lanzado sin
consola puede pedir datos por teclado.** Un fallo ruidoso se arregla; uno
que se queda quieto no se diagnostica ni se reporta -- quien lo sufre cree
que el programa "va lento".
"""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
PIPELINE = REPO / "MemorIA2GO.py"


def _config(tmp_path: Path, exports: str, vault: str) -> Path:
    f = tmp_path / "config.yaml"
    f.write_text(yaml.safe_dump({"paths": {"exports_dir": exports, "base_vault": vault}}),
                 encoding="utf-8")
    return f


def _lanzar(cfg: Path, *extra: str) -> subprocess.CompletedProcess:
    """Como lo lanza el launcher: sin consola y sin nadie escribiendo."""
    return subprocess.run(
        [sys.executable, str(PIPELINE), "--config", str(cfg), "--yes", *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=60,
        env={"PYTHONIOENCODING": "utf-8", "PATH": ""} | dict(__import__("os").environ),
    )


@pytest.mark.parametrize("caso,exports,vault", [
    ("la carpeta de exports no existe todavia", "C:/no_existe_esta_carpeta_de_exports", "C:/vault"),
    ("exports_dir sin configurar", "", "C:/vault"),
    ("base_vault sin configurar", ".", ""),
])
def test_con_config_incompleta_termina_y_no_se_cuelga(tmp_path, caso, exports, vault):
    """EL BUG. Antes: input() eterno. Ahora: sale con codigo != 0 y explica."""
    r = _lanzar(_config(tmp_path, exports, vault), "--no-wizard")

    assert r.returncode != 0, f"[{caso}] deberia fallar, no seguir como si nada"
    salida = r.stdout + r.stderr
    assert "can't ask you" in salida.lower(), \
        f"[{caso}] no dice por que se para; salida: {salida[-300:]}"


def test_dice_QUE_ruta_es_la_que_falla(tmp_path):
    """Un 'configuracion invalida' a secas obliga a adivinar cual de las dos."""
    r = _lanzar(_config(tmp_path, "C:/una_carpeta_que_no_esta", "C:/vault"), "--no-wizard")

    assert "does not exist" in (r.stdout + r.stderr).lower()
    assert "una_carpeta_que_no_esta" in r.stdout + r.stderr


def test_sin_el_flag_tampoco_pregunta_si_no_hay_consola(tmp_path):
    """La red de verdad: aunque nadie se acuerde de pasar --no-wizard, con la
    entrada cerrada no puede haber un input(). Es lo que hace imposible el
    cuelgue, en vez de improbable. Ojo: NO vale comprobar isatty() antes de
    preguntar -- en Windows devuelve True con stdin=DEVNULL. El unico momento
    en que se sabe seguro es cuando input() da EOF."""
    r = _lanzar(_config(tmp_path, "C:/tampoco_existe", "C:/vault"))

    assert r.returncode != 0
    assert "nobody answered" in (r.stdout + r.stderr).lower()


def test_el_launcher_lanza_el_pipeline_sin_asistente_y_sin_entrada():
    """Contrato con launcher.py: los dos sitios donde arranca el pipeline
    tienen que pasar --no-wizard y cerrar stdin. Si alguien anade un tercero
    y se olvida, este test no lo ve -- por eso ademas existe la red de
    arriba, que no depende de acordarse."""
    codigo = (REPO / "launcher.py").read_text(encoding="utf-8")
    llamadas = codigo.count('str(HERE / "MemorIA2GO.py")')

    assert llamadas >= 2, "cambio la forma de invocar el pipeline"
    assert codigo.count('"--no-wizard"') >= llamadas
    assert codigo.count("stdin=subprocess.DEVNULL") >= llamadas
