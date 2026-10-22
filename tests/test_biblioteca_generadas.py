# -*- coding: utf-8 -*-
"""Imagenes generadas de la biblioteca del export (library_files.json) colgadas de SU conversacion.

Desde el export de 2026-07 los mensajes del asistente ya no traen las imagenes generadas (ni el JSON con
su prompt): solo quedan como ficheros sueltos en la biblioteca, y cada entrada dice de que hilo salio en
`origination_thread_id` (= conversation_id). Se cuelgan de su nota como un mensaje `tool` al final, con
el titulo y la hora que les puso ChatGPT, igual que dejaban las notas antiguas:

    ### Tool

    *Polluelo de gorrion en grafito* · 2026-10-17 23:12

    ![](CHATGPT/GENERADAS/5f7fa7a14d883163.png)

El importador lo hace con los exports nuevos y recuperar_imagenes.py --biblioteca con las notas que ya
existen; las dos usan el MISMO texto, para que el merge no duplique nada cuando llegue el siguiente export.
"""
import datetime
import json
import re
import shutil
from pathlib import Path

import pytest

import recuperar_imagenes as rec
import split_chatgpt_export as sce
from test_recuperar_imagenes import (FECHA_VIEJA, JPG, PNG, PNG2, _conv, _foto, _fusionar, _importar, _notas,
                                     _por_proyectos, _recuperar, _zip)

HILO = "conv-rec-0001"
CREADA = "2026-10-17T21:12:23.484227+00:00"


def _entrada(fid, nombre, hilo=HILO, creada=CREADA, estado="ready", generada=True):
    return {"file_id": fid, "file_name": nombre, "mime_type": "image/png", "created_at": creada, "state": estado,
            "image_gen_generation_id": "s_1" if generada else None, "origination_thread_id": hilo}


def _hora(creada=CREADA):
    return datetime.datetime.fromisoformat(creada).astimezone().strftime("%Y-%m-%d %H:%M")


def _export(tmp_path, biblioteca, ficheros, nombre="export.zip", convs=None):
    convs = convs if convs is not None else [_conv([("sediment://file_subida", False)])]
    return _zip(tmp_path / nombre, convs, {"file_subida.dat": PNG2, **ficheros}, biblioteca)


def _nota_importada(tmp_path, zip_, nombre="vault"):
    base = tmp_path / nombre
    _importar(zip_, base / "RAW_VAULT" / "Conversaciones", base)
    return base, _notas(base / "RAW_VAULT" / "Conversaciones")[0]


# ---- el importador -------------------------------------------------------------------------------------
def test_el_importador_cuelga_la_generada_de_su_conversacion_al_final(tmp_path):
    z = _export(tmp_path, [_entrada("file_gen1", "Polluelo de gorrion en grafito.png")], {"file_gen1.dat": PNG})
    base, nota = _nota_importada(tmp_path, z)
    t = nota.read_text(encoding="utf-8")
    assert t.rstrip().endswith("\n".join(["### Tool", "", f"*Polluelo de gorrion en grafito* · {_hora()}", "",
                                          t.rstrip().rsplit("\n", 1)[1]]))
    enlace = re.findall(r"!\[\]\((CHATGPT/GENERADAS/[^)]+)\)", t)
    assert len(enlace) == 1 and enlace[0].endswith(".png")
    assert (base / enlace[0]).read_bytes() == PNG


def test_el_bloque_tiene_exactamente_el_formato_acordado(tmp_path):
    z = _export(tmp_path, [_entrada("file_gen1", "Polluelo de gorrion en grafito.png")], {"file_gen1.dat": PNG})
    base, nota = _nota_importada(tmp_path, z)
    fname = next((base / "CHATGPT" / "GENERADAS").glob("*.png")).name
    esperado = f"### Tool\n\n*Polluelo de gorrion en grafito* · {_hora()}\n\n![](CHATGPT/GENERADAS/{fname})"
    assert nota.read_text(encoding="utf-8").rstrip().endswith(esperado)


def test_va_a_generadas_con_su_origen_y_titulo_en_el_manifiesto(tmp_path):
    z = _export(tmp_path, [_entrada("file_gen1", "Polluelo.png")], {"file_gen1.dat": PNG})
    base, _ = _nota_importada(tmp_path, z)
    man = json.loads((base / "CHATGPT" / "GENERADAS" / "_image_manifest.json").read_text(encoding="utf-8"))
    (m,) = man.values()
    assert m["origen"] == "generada" and m["titulo_biblioteca"] == "Polluelo"
    assert m["creada"] == "2026-10-17T21:12:23" and m["primera_conversacion"] == "Con imagenes"


def test_varias_imagenes_del_mismo_hilo_van_en_orden_de_creacion(tmp_path):
    # los ids van al reves de la hora: ordenar por id daria el orden contrario
    lib = [_entrada("file_a", "Segunda.png", creada="2026-10-17T21:30:00+00:00"),
           _entrada("file_z", "Primera.png", creada="2026-10-17T21:10:00+00:00")]
    z = _export(tmp_path, lib, {"file_a.dat": PNG, "file_z.dat": JPG})
    _, nota = _nota_importada(tmp_path, z)
    t = nota.read_text(encoding="utf-8")
    assert t.count("### Tool") == 2 and t.index("*Primera*") < t.index("*Segunda*")


def test_se_salta_lo_que_la_conversacion_ya_enlaza(tmp_path):
    """Seis de las 418 generadas ya venian enlazadas por su puntero: no se duplican."""
    convs = [_conv([("sediment://file_gen1", True)])]
    z = _export(tmp_path, [_entrada("file_gen1", "Ya estaba.png")], {"file_gen1.dat": PNG}, convs=convs)
    _, nota = _nota_importada(tmp_path, z)
    t = nota.read_text(encoding="utf-8")
    assert t.count("![](CHATGPT/GENERADAS/") == 1 and "*Ya estaba*" not in t


def test_se_salta_lo_que_no_tiene_fichero_en_el_zip(tmp_path):
    z = _export(tmp_path, [_entrada("file_sin_fichero", "No viene.png", estado="created")], {})
    _, nota = _nota_importada(tmp_path, z)
    assert "### Tool" not in nota.read_text(encoding="utf-8")


def test_una_imagen_de_un_hilo_que_el_export_no_trae_no_rompe_nada(tmp_path):
    z = _export(tmp_path, [_entrada("file_gen1", "De otro hilo.png", hilo="otro-hilo")], {"file_gen1.dat": PNG})
    _, nota = _nota_importada(tmp_path, z)
    assert "### Tool" not in nota.read_text(encoding="utf-8")


def test_solo_las_generadas_no_las_subidas_de_la_biblioteca(tmp_path):
    z = _export(tmp_path, [_entrada("file_up", "Captura.png", generada=False)], {"file_up.dat": PNG})
    _, nota = _nota_importada(tmp_path, z)
    assert "### Tool" not in nota.read_text(encoding="utf-8")


def test_sin_biblioteca_el_importador_no_cambia(tmp_path):
    z = _export(tmp_path, None, {})
    _, nota = _nota_importada(tmp_path, z)
    assert "### Tool" not in nota.read_text(encoding="utf-8")


def test_el_importador_cuenta_en_el_resumen_las_que_ha_colgado(tmp_path):
    z = _export(tmp_path, [_entrada("file_gen1", "Una.png")], {"file_gen1.dat": PNG})
    import subprocess, sys
    r = subprocess.run([sys.executable, str(Path(rec.__file__).parent / "split_chatgpt_export.py"), str(z),
                        str(tmp_path / "RAW"), "--generadas-dir", str(tmp_path / "G"),
                        "--adjuntos-dir", str(tmp_path / "A")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert "Biblioteca: 1 imagenes generadas colgadas de su conversacion" in r.stdout


@pytest.mark.parametrize("nombre,titulo", [
    ("Polluelo de gorrión.png", "Polluelo de gorrión"), ("Sin extension", "Sin extension"),
    ("Con *asteriscos* raros.png", "Con asteriscos raros"), ("Dos\nlineas.png", "Dos lineas"),
    ("  Con espacios .jpg", "Con espacios"), ("Con.punto.webp", "Con.punto"), ("notas.txt", "notas.txt")])
def test_el_titulo_se_limpia_igual_siempre(nombre, titulo):
    assert sce.titulo_biblioteca({"file_name": nombre}) == titulo


def test_un_titulo_vacio_sale_como_imagen_generada():
    assert sce.texto_biblioteca({"file_name": "", "created_at": CREADA}, "X").startswith("*Imagen generada*")


def test_una_fecha_ilegible_no_rompe_el_bloque():
    assert sce.texto_biblioteca({"file_name": "A.png", "created_at": "ayer"}, "X") == "*A*\n\nX"


@pytest.mark.parametrize("fid,esquema", [("file_00000000abc", "sediment://"), ("file-AbC123", "file-service://")])
def test_el_esquema_del_puntero_sale_del_id(fid, esquema):
    assert sce.puntero_de_biblioteca({"file_id": fid}) == esquema + fid


# ---- la reparacion de notas que ya existen ------------------------------------------------------------------------
@pytest.fixture
def vault_viejo(tmp_path):
    """Un vault construido por el pipeline con un export SIN biblioteca (como los de antes)."""
    sin = _zip(tmp_path / "sin_biblioteca.zip", [_conv([("sediment://file_subida", False)])], {"file_subida.dat": PNG2})
    base = tmp_path / "vault"
    _importar(sin, base / "RAW_VAULT" / "Conversaciones", base)
    _fusionar(base / "RAW_VAULT", base / "MERGED_VAULT")
    _por_proyectos(base / "MERGED_VAULT", base / "PRJ_VAULT")
    for d in ("RAW_VAULT/Conversaciones", "MERGED_VAULT/Conversaciones", "PRJ_VAULT"):
        for n in _notas(base / d):
            import os
            os.utime(n, (FECHA_VIEJA, FECHA_VIEJA))
    con = _export(tmp_path, [_entrada("file_gen1", "Polluelo de gorrion en grafito.png"),
                             _entrada("file_gen2", "Otro.png", creada="2026-10-17T22:00:00+00:00")],
                  {"file_gen1.dat": PNG, "file_gen2.dat": JPG}, nombre="con_biblioteca.zip")
    return base, con, tmp_path


def _bloques(nota: Path):
    return nota.read_text(encoding="utf-8").count("### Tool")


def test_la_simulacion_cuenta_y_no_escribe_nada(vault_viejo):
    base, export, tmp = vault_viejo
    antes = _foto(base)
    r = _recuperar(base, export, tmp, biblioteca=True)
    assert _foto(base) == antes and not (tmp / "logs").exists()
    b = r["biblioteca"]
    assert (b["generadas"], b["copiadas"], b["con_hilo"], b["bloques"], b["notas_a_cambiar"]) == (2, 2, 2, 6, 3)
    assert (b["sin_nota"], b["sin_fichero"], b["ya_enlazadas"], b["notas_cambiadas"]) == (0, 0, 0, 0)


def test_aplicar_cuelga_las_imagenes_en_las_tres_copias_de_la_nota(vault_viejo):
    base, export, tmp = vault_viejo
    r = _recuperar(base, export, tmp, aplicar=True, biblioteca=True)
    assert r["biblioteca"]["notas_cambiadas"] == 3 and r["biblioteca"]["bloques"] == 6
    for d in ("RAW_VAULT/Conversaciones", "MERGED_VAULT/Conversaciones", "PRJ_VAULT"):
        for n in _notas(base / d):
            t = n.read_text(encoding="utf-8")
            assert _bloques(n) == 2 and t.index("*Polluelo de gorrion en grafito*") < t.index("*Otro*")
            assert t.rstrip().endswith(".jpg)")
    assert len(list((base / "CHATGPT" / "GENERADAS").glob("*.png"))) == 1
    assert len(list((base / "CHATGPT" / "GENERADAS").glob("*.jpg"))) == 1


def test_no_toca_las_notas_de_otros_hilos(vault_viejo):
    base, export, tmp = vault_viejo
    otra = base / "RAW_VAULT" / "Conversaciones" / "2026" / "01" / "otra.md"
    otra.parent.mkdir(parents=True, exist_ok=True)
    otra.write_text('---\ntitle: "Otra"\nconv_id: "otro-hilo"\n---\n\n### User\n\nhola\n', encoding="utf-8")
    antes = otra.read_bytes()
    _recuperar(base, export, tmp, aplicar=True, biblioteca=True)
    assert otra.read_bytes() == antes


def test_conserva_la_fecha_de_modificacion(vault_viejo):
    base, export, tmp = vault_viejo
    _recuperar(base, export, tmp, aplicar=True, biblioteca=True)
    for d in ("RAW_VAULT/Conversaciones", "MERGED_VAULT/Conversaciones", "PRJ_VAULT"):
        for n in _notas(base / d):
            assert int(n.stat().st_mtime) == FECHA_VIEJA


def test_es_idempotente(vault_viejo):
    base, export, tmp = vault_viejo
    _recuperar(base, export, tmp, aplicar=True, biblioteca=True)
    antes = _foto(base)
    r = _recuperar(base, export, tmp, aplicar=True, biblioteca=True)
    assert r["biblioteca"]["notas_cambiadas"] == 0 and r["biblioteca"]["bloques"] == 0 and r["biblioteca"]["copia"] is None
    assert _foto(base) == antes


def test_la_nota_reparada_es_identica_a_la_que_escribe_el_importador_nuevo(vault_viejo, tmp_path):
    base, export, tmp = vault_viejo
    _recuperar(base, export, tmp, aplicar=True, biblioteca=True)
    fresco = tmp / "fresco"
    _importar(export, fresco / "RAW_VAULT" / "Conversaciones", fresco)
    reparada = _notas(base / "RAW_VAULT" / "Conversaciones")[0].read_text(encoding="utf-8")
    nueva = _notas(fresco / "RAW_VAULT" / "Conversaciones")[0].read_text(encoding="utf-8")
    assert reparada == nueva


def test_el_siguiente_export_no_duplica_los_bloques(vault_viejo):
    """El punto de todo esto: tras reparar, un export nuevo con la biblioteca fusiona sin repetir."""
    base, export, tmp = vault_viejo
    _recuperar(base, export, tmp, aplicar=True, biblioteca=True)
    convs2 = [_conv([("sediment://file_subida", False)], extra_turno="Una cosa mas")]
    siguiente = _zip(tmp / "siguiente.zip", convs2, {"file_subida.dat": PNG2, "file_gen1.dat": PNG, "file_gen2.dat": JPG},
                     [_entrada("file_gen1", "Polluelo de gorrion en grafito.png"),
                      _entrada("file_gen2", "Otro.png", creada="2026-10-17T22:00:00+00:00")])
    _importar(siguiente, base / "RAW_VAULT" / "Conversaciones", base)
    _fusionar(base / "RAW_VAULT", base / "MERGED_NUEVO")
    (nota,) = _notas(base / "MERGED_NUEVO" / "Conversaciones")
    t = nota.read_text(encoding="utf-8")
    assert t.count("### Tool") == 2, f"{t.count('### Tool')} bloques tool: debian seguir siendo 2"
    assert t.count("*Otro*") == 1 and t.count("*Polluelo de gorrion en grafito*") == 1
    assert t.count("Una cosa mas") == 1


def test_una_imagen_cuyo_hilo_no_esta_en_el_vault_se_copia_igual_y_se_cuenta(tmp_path):
    base = tmp_path / "vault"
    (base / "MERGED_VAULT" / "Conversaciones").mkdir(parents=True)
    z = _export(tmp_path, [_entrada("file_gen1", "Huerfana.png", hilo="hilo-que-no-tengo")], {"file_gen1.dat": PNG})
    r = _recuperar(base, z, tmp_path, aplicar=True, biblioteca=True)
    b = r["biblioteca"]
    assert (b["copiadas"], b["con_hilo"], b["sin_nota"], b["bloques"]) == (1, 0, 1, 0)
    assert len(list((base / "CHATGPT" / "GENERADAS").glob("*.png"))) == 1


def test_una_entrada_sin_hilo_se_copia_pero_no_se_cuelga(tmp_path):
    base = tmp_path / "vault"
    (base / "MERGED_VAULT" / "Conversaciones").mkdir(parents=True)
    e = _entrada("file_gen1", "Sin hilo.png")
    del e["origination_thread_id"]
    z = _export(tmp_path, [e], {"file_gen1.dat": PNG})
    r = _recuperar(base, z, tmp_path, aplicar=True, biblioteca=True)
    assert r["biblioteca"]["copiadas"] == 1 and r["biblioteca"]["con_hilo"] == 0


def test_deshacer_devuelve_las_notas_y_las_imagenes_se_quedan(vault_viejo):
    base, export, tmp = vault_viejo
    antes = {n: n.read_bytes() for d in ("RAW_VAULT/Conversaciones", "MERGED_VAULT/Conversaciones", "PRJ_VAULT")
             for n in _notas(base / d)}
    r = _recuperar(base, export, tmp, aplicar=True, biblioteca=True)
    assert rec.deshacer(Path(r["biblioteca"]["copia"]), log=lambda *_: None) == 3
    for n, b in antes.items():
        assert n.read_bytes() == b and int(n.stat().st_mtime) == FECHA_VIEJA
    assert list((base / "CHATGPT" / "GENERADAS").glob("*.png"))


def test_avisos_y_biblioteca_en_la_misma_pasada_se_deshacen_en_orden(tmp_path):
    """La copia de la biblioteca se hace DESPUES de arreglar los avisos: se deshace primero."""
    sin = _zip(tmp_path / "sin.zip", [_conv([("sediment://file_aaa", False)])], {})
    base = tmp_path / "vault"
    _importar(sin, base / "RAW_VAULT" / "Conversaciones", base)
    original = _notas(base / "RAW_VAULT" / "Conversaciones")[0].read_bytes()
    z = _zip(tmp_path / "c.zip", [_conv([("sediment://file_aaa", False)])], {"file_aaa.dat": PNG, "file_gen1.dat": JPG},
             [_entrada("file_gen1", "Generada.png")])
    r = _recuperar(base, z, tmp_path, aplicar=True, biblioteca=True)
    nota = _notas(base / "RAW_VAULT" / "Conversaciones")[0]
    t = nota.read_text(encoding="utf-8")
    assert "imagen no disponible" not in t and _bloques(nota) == 1
    assert r["copia"] and r["biblioteca"]["copia"] and r["copia"] != r["biblioteca"]["copia"]
    rec.deshacer(Path(r["biblioteca"]["copia"]), log=lambda *_: None)
    assert "imagen no disponible" not in nota.read_text(encoding="utf-8") and _bloques(nota) == 0
    rec.deshacer(Path(r["copia"]), log=lambda *_: None)
    assert nota.read_bytes() == original


def test_cli_cuenta_la_biblioteca_en_la_simulacion_y_en_aplicar(vault_viejo):
    import subprocess, sys
    base, export, tmp = vault_viejo
    raiz = Path(rec.__file__).parent
    r = subprocess.run([sys.executable, str(raiz / "recuperar_imagenes.py"), "--export", str(export),
                        "--base-vault", str(base), "--biblioteca"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=raiz)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "biblioteca: 2 generadas; 2 por copiar a GENERADAS; 6 por anadir a sus conversaciones (3 notas)" in r.stdout
    r = subprocess.run([sys.executable, str(raiz / "recuperar_imagenes.py"), "--export", str(export),
                        "--base-vault", str(base), "--biblioteca", "--aplicar"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=raiz)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "6 anadidas a sus conversaciones (3 notas)" in r.stdout and "--deshacer" in r.stdout
    for linea in r.stdout.splitlines():                  # la copia cae en logs/ del repo: se limpia
        if "copia (biblioteca):" in linea:
            shutil.rmtree(linea.split(":", 1)[1].strip(), ignore_errors=True)
