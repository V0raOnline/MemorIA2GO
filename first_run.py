#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
first_run.py — Lo que pasa entre el doble clic y la pestaña del navegador.

Es el punto de entrada del paquete portable de Windows. Prepara lo mínimo
para que la aplicación pueda arrancar y se aparta: crea la configuración si
no existe y lanza `launcher.py`, que abre el navegador solo.

DISEÑO (V0ra, 2026-08-10): el instalador es para gente sin experiencia en
consolas -- músicos, escritores, pensadores. No hay asistente ni pantallas
propias a propósito: la aplicación ya tiene su pestaña de Configuración,
con explorador de rutas, y el Observatorio ya dice "configura la carpeta
base en la pestaña Configuración" cuando aún no hay nada. Duplicar eso aquí
seria un segundo sitio donde configurar lo mismo, que es peor que ninguno.

LA REGLA QUE GOBIERNA ESTE FICHERO: **nunca se pisa una configuración que
ya existe.** Volver a descomprimir el zip encima, o ejecutar esto dos
veces, no puede costarle a nadie las rutas que ya había puesto. Es el mismo
pacto que el del pipeline, aplicado al arranque.

Las rutas de ejemplo se vacían al copiar. En el `.example` valen como
documentación (`G:\\ruta\\a\\tu\\vault` se lee como "aquí va lo tuyo"), pero
en una instalación recién hecha son una trampa: parecen rutas de verdad ya
configuradas, y quien no distingue un marcador de posición de una ruta real
no sabe que tiene que cambiarlas. Vacías, la Verificación dice "No
configurado" en todos los campos a la vez y no hay ambigüedad.
"""
import re
import runpy
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CONFIG = AQUI / "memoria_config.yaml"
PLANTILLA = AQUI / "memoria_config.yaml.example"

# Un valor es marcador de posición si contiene "ruta\a" o "ruta/a": es lo que
# usa la plantilla para decir "esto lo rellenas tú". Se detecta por patrón y
# no por lista de campos, para que un marcador nuevo en la plantilla quede
# cubierto sin tocar este fichero.
MARCADOR_RE = re.compile(r"ruta[\\/]a[\\/]", re.IGNORECASE)

# Captura `  clave: 'valor'` conservando indentación y comillas. Se parchea
# línea a línea, no reescribiendo el YAML, para que los comentarios de la
# plantilla lleguen intactos: son la única documentación que tiene delante
# quien abre ese fichero sin saber lo que mira.
LINEA_RE = re.compile(r"^(\s*)([A-Za-z_][\w]*)\s*:\s*(['\"])(.*)\3\s*$")


def vaciar_marcadores(texto: str) -> tuple[str, int]:
    """Deja en '' todo valor que sea un marcador de posición de la plantilla."""
    salida, vaciados = [], 0
    for linea in texto.splitlines(keepends=True):
        m = LINEA_RE.match(linea.rstrip("\r\n"))
        if m and MARCADOR_RE.search(m.group(4)):
            fin = linea[len(linea.rstrip("\r\n")):]
            salida.append(f"{m.group(1)}{m.group(2)}: ''{fin}")
            vaciados += 1
        else:
            salida.append(linea)
    return "".join(salida), vaciados


def preparar_config(config: Path = CONFIG, plantilla: Path = PLANTILLA) -> str:
    """Crea la configuración desde la plantilla si no la hay.

    Devuelve qué hizo: 'ya_existia', 'creada' o 'sin_plantilla'. Nunca
    sobrescribe: si el fichero está, se respeta tal cual esté, aunque esté
    a medias o mal.
    """
    if config.exists():
        return "ya_existia"
    if not plantilla.exists():
        return "sin_plantilla"

    texto, _ = vaciar_marcadores(plantilla.read_text(encoding="utf-8"))
    config.write_text(texto, encoding="utf-8", newline="")
    return "creada"


def main() -> int:
    estado = preparar_config()
    if estado == "sin_plantilla":
        # Sin plantilla no se inventa una configuración: se dice en voz alta.
        # Un YAML generado a ciegas aquí seria una suposición sobre el disco
        # de otra persona.
        print("Can't find memoria_config.yaml or memoria_config.yaml.example.",
              file=sys.stderr)
        print(f"Both should be in {AQUI}.", file=sys.stderr)
        return 1
    if estado == "creada":
        print("Configuration created. Fill in your paths in the Configuration tab.")

    # runpy en vez de import: launcher.py define su propio main() bajo
    # __name__ == "__main__" y asi se ejecuta igual que si lo hubieras
    # llamado a mano, sin duplicar aqui su arranque.
    #
    # Los argumentos se dejan pasar tal cual. Sin doble clic no hay ninguno
    # y arranca en el puerto de siempre abriendo el navegador, que es el
    # caso para el que existe esto; pero asi `first_run.py --no-browser
    # --port 80` sigue valiendo -- lo necesita quien quiera dejarlo de fondo
    # (README, "URL bonita"), y lo necesitamos nosotros para poder probar el
    # paquete construido sin abrirle una pestana a nadie.
    sys.argv = [str(AQUI / "launcher.py")] + sys.argv[1:]
    runpy.run_path(str(AQUI / "launcher.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
