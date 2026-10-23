# -*- coding: utf-8 -*-
"""galeria_tintero.py: la galeria de los posts de Substack que construye Tintero. Cada regla que
INKWELL_GALLERY.md afirma esta fijada aqui: si un test falla, o se corrige el codigo o el documento.

Nunca sale a Internet: la API de Substack y las descargas pasan por `leer`, y aqui `leer` es un falso
que sirve lo que cada test dice (y apunta lo que se le pidio). Las notas se escriben con el mismo
frontmatter que escribe substack/build_substack_vault.py.
"""
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest
from PIL import Image

import galeria_tintero as gt

RAIZ = Path(__file__).resolve().parent.parent
DOC = RAIZ / "INKWELL_GALLERY.md"


def _png(color=(200, 30, 30), tam=(1200, 800)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", tam, color).save(b, "PNG")
    return b.getvalue()


def _nota(vault: Path, rel: str, *, post_id, titulo="Un post", slug=None, estado="published", fecha="2026-10-01",
          tipo="newsletter", sub="", pub="mipub", seccion="", tags=(), stats=None, cuerpo="Texto del post."):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = ["---", f'title: "{titulo}"']
    if fecha:
        fm.append(f"date: {fecha}")
    fm += ["source: substack_export", f'publication: "{pub}"', f'post_id: "{post_id}"', f'slug: "{slug or post_id}"',
           f'status: "{estado}"', f'type: "{tipo}"']
    if sub:
        fm.append(f'subtitle: "{sub}"')
    if seccion:
        fm.append(f'section: "{seccion}"')
    if tags:
        fm.append("tags:")
        fm += [f'  - "{t}"' for t in tags]
    for k, v in (stats or {}).items():
        fm.append(f"{k}: {v}")
    fm.append("---")
    partes = ["\n".join(fm), "", f"# {titulo}"]
    if sub:
        partes.append(f"*{sub}*")
    partes.append(cuerpo)
    p.write_text("\n\n".join(partes) + "\n", encoding="utf-8")
    return p


class Red:
    """Un Substack falso: {url: bytes o excepcion}; el archivo de la API se arma con `portadas`."""

    def __init__(self, portadas=None, imagenes=None, api_caida=False):
        self.portadas = portadas or {}            # {pubslug: {slug: url}}
        self.imagenes = imagenes or {}            # {url: bytes | Exception}
        self.api_caida = api_caida
        self.pedidas = []

    def __call__(self, url):
        self.pedidas.append(url)
        m = re.match(r"https://([a-z0-9-]+)\.substack\.com/api/v1/archive\?sort=new&offset=(\d+)&limit=50$", url)
        if m:
            if self.api_caida:
                raise OSError("sin conexion")
            todos = [{"slug": s, "cover_image": u} for s, u in self.portadas.get(m.group(1), {}).items()]
            off = int(m.group(2))
            return json.dumps(todos[off:off + 12]).encode()          # el servidor sirve menos de lo pedido
        r = self.imagenes.get(url)
        if r is None:
            raise OSError(f"404 {url}")
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "SUBSTACK_VAULT"
    (v / ".obsidian").mkdir(parents=True)
    _nota(v, "MiPub/Posts/2026/10/2026-10-05_portada.md", post_id="1", titulo="Con portada", slug="con-portada",
          sub="El subtitulo", seccion="Ensayo", tags=("ia", "glitch"), stats={"views": 49, "likes": 6, "comments": 3},
          cuerpo="![](https://img.test/texto1.png)\n*Pie de la foto*\n\nUno dos tres cuatro.")
    _nota(v, "MiPub/Posts/2026/09/2026-09-01_solo-texto.md", post_id="2", titulo="Solo imagen en el texto",
          slug="solo-texto", fecha="2026-09-01", cuerpo="Antes.\n\n![](https://img.test/texto2.png)\n\nDespues.")
    _nota(v, "MiPub/Posts/2026/08/2026-08-01_retirado.md", post_id="3", titulo="Retirado", slug="retirado",
          estado="retired", fecha="2026-08-01", cuerpo="Nada de imagenes.")
    _nota(v, "MiPub/Drafts/084.md", post_id="4", titulo="084", slug="084", estado="draft", fecha="",
          cuerpo="Un borrador.")
    _nota(v, "MiPub/Posts/2026/07/2026-07-01_podcast.md", post_id="5", titulo="Episodio", slug="episodio",
          tipo="podcast", fecha="2026-07-01", cuerpo="Audio.")
    return v


def _red_basica():
    return Red(portadas={"mipub": {"con-portada": "https://cdn.test/cover1.png", "retirado": "https://cdn.test/cover3.png"}},
               imagenes={"https://cdn.test/cover1.png": _png((0, 0, 200)), "https://img.test/texto1.png": _png(),
                         "https://img.test/texto2.png": _png((0, 200, 0)), "https://cdn.test/cover3.png": _png()})


def _datos(pagina: Path) -> dict:
    m = re.search(r"const DATOS = (.*?);\nconst MESES", Path(pagina).read_text(encoding="utf-8"), re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def _por_titulo(posts):
    return {p["titulo"]: p for p in posts}


def _plantilla():
    return gt.PLANTILLA.read_text(encoding="utf-8")


def test_el_documento_existe_y_dice_que_lo_vigila_este_test():
    assert "tests/test_galeria_tintero.py" in DOC.read_text(encoding="utf-8")


# ---- las notas ------------------------------------------------------------------------------------
def test_lee_los_posts_con_su_publicacion_y_lo_que_hay_en_su_cabecera(vault):
    p = _por_titulo(gt.leer_posts(vault))["Con portada"]
    assert (p["pub"], p["pubslug"], p["id"], p["sub"], p["seccion"], p["tags"]) == \
        ("MiPub", "mipub", "1", "El subtitulo", "Ensayo", ["ia", "glitch"])
    assert p["stats"] == {"views": "49", "likes": "6", "comments": "3"}


def test_no_lee_indices_carpetas_ocultas_ni_notas_que_no_son_de_tintero(vault):
    (vault / "MiPub" / "_indice.md").write_text("---\nsource: substack_export\npost_id: \"9\"\n---\n", encoding="utf-8")
    _nota(vault, ".gallery/copia.md", post_id="10")
    (vault / "MiPub" / "mia.md").write_text("---\ntitle: mia\n---\nmaterial propio\n", encoding="utf-8")
    assert {p["id"] for p in gt.leer_posts(vault)} == {"1", "2", "3", "4", "5"}


def test_un_vault_de_una_sola_publicacion_tambien_vale(tmp_path):
    v = tmp_path / "plano"
    _nota(v, "Posts/2026/10/x.md", post_id="1", pub="solita")
    (p,) = gt.leer_posts(v)
    assert p["pub"] == "solita"


def test_un_post_repetido_sale_una_vez_la_nota_mas_reciente(vault):
    vieja = _nota(vault, "MiPub/Borradores/084.md", post_id="4", titulo="084 viejo", slug="084", estado="draft", fecha="")
    os.utime(vieja, (1_600_000_000, 1_600_000_000))
    posts = [p for p in gt.leer_posts(vault) if p["id"] == "4"]
    assert len(posts) == 1 and posts[0]["titulo"] == "084"


def test_el_extracto_son_50_palabras_sin_titulo_subtitulo_avisos_imagenes_ni_pies():
    cuerpo = ("# Titulo\n\n*El subtitulo*\n\n> [!warning] Retirado\n> Aviso de Tintero\n\n"
              "![alt](https://x.test/a.png)\n*Pie de la foto*\n\nUn [enlace](https://x.test) con **negrita** y "
              + " ".join(f"p{i}" for i in range(60)))
    e = gt.extracto(cuerpo, "El subtitulo")
    assert e.startswith("Un enlace con negrita y p0") and e.endswith("…")
    assert len(e.rstrip("…").split()) == 50
    for fuera in ("Titulo", "subtitulo", "Aviso", "Pie", "https"):
        assert fuera not in e, fuera


def test_un_parrafo_en_cursiva_que_no_es_pie_ni_subtitulo_si_entra():
    assert gt.extracto("*Una frase en cursiva.*\n\nY otra.", "Otro subtitulo") == "Una frase en cursiva. Y otra."


# ---- portadas -------------------------------------------------------------------------------------
def test_la_portada_sale_de_la_api_si_no_de_la_primera_imagen_si_no_la_inicial(vault, tmp_path):
    posts = gt.leer_posts(vault)
    r = gt.poner_portadas(posts, tmp_path / "g", leer=_red_basica(), log=lambda *_: None)
    p = _por_titulo(posts)
    assert p["Con portada"]["origen"] == "api"
    with Image.open(p["Con portada"]["portada"]) as im:
        assert im.getpixel((5, 5))[2] > 150 and max(im.size) == 640                 # la azul de la API, 640 px
    assert p["Solo imagen en el texto"]["origen"] == "texto"
    assert p["Episodio"]["origen"] == "" and p["Episodio"]["portada"] is None
    assert (r["api"], r["texto"], r["inicial"]) == (1, 1, 3)


def test_lo_retirado_no_usa_la_portada_de_la_api_aunque_la_hubiera(vault, tmp_path):
    posts = gt.leer_posts(vault)
    gt.poner_portadas(posts, tmp_path / "g", leer=_red_basica(), log=lambda *_: None)
    assert _por_titulo(posts)["Retirado"]["portada"] is None


def test_la_api_se_lee_entera_aunque_sirva_menos_de_lo_pedido():
    red = Red(portadas={"mipub": {f"s{i}": f"https://cdn.test/{i}.png" for i in range(30)}})
    assert len(gt.portadas_de_la_api("mipub", red)) == 30
    assert gt.portadas_de_la_api("no valido/../", red) == {}


def test_la_segunda_vez_no_baja_nada(vault, tmp_path):
    gt.poner_portadas(gt.leer_posts(vault), tmp_path / "g", leer=_red_basica(), log=lambda *_: None)
    red = _red_basica()
    r = gt.poner_portadas(gt.leer_posts(vault), tmp_path / "g", leer=red, log=lambda *_: None)
    assert r["bajadas"] == 0 and r["reutilizadas"] == 2
    assert all("/api/v1/archive" in u for u in red.pedidas)                 # solo pregunto, no bajo


def test_si_substack_cambia_la_portada_se_baja_la_nueva(vault, tmp_path):
    gt.poner_portadas(gt.leer_posts(vault), tmp_path / "g", leer=_red_basica(), log=lambda *_: None)
    red = _red_basica()
    red.portadas["mipub"]["con-portada"] = "https://cdn.test/nueva.png"
    red.imagenes["https://cdn.test/nueva.png"] = _png((250, 250, 0))
    posts = gt.leer_posts(vault)
    gt.poner_portadas(posts, tmp_path / "g", leer=red, log=lambda *_: None)
    with Image.open(_por_titulo(posts)["Con portada"]["portada"]) as im:
        assert im.getpixel((5, 5))[0] > 200 and im.getpixel((5, 5))[2] < 60


def test_sin_red_no_sale_a_internet_y_usa_lo_ya_bajado(vault, tmp_path):
    gt.poner_portadas(gt.leer_posts(vault), tmp_path / "g", leer=_red_basica(), log=lambda *_: None)
    red = Red()
    posts = gt.leer_posts(vault)
    r = gt.poner_portadas(posts, tmp_path / "g", con_red=False, leer=red, log=lambda *_: None)
    assert red.pedidas == [] and r["reutilizadas"] == 2 and _por_titulo(posts)["Con portada"]["origen"] == "api"
    vacio = gt.poner_portadas(gt.leer_posts(vault), tmp_path / "otra", con_red=False, leer=red, log=lambda *_: None)
    assert vacio["inicial"] == 5


def test_si_la_api_no_responde_se_sigue_con_la_primera_imagen_y_se_avisa(vault, tmp_path):
    red = _red_basica()
    red.api_caida = True
    avisos = []
    posts = gt.leer_posts(vault)
    r = gt.poner_portadas(posts, tmp_path / "g", leer=red, log=avisos.append)
    assert r["api_caida"] == ["mipub"] and any("mipub" in a for a in avisos)
    assert _por_titulo(posts)["Con portada"]["origen"] == "texto"


def test_una_portada_que_no_se_puede_bajar_pasa_a_la_siguiente_y_se_reintenta_luego(vault, tmp_path):
    red = _red_basica()
    red.imagenes["https://cdn.test/cover1.png"] = OSError("HTTP Error 403: Forbidden")
    avisos = []
    posts = gt.leer_posts(vault)
    r = gt.poner_portadas(posts, tmp_path / "g", leer=red, log=avisos.append)
    assert r["fallidas"] == 1 and _por_titulo(posts)["Con portada"]["origen"] == "texto" and avisos
    red2 = _red_basica()
    gt.poner_portadas(gt.leer_posts(vault), tmp_path / "g", leer=red2, log=lambda *_: None)
    assert "https://cdn.test/cover1.png" in red2.pedidas                    # se reintenta


def test_una_imagen_rota_tampoco_tumba_nada(vault, tmp_path):
    red = _red_basica()
    red.imagenes["https://img.test/texto2.png"] = b"no es una imagen"
    posts = gt.leer_posts(vault)
    r = gt.poner_portadas(posts, tmp_path / "g", leer=red, log=lambda *_: None)
    assert r["fallidas"] == 1 and _por_titulo(posts)["Solo imagen en el texto"]["portada"] is None


def test_sin_pillow_y_con_red_se_para_avisando(vault, tmp_path, monkeypatch):
    red = _red_basica()                                   # sus imagenes se hacen con Pillow: antes de quitarlo
    monkeypatch.setitem(sys.modules, "PIL", None)
    with pytest.raises(gt.ErrorGaleria, match="Pillow"):
        gt.poner_portadas(gt.leer_posts(vault), tmp_path / "g", leer=red, log=lambda *_: None)


# ---- la pagina ------------------------------------------------------------------------------------
def test_la_pagina_lleva_los_temas_el_aviso_legal_y_la_mascota(vault, tmp_path):
    r = gt.generar(vault, tmp_path / "g", leer=_red_basica(), tema="cool", log=lambda *_: None)
    html = Path(r["pagina"]).read_text(encoding="utf-8")
    assert "--accent:" in html and "/*__TOKENS__*/" not in html and _datos(r["pagina"])["tema"] == "cool"
    assert "CC BY-NC-SA 4.0" in html and html.index("CC BY-NC-SA") < html.index("<html")
    assert "Own your AI memory" in html and 'src="tintero.png"' in html
    with Image.open(tmp_path / "g" / "tintero.png") as im:
        assert max(im.size) <= 96


def test_los_enlaces_de_las_portadas_resuelven(vault, tmp_path):
    r = gt.generar(vault, tmp_path / "g", leer=_red_basica(), log=lambda *_: None)
    con = [p for p in _datos(r["pagina"])["posts"] if p.get("portada")]
    assert len(con) == 2 and all((tmp_path / "g" / unquote(p["portada"])).is_file() for p in con)


def test_substack_solo_para_lo_publicado_y_obsidian_al_vault_mas_cercano(vault, tmp_path):
    r = gt.generar(vault, tmp_path / "g", leer=_red_basica(), log=lambda *_: None)
    p = _por_titulo(_datos(r["pagina"])["posts"])
    assert p["Con portada"]["web"] == "https://mipub.substack.com/p/con-portada"
    assert "web" not in p["Retirado"] and "web" not in p["084"]
    assert p["Con portada"]["obs"] == ("obsidian://open?vault=SUBSTACK_VAULT&file="
                                       "MiPub%2FPosts%2F2026%2F10%2F2026-10-05_portada")


def test_sin_vault_de_obsidian_el_enlace_va_por_ruta(tmp_path):
    nota = _nota(tmp_path / "suelto", "Posts/x.md", post_id="1")
    assert gt.enlace_obsidian(nota).startswith("obsidian://open?path=")


def test_sin_estadisticas_no_se_pinta_cero(vault, tmp_path):
    r = gt.generar(vault, tmp_path / "g", leer=_red_basica(), log=lambda *_: None)
    p = _por_titulo(_datos(r["pagina"])["posts"])
    assert "stats" not in p["Solo imagen en el texto"]
    assert '"views" in s ?' in _plantilla()


def test_un_titulo_con_script_no_rompe_la_pagina(vault, tmp_path):
    _nota(vault, "MiPub/Posts/2026/06/raro.md", post_id="6", titulo="x</script><script>alert(1)</script>")
    r = gt.generar(vault, tmp_path / "g", leer=_red_basica(), log=lambda *_: None)
    assert Path(r["pagina"]).read_text(encoding="utf-8").count("</script>") == 1


def test_los_borradores_se_ocultan_por_defecto_y_se_ven_con_su_filtro_o_con_todo():
    p = _plantilla()
    assert 'data-v="" aria-pressed="true">No drafts</button>' in p
    assert 'if (!f["f-estado"] && p.estado === "draft") return false;' in p
    assert 'data-v="draft"' in p and 'data-v="todo"' in p and "drafts hidden" in p


def test_texto_es_todo_lo_que_no_es_podcast():
    assert 'if (f["f-tipo"] === "texto" && p.tipo === "podcast") return false;' in _plantilla()


def test_buscar_es_por_trozos_sin_acentos_y_exige_todas_las_palabras_en_lo_que_enseña():
    p = _plantilla()
    assert '.normalize("NFD")' in p and "terminos.every((t) => p.busca.includes(t))" in p
    linea = re.search(r"p\.busca = norm\(\[(.*?)\]\.join", p).group(1)
    assert [c.strip() for c in linea.split(",")] == ["p.titulo", "p.sub", "p.ext", "p.seccion", "p.pub", 'p.tags.join(" ")']


def test_las_portadas_se_recortan_desde_arriba():
    assert "object-fit: cover; object-position: top;" in _plantilla()


# ---- que escribe y que no -------------------------------------------------------------------------
def test_por_defecto_escribe_solo_en_su_carpeta_y_no_toca_ninguna_nota(vault):
    antes = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    gt.generar(vault, leer=_red_basica(), log=lambda *_: None)
    despues = {p for p in vault.rglob("*") if p.is_file()}
    assert {p: p.read_bytes() for p in antes} == antes
    nuevos = sorted(p.relative_to(vault).as_posix() for p in despues - set(antes))
    assert nuevos == [".gallery/covers/MiPub/1.jpg", ".gallery/covers/MiPub/2.jpg", ".gallery/covers/_origen.json",
                      ".gallery/estado.json", ".gallery/index.html", ".gallery/tintero.png"]
    estado = json.loads((vault / ".gallery" / "estado.json").read_text(encoding="utf-8"))
    assert (estado["posts"], estado["borradores"]) == (5, 1)


def test_un_vault_sin_posts_se_niega(tmp_path):
    (tmp_path / "vacio").mkdir()
    with pytest.raises(gt.ErrorGaleria, match="no Inkwell posts found"):
        gt.generar(tmp_path / "vacio", leer=Red(), log=lambda *_: None)


def test_cli_sin_red_con_una_configuracion_vacia(vault, tmp_path):
    cfg = tmp_path / "config_vacia.yaml"
    cfg.write_text("paths: {}\noptions: {}\n", encoding="utf-8")
    entorno = {**os.environ, "MEMORIA_CONFIG": str(cfg), "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(RAIZ / "galeria_tintero.py"), "--vault", str(vault), "--salida",
                        str(tmp_path / "g"), "--sin-red"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=RAIZ, env=entorno)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "5 posts (1 drafts)" in r.stdout and "5 with the initial" in r.stdout
    r = subprocess.run([sys.executable, str(RAIZ / "galeria_tintero.py")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=RAIZ, env=entorno)
    assert r.returncode == 2 and "substack_vault" in r.stderr
