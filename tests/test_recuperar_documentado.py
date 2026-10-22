# -*- coding: utf-8 -*-
"""Cada regla que RECUPERAR_IMAGENES.md afirma, fijada por un test.

Como test_cartografia_documentada.py: el documento cuenta que hace recuperar_imagenes.py y sus
trampas (un export no lo trae todo, la imagen de la biblioteca va al final, el orden al deshacer...).
Una documentacion que nada vigila deja de ser cierta en silencio cuando alguien toca el codigo. Estos
tests dicen como se comporta HOY, que es lo que el documento promete. Si uno falla, o se corrige el
codigo o se corrige el documento.

Los vaults se construyen con el pipeline real (importar, fusionar, proyectos), con los mismos
ayudantes que test_recuperar_imagenes.py y test_biblioteca_generadas.py.
"""
import json
import os
from pathlib import Path

import pytest

import recuperar_imagenes as rec
from test_biblioteca_generadas import _entrada, _export, _hora
from test_recuperar_imagenes import (FECHA_VIEJA, JPG, PNG, PNG2, _conv, _foto, _fusionar, _importar, _notas,
                                     _por_proyectos, _recuperar, _zip)

DOC = Path(__file__).resolve().parent.parent / "RECUPERAR_IMAGENES.md"
CARPETAS = ("RAW_VAULT/Conversaciones", "MERGED_VAULT/Conversaciones", "PRJ_VAULT")
CONVS = [_conv([("sediment://file_aaa", False), ("file-service://file-bbb", True)])]


def _vault(tmp_path, convs, ficheros=None, biblioteca=None, nombre="vault"):
    """Un vault hecho por el pipeline real con un export; con `ficheros` vacio, todo queda como aviso."""
    base = tmp_path / nombre
    z = _zip(tmp_path / f"{nombre}_import.zip", convs, ficheros or {}, biblioteca)
    _importar(z, base / "RAW_VAULT" / "Conversaciones", base)
    _fusionar(base / "RAW_VAULT", base / "MERGED_VAULT")
    _por_proyectos(base / "MERGED_VAULT", base / "PRJ_VAULT")
    for d in CARPETAS:
        for n in _notas(base / d):
            os.utime(n, (FECHA_VIEJA, FECHA_VIEJA))
    return base


def _todas(base):
    return [n for d in CARPETAS for n in _notas(base / d)]


def _texto(base):
    return "\n".join(n.read_text(encoding="utf-8") for n in _todas(base))


@pytest.fixture
def con_avisos(tmp_path):
    return _vault(tmp_path, CONVS)


def test_el_documento_existe_y_dice_que_lo_vigila_este_test():
    assert "tests/test_recuperar_documentado.py" in DOC.read_text(encoding="utf-8")


# ---- los avisos -----------------------------------------------------------------------------------

def test_sin_aplicar_no_escribe_nada_ni_copia_de_seguridad(con_avisos, tmp_path):
    antes = _foto(con_avisos)
    r = _recuperar(con_avisos, _zip(tmp_path / "e.zip", CONVS, {"file_aaa.dat": PNG, "file-bbb.dat": JPG}), tmp_path)
    assert r["recuperables"] == 2 and r["notas_a_cambiar"] == 3
    assert _foto(con_avisos) == antes and not (tmp_path / "logs").exists()


def test_cambia_el_aviso_por_el_enlace_en_raw_merged_y_prj(con_avisos, tmp_path):
    assert all("imagen no disponible en el export" in n.read_text(encoding="utf-8") for n in _todas(con_avisos))
    _recuperar(con_avisos, _zip(tmp_path / "e.zip", CONVS, {"file_aaa.dat": PNG, "file-bbb.dat": JPG}), tmp_path,
               aplicar=True)
    for n in _todas(con_avisos):
        t = n.read_text(encoding="utf-8")
        assert "imagen no disponible" not in t and "![](CHATGPT/ADJUNTOS/" in t and "![](CHATGPT/GENERADAS/" in t


def test_un_export_que_no_lo_trae_todo_deja_el_resto_y_el_orden_da_igual(con_avisos, tmp_path):
    solo_b = _zip(tmp_path / "b.zip", CONVS, {"file-bbb.dat": JPG})
    solo_a = _zip(tmp_path / "a.zip", CONVS, {"file_aaa.dat": PNG})
    r = _recuperar(con_avisos, solo_b, tmp_path, aplicar=True)
    assert (r["recuperables"], r["sin_recuperar"]) == (1, 1)
    assert _texto(con_avisos).count("imagen no disponible") == 3                    # el de file_aaa, en las 3 copias
    _recuperar(con_avisos, solo_a, tmp_path / "otra", aplicar=True)
    assert "imagen no disponible" not in _texto(con_avisos)


def test_repetir_no_hace_dano(con_avisos, tmp_path):
    z = _zip(tmp_path / "e.zip", CONVS, {"file_aaa.dat": PNG, "file-bbb.dat": JPG})
    _recuperar(con_avisos, z, tmp_path, aplicar=True)
    antes = _foto(con_avisos)
    r = _recuperar(con_avisos, z, tmp_path / "otra", aplicar=True)
    assert r["marcas"] == 0 and r["notas_cambiadas"] == 0 and r["copia"] is None
    assert _foto(con_avisos) == antes


def test_el_banco_de_un_aviso_de_otro_export_lo_decide_la_biblioteca(con_avisos, tmp_path):
    """El export no trae ESTA conversacion: file_aaa consta como generada en su biblioteca; file-bbb no esta."""
    otra = [_conv([], titulo="Otra", cid="otra-conversacion")]
    z = _zip(tmp_path / "e.zip", otra, {"file_aaa.dat": PNG, "file-bbb.dat": JPG},
             [_entrada("file_aaa", "Generada.png", hilo="conv-rec-0001")])
    _recuperar(con_avisos, z, tmp_path, aplicar=True)
    t = _todas(con_avisos)[0].read_text(encoding="utf-8")
    assert t.count("![](CHATGPT/GENERADAS/") == 1 and t.count("![](CHATGPT/ADJUNTOS/") == 1
    assert list((con_avisos / "CHATGPT" / "GENERADAS").glob("*.png"))
    assert list((con_avisos / "CHATGPT" / "ADJUNTOS").glob("*.jpg"))


def test_la_misma_imagen_en_varias_notas_se_copia_una_vez(con_avisos, tmp_path):
    _recuperar(con_avisos, _zip(tmp_path / "e.zip", CONVS, {"file_aaa.dat": PNG, "file-bbb.dat": JPG}), tmp_path,
               aplicar=True)
    ficheros = [p for p in (con_avisos / "CHATGPT").rglob("*") if p.is_file() and not p.name.startswith("_")]
    assert len(ficheros) == 2                                          # dos imagenes, aunque haya tres notas
    enlaces = {n: sorted(l for l in n.read_text(encoding="utf-8").splitlines() if l.startswith("![](")) for n in _todas(con_avisos)}
    assert len({tuple(v) for v in enlaces.values()}) == 1             # las tres notas enlazan los mismos ficheros


def test_conserva_la_fecha_y_el_numero_de_turnos(con_avisos, tmp_path):
    turnos = {n: n.read_text(encoding="utf-8").count("\n### ") for n in _todas(con_avisos)}
    _recuperar(con_avisos, _zip(tmp_path / "e.zip", CONVS, {"file_aaa.dat": PNG, "file-bbb.dat": JPG}), tmp_path,
               aplicar=True)
    for n in _todas(con_avisos):
        assert int(n.stat().st_mtime) == FECHA_VIEJA
        assert n.read_text(encoding="utf-8").count("\n### ") == turnos[n]


def test_los_enlaces_simbolicos_se_saltan(con_avisos, tmp_path):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    ajena = fuera / "ajena.md"
    ajena.write_text("*[imagen no disponible en el export: sediment://file_aaa]*\n", encoding="utf-8")
    enlace = con_avisos / "RAW_VAULT" / "Conversaciones" / "enlace.md"
    try:
        os.symlink(ajena, enlace)
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no deja crear enlaces simbolicos sin permisos")
    _recuperar(con_avisos, _zip(tmp_path / "e.zip", CONVS, {"file_aaa.dat": PNG, "file-bbb.dat": JPG}), tmp_path,
               aplicar=True)
    assert "imagen no disponible" in ajena.read_text(encoding="utf-8")


# ---- la biblioteca ------------------------------------------------------------------------------------

@pytest.fixture
def sin_biblioteca(tmp_path):
    """Un vault de un export de los de antes (sin biblioteca) y el export nuevo, con ella."""
    base = _vault(tmp_path, [_conv([("sediment://file_subida", False)])], {"file_subida.dat": PNG2})
    return base


def test_la_biblioteca_va_al_final_de_cada_nota_con_su_hora_local(sin_biblioteca, tmp_path):
    z = _export(tmp_path, [_entrada("file_gen1", "Polluelo.png")], {"file_gen1.dat": PNG})
    _recuperar(sin_biblioteca, z, tmp_path, aplicar=True, biblioteca=True)
    for n in _todas(sin_biblioteca):
        t = n.read_text(encoding="utf-8").rstrip()
        cola = t[t.rindex("### Tool"):]
        assert cola.startswith(f"### Tool\n\n*Polluelo* · {_hora()}\n\n![](CHATGPT/GENERADAS/") and cola.endswith(".png)")


@pytest.mark.parametrize("nombre,titulo", [("Con *asteriscos*.png", "*Con asteriscos*"), ("", "*Imagen generada*")])
def test_el_titulo_va_sin_extension_ni_asteriscos_y_si_no_hay_imagen_generada(sin_biblioteca, tmp_path, nombre, titulo):
    z = _export(tmp_path, [_entrada("file_gen1", nombre)], {"file_gen1.dat": PNG})
    _recuperar(sin_biblioteca, z, tmp_path, aplicar=True, biblioteca=True)
    assert f"### Tool\n\n{titulo} · " in _todas(sin_biblioteca)[0].read_text(encoding="utf-8")


def test_repetir_la_biblioteca_no_anade_otra_vez(sin_biblioteca, tmp_path):
    z = _export(tmp_path, [_entrada("file_gen1", "Polluelo.png")], {"file_gen1.dat": PNG})
    _recuperar(sin_biblioteca, z, tmp_path, aplicar=True, biblioteca=True)
    antes = _foto(sin_biblioteca)
    r = _recuperar(sin_biblioteca, z, tmp_path / "otra", aplicar=True, biblioteca=True)
    assert r["biblioteca"]["bloques"] == 0 and _foto(sin_biblioteca) == antes


def test_una_generada_sin_su_conversacion_en_el_vault_se_copia_y_no_se_cuelga(sin_biblioteca, tmp_path):
    antes = {n: n.read_bytes() for n in _todas(sin_biblioteca)}
    z = _export(tmp_path, [_entrada("file_gen1", "Huerfana.png", hilo="hilo-que-no-tengo")], {"file_gen1.dat": PNG})
    r = _recuperar(sin_biblioteca, z, tmp_path, aplicar=True, biblioteca=True)
    assert (r["biblioteca"]["copiadas"], r["biblioteca"]["sin_nota"]) == (1, 1)
    assert {n: n.read_bytes() for n in _todas(sin_biblioteca)} == antes
    assert list((sin_biblioteca / "CHATGPT" / "GENERADAS").glob("*.png"))


def test_las_generadas_sin_fichero_en_el_zip_se_saltan(sin_biblioteca, tmp_path):
    z = _export(tmp_path, [_entrada("file_gen1", "Sin fichero.png", estado="created")], {})
    r = _recuperar(sin_biblioteca, z, tmp_path, aplicar=True, biblioteca=True)
    assert (r["biblioteca"]["sin_fichero"], r["biblioteca"]["copiadas"], r["biblioteca"]["bloques"]) == (1, 0, 0)


def test_sin_la_opcion_biblioteca_no_se_copia_ninguna_generada_de_la_biblioteca(sin_biblioteca, tmp_path):
    z = _export(tmp_path, [_entrada("file_gen1", "Polluelo.png")], {"file_gen1.dat": PNG})
    r = _recuperar(sin_biblioteca, z, tmp_path, aplicar=True)
    gen = sin_biblioteca / "CHATGPT" / "GENERADAS"
    assert r["biblioteca"] is None and not [p for p in gen.rglob("*") if p.is_file() and not p.name.startswith("_")]


# ---- deshacer --------------------------------------------------------------------------------------------

def _avisos_y_biblioteca(tmp_path):
    base = _vault(tmp_path, [_conv([("sediment://file_aaa", False)])])
    original = {n: n.read_bytes() for n in _todas(base)}
    z = _zip(tmp_path / "c.zip", [_conv([("sediment://file_aaa", False)])], {"file_aaa.dat": PNG, "file_gen1.dat": JPG},
             [_entrada("file_gen1", "Generada.png")])
    r = _recuperar(base, z, tmp_path, aplicar=True, biblioteca=True)
    return base, original, r


def test_deshacer_las_dos_primero_la_biblioteca_deja_las_notas_como_estaban(tmp_path):
    base, original, r = _avisos_y_biblioteca(tmp_path)
    rec.deshacer(Path(r["biblioteca"]["copia"]), log=lambda *_: None)
    rec.deshacer(Path(r["copia"]), log=lambda *_: None)
    assert {n: n.read_bytes() for n in _todas(base)} == original


def test_deshacer_al_reves_deja_las_notas_con_los_enlaces(tmp_path):
    base, original, r = _avisos_y_biblioteca(tmp_path)
    rec.deshacer(Path(r["copia"]), log=lambda *_: None)
    rec.deshacer(Path(r["biblioteca"]["copia"]), log=lambda *_: None)
    t = _todas(base)[0].read_text(encoding="utf-8")
    assert "imagen no disponible" not in t and "![](CHATGPT/ADJUNTOS/" in t


def test_deshacer_no_borra_las_imagenes_copiadas(tmp_path):
    base, original, r = _avisos_y_biblioteca(tmp_path)
    imagenes = sorted(p.name for p in (base / "CHATGPT").rglob("*") if p.is_file() and not p.name.startswith("_"))
    rec.deshacer(Path(r["biblioteca"]["copia"]), log=lambda *_: None)
    rec.deshacer(Path(r["copia"]), log=lambda *_: None)
    assert len(imagenes) == 2
    assert sorted(p.name for p in (base / "CHATGPT").rglob("*") if p.is_file() and not p.name.startswith("_")) == imagenes


def test_las_copias_de_seguridad_se_llaman_como_dice_el_documento_y_llevan_su_diario(tmp_path):
    base, original, r = _avisos_y_biblioteca(tmp_path)
    copia, copia_b = Path(r["copia"]), Path(r["biblioteca"]["copia"])
    assert copia.parent == tmp_path / "logs" and copia.name.startswith("recuperar_imagenes_")
    assert copia_b.name.endswith("_biblioteca")
    diario = json.loads((copia / "diario.json").read_text(encoding="utf-8"))
    assert {"export", "base", "notas"} <= set(diario) and len(diario["notas"]) == 3


# ---- con que se genero (--metadatos) -----------------------------------------------------------------------

def test_metadatos_completa_lo_que_falta_y_no_toca_lo_que_ya_esta(tmp_path):
    """Un banco como lo dejaba el importador antes: una generada sin generador; y otra que el export
    tambien describe pero que ya lo tiene apuntado (aunque el export diga otra cosa, no se toca)."""
    import hashlib
    conv = _conv([("sediment://file_aaa", True), ("file-service://file-bbb", True)])
    base = tmp_path / "vault"
    gen = base / "CHATGPT" / "GENERADAS"
    gen.mkdir(parents=True)
    falta, ya = f"{hashlib.sha1(JPG).hexdigest()[:16]}.jpg", f"{hashlib.sha1(PNG).hexdigest()[:16]}.png"
    (gen / falta).write_bytes(JPG)
    (gen / ya).write_bytes(PNG)
    (gen / "_image_manifest.json").write_text(json.dumps({falta: {"origen": "generada"},
                                                          ya: {"origen": "generada", "generador": "x"}}),
                                              encoding="utf-8")
    z = _zip(tmp_path / "e.zip", [conv], {"file_aaa.dat": PNG, "file-bbb.dat": JPG})
    r = rec.completar_metadatos(z, base, aplicar=True, carpeta_logs=tmp_path / "logs", log=lambda *_: None)
    man = json.loads((gen / "_image_manifest.json").read_text(encoding="utf-8"))
    assert man[falta]["generador"] == "chatgpt-dalle"                                  # traia prompt de DALL-E
    assert man[ya] == {"origen": "generada", "generador": "x"}
    assert Path(r["copia"]).name.endswith("_metadatos")
