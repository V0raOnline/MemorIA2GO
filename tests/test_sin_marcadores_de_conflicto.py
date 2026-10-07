# -*- coding: utf-8 -*-
"""Ningun fichero versionado puede llevar un conflicto de git sin resolver.

Motivo: el port de la v3.0.0 a `release/en` commiteo marcadores `<<<<<<< HEAD`
en `web/index.html`, y el tag publicado los llevaba: la pagina de
Configuracion los mostraba y habia dos botones de guardar, uno en espanol.
Ningun test lo vio porque las baterias prueban la API, no el HTML, y el
fichero seguia siendo HTML valido para el navegador.

Solo se buscan `<<<<<<< ` y `>>>>>>> ` al principio de linea, con espacio
detras: son los que git escribe siempre. El separador `=======` suelto se
ignora a proposito, porque en Markdown subraya titulos.

Los marcadores se construyen aqui con "<" * 7 para que este fichero no se
delate a si mismo.
"""
import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ABRE = "<" * 7
CIERRA = ">" * 7
MARCADOR = re.compile(rf"^({ABRE}|{CIERRA}) ", re.M)

EXTENSIONES = (".py", ".js", ".html", ".css", ".md", ".yaml", ".yml", ".example",
               ".json", ".txt", ".bat", ".cmd", ".toml", ".cfg", ".ini")
IGNORAR = ("dist/", "python/", "bck/", "OLD/", "test_exports/", "__pycache__/", ".git/")


def buscar_marcadores(texto: str) -> list:
    """Numeros de linea (desde 1) con un marcador de conflicto."""
    return [texto.count("\n", 0, m.start()) + 1 for m in MARCADOR.finditer(texto)]


def _ficheros_versionados():
    """Lo que git versiona; si no hay git (p.ej. dentro del paquete), recorre
    la carpeta saltandose lo que no es codigo propio."""
    try:
        salida = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=True).stdout
        rutas = [RAIZ / r for r in salida.splitlines() if r]
        if rutas:
            return rutas
    except (OSError, subprocess.CalledProcessError):
        pass
    return [p for p in RAIZ.rglob("*") if p.is_file()]


def test_el_detector_ve_un_marcador_de_verdad():
    muestra = f"linea uno\n{ABRE} HEAD\nuna\n=======\notra\n{CIERRA} abc123 (mensaje)\nfin\n"
    assert buscar_marcadores(muestra) == [2, 6]


def test_el_detector_no_se_confunde_con_markdown_ni_con_texto_normal():
    assert buscar_marcadores("Titulo\n=======\n\ntexto con <<< y >>> dentro\n") == []
    assert buscar_marcadores(f"no al principio: {ABRE} HEAD\n") == []
    assert buscar_marcadores(f"{ABRE}sin espacio\n") == []


def test_ningun_fichero_versionado_lleva_marcadores_de_conflicto():
    culpables = []
    for ruta in _ficheros_versionados():
        rel = ruta.relative_to(RAIZ).as_posix()
        if not rel.endswith(EXTENSIONES) or any(rel.startswith(i) or f"/{i}" in f"/{rel}" for i in IGNORAR):
            continue
        try:
            texto = ruta.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lineas = buscar_marcadores(texto)
        if lineas:
            culpables.append(f"{rel}: lineas {lineas}")
    assert not culpables, "conflicto de git sin resolver en:\n  " + "\n  ".join(culpables)
