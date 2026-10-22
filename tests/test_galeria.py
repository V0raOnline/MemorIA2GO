# -*- coding: utf-8 -*-
"""galeria.py: la galeria HTML de imagenes y videos, como complemento (no parte del pipeline).

Contra un vault de prueba con todo lo que hay en el real: generadas y subidas de ChatGPT enlazadas
desde sus notas (con prompt antiguo, con bloque de la biblioteca), Grok con video y con Imagine sin
nota, Copilot con su nota por imagen, una imagen rota. Lo que se vigila:
  - que cada imagen lleve lo que se sabe de ella (conversacion, proyecto, generador, modelo, prompt,
    lo que pediste) y quede en su tira;
  - que las miniaturas se hagan solo una vez, partan de las propias si existen y que un fichero roto
    no tumbe nada;
  - que la pagina lleve los temas de la app, el aviso legal, enlaces que resuelven y no se pueda
    romper con un titulo raro;
  - que no toque nada del vault fuera de su carpeta.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

import galeria as gal

RAIZ = Path(__file__).resolve().parent.parent


def _png(ruta: Path, color=(200, 30, 30), tam=(900, 600)):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", tam, color).save(ruta)
    return ruta


def _nota(base: Path, rel: str, fm: dict, cuerpo: str):
    p = base / "MERGED_VAULT" / "Conversaciones" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    cabecera = "".join(f'{k}: "{v}"\n' for k, v in fm.items())
    p.write_text(f"---\n{cabecera}---\n\n{cuerpo}", encoding="utf-8")
    return p


def _manifiesto(carpeta: Path, datos: dict):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "_image_manifest.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def vault(tmp_path):
    base = tmp_path / "02 Obsidian_vaults"
    gen, adj = base / "CHATGPT" / "GENERADAS", base / "CHATGPT" / "ADJUNTOS"
    _png(gen / "aaaa.png", (10, 200, 10))
    _png(gen / "bbbb.png", (10, 10, 200))
    _png(adj / "cccc.jpg", (200, 200, 10))
    _png(gen / "roto.png").write_bytes(b"esto no es una imagen")
    _manifiesto(gen, {
        "aaaa.png": {"origen": "generada", "generador": "chatgpt-imagen", "modelo": "gpt-5", "edicion": True},
        "bbbb.png": {"origen": "generada", "generador": "chatgpt-biblioteca", "titulo_biblioteca": "Polluelo"},
        "roto.png": {"origen": "generada"},
    })
    _manifiesto(adj, {"cccc.jpg": {"origen": "subida", "adjunto_nombre": "captura.jpg"}})
    _nota(base, "2026/10/vieja.md", {"title": "Logo para ARKINESIS", "date": "2026-03-05", "provider": "chatgpt",
                                     "Project_name": "ARKINESIS"},
          "### User\n\n![](CHATGPT/ADJUNTOS/cccc.jpg)\nhazme un logo cyan\n\n### Assistant\n\n"
          '{"prompt": "clean elegant logo, neon cyan", "size": "1024x1024"}\n\n### Tool\n\n![](CHATGPT/GENERADAS/aaaa.png)\n')
    _nota(base, "2026/10/nueva.md", {"title": "Esbozar el gorrioncito", "date": "2026-10-17", "provider": "chatgpt",
                                     "Project_name": "none"},
          "### User\n\nQuiero el gorrioncito en grafito\n\n### Assistant\n\nAqui va.\n\n### Tool\n\n"
          "*Polluelo* · 2026-10-17 23:12\n\n![](CHATGPT/GENERADAS/bbbb.png)\n")
    # Grok: imagen del chat, un video y una de Imagine que ninguna nota enlaza
    _png(base / "GROK" / "GENERADAS_IMAGEN" / "g1.jpg")
    (base / "GROK" / "GENERADAS_VIDEO").mkdir(parents=True)
    (base / "GROK" / "GENERADAS_VIDEO" / "v1.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    _png(base / "GROK" / "IMAGINE" / "im1.jpg")
    _manifiesto(base / "GROK" / "GENERADAS_VIDEO", {"v1.mp4": {"origen": "generada", "prompt": "gato bailando",
                                                               "create_time": "2026-08-23T17:14:12Z"}})
    _manifiesto(base / "GROK" / "IMAGINE", {"im1.jpg": {"origen": "imagine", "create_time": "2026-08-23T17:14:12Z"}})
    _nota(base, "2026/08/grok.md", {"title": "Charla con Grok", "date": "2026-08-20", "provider": "grok"},
          "### User\n\ndibuja un gato\n\n### Assistant\n\n![](GROK/GENERADAS_IMAGEN/g1.jpg)\n![](GROK/GENERADAS_VIDEO/v1.mp4)\n")
    # Copilot: dos variantes del mismo prompt el mismo dia, cada una con su nota
    cop = base / "COPILOT" / "GENERADAS_IMAGEN"
    for n in ("A", "B"):
        _png(cop / "Archivos" / f"2025-05-04 · nautilus · {n}.jpg")
        nota = cop / "Imágenes" / "2025-05" / f"2025-05-04 · nautilus · {n}.md"
        nota.parent.mkdir(parents=True, exist_ok=True)
        nota.write_text(f'---\nprompt: "un nautilus navegando"\ncreated_at: "2025-05-04T11:55:26+00:00"\n---\n\n'
                        f"![[2025-05-04 · nautilus · {n}.jpg]]\n", encoding="utf-8")
    return base


def _por_ruta(items):
    return {i["ruta"]: i for i in items}


# ---- lo que se sabe de cada imagen -------------------------------------------------------------
def test_recoge_todos_los_bancos_y_copilot(vault):
    items = _por_ruta(gal.recoger(vault))
    assert {i["prov"] for i in items.values()} == {"chatgpt", "grok", "copilot"}
    assert len(items) == 9                                   # 4 chatgpt (una rota) + 3 grok + 2 copilot


def test_generada_antigua_con_su_prompt_peticion_proyecto_y_modelo(vault):
    it = _por_ruta(gal.recoger(vault))["CHATGPT/GENERADAS/aaaa.png"]
    assert (it["origen"], it["gen"], it["modelo"], it["ed"]) == ("generada", "chatgpt-imagen", "gpt-5", True)
    assert it["prompt"] == "clean elegant logo, neon cyan"
    assert it["pet"] == "hazme un logo cyan"
    assert it["conv"]["titulo"] == "Logo para ARKINESIS" and it["conv"]["proyecto"] == "ARKINESIS"
    assert it["conv"]["nota"] == "MERGED_VAULT/Conversaciones/2026/10/vieja"


def test_generada_de_la_biblioteca_con_su_titulo_y_hora(vault):
    it = _por_ruta(gal.recoger(vault))["CHATGPT/GENERADAS/bbbb.png"]
    assert (it["gen"], it["titulo"], it["hora"]) == ("chatgpt-biblioteca", "Polluelo", "2026-10-17 23:12")
    assert it["pet"] == "Quiero el gorrioncito en grafito"


def test_subida_sin_generador_y_con_su_nombre(vault):
    it = _por_ruta(gal.recoger(vault))["CHATGPT/ADJUNTOS/cccc.jpg"]
    assert (it["origen"], it["gen"], it["titulo"]) == ("subida", None, "captura.jpg")


def test_grok_video_y_generador_por_banco(vault):
    items = _por_ruta(gal.recoger(vault))
    v = items["GROK/GENERADAS_VIDEO/v1.mp4"]
    assert (v["tipo"], v["gen"], v["prompt"]) == ("video", "grok-chat", "gato bailando")
    assert items["GROK/IMAGINE/im1.jpg"]["gen"] == "grok-imagine"
    assert items["GROK/IMAGINE/im1.jpg"]["conv"] is None and items["GROK/IMAGINE/im1.jpg"]["fecha"] == "2026-08-23"


def test_copilot_con_su_prompt_su_nota_y_su_fecha(vault):
    it = [i for i in gal.recoger(vault) if i["prov"] == "copilot"][0]
    assert (it["gen"], it["prompt"], it["fecha"]) == ("copilot", "un nautilus navegando", "2025-05-04")
    assert it["nota"].startswith("COPILOT/GENERADAS_IMAGEN/Imágenes/2025-05/")


def test_sin_generador_en_el_manifiesto_no_se_inventa(vault):
    it = _por_ruta(gal.recoger(vault))["CHATGPT/GENERADAS/roto.png"]
    assert it["gen"] is None


def test_una_imagen_enlazada_desde_dos_notas_toma_la_primera(vault):
    _nota(vault, "2026/11/otra.md", {"title": "Zzz despues", "date": "2026-11-01"}, "### Tool\n\n![](CHATGPT/GENERADAS/aaaa.png)\n")
    assert _por_ruta(gal.recoger(vault))["CHATGPT/GENERADAS/aaaa.png"]["conv"]["titulo"] == "Logo para ARKINESIS"


# ---- tiras ---------------------------------------------------------------------------------------
def test_agrupa_por_conversacion_por_prompt_en_copilot_y_por_dia_sin_conversacion(vault):
    grupos = {g["titulo"]: g for g in gal.agrupar(gal.recoger(vault))}
    assert len(grupos["Logo para ARKINESIS"]["imgs"]) == 2               # la subida y la generada
    assert len(grupos["Charla con Grok"]["imgs"]) == 2                   # imagen y video
    assert len(grupos["un nautilus navegando"]["imgs"]) == 2             # las dos variantes de Copilot
    assert "Grok · sin conversación" in grupos


def test_las_tiras_van_de_mas_reciente_a_mas_antigua(vault):
    fechas = [g["fecha"] for g in gal.agrupar(gal.recoger(vault))]
    assert fechas == sorted(fechas, reverse=True)


# ---- miniaturas ----------------------------------------------------------------------------------------
def test_miniaturas_una_vez_y_luego_se_reutilizan(vault, tmp_path):
    items = gal.recoger(vault)
    r = gal.generar_miniaturas(items, vault, tmp_path / "g", log=lambda *_: None)
    assert (r["hechas"], r["fallidas"]) == (7, 1)                         # 8 imagenes (el video no), 1 rota
    r2 = gal.generar_miniaturas(gal.recoger(vault), vault, tmp_path / "g", log=lambda *_: None)
    assert (r2["hechas"], r2["reutilizadas"]) == (0, 7)


def test_las_miniaturas_son_pequenas(vault, tmp_path):
    items = gal.recoger(vault)
    gal.generar_miniaturas(items, vault, tmp_path / "g", log=lambda *_: None)
    with Image.open(tmp_path / "g" / "miniaturas" / "CHATGPT" / "GENERADAS" / "aaaa.jpg") as im:
        assert max(im.size) == gal.LADO_MINIATURA


def test_parte_de_las_miniaturas_propias_si_existen(vault, tmp_path):
    _png(vault / "CHATGPT" / "GENERADAS_Thmbnails" / "thmbnail_aaaa.png", (250, 0, 250), (320, 200))
    gal.generar_miniaturas(gal.recoger(vault), vault, tmp_path / "g", log=lambda *_: None)
    with Image.open(tmp_path / "g" / "miniaturas" / "CHATGPT" / "GENERADAS" / "aaaa.jpg") as im:
        r, g, b = im.convert("RGB").getpixel((5, 5))
        assert r > 200 and g < 60 and b > 200, "deberia salir de la miniatura propia (magenta), no del original (verde)"


def test_un_original_mas_nuevo_rehace_su_miniatura(vault, tmp_path):
    gal.generar_miniaturas(gal.recoger(vault), vault, tmp_path / "g", log=lambda *_: None)
    original = vault / "CHATGPT" / "GENERADAS" / "aaaa.png"
    futuro = (tmp_path / "g" / "miniaturas" / "CHATGPT" / "GENERADAS" / "aaaa.jpg").stat().st_mtime + 100
    os.utime(original, (futuro, futuro))
    r = gal.generar_miniaturas(gal.recoger(vault), vault, tmp_path / "g", log=lambda *_: None)
    assert r["hechas"] == 1


# ---- la pagina -------------------------------------------------------------------------------------------
def _datos_de(html: str) -> dict:
    m = re.search(r"const DATOS = (.*?);\nconst MESES", html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_la_pagina_lleva_los_temas_de_la_app_y_el_aviso_legal(vault, tmp_path):
    r = gal.generar(vault, tmp_path / "g", log=lambda *_: None)
    html = Path(r["pagina"]).read_text(encoding="utf-8")
    for tema in ('data-theme="cool"', 'data-theme="light"'):
        assert tema in html, tema
    assert "--accent:" in html and "/*__TOKENS__*/" not in html
    assert "CC BY-NC-SA 4.0" in html and '<link rel="license"' in html
    assert html.index("CC BY-NC-SA") < html.index("<html")


def test_los_enlaces_de_la_pagina_resuelven_a_ficheros(vault, tmp_path):
    salida = tmp_path / "g"
    r = gal.generar(vault, salida, log=lambda *_: None)
    datos = _datos_de(Path(r["pagina"]).read_text(encoding="utf-8"))
    from urllib.parse import unquote
    vistos = 0
    for g in datos["grupos"]:
        for im in g["imgs"]:
            for clave in ("t", "o"):
                if im.get(clave):
                    assert (salida / unquote(im[clave])).resolve().is_file(), im[clave]
                    vistos += 1
    assert vistos >= 16


def test_la_pagina_lleva_lo_que_hace_falta_para_filtrar(vault, tmp_path):
    r = gal.generar(vault, tmp_path / "g", log=lambda *_: None)
    datos = _datos_de(Path(r["pagina"]).read_text(encoding="utf-8"))
    imgs = [im for g in datos["grupos"] for im in g["imgs"]]
    assert {im["prov"] for im in imgs} == {"chatgpt", "grok", "copilot"}
    assert {im["origen"] for im in imgs} == {"generada", "subida"}
    assert {im["tipo"] for im in imgs} == {"imagen", "video"}
    assert {"chatgpt-imagen", "chatgpt-biblioteca", "grok-chat", "grok-imagine", "copilot"} <= {im.get("gen") for im in imgs}
    assert any(g.get("proyecto") == "ARKINESIS" for g in datos["grupos"])
    assert datos["vault"] == "02 Obsidian_vaults" and datos["etiquetas"]["generador"]["copilot"] == "Copilot"


def test_un_titulo_con_script_no_rompe_la_pagina(vault, tmp_path):
    _nota(vault, "2026/12/raro.md", {"title": "x</script><script>alert(1)</script>", "date": "2026-12-01"},
          "### Tool\n\n![](CHATGPT/GENERADAS/roto.png)\n")
    r = gal.generar(vault, tmp_path / "g", log=lambda *_: None)
    html = Path(r["pagina"]).read_text(encoding="utf-8")
    assert html.count("</script>") == 1                                   # solo el cierre del script de la pagina
    assert any("alert(1)" in g["titulo"] for g in _datos_de(html)["grupos"])


def test_el_tema_por_defecto_es_el_pedido(vault, tmp_path):
    r = gal.generar(vault, tmp_path / "g", tema="cool", log=lambda *_: None)
    assert _datos_de(Path(r["pagina"]).read_text(encoding="utf-8"))["tema"] == "cool"


def test_sin_miniaturas_la_pagina_usa_los_originales(vault, tmp_path):
    r = gal.generar(vault, tmp_path / "g", miniaturas=False, log=lambda *_: None)
    assert not (tmp_path / "g" / "miniaturas").exists()
    imgs = [im for g in _datos_de(Path(r["pagina"]).read_text(encoding="utf-8"))["grupos"] for im in g["imgs"]]
    assert all(im["t"] == im["o"] for im in imgs if im["tipo"] == "imagen")


# ---- no toca el vault ----------------------------------------------------------------------------------------
def _foto(base: Path):
    return {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob("*") if p.is_file()}


def test_por_defecto_escribe_solo_en_su_carpeta_dentro_del_vault(vault):
    antes = _foto(vault)
    r = gal.generar(vault, log=lambda *_: None)
    despues = _foto(vault)
    assert Path(r["pagina"]) == vault / ".galeria" / "index.html"
    assert {k: v for k, v in despues.items() if not k.startswith(".galeria/")} == antes


def test_una_base_sin_imagenes_se_niega(tmp_path):
    (tmp_path / "vacio").mkdir()
    with pytest.raises(gal.ErrorGaleria, match="no he encontrado imagenes"):
        gal.generar(tmp_path / "vacio", log=lambda *_: None)


def test_cli(vault, tmp_path):
    r = subprocess.run([sys.executable, str(RAIZ / "galeria.py"), "--base-vault", str(vault), "--salida", str(tmp_path / "g")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RAIZ)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "9 imagenes y videos" in r.stdout and "miniaturas: 7 nuevas" in r.stdout and "1 fallidas" in r.stdout
    r = subprocess.run([sys.executable, str(RAIZ / "galeria.py"), "--base-vault", str(tmp_path / "no_existe")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RAIZ)
    assert r.returncode == 2 and "[error]" in r.stdout


def test_lo_transparente_queda_sobre_blanco_y_no_negro(vault, tmp_path):
    ruta = vault / "CHATGPT" / "ADJUNTOS" / "transparente.png"
    Image.new("RGBA", (400, 300), (0, 0, 0, 0)).save(ruta)
    gal.generar_miniaturas(gal.recoger(vault), vault, tmp_path / "g", log=lambda *_: None)
    with Image.open(tmp_path / "g" / "miniaturas" / "CHATGPT" / "ADJUNTOS" / "transparente.jpg") as im:
        assert min(im.convert("RGB").getpixel((10, 10))) > 240


def test_un_cambio_de_version_rehace_todas_las_miniaturas(vault, tmp_path):
    gal.generar_miniaturas(gal.recoger(vault), vault, tmp_path / "g", log=lambda *_: None)
    (tmp_path / "g" / "miniaturas" / ".version").write_text("0", encoding="utf-8")
    r = gal.generar_miniaturas(gal.recoger(vault), vault, tmp_path / "g", log=lambda *_: None)
    assert (r["hechas"], r["reutilizadas"]) == (7, 0)


def test_el_prompt_de_una_imagen_no_se_hereda_tras_otra_peticion(vault):
    _png(vault / "CHATGPT" / "GENERADAS" / "dddd.png")
    _png(vault / "CHATGPT" / "GENERADAS" / "eeee.png")
    _nota(vault, "2026/09/dos.md", {"title": "Dos peticiones", "date": "2026-09-01"},
          '### User\n\nprimera\n\n### Assistant\n\n{"prompt": "un faro"}\n\n### Tool\n\n![](CHATGPT/GENERADAS/dddd.png)\n\n'
          "### User\n\nsegunda, sin prompt\n\n### Tool\n\n![](CHATGPT/GENERADAS/eeee.png)\n")
    items = _por_ruta(gal.recoger(vault))
    assert items["CHATGPT/GENERADAS/dddd.png"]["prompt"] == "un faro"
    assert items["CHATGPT/GENERADAS/eeee.png"]["prompt"] == ""
    assert items["CHATGPT/GENERADAS/eeee.png"]["pet"] == "segunda, sin prompt"


def test_los_enlaces_son_relativos_para_que_la_galeria_viaje_con_el_vault(vault):
    r = gal.generar(vault, log=lambda *_: None)
    imgs = [im for g in _datos_de(Path(r["pagina"]).read_text(encoding="utf-8"))["grupos"] for im in g["imgs"]]
    assert all(not im["o"].startswith("file:") and im["o"].startswith("../") for im in imgs)
    assert all(im["t"].startswith("miniaturas/") for im in imgs if im.get("t"))


def test_los_filtros_van_bajo_su_boton_con_segmentados_y_sin_modelo(vault, tmp_path):
    html = Path(gal.generar(vault, tmp_path / "g", log=lambda *_: None)["pagina"]).read_text(encoding="utf-8")
    assert 'id="b-filtros"' in html and 'id="panel-filtros" hidden' in html
    for seg, valores in (("f-origen", ("generada", "subida")), ("f-tipo", ("imagen", "video"))):
        bloque = html[html.index(f'id="{seg}"'):html.index("</div>", html.index(f'id="{seg}"'))]
        assert 'class="seg"' in html[html.index(f'id="{seg}"') - 30:html.index(f'id="{seg}"')]
        assert all(f'data-v="{v}"' in bloque for v in valores) and 'data-v=""' in bloque
    assert "f-modelo" not in html
