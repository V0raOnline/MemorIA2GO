#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — Construye el paquete portable de Windows de M3M0R·IA.

Produce un zip que se descomprime donde uno quiera y funciona: lleva su
propio Python dentro, las dependencias instaladas, y un acceso directo que
arranca la aplicación y abre el navegador.

USO (en la máquina de desarrollo, no en la del usuario):
    python installer/build.py
    python installer/build.py --salida C:/temp --sin-zip

POR QUE PORTABLE Y CON PYTHON EMBEBIDO (decidido con V0ra 2026-08-10). El
destinatario es gente sin experiencia en consolas -- músicos, escritores,
pensadores. Frente a las dos alternativas obvias:

  - Un `.bat` que instale Python en el sistema: pide administrador y puede
    romperle a alguien un Python que ya tenía funcionando. Inaceptable en
    una herramienta cuyo pacto es que nada se pierde.
  - Un `.exe` único (PyInstaller): dispara falsos positivos de antivirus con
    muchísima frecuencia. A un no técnico eso no le da un aviso, le da un
    susto del que no vuelve.

El paquete portable no toca nada del sistema, no pide permisos, y se
desinstala arrastrando la carpeta a la papelera. Todo está a la vista, que
es la misma promesa que hace el vault.

VERIFICACION DE LA DESCARGA. Este script baja el intérprete de Python de
python.org, y eso es una cadena de suministro: lo que entre aquí acabará
ejecutándose en el ordenador de otra persona. Por eso el SHA-256 va
**fijado a mano** desde la página oficial y se comprueba antes de
descomprimir. Si no está fijado, el script se niega a construir. Un hash
inventado o calculado sobre lo que acabas de bajar no verifica nada.
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Version del interprete que viaja dentro del paquete. El proyecto pide
# 3.10+; se fija una concreta para que el paquete sea reproducible y para
# que el hash de abajo signifique algo.
PY_VERSION = "3.11.9"
PY_ZIP = f"python-{PY_VERSION}-embed-amd64.zip"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/{PY_ZIP}"

# Lo que python.org publica para este fichero es un MD5, y solo eso: en la
# pagina de la version no hay SHA-256 (comprobado 2026-08-10). Se comprueban
# los dos, y cada uno responde a una pregunta distinta:
#
#   PY_MD5    es el valor PUBLICADO. Es la unica cifra que viene de fuera y
#             la unica capaz de decir 'esto no es lo que python.org sirve'.
#             MD5 es debil frente a un atacante con recursos; es lo que hay
#             publicado, y descartarlo por debil seria quedarse sin ninguna.
#   PY_SHA256 se calculo aqui, sobre el fichero que YA habia pasado el MD5.
#             No aporta procedencia: aporta que los bytes son exactamente los
#             mismos con los que se probo, y cierra el hueco teorico de una
#             colision de MD5.
#
# La cadena de confianza fuerte de verdad seria la firma GPG (.asc, con la
# clave del release manager de Python). No esta implementada: pide gpg en la
# maquina que construye. Queda dicho para que nadie crea que esto es mas de
# lo que es.
PY_MD5 = "6d9aa08531d48fcc261ba667e2df17c4"
PY_SHA256 = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"

CONTENIDO_BAT = (
    '@echo off\r\n'
    'rem Punto de entrada de M3M0R.IA. Todo relativo a este fichero, asi que\r\n'
    'rem la carpeta se puede mover, copiar a otro equipo o llevar en un USB.\r\n'
    'cd /d "%~dp0app"\r\n'
    'python\\python.exe first_run.py %*\r\n'
)

NOMBRE = "M3M0R-IA"
REQUISITOS = REPO / "requirements.txt"


def descargar(url: str, destino: Path) -> Path:
    if destino.exists():
        print(f"  ya descargado: {destino.name}")
        return destino
    print(f"  bajando {url}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, destino)
    return destino


def verificar(fichero: Path) -> None:
    """Comprueba el fichero descargado contra los dos hashes fijados.

    Se para en el primero que falle y no construye nada. Lo que entre por
    aqui acaba ejecutandose en el ordenador de otra persona.
    """
    datos = fichero.read_bytes()
    for nombre, esperado, obtenido in (
        ("MD5 (publicado por python.org)", PY_MD5, hashlib.md5(datos).hexdigest()),
        ("SHA-256 (fijado al construir)", PY_SHA256, hashlib.sha256(datos).hexdigest()),
    ):
        if obtenido != esperado.lower().strip():
            raise SystemExit(
                f"\nERROR: {nombre} no coincide en {fichero.name}.\n"
                f"  esperado: {esperado}\n"
                f"  obtenido: {obtenido}\n"
                "No se construye nada con esto."
            )
    print(f"  verificado ({len(datos):,} bytes, MD5 y SHA-256 correctos)")


def python_embebido(destino: Path, cache: Path) -> None:
    """Descomprime el Python embebido y le habilita site-packages.

    El paquete embebido viene con `import site` comentado en su `._pth`, lo
    que deja fuera site-packages y por tanto TODAS las dependencias. Es el
    tropiezo clasico de esta tecnica: descomprimes, instalas, y el programa
    dice que no encuentra flask sin mas explicacion.
    """
    zip_py = descargar(PY_URL, cache / PY_ZIP)
    verificar(zip_py)

    destino.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_py) as z:
        z.extractall(destino)

    pth = next(destino.glob("python*._pth"), None)
    if pth is None:
        raise SystemExit("ERROR: el Python embebido no trae fichero ._pth")
    texto = pth.read_text(encoding="utf-8")
    if "\n#import site" in texto or texto.startswith("#import site"):
        texto = texto.replace("#import site", "import site")

    # Y la carpeta de la aplicacion, que es la trampa gorda de esta tecnica.
    # Con un `._pth`, Python NO anade a sys.path ni el directorio del script
    # ni el actual: la ruta sale entera de este fichero, y su `.` apunta al
    # directorio de python.exe, no al de la aplicacion. Resultado: ningun
    # subproceso podia importar config_loader. El launcher se libraba porque
    # first_run lo arranca con runpy.run_path, que si mete su carpeta.
    if "\n..\n" not in "\n" + texto:
        texto = texto.replace("\n.\n", "\n.\n..\n", 1)
    pth.write_text(texto, encoding="utf-8")
    print("  ._pth: site-packages y la carpeta de la aplicacion")


def dependencias(python_dir: Path) -> None:
    """Instala los requisitos DENTRO del Python embebido.

    Se usa el pip de la maquina de desarrollo con --target en vez de meter
    pip en el paquete: el usuario final no va a instalar nada nunca, asi que
    llevar pip dentro solo suma peso y superficie. --only-binary evita
    compilar en la maquina de quien construye (lxml, sobre todo).
    """
    sitio = python_dir / "Lib" / "site-packages"
    subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "--target", str(sitio),
         "--only-binary", ":all:",
         # Sin .pyc: los compila el Python de ESTA maquina y cada uno guarda
         # dentro la ruta de su fuente, asi que el paquete acabaria repartiendo
         # el arbol de carpetas de quien construye. Se compilan solos, en el
         # ordenador del usuario, la primera vez que se importan.
         "--no-compile",
         "--python-version", ".".join(PY_VERSION.split(".")[:2]),
         "--platform", "win_amd64",
         "-r", str(REQUISITOS)],
        check=True,
    )
    # Los lanzadores de consola (flask.exe, pygmentize.exe...) llevan dentro
    # la ruta del interprete que los genero. No los usa nadie aqui: la
    # aplicacion arranca por first_run.py, nunca por un entry point.
    shutil.rmtree(sitio / "bin", ignore_errors=True)


def copiar_aplicacion(destino: Path) -> None:
    """Copia el codigo via `git archive`: se lleva exactamente lo versionado.

    Nada de listas de exclusion a mano. Lo que este en .gitignore
    (CONFIG, CONTEXT.md, session_files.json, el config real de quien
    construye) se queda fuera por construccion, no por acordarse.
    """
    destino.mkdir(parents=True, exist_ok=True)
    tar = subprocess.run(["git", "archive", "HEAD"], cwd=REPO,
                         check=True, stdout=subprocess.PIPE).stdout
    tmp = destino / "_app.tar"
    tmp.write_bytes(tar)
    shutil.unpack_archive(str(tmp), str(destino), format="tar")
    tmp.unlink()
    # Los tests y el instalador no le sirven de nada a quien solo quiere usarlo
    for sobra in ("tests", "installer"):
        shutil.rmtree(destino / sobra, ignore_errors=True)


def hacer_icono(png: Path, ico: Path, lado: int = 256) -> Path:
    """Convierte el PNG de la mascota en el .ico del acceso directo.

    Lo hace .NET, no Python. La via aparentemente mas limpia -- escribir a
    mano un .ico con el PNG dentro, que el formato admite desde Vista y
    salen quince lineas sin dependencias -- se probo y se descarto: Windows
    lo acepta como icono pero GDI+ revienta al rasterizarlo
    ("el intervalo solicitado se extiende mas alla del final de la matriz").
    Se cargaria en unos sitios y en otros no, que es peor que no tener
    icono. Dejandoselo a System.Drawing, el fichero lo produce el propio
    Windows en el formato clasico y se ve en todas partes.

    Verificado cargando el resultado con System.Drawing.Icon y rasterizando:
    256x256, Format32bppArgb, alfa conservado.

    (Este script solo corre en Windows de todas formas: construye un paquete
    de Windows y ya usa PowerShell para el acceso directo.)
    """
    ps = (
        "Add-Type -AssemblyName System.Drawing; "
        f"$src = [System.Drawing.Image]::FromFile('{png}'); "
        f"$bmp = New-Object System.Drawing.Bitmap($src, {lado}, {lado}); "
        "$ico = [System.Drawing.Icon]::FromHandle($bmp.GetHicon()); "
        f"$fs = [System.IO.File]::Create('{ico}'); "
        "$ico.Save($fs); $fs.Close(); $ico.Dispose(); $bmp.Dispose(); $src.Dispose()"
    )
    subprocess.run(["powershell", "-NonInteractive", "-Command", ps], check=True)
    if not ico.exists() or ico.stat().st_size < 1024:
        raise SystemExit(f"ERROR: no se pudo generar {ico.name} desde {png.name}")
    return ico


def punto_de_entrada(raiz: Path, app: Path) -> None:
    """Escribe el .bat que se pulsa, y el .ico que usara el acceso directo.

    NO se crea aqui ningun .lnk, y esa es la correccion del 2026-08-11. Un
    acceso directo de Windows guarda rutas ABSOLUTAS: el que se empaquetaba
    apuntaba a esta carpeta de construccion, asi que en el ordenador de
    cualquier otra persona no llevaba a ninguna parte. Lo caso V0ra
    probandolo en un equipo limpio. Desde la maquina donde se construye el
    fallo es invisible, porque aqui esas rutas si existen.

    El punto de entrada es un .bat: `%~dp0` es la carpeta del propio fichero,
    asi que funciona se descomprima donde se descomprima. El .lnk con icono
    lo crea `first_run.py` en el primer arranque, ya en la maquina del
    usuario, que es el unico sitio donde puede escribirse correcto.

    Llama a python.exe y no a pythonw.exe por lo de siempre: si algo peta,
    que se vea. Un fallo silencioso al arrancar es lo peor que le puede
    pasar a alguien que no sabe donde mirar.
    """
    hacer_icono(app / "assets" / "M3M0R-IA_Small.png", app / "assets" / "M3M0R-IA.ico")

    bat = raiz / f"{NOMBRE}.bat"
    bat.write_text(CONTENIDO_BAT, encoding="utf-8", newline="")
    print(f"  punto de entrada: {bat.name} (rutas relativas) + icono para el acceso directo")


def sin_rutas_de_esta_maquina(raiz: Path) -> None:
    """Se planta si el paquete lleva dentro rutas de quien lo construye.

    Existe por dos fallos del mismo dia (2026-08-11): el .lnk empaquetado
    apuntaba a la carpeta de construccion -- lo caso V0ra probando en un
    equipo limpio, porque aqui esas rutas SI existen y no se nota -- y al
    ir a arreglarlo aparecieron 807 .pyc y cinco .exe de pip con lo mismo
    dentro. Lo segundo no rompe nada, pero reparte el arbol de carpetas y
    el nombre de usuario de quien construye a todo el que reciba el zip.

    Se busca por lo que ES esta maquina (home y repo), no por una lista de
    cadenas sospechosas: asi vale para cualquiera que construya.
    """
    agujas = {str(Path.home()), str(REPO), str(REPO.drive) + "\\GHU"}
    agujas = {a for a in agujas if len(a) > 3}
    sospechosos = []
    for f in raiz.rglob("*"):
        if not f.is_file():
            continue
        datos = f.read_bytes()
        for cod in ("utf-8", "utf-16-le", "latin-1"):
            try:
                texto = datos.decode(cod)
            except (UnicodeDecodeError, LookupError):
                continue
            if any(a in texto for a in agujas):
                sospechosos.append(f.relative_to(raiz).as_posix())
                break
    if sospechosos:
        raise SystemExit(
            "\nERROR: el paquete lleva rutas de esta maquina dentro:\n"
            + "\n".join(f"  {x}" for x in sospechosos[:15])
            + (f"\n  ... y {len(sospechosos) - 15} mas" if len(sospechosos) > 15 else "")
            + "\nNo se empaqueta: eso no funciona en otro ordenador y ademas se reparte."
        )
    print("  sin rutas de esta maquina")


def main() -> int:
    ap = argparse.ArgumentParser(description="Construye el paquete portable de Windows.")
    ap.add_argument("--salida", default=str(REPO / "dist"), help="Carpeta de salida")
    ap.add_argument("--sin-zip", action="store_true", help="Deja la carpeta sin comprimir")
    args = ap.parse_args()

    salida = Path(args.salida).resolve()
    raiz = salida / NOMBRE
    app = raiz / "app"
    if raiz.exists():
        shutil.rmtree(raiz)

    print("1/4 codigo de la aplicacion")
    copiar_aplicacion(app)
    print("2/4 Python embebido")
    python_embebido(app / "python", salida / "_cache")
    print("3/4 dependencias")
    dependencias(app / "python")
    print("4/4 punto de entrada")
    punto_de_entrada(raiz, app)

    print("comprobando que no se cuele nada de esta maquina")
    sin_rutas_de_esta_maquina(raiz)

    if not args.sin_zip:
        print("comprimiendo...")
        shutil.make_archive(str(salida / NOMBRE), "zip", root_dir=raiz)
        mb = (salida / f"{NOMBRE}.zip").stat().st_size / 1024 / 1024
        print(f"\nlisto: {salida / NOMBRE}.zip  ({mb:.0f} MB)")
    else:
        print(f"\nlisto: {raiz}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
