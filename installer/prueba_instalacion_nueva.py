# -*- coding: utf-8 -*-
"""Ejercita TODA la API en los estados por los que pasa una instalacion nueva.

USO:  python installer/prueba_instalacion_nueva.py

Existe porque los dos peores fallos del instalador (2026-08-10 y 11) solo
aparecian sin configuracion valida, que es el unico estado en el que ningun
desarrollador vive. Prueba el ARBOL DE TRABAJO y no lo commiteado: sirve
antes de commitear, que es cuando hace falta.

No busca bugs concretos: pone la aplicacion en cada estado por el que pasa
alguien que acaba de instalar y llama a todos los GET. Lo que devuelva 500
es una mina; lo que devuelva 200 con un error dentro, tambien merece mirada.

Estados, en el orden real:
  1. recien instalado    -- config creada por first_run, rutas vacias
  2. options suelto      -- el bug de hoy, por si vuelve
  3. rutas inventadas    -- configuro algo que en ese equipo no existe
  4. rutas correctas     -- carpetas vacias, sin exports todavia
"""
import json
import shutil
import tempfile
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="m3m0ria_banco_"))
BANCO = SCRATCH / "banco"
PUERTO = 8811

GET = [
    "/", "/api/config", "/api/stats", "/api/verificar", "/api/topics",
    "/api/gizmos-pendientes", "/api/layout", "/api/browse?path=C:/",
    "/api/pendientes?provider=grok", "/api/suno/stats", "/api/flowmusic/stats",
    "/api/substack/stats",
]


def preparar():
    if BANCO.exists():
        shutil.rmtree(BANCO)
    BANCO.mkdir(parents=True)
    tar = subprocess.run(["git", "archive", "HEAD"], cwd=REPO, check=True,
                         stdout=subprocess.PIPE).stdout
    (BANCO / "a.tar").write_bytes(tar)
    shutil.unpack_archive(str(BANCO / "a.tar"), str(BANCO), format="tar")
    (BANCO / "a.tar").unlink()
    # Encima, el arbol de trabajo: esto se usa ANTES de commitear, asi que
    # tiene que probar lo que acabas de escribir y no lo que hay en git.
    for f in list(REPO.glob("*.py")) + list(REPO.glob("web/*.js")):
        destino = BANCO / f.relative_to(REPO)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, destino)


def escribir_config(texto: str):
    (BANCO / "memoria_config.yaml").write_text(texto, encoding="utf-8")


def arrancar():
    p = subprocess.Popen([sys.executable, "launcher.py", "--port", str(PUERTO), "--no-browser"],
                         cwd=str(BANCO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace",
                         env={"PYTHONIOENCODING": "utf-8", **__import__("os").environ})
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", PUERTO), timeout=0.4):
                return p
        except OSError:
            time.sleep(0.25)
    raise SystemExit("el servidor no arranco")


def pedir(ruta: str):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}{ruta}", timeout=25) as r:
            cuerpo = r.read(4000).decode("utf-8", "replace")
            return r.status, cuerpo
    except urllib.error.HTTPError as e:
        return e.code, e.read(1500).decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def probar(nombre: str, config: str):
    escribir_config(config)
    srv = arrancar()
    print(f"\n{'=' * 76}\nESTADO: {nombre}\n{'=' * 76}")
    minas = []
    for ruta in GET:
        codigo, cuerpo = pedir(ruta)
        marca = "ok " if codigo == 200 else ("--- " if codigo in (400, 404) else "MINA")
        if codigo not in (200, 400, 404):
            minas.append((ruta, codigo, cuerpo[:200]))
        extra = ""
        if codigo == 200 and '"error"' in cuerpo:
            extra = "  <- 200 pero con error dentro: " + cuerpo[:90]
            minas.append((ruta, "200+error", cuerpo[:200]))
        print(f"  {marca} {codigo:<5} {ruta:<34}{extra}")
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except subprocess.TimeoutExpired:
        srv.kill()
    return minas


preparar()
exports = BANCO / "exports_de_prueba"; exports.mkdir()
vault = BANCO / "vault_de_prueba"; vault.mkdir()

ESTADOS = [
    ("1. recien instalado (rutas vacias)",
     (REPO / "memoria_config.yaml.example").read_text(encoding="utf-8")
     .replace("'G:\\ruta\\a\\tu\\vault'", "''")
     .replace("'G:\\ruta\\a\\tus\\exports'", "''")
     .replace("'G:\\ruta\\a\\MemorIA2GO\\gizmo_map.json'", "''")),
    ("2. bloque options suelto (el bug de hoy)",
     "paths:\n  base_vault: ''\n  exports_dir: ''\noptions:\n"),
    ("3. rutas que en este equipo no existen",
     "paths:\n  base_vault: 'C:/no_esta/vault'\n  exports_dir: 'C:/no_esta/exports'\noptions:\n  make_index: true\n"),
    ("4. rutas correctas, carpetas vacias",
     f"paths:\n  base_vault: '{vault}'\n  exports_dir: '{exports}'\noptions:\n  make_index: true\n"),
]

todas = []
for nombre, cfg in ESTADOS:
    todas += [(nombre, *m) for m in probar(nombre, cfg)]

print(f"\n{'=' * 76}\nRESUMEN: {len(todas)} minas\n{'=' * 76}")
for estado, ruta, codigo, cuerpo in todas:
    print(f"  [{estado.split('.')[0]}] {ruta}  -> {codigo}")
    print(f"        {cuerpo[:150]}")

sys.exit(1 if todas else 0)
