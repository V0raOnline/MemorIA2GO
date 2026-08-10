# -*- coding: utf-8 -*-
"""Comprueba que todo getElementById de app.js apunta a algo que existe.

BUG REAL que motiva este fichero (2026-08-10, cazado abriendo el paquete
recien construido, no leyendo el codigo): la primera pantalla de una
instalacion nueva mostraba

    Error cargando estadisticas: Cannot set properties of null

en vez del mensaje que el propio codigo escribe dos lineas antes,
"configura la carpeta base en la pestana Configuracion". El manejador del
caso "sin configurar" pedia `projects-top`, un panel retirado del HTML hace
tiempo; getElementById devolvia null, saltaba la excepcion, y el catch de
mas abajo pisaba el mensaje bueno con el error crudo.

La forma del fallo es la de siempre en esta casa: **el comportamiento
correcto existia, estaba escrito, y se deshacia a si mismo.** Y solo se
manifestaba sin configuracion valida -- el unico caso que nadie prueba,
porque quien desarrolla siempre tiene una. Justo el caso del destinatario
del instalador.

En JavaScript esto no es un error de compilacion ni de arranque: no pasa
nada hasta que ese camino se ejecuta. Este test lo convierte en algo que se
ve sin abrir un navegador.
"""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
HTML = WEB / "index.html"
JS = WEB / "app.js"


def _ids_disponibles() -> set:
    """Ids del HTML servido, mas los que el propio JS crea al inyectar."""
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    estaticos = set(re.findall(r'id="([^"]+)"', html))
    # Plantillas dentro de app.js: `<div id="algo">`, con o sin escapar
    dinamicos = set(re.findall(r'id=["\']([\w-]+)["\']', js))
    dinamicos |= set(re.findall(r'id=\\?"([\w-]+)', js))
    return estaticos | dinamicos


def _pedidos() -> list:
    js = JS.read_text(encoding="utf-8")
    return [(m.group(1), js[:m.start()].count("\n") + 1)
            for m in re.finditer(r'getElementById\(["\']([\w-]+)["\']\)', js)]


def test_los_ficheros_del_frontend_existen():
    assert HTML.exists() and JS.exists()


def test_ningun_getElementById_apunta_a_un_id_inexistente():
    disponibles = _ids_disponibles()
    fantasma = sorted({(i, n) for i, n in _pedidos() if i not in disponibles})

    assert not fantasma, "getElementById sobre ids que no existen:\n" + "\n".join(
        f"  app.js:{n} -> '{i}'" for i, n in fantasma
    )


def test_hay_algo_que_comprobar():
    """Red del propio test: si los patrones dejan de casar por un cambio de
    estilo en el codigo, el test de arriba pasaria vacio y no protegeria
    nada. Es el modo de fallo de los tests que barren ficheros."""
    pedidos = _pedidos()

    assert len(pedidos) > 40, f"solo {len(pedidos)} getElementById; el patron no esta casando"
    assert len(_ids_disponibles()) > 40


@pytest.mark.parametrize("id_critico", [
    "dashboard-summary",   # donde aterriza el mensaje de "sin configurar"
    "topics-top",
    "evolution-chart",
])
def test_los_ids_del_camino_sin_configurar_existen(id_critico):
    """Los tres que toca el manejador de stats.error. Son los que ve alguien
    que acaba de instalar y todavia no ha configurado nada: si uno falla,
    la primera pantalla del producto muestra una excepcion."""
    assert id_critico in _ids_disponibles()
