# -*- coding: utf-8 -*-
"""Cada regla que GALLERY.md afirma, fijada por un test.

Como test_cartografia_documentada.py: la documentacion de la galeria cuenta de donde sale lo que
ensena de cada imagen y sus trampas (solo mira MERGED, el prompt no se hereda, retocar una miniatura
propia no la rehace...). Una documentacion que nada vigila deja de ser cierta en silencio cuando
alguien toca el codigo. Estos tests no dicen como DEBERIA comportarse: dicen como se comporta HOY,
que es lo que el documento promete. Si uno falla, o se corrige el codigo o se corrige el documento.

Lo que hace la pagina en el navegador (buscar, el enlace a Obsidian) se fija sobre el texto de la
plantilla: es JavaScript y aqui no hay navegador, pero si alguien cambia esa linea, el documento
tiene que cambiar con ella.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest
from PIL import Image

import galeria as gal

DOC = Path(__file__).resolve().parent.parent / "GALLERY.md"


def _png(ruta: Path, color=(200, 30, 30)):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (600, 400), color).save(ruta)
    return ruta


def _nota(base: Path, vault: str, rel: str, fm: dict, cuerpo: str):
    p = base / vault / "Conversations" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\n" + "".join(f'{k}: "{v}"\n' for k, v in fm.items()) + "---\n\n" + cuerpo, encoding="utf-8")
    return p


def _manifiesto(carpeta: Path, datos: dict):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "_image_manifest.json").write_text(json.dumps(datos), encoding="utf-8")


@pytest.fixture
def base(tmp_path):
    b = tmp_path / "Mi base"
    _png(b / "CHATGPT" / "GENERATED" / "aaaa.png")
    return b


def _items(base, copilot=None):
    return {i["ruta"]: i for i in gal.recoger(base, copilot)}


def _datos(pagina: Path) -> dict:
    m = re.search(r"const DATOS = (.*?);\nconst MESES", pagina.read_text(encoding="utf-8"), re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def _plantilla() -> str:
    return gal.PLANTILLA.read_text(encoding="utf-8")


def test_el_documento_existe_y_dice_que_lo_vigila_este_test():
    assert "tests/test_galeria_documentada.py" in DOC.read_text(encoding="utf-8")


# ---- de donde sale cada cosa ------------------------------------------------------------------

def test_solo_se_mira_merged_lo_enlazado_desde_raw_sale_sin_conversacion(base):
    _nota(base, "RAW_VAULT", "n.md", {"title": "Solo en RAW"}, "### Tool\n\n![](CHATGPT/GENERATED/aaaa.png)\n")
    it = _items(base)["CHATGPT/GENERATED/aaaa.png"]
    assert it["conv"] is None
    assert [g["titulo"] for g in gal.agrupar([it])] == ["ChatGPT · no conversation"]


def test_en_dos_conversaciones_sale_una_vez_en_la_primera_por_ruta_no_por_fecha(base):
    _nota(base, "MERGED_VAULT", "a/vieja.md", {"title": "Primera por ruta", "date": "2020-01-01"},
          "### Tool\n\n![](CHATGPT/GENERATED/aaaa.png)\n")
    _nota(base, "MERGED_VAULT", "b/nueva.md", {"title": "Mas reciente", "date": "2026-12-01"},
          "### Tool\n\n![](CHATGPT/GENERATED/aaaa.png)\n")
    items = gal.recoger(base)
    assert len(items) == 1 and items[0]["conv"]["titulo"] == "Primera por ruta"


def test_lo_que_pediste_es_tu_ultimo_mensaje_antes_de_la_imagen_sin_enlaces_y_cortado(base):
    largo = "palabra " * 80
    _nota(base, "MERGED_VAULT", "n.md", {"title": "T"},
          "### User\n\nla primera\n\n### User\n\n![](otra.png) " + largo + "\n\n### Tool\n\n![](CHATGPT/GENERATED/aaaa.png)\n")
    pet = _items(base)["CHATGPT/GENERATED/aaaa.png"]["pet"]
    assert pet.startswith("palabra") and "otra.png" not in pet
    assert len(pet) == 301 and pet.endswith("…")                       # 300 caracteres y la elipsis


def test_el_prompt_de_chatgpt_solo_existe_si_la_nota_lo_guarda(base):
    _png(base / "CHATGPT" / "GENERATED" / "bbbb.png")
    _nota(base, "MERGED_VAULT", "antigua.md", {"title": "Export antiguo"},
          '### User\n\nun faro\n\n### Assistant\n\n{"prompt": "a lighthouse"}\n\n### Tool\n\n![](CHATGPT/GENERATED/aaaa.png)\n')
    _nota(base, "MERGED_VAULT", "nueva.md", {"title": "Export nuevo"},
          "### User\n\nun faro\n\n### Tool\n\n*Faro* · 2026-10-17 23:12\n\n![](CHATGPT/GENERATED/bbbb.png)\n")
    items = _items(base)
    assert items["CHATGPT/GENERATED/aaaa.png"]["prompt"] == "a lighthouse"
    assert items["CHATGPT/GENERATED/bbbb.png"]["prompt"] == ""
    assert (items["CHATGPT/GENERATED/bbbb.png"]["titulo"], items["CHATGPT/GENERATED/bbbb.png"]["hora"]) == \
        ("Faro", "2026-10-17 23:12")


def test_el_prompt_no_se_hereda_tras_otra_peticion(base):
    _png(base / "CHATGPT" / "GENERATED" / "bbbb.png")
    _nota(base, "MERGED_VAULT", "n.md", {"title": "T"},
          '### User\n\nuno\n\n### Assistant\n\n{"prompt": "uno"}\n\n### Tool\n\n![](CHATGPT/GENERATED/aaaa.png)\n\n'
          "### User\n\ndos\n\n### Tool\n\n![](CHATGPT/GENERATED/bbbb.png)\n")
    assert _items(base)["CHATGPT/GENERATED/bbbb.png"]["prompt"] == ""


def test_dalle_y_grok_toman_el_prompt_de_su_banco_y_el_generador_de_grok_es_el_banco(base):
    _manifiesto(base / "CHATGPT" / "GENERATED", {"aaaa.png": {"generador": "chatgpt-dalle", "prompt": "un gato"}})
    _png(base / "GROK" / "IMAGINE" / "g.jpg")
    _manifiesto(base / "GROK" / "IMAGINE", {"g.jpg": {"prompt": "un perro"}})
    items = _items(base)
    assert items["CHATGPT/GENERATED/aaaa.png"]["prompt"] == "un gato"
    assert (items["GROK/IMAGINE/g.jpg"]["prompt"], items["GROK/IMAGINE/g.jpg"]["gen"]) == ("un perro", "grok-imagine")


def test_generada_o_subida_lo_dice_el_banco(base):
    _png(base / "CHATGPT" / "ATTACHMENTS" / "s.png")
    items = _items(base)
    assert items["CHATGPT/GENERATED/aaaa.png"]["origen"] == "generada"
    assert items["CHATGPT/ATTACHMENTS/s.png"]["origen"] == "subida" and items["CHATGPT/ATTACHMENTS/s.png"]["gen"] is None


def test_el_modelo_y_la_edicion_salen_del_manifiesto(base):
    _manifiesto(base / "CHATGPT" / "GENERATED", {"aaaa.png": {"generador": "chatgpt-imagen", "modelo": "gpt-5",
                                                              "edicion": True}})
    it = _items(base)["CHATGPT/GENERATED/aaaa.png"]
    assert (it["gen"], it["modelo"], it["ed"]) == ("chatgpt-imagen", "gpt-5", True)
    assert '"edit of another image"' in _plantilla()


def test_sin_generador_en_el_manifiesto_no_se_inventa(base):
    assert _items(base)["CHATGPT/GENERATED/aaaa.png"]["gen"] is None


# ---- como se agrupa -----------------------------------------------------------------------------

def test_copilot_se_agrupa_por_prompt_y_dia(tmp_path, base):
    cop = tmp_path / "copilot"
    for nombre, dia, prompt in (("a", "2025-05-04", "un nautilus"), ("b", "2025-05-04", "un nautilus"),
                                ("c", "2025-05-05", "un nautilus"), ("d", "2025-05-04", "otro prompt")):
        _png(cop / "Files" / f"{nombre}.jpg")
        nota = cop / "Images" / f"{nombre}.md"
        nota.parent.mkdir(parents=True, exist_ok=True)
        nota.write_text(f'---\nprompt: "{prompt}"\ncreated_at: "{dia}T10:00:00"\n---\n\n![[{nombre}.jpg]]\n',
                        encoding="utf-8")
    grupos = gal.agrupar([i for i in gal.recoger(base, cop) if i["prov"] == "copilot"])
    assert sorted(len(g["imgs"]) for g in grupos) == [1, 1, 2]           # mismo prompt y dia; otro dia; otro prompt


def test_lo_que_no_enlaza_ninguna_nota_va_por_dia_y_proveedor(base):
    _manifiesto(base / "GROK" / "IMAGINE", {"x.jpg": {"create_time": "2026-08-23T10:00:00Z"},
                                           "y.jpg": {"create_time": "2026-08-23T18:00:00Z"},
                                           "z.jpg": {"create_time": "2026-08-24T10:00:00Z"}})
    for n in ("x", "y", "z"):
        _png(base / "GROK" / "IMAGINE" / f"{n}.jpg")
    grupos = [g for g in gal.agrupar(gal.recoger(base)) if g["titulo"] == "Grok · no conversation"]
    assert sorted(len(g["imgs"]) for g in grupos) == [1, 2]
    assert [g["fecha"] for g in grupos] == ["2026-08-24", "2026-08-23"]           # de mas reciente a mas antigua


def test_sin_fecha_en_el_manifiesto_se_usa_la_del_fichero(base):
    f = base / "CHATGPT" / "GENERATED" / "aaaa.png"
    os.utime(f, (1700000000, 1700000000))                                          # 2023-11-14
    assert _items(base)["CHATGPT/GENERATED/aaaa.png"]["fecha"] == "2023-11-14"


def test_formatos_que_entran_y_los_que_no(base):
    carpeta = base / "CHATGPT" / "GENERATED"
    for nombre in ("b.jpg", "c.jpeg", "d.webp", "e.gif"):
        _png(carpeta / nombre)
    for nombre in ("v.mp4", "w.webm", "x.mov", "foto.heic", "dibujo.svg"):
        (carpeta / nombre).write_bytes(b"x")
    _png(carpeta / "_oculta.png")
    nombres = {Path(r).name for r in _items(base)}
    assert nombres == {"aaaa.png", "b.jpg", "c.jpeg", "d.webp", "e.gif", "v.mp4", "w.webm", "x.mov"}


# ---- la pagina: buscar y Obsidian -----------------------------------------------------------------

def test_buscar_es_por_trozos_sin_acentos_ni_mayusculas_y_exige_todas_las_palabras():
    p = _plantilla()
    assert '.normalize("NFD")' in p and ".toLowerCase()" in p
    assert "terminos.every((t) => im.busca.includes(t))" in p


def test_donde_busca():
    linea = re.search(r"im\.busca = norm\(\[(.*?)\]\.join", _plantilla(), re.S).group(1)
    for campo in ("g.titulo", "g.proyecto", "im.titulo", "im.prompt", "im.pet", '"proveedor"', '"generador"', "im.modelo"):
        assert campo in linea, campo
    assert not re.search(r"im\.[ot]\b", linea)                            # el nombre del fichero no


def test_abrir_en_obsidian_usa_el_nombre_de_la_carpeta_base_como_vault(base, tmp_path):
    _nota(base, "MERGED_VAULT", "n.md", {"title": "T"}, "### Tool\n\n![](CHATGPT/GENERATED/aaaa.png)\n")
    r = gal.generar(base, tmp_path / "g", log=lambda *_: None)
    assert _datos(Path(r["pagina"]))["vault"] == "Mi base"
    assert "obsidian://open?vault=${encodeURIComponent(DATOS.vault)}" in _plantilla()


def test_copilot_fuera_de_la_base_entra_sin_enlace_a_obsidian(base, tmp_path):
    cop = tmp_path / "fuera"
    _png(cop / "Files" / "a.jpg")
    (cop / "Images").mkdir(parents=True)
    (cop / "Images" / "a.md").write_text('---\nprompt: "p"\n---\n\n![[a.jpg]]\n', encoding="utf-8")
    (it,) = [i for i in gal.recoger(base, cop) if i["prov"] == "copilot"]
    assert it["nota"] is None


# ---- miniaturas -----------------------------------------------------------------------------------

def test_las_miniaturas_propias_se_usan_pero_retocarlas_no_rehace_la_de_la_galeria(base, tmp_path):
    propia = _png(base / "CHATGPT" / "GENERATED_Thmbnails" / "thmbnail_aaaa.png", (0, 0, 250))
    salida = tmp_path / "g"
    assert gal.generar_miniaturas(gal.recoger(base), base, salida, log=lambda *_: None)["hechas"] == 1
    _png(propia, (0, 250, 0))                                                   # retocada despues
    futuro = (salida / "thumbnails" / "CHATGPT" / "GENERATED" / "aaaa.jpg").stat().st_mtime + 100
    os.utime(propia, (futuro, futuro))
    r = gal.generar_miniaturas(gal.recoger(base), base, salida, log=lambda *_: None)
    assert (r["hechas"], r["reutilizadas"]) == (0, 1)
    shutil.rmtree(salida / "thumbnails")                                        # lo que dice el documento
    assert gal.generar_miniaturas(gal.recoger(base), base, salida, log=lambda *_: None)["hechas"] == 1


def test_los_videos_no_tienen_miniatura_y_la_tira_carga_el_primer_fotograma(base, tmp_path):
    (base / "GROK" / "GENERATED_VIDEO").mkdir(parents=True)
    (base / "GROK" / "GENERATED_VIDEO" / "v.mp4").write_bytes(b"x")
    r = gal.generar(base, tmp_path / "g", log=lambda *_: None)
    (v,) = [im for g in _datos(Path(r["pagina"]))["grupos"] for im in g["imgs"] if im["tipo"] == "video"]
    assert "t" not in v and 'preload="metadata"' in _plantilla()


def test_un_fichero_roto_no_para_nada_y_sale_sin_miniatura(base, tmp_path):
    (base / "CHATGPT" / "GENERATED" / "roto.png").write_bytes(b"no es una imagen")
    avisos = []
    r = gal.generar(base, tmp_path / "g", log=avisos.append)
    assert r["miniaturas"]["fallidas"] == 1 and any("roto.png" in a for a in avisos)
    (roto,) = [im for g in _datos(Path(r["pagina"]))["grupos"] for im in g["imgs"] if im["o"].endswith("roto.png")]
    assert "t" not in roto and "no thumbnail" in _plantilla()


def test_sin_pillow_se_para_avisando(base, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    with pytest.raises(gal.ErrorGaleria, match="Pillow"):
        gal.generar(base, tmp_path / "g", log=lambda *_: None)
    r = gal.generar(base, tmp_path / "g2", miniaturas=False, log=lambda *_: None)    # la salida que se ofrece
    assert Path(r["pagina"]).is_file()


def test_mover_la_base_entera_no_rompe_los_enlaces(base, tmp_path):
    gal.generar(base, log=lambda *_: None)
    movida = tmp_path / "otro sitio" / "Mi base"
    shutil.move(str(base), str(movida))
    galeria = movida / ".gallery"
    datos = _datos(galeria / "index.html")
    enlaces = [im[k] for g in datos["grupos"] for im in g["imgs"] for k in ("t", "o") if im.get(k)]
    assert enlaces and all((galeria / unquote(e)).resolve().is_file() for e in enlaces)


# ---- que escribe y que no -------------------------------------------------------------------------

def test_escribe_solo_en_su_carpeta_lo_que_dice_la_tabla(base):
    _nota(base, "MERGED_VAULT", "n.md", {"title": "T"}, "### Tool\n\n![](CHATGPT/GENERATED/aaaa.png)\n")
    antes = {p: p.read_bytes() for p in base.rglob("*") if p.is_file()}
    gal.generar(base, log=lambda *_: None)
    despues = {p: p.read_bytes() for p in base.rglob("*") if p.is_file()}
    nuevos = {p.relative_to(base).as_posix() for p in despues if p not in antes}
    assert {p: despues[p] for p in antes} == antes, "no toca nada que ya existia"
    assert nuevos == {".gallery/index.html", ".gallery/thumbnails/.version", ".gallery/imageIA.png",
                      ".gallery/thumbnails/CHATGPT/GENERATED/aaaa.jpg"}
    with Image.open(base / ".gallery" / "thumbnails" / "CHATGPT" / "GENERATED" / "aaaa.jpg") as im:
        assert max(im.size) == 480


def test_es_regenerable_borrarla_entera_y_rehacerla_da_lo_mismo(base):
    _nota(base, "MERGED_VAULT", "n.md", {"title": "T"}, "### Tool\n\n![](CHATGPT/GENERATED/aaaa.png)\n")
    gal.generar(base, log=lambda *_: None)
    primera = _datos(base / ".gallery" / "index.html")["grupos"]
    shutil.rmtree(base / ".gallery")
    gal.generar(base, log=lambda *_: None)
    assert _datos(base / ".gallery" / "index.html")["grupos"] == primera


def test_cada_tira_se_pinta_al_desplegarla():
    assert 'd.addEventListener("toggle", () => { if (d.open && !d.dataset.pintada) pintarTira(' in _plantilla()
