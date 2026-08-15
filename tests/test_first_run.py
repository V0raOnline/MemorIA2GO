# -*- coding: utf-8 -*-
"""Tests del primer arranque del paquete portable (first_run.py).

Lo que se protege aqui no es un formato, es una promesa: **volver a
descomprimir el zip encima no puede costarle a nadie las rutas que ya
habia puesto.** Es el pacto del pipeline ("nunca se borra nada") aplicado
al arranque, y es justo el fallo que nadie reporta -- quien lo sufre
piensa que se equivoco al configurar, no que la herramienta le piso el
fichero.

Los tests parten de la PLANTILLA REAL del repo, no de una copia a mano.
Si alguien anade un marcador de posicion nuevo al `.example` y este
fichero no se entera, los tests avisan.
"""
from pathlib import Path

import pytest

import first_run

PLANTILLA_REAL = Path(first_run.__file__).resolve().parent / "memoria_config.yaml.example"


def test_la_plantilla_real_existe():
    """Si esto se cae, el paquete portable arranca sin poder configurarse."""
    assert PLANTILLA_REAL.exists(), "falta memoria_config.yaml.example en el repo"


def test_crea_la_configuracion_si_no_hay(tmp_path):
    cfg = tmp_path / "memoria_config.yaml"

    estado = first_run.preparar_config(cfg, PLANTILLA_REAL)

    assert estado == "creada"
    assert cfg.exists()


def test_no_pisa_una_configuracion_existente(tmp_path):
    """La promesa del fichero. Descomprimir encima no borra tus rutas."""
    cfg = tmp_path / "memoria_config.yaml"
    mio = "paths:\n  base_vault: 'D:/lo/mio'\n"
    cfg.write_text(mio, encoding="utf-8")

    estado = first_run.preparar_config(cfg, PLANTILLA_REAL)

    assert estado == "ya_existia"
    assert cfg.read_text(encoding="utf-8") == mio


def test_no_pisa_ni_aunque_la_configuracion_sea_un_desastre(tmp_path):
    """Un YAML a medias sigue siendo trabajo de alguien. Se respeta igual:
    que este mal no autoriza a sustituirlo."""
    cfg = tmp_path / "memoria_config.yaml"
    roto = "paths:\n  base_vault: 'D:/a medio\n"
    cfg.write_text(roto, encoding="utf-8")

    assert first_run.preparar_config(cfg, PLANTILLA_REAL) == "ya_existia"
    assert cfg.read_text(encoding="utf-8") == roto


def test_las_rutas_de_ejemplo_llegan_vacias(tmp_path):
    """Motivo (V0ra, 2026-08-10): 'G:\\ruta\\a\\tu\\vault' le parece una ruta
    de verdad a quien no distingue un marcador de posicion, y no sabe que
    tiene que cambiarla. Vacias, toda la Verificacion dice 'No configurado'
    a la vez."""
    cfg = tmp_path / "memoria_config.yaml"
    first_run.preparar_config(cfg, PLANTILLA_REAL)

    texto = cfg.read_text(encoding="utf-8")

    assert "ruta\\a" not in texto and "ruta/a" not in texto, \
        "algun marcador de posicion sobrevivio a la copia"
    assert "base_vault: ''" in texto
    assert "exports_dir: ''" in texto


def test_los_comentarios_de_la_plantilla_sobreviven(tmp_path):
    """El `.example` es la unica documentacion que tiene delante quien abre
    ese fichero a mano. Vaciar rutas no puede costar los comentarios."""
    cfg = tmp_path / "memoria_config.yaml"
    first_run.preparar_config(cfg, PLANTILLA_REAL)

    original = PLANTILLA_REAL.read_text(encoding="utf-8")
    copia = cfg.read_text(encoding="utf-8")
    coment = lambda t: [l for l in t.splitlines() if l.lstrip().startswith("#")]

    assert coment(copia) == coment(original)
    assert len(coment(copia)) > 10, "la plantilla deberia venir comentada"


def test_las_opciones_no_se_tocan(tmp_path):
    """Solo se vacian marcadores de RUTA. Los valores por defecto de
    options (prj_vault_name, by_year...) son configuracion buena."""
    cfg = tmp_path / "memoria_config.yaml"
    first_run.preparar_config(cfg, PLANTILLA_REAL)

    texto = cfg.read_text(encoding="utf-8")

    assert "prj_vault_name: 'PRJ_VAULT'" in texto
    assert "by_year: true" in texto


def test_la_configuracion_creada_es_yaml_valido_y_la_lee_config_loader(tmp_path):
    """De extremo a extremo: lo que escribimos tiene que poder leerlo el
    cargador real de la aplicacion, no solo parecer YAML."""
    from config_loader import load_config

    cfg = tmp_path / "memoria_config.yaml"
    first_run.preparar_config(cfg, PLANTILLA_REAL)

    datos = load_config(str(cfg))

    assert datos["paths"]["base_vault"] == ""
    assert datos["paths"]["exports_dir"] == ""
    assert datos["options"]["prj_vault_name"] == "PRJ_VAULT"


def test_sin_plantilla_lo_dice_en_vez_de_inventarse_una(tmp_path):
    """Generar un YAML a ciegas seria suponer cosas del disco de otra
    persona. Se falla en voz alta, que es el pacto de la casa."""
    estado = first_run.preparar_config(tmp_path / "memoria_config.yaml",
                                       tmp_path / "no_existe.example")

    assert estado == "sin_plantilla"
    assert not (tmp_path / "memoria_config.yaml").exists()


@pytest.mark.parametrize("linea,esperado", [
    ("  base_vault: 'G:\\ruta\\a\\tu\\vault'", "  base_vault: ''"),
    ('  exports_dir: "G:/ruta/a/tus/exports"', "  exports_dir: ''"),
    ("  suno_backup: ''", "  suno_backup: ''"),
    ("  mio: 'D:/musica/backup'", "  mio: 'D:/musica/backup'"),
    ("  make_index: true", "  make_index: true"),
    ("# comentario con ruta/a/algo dentro", "# comentario con ruta/a/algo dentro"),
])
def test_solo_se_vacian_los_marcadores(linea, esperado):
    """Una ruta real del usuario que casualmente pase por una carpeta
    llamada 'ruta' no debe borrarse; y los comentarios, nunca."""
    salida, _ = first_run.vaciar_marcadores(linea + "\n")

    assert salida == esperado + "\n"


# ── El acceso directo, tras el fallo del 2026-08-11 ──────────────────────
#
# V0ra probo el paquete en un equipo limpio y no arrancaba: el `.lnk` que se
# empaquetaba llevaba dentro las rutas ABSOLUTAS de la maquina donde se
# construyo. Un acceso directo de Windows no puede viajar en un zip. Ahora
# el punto de entrada es un `.bat` relativo y el `.lnk` se crea aqui, en la
# maquina del usuario, la primera vez que arranca.
#
# Es cosmetico -- da icono propio y permite anclarlo -- asi que la propiedad
# que de verdad hay que proteger es que NUNCA impida arrancar.

def test_sin_python_embebido_no_hace_nada(tmp_path, monkeypatch):
    """Arrancando desde el repo (sin paquete) no hay nada que crear."""
    monkeypatch.setattr(first_run, "AQUI", tmp_path)

    assert first_run.asegurar_acceso_directo() == "no_aplica"


def test_reconoce_un_acceso_directo_que_ya_apunta_bien(tmp_path, monkeypatch):
    app = tmp_path / "app"
    (app / "python").mkdir(parents=True)
    destino = app / "python" / "python.exe"
    destino.write_bytes(b"")
    monkeypatch.setattr(first_run, "AQUI", app)
    # Un .lnk de verdad guarda las rutas en UTF-16; se imita solo eso
    (tmp_path / "M3M0R-IA.lnk").write_bytes(b"L\x00" + str(destino).encode("utf-16-le"))

    assert first_run.asegurar_acceso_directo() == "ya_correcto"


def test_un_acceso_directo_de_otra_maquina_se_considera_rancio(tmp_path, monkeypatch):
    """EL BUG, en forma de test: el .lnk viene del zip apuntando a la carpeta
    de quien construyo. No menciona el python.exe de aqui, asi que hay que
    rehacerlo en vez de dejarlo roto."""
    app = tmp_path / "app"
    (app / "python").mkdir(parents=True)
    (app / "python" / "python.exe").write_bytes(b"")
    monkeypatch.setattr(first_run, "AQUI", app)
    ajeno = r"C:\Users\OtraPersona\build\M3M0R-IA\app\python\python.exe"
    (tmp_path / "M3M0R-IA.lnk").write_bytes(b"L\x00" + ajeno.encode("utf-16-le"))

    assert first_run.asegurar_acceso_directo() != "ya_correcto"


def test_si_falla_no_revienta_el_arranque(tmp_path, monkeypatch):
    """La propiedad que importa. Sin PowerShell, sin permisos o en una
    carpeta de solo lectura, la aplicacion tiene que arrancar igual: esto
    solo era el icono."""
    app = tmp_path / "app"
    (app / "python").mkdir(parents=True)
    (app / "python" / "python.exe").write_bytes(b"")
    monkeypatch.setattr(first_run, "AQUI", app)

    def revienta(*a, **k):
        raise OSError("no hay powershell aqui")
    monkeypatch.setattr(first_run.subprocess, "run", revienta)

    assert first_run.asegurar_acceso_directo() == "fallo"   # y no una excepcion
