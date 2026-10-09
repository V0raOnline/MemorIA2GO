# -*- coding: utf-8 -*-
"""Aislamiento comun de los tests."""
import os

import pytest

import layout


@pytest.fixture(autouse=True)
def _sin_layout_heredado_del_entorno():
    """Ningun test hereda el layout de otro.

    `launcher` deja el layout activo en `os.environ` antes de cada peticion
    (los procesos hijos y los modulos que importa lo leen de ahi), y el entorno
    manda sobre el marcador del vault. Sin esto, un test de Flask dejaba puesto
    el layout clasico y el siguiente, que prueba un vault con OTRO layout, lo
    veia ignorado: pasaba aislado y fallaba en la suite, que es la peor forma de
    fallar un test.
    """
    previo = os.environ.pop(layout.ENV_LAYOUT, None)
    try:
        yield
    finally:
        os.environ.pop(layout.ENV_LAYOUT, None)
        if previo is not None:
            os.environ[layout.ENV_LAYOUT] = previo
