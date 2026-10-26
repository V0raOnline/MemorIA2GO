# -*- coding: utf-8 -*-
"""Ningun modulo escribe a mano un nombre de carpeta del vault.

Motivo: layout.py es la unica fuente de esos nombres (RAW_VAULT, MERGED_VAULT,
CHATGPT/GENERATED...). Un literal suelto en cualquier otro fichero es una
carpeta que NO se renombra cuando el layout cambia: el pipeline escribiria en
un sitio, el resto leeria de otro, y no daria ningun error. Es el mismo tipo de
fallo silencioso que ya costo caro (enlaces rotos con la verificacion en verde),
asi que se vigila con un test en vez de con disciplina.

Se analiza el AST, no el texto: asi un comentario, un docstring o un mensaje al
usuario que MENCIONA "RAW_VAULT" no cuentan; si cuenta una cadena que ES una
ruta o un componente de ruta ("RAW_VAULT", "CHATGPT/GENERATED", "/MERGED_VAULT/x").

Si hace falta una excepcion legitima, se anade a EXCEPCIONES con el motivo.
"""
import ast
import re
import subprocess
from pathlib import Path

import layout

RAIZ = Path(__file__).resolve().parent.parent

# Lo que no es codigo del producto: los tests construyen fixtures con los
# nombres clasicos a proposito, y bck/ y dist/ son del usuario / generados.
IGNORAR = ("tests/", "bck/", "dist/", "python/", "OLD/", "installer/", "test_exports/",
           "__pycache__/", ".git/")
# El propio layout.py es quien define los nombres.
PROPIOS = {"layout.py"}

# (fichero, cadena) -> motivo. Solo con una razon de verdad.
EXCEPCIONES = {
    ("flowmusic/build_flowmusic_vault.py", "Conversations"):
        "Carpeta DENTRO del vault de Flow Music (transcripciones de cada cancion): otro "
        "concepto que la subcarpeta de conversaciones de RAW/MERGED, solo comparte la palabra.",
}


def _tokens_prohibidos():
    """Cada componente de ruta de cada valor del layout clasico."""
    toks = set()
    for v in layout.CLASICO.a_dict().values():
        toks.update(p for p in v.split("/") if p)
    return toks


TOKENS = _tokens_prohibidos()


def _docstrings(arbol):
    ids = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            cuerpo = nodo.body
            if cuerpo and isinstance(cuerpo[0], ast.Expr) and isinstance(cuerpo[0].value, ast.Constant) \
                    and isinstance(cuerpo[0].value.value, str):
                ids.add(id(cuerpo[0].value))
    return ids


def literales_de_ruta(codigo: str):
    """[(linea, cadena)] de las cadenas del codigo que son nombres de carpeta del vault."""
    arbol = ast.parse(codigo)
    docs = _docstrings(arbol)
    hallados = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) and id(nodo) not in docs:
            componentes = [c for c in re.split(r"[/\\]", nodo.value) if c]
            if any(c in TOKENS for c in componentes):
                hallados.append((nodo.lineno, nodo.col_offset, nodo.value))
    # ast.walk recorre en anchura: se ordena por posicion para un informe legible.
    return [(linea, cadena) for linea, _col, cadena in sorted(hallados)]


def _ficheros_versionados():
    try:
        salida = subprocess.run(["git", "ls-files", "*.py"], cwd=RAIZ, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=True).stdout
        rutas = [RAIZ / r for r in salida.splitlines() if r]
        if rutas:
            return rutas
    except (OSError, subprocess.CalledProcessError):
        pass
    return [p for p in RAIZ.rglob("*.py")]


def test_el_detector_ve_una_ruta_y_no_una_frase():
    assert literales_de_ruta('x = base / "RAW_VAULT" / "Conversations"') == \
        [(1, "RAW_VAULT"), (1, "Conversations")]
    assert literales_de_ruta('p = "CHATGPT/GENERATED"') == [(1, "CHATGPT/GENERATED")]
    assert literales_de_ruta('p = f"{b}/MERGED_VAULT/x"') == [(1, "/MERGED_VAULT/x")]
    assert literales_de_ruta('p = "C:\\\\vault\\\\GROK"') != []
    # un mensaje que solo MENCIONA el nombre no es una ruta
    assert literales_de_ruta('print("Paso 1 — Importar (RAW_VAULT)")') == []
    assert literales_de_ruta('def f():\n    """Escribe en RAW_VAULT/Conversations."""\n    return 1') == []
    # ni una variable de entorno que casualmente empieza igual
    assert literales_de_ruta('os.environ["GROK_COOKIE"]') == []


def test_ningun_modulo_escribe_a_mano_un_nombre_de_carpeta_del_vault():
    culpables = []
    for ruta in _ficheros_versionados():
        rel = ruta.relative_to(RAIZ).as_posix()
        if rel in PROPIOS or any(rel.startswith(i) or f"/{i}" in f"/{rel}" for i in IGNORAR):
            continue
        try:
            codigo = ruta.read_text(encoding="utf-8")
            hallados = literales_de_ruta(codigo)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for linea, cadena in hallados:
            if (rel, cadena) not in EXCEPCIONES:
                culpables.append(f"{rel}:{linea}  {cadena!r}")
    assert not culpables, (
        f"{len(culpables)} nombre(s) de carpeta escritos a mano; deben salir de layout.py:\n  "
        + "\n  ".join(culpables))
