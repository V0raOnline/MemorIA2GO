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
EL ACCESO DIRECTO NACE AQUI, NO EN LA MAQUINA DE QUIEN CONSTRUYE. Un `.lnk`
guarda rutas ABSOLUTAS, asi que no puede viajar dentro de un zip: el que se
empaquetaba apuntaba a la carpeta de construccion y en cualquier otro
ordenador no llevaba a ninguna parte. Lo caso V0ra probandolo en un equipo
limpio el 2026-08-11 -- es de las cosas que solo se ven fuera de la maquina
donde se hizo. El punto de entrada real es `M3M0R-IA.bat`, tres lineas y
todo relativo a si mismo; el `.lnk` bonito se crea (o se rehace) aqui, con
las rutas de esta maquina, la primera vez que arranca.
"""
import re
import runpy
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CONFIG = AQUI / "memoria_config.yaml"
PLANTILLA = AQUI / "memoria_config.yaml.example"

# Los otros dos ficheros que la aplicacion espera encontrar. Viajan como
# `.example` y hasta hoy nadie los renombraba, asi que el pipeline salia
# a buscar un topic_map.json que no existia. Idea de V0ra, probando en
# limpio: si el instalador renombra uno, que renombre los tres.
MAPAS = ("topic_map.json", "gizmo_map.json")

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


def asegurar_acceso_directo() -> str:
    """Crea junto a la carpeta el .lnk con icono, si falta o si esta rancio.

    Es puramente cosmetico -- sirve para tener icono propio y para poder
    anclarlo a la barra de tareas. Por eso NADA de lo que pase aqui puede
    impedir que la aplicacion arranque: si falla, se dice y se sigue.

    'Rancio' = el .lnk no menciona el python.exe de AHORA. Pasa si alguien
    mueve la carpeta despues de haber arrancado una vez. Se detecta mirando
    los bytes (un .lnk guarda las rutas en UTF-16) en vez de parsear el
    formato: para decidir si hay que rehacerlo, basta.
    """
    destino = AQUI / "python" / "python.exe"
    if not destino.exists():          # arranque desde el repo, sin empaquetar
        return "no_aplica"

    lnk = AQUI.parent / "M3M0R-IA.lnk"
    if lnk.exists():
        try:
            if str(destino).encode("utf-16-le") in lnk.read_bytes():
                return "ya_correcto"
        except OSError:
            pass

    icono = AQUI / "assets" / "M3M0R-IA.ico"
    ps = (
        "$w = New-Object -ComObject WScript.Shell; "
        f"$s = $w.CreateShortcut('{lnk}'); "
        f"$s.TargetPath = '{destino}'; "
        "$s.Arguments = 'first_run.py'; "
        f"$s.WorkingDirectory = '{AQUI}'; "
        "$s.Description = 'M3M0R.IA - tu memoria, en tu disco'; "
        + (f"$s.IconLocation = '{icono}'; " if icono.exists() else "")
        + "$s.Save()"
    )
    try:
        subprocess.run(["powershell", "-NonInteractive", "-Command", ps],
                       check=True, capture_output=True, timeout=30)
        return "creado"
    except Exception:
        # Sin PowerShell, sin permisos, o carpeta de solo lectura. El .bat
        # sigue funcionando: esto solo era el icono.
        return "fallo"


def preparar_mapas() -> list:
    """Crea topic_map.json y gizmo_map.json desde su plantilla si faltan.

    Misma regla que la configuracion: **nunca se pisa lo que ya hay.** Estos
    dos son curaduria del usuario -- los temas, sobre todo, no los
    reconstruye ningun reproceso.
    """
    creados = []
    for nombre in MAPAS:
        destino = AQUI / nombre
        plantilla = AQUI / f"{nombre}.example"
        if destino.exists() or not plantilla.exists():
            continue
        destino.write_text(plantilla.read_text(encoding="utf-8"),
                           encoding="utf-8", newline="")
        creados.append(nombre)
    return creados


def main() -> int:
    estado = preparar_config()
    for nombre in preparar_mapas():
        print(f"Creado {nombre} desde su plantilla.")
    if estado == "sin_plantilla":
        # Sin plantilla no se inventa una configuración: se dice en voz alta.
        # Un YAML generado a ciegas aquí seria una suposición sobre el disco
        # de otra persona.
        print("No encuentro memoria_config.yaml ni memoria_config.yaml.example.",
              file=sys.stderr)
        print(f"Deberian estar los dos en {AQUI}.", file=sys.stderr)
        return 1
    if estado == "creada":
        print("Configuracion creada. Rellena tus rutas en la pestana Configuracion.")

    if asegurar_acceso_directo() == "creado":
        print("Acceso directo M3M0R-IA.lnk creado; puedes anclarlo o copiarlo al escritorio.")

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
