# -*- coding: utf-8 -*-
"""Tests de substack/build_substack_vault.py — el motor de Tintero/Inkwell.

Fixtures sinteticos inline, sin datos reales: el export de V0ra lleva emails
de suscriptores y no tiene por que existir una copia dentro de tests/.

Los casos cubiertos salen de trampas MEDIDAS contra el export real
(2026-07-31), no de imaginacion: la etiqueta oculta de los bloques
preformateados, el placeholder `_-` del CSV de estadisticas, el cruce que
falla si se hace solo por titulo, y la distincion borrador/retirado.
"""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "substack"))

import build_substack_vault as bsv  # noqa: E402


def _make_zip(tmp_path, name, entries: dict) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for arcname, content in entries.items():
            zf.writestr(arcname, content)
    return path


# ─────────────────────────────────────────
# HTML -> Markdown
# ─────────────────────────────────────────

def test_etiqueta_oculta_de_bloque_preformateado_no_es_contenido():
    """Substack mete un <label class="hide-text"> invisible dentro de CADA
    bloque preformateado. Aflora al quitar etiquetas a lo bruto -- asi es
    como acababa en turnos de 'user' en el import degradado. SEÑUELO: el
    contenido real del <pre> tiene que sobrevivir en el mismo test, o el
    filtro podria estar tirando el bloque entero y nadie se enteraria."""
    html = ('<div class="preformatted-block" data-component-name="PreformattedTextBlockToDOM">'
            '<label class="hide-text" contenteditable="false">'
            'Text within this block will maintain its original spacing when published</label>'
            '<pre class="text">esto SI es contenido</pre></div>')
    md = bsv.html_a_markdown(html)
    assert "Text within this block" not in md
    assert "esto SI es contenido" in md
    assert "```" in md


def test_widget_de_suscripcion_se_descarta():
    html = ('<p>Obra.</p>'
            '<div class="subscription-widget-wrap-editor" data-component-name="SubscribeWidgetToDOM">'
            '<p>¡Gracias por leer! Suscríbete</p></div>')
    md = bsv.html_a_markdown(html)
    assert "Obra." in md
    assert "Gracias por leer" not in md


def test_formato_inline_y_bloques():
    html = ("<h3>Titulo</h3><p>Un <strong>negrita</strong> y una <em>cursiva</em> "
            'con <a href="https://ejemplo.test">enlace</a>.</p>'
            "<ul><li>uno</li><li>dos</li></ul><hr>")
    md = bsv.html_a_markdown(html)
    assert "### Titulo" in md
    assert "**negrita**" in md
    assert "*cursiva*" in md
    assert "[enlace](https://ejemplo.test)" in md
    assert "- uno" in md and "- dos" in md
    assert "---" in md


def test_imagen_remota_se_conserva_como_enlace():
    """Las imagenes NO viajan en el zip. Hasta que exista el backfill, la
    URL remota es lo unico que hay y perderla seria perder la imagen."""
    html = '<figure><img src="https://s3.test/foto.png" alt="pie"></figure>'
    md = bsv.html_a_markdown(html)
    assert "![pie](https://s3.test/foto.png)" in md


# ─────────────────────────────────────────
# Estadisticas: la trampa del placeholder y el cruce
# ─────────────────────────────────────────

def test_placeholder_no_aplica_no_revienta_ni_cuenta_como_cero():
    """`_-` aparece en las 104 filas del CSV real. Un int() ingenuo revienta;
    tratarlo como 0 mentiria. Tiene que ser None (= no se escribe)."""
    assert bsv.a_numero("_-") is None
    assert bsv.a_numero("") is None
    assert bsv.a_numero("   ") is None
    assert bsv.a_numero("55") == 55
    assert bsv.a_numero("0.375") == 0.375
    assert bsv.a_numero("no-es-un-numero") is None


def test_cruce_necesita_titulo_y_fecha(tmp_path):
    """Medido: hay titulos repetidos en el export real y el cruce por titulo
    solo deja 102 de 104. La clave lleva el dia a proposito."""
    csv_path = tmp_path / "stats_2026-07-31.csv"
    csv_path.write_text(
        "title,post_date,section_name,tags,views\n"
        "Repetido,2026-01-01T00:00:00.000Z,Seccion A,uno,10\n"
        "Repetido,2026-02-02T00:00:00.000Z,Seccion B,dos,20\n",
        encoding="utf-8")
    indice = bsv.cargar_stats(csv_path)
    assert len(indice) == 2
    assert indice[(bsv.normaliza_titulo("Repetido"), "2026-01-01")]["section_name"] == "Seccion A"
    assert indice[(bsv.normaliza_titulo("Repetido"), "2026-02-02")]["section_name"] == "Seccion B"


def test_normaliza_titulo_aguanta_acentos_descompuestos():
    assert bsv.normaliza_titulo("Fenomenología") == bsv.normaliza_titulo("Fenomenología")


# ─────────────────────────────────────────
# Estado: borrador de verdad vs. despublicado
# ─────────────────────────────────────────

def test_clasificar_estado():
    """Decision de V0ra (2026-07-31): un post con is_published=false pero CON
    fecha y metricas no es un borrador, es un retirado. En el export real son
    los dos 'Versos EreKtos'."""
    assert bsv.clasificar_estado({"is_published": "true"}, False) == "published"
    assert bsv.clasificar_estado({"is_published": "false", "post_date": ""}, False) == "draft"
    assert bsv.clasificar_estado(
        {"is_published": "false", "post_date": "2025-12-06T00:00:00.000Z"}, True) == "retired"
    # Sin fecha pero con stats: tambien estuvo publicado alguna vez.
    assert bsv.clasificar_estado({"is_published": "false", "post_date": ""}, True) == "retired"


# ─────────────────────────────────────────
# Punta a punta: la nota se relee del disco (criterio de "hecho")
# ─────────────────────────────────────────

def _export_sintetico(tmp_path) -> Path:
    return _make_zip(tmp_path, "substack.zip", {
        "posts.csv": (
            "post_id,post_date,is_published,email_sent_at,inbox_sent_at,type,audience,title,subtitle,podcast_url\n"
            "111.publicado,2026-01-15T10:00:00.000Z,true,,,newsletter,everyone,Publicado,Un subtitulo,\n"
            "222.retirado,2025-12-06T10:00:00.000Z,false,,,newsletter,everyone,Retirado,,\n"
            "333.borrador,,false,,,newsletter,everyone,,,\n"
            "444.episodio,2026-02-20T10:00:00.000Z,true,,,podcast,everyone,Episodio,,\n"
        ),
        "posts/111.publicado.html": "<p>Cuerpo del publicado.</p>",
        "posts/222.retirado.html": "<p>Cuerpo del retirado.</p>",
        "posts/333.borrador.html": "<p>Cuerpo del borrador.</p>",
        "posts/444.episodio.html": "<p>Cuerpo del episodio.</p>",
        # PII de terceros: el script no debe leerlos JAMAS.
        "posts/111.delivers.csv": "post_id,timestamp,email\n111,2026-01-15T10:00:00.000Z,suscriptor@ejemplo.test\n",
        "posts/111.opens.csv": "post_id,email,country,city\n111,suscriptor@ejemplo.test,ES,Madrid\n",
        "email_list.publicacion.csv": "email,active_subscription\nsuscriptor@ejemplo.test,true\n",
    })


def _stats_sinteticas(tmp_path) -> Path:
    p = tmp_path / "stats_2026-07-31.csv"
    p.write_text(
        "title,post_date,section_name,tags,views,likes,comments,restacks,shares,opens,clicks,"
        "podcast_preview_downloads\n"
        "Publicado,2026-01-15T10:00:00.000Z,Bitacora Glitch,\"uno, dos\",55,6,1,1,0,43,0,_-\n"
        "Retirado,2025-12-06T10:00:00.000Z,Hackeo limbico,tres,36,2,0,2,0,0,0,_-\n",
        encoding="utf-8")
    return p


def test_punta_a_punta_escribe_y_clasifica(tmp_path):
    vault = tmp_path / "vault"
    r = bsv.construir_vault(_export_sintetico(tmp_path), vault,
                            _stats_sinteticas(tmp_path), log=lambda *a: None)
    assert r["posts"] == 4
    assert (r["published"], r["retired"], r["draft"]) == (2, 1, 1)
    assert r["cruzados"] == 2
    assert r["csv_ignorados"] == 3

    # El publicado va al arbol año/mes; el borrador, a su carpeta propia y
    # SIN fecha (que es lo que hace viable la decision de categoria propia).
    nota = vault / "Posts" / "2026" / "01" / "2026-01-15_publicado.md"
    assert nota.is_file()
    assert (vault / "Drafts" / "borrador.md").is_file()

    # Releer del disco, no fiarse de lo que se creyo escribir.
    texto = nota.read_text(encoding="utf-8")
    assert 'status: "published"' in texto
    assert 'section: "Bitacora Glitch"' in texto
    assert 'type: "newsletter"' in texto
    assert "stats_snapshot: 2026-07-31" in texto
    assert "views: 55" in texto
    assert "Cuerpo del publicado." in texto
    # `_-` no se escribe como 0 ni como "_-".
    assert "_-" not in texto


def test_ningun_dato_de_suscriptor_llega_al_vault(tmp_path):
    """El test que de verdad importa de la parte de privacidad: no que el
    script 'no lea' los CSV (eso no se puede afirmar desde fuera), sino que
    ni un email de tercero aparece en NINGUNA nota escrita."""
    vault = tmp_path / "vault"
    bsv.construir_vault(_export_sintetico(tmp_path), vault,
                        _stats_sinteticas(tmp_path), log=lambda *a: None)
    notas = list(vault.rglob("*.md"))
    assert notas
    todo = "\n".join(n.read_text(encoding="utf-8") for n in notas)
    assert "suscriptor@ejemplo.test" not in todo
    assert "Madrid" not in todo


def test_retirado_y_podcast_se_avisan_en_la_nota(tmp_path):
    """Las perdidas se anotan en la nota, no en silencio."""
    vault = tmp_path / "vault"
    bsv.construir_vault(_export_sintetico(tmp_path), vault,
                        _stats_sinteticas(tmp_path), log=lambda *a: None)
    retirado = (vault / "Posts" / "2025" / "12" / "2025-12-06_retirado.md").read_text(encoding="utf-8")
    assert "Retired" in retirado and 'status: "retired"' in retirado
    episodio = (vault / "Posts" / "2026" / "02" / "2026-02-20_episodio.md").read_text(encoding="utf-8")
    assert "Audio not included" in episodio


def test_sin_stats_la_nota_se_construye_igual(tmp_path):
    """La fuente de estadisticas es opcional (mismo patron que gizmo_map)."""
    vault = tmp_path / "vault"
    r = bsv.construir_vault(_export_sintetico(tmp_path), vault, None, log=lambda *a: None)
    assert r["cruzados"] == 0
    texto = (vault / "Posts" / "2026" / "01" / "2026-01-15_publicado.md").read_text(encoding="utf-8")
    assert "Cuerpo del publicado." in texto
    assert "stats_snapshot" not in texto
    # Sin stats no hay forma de saber que estuvo publicado: cae a borrador.
    assert (vault / "Drafts" / "retirado.md").is_file() or \
           (vault / "Posts" / "2025" / "12" / "2025-12-06_retirado.md").is_file()


def test_zip_que_no_es_de_substack_se_rechaza(tmp_path):
    import pytest
    zpath = _make_zip(tmp_path, "otro.zip", {"conversations.json": "[]"})
    with pytest.raises(ValueError):
        bsv.construir_vault(zpath, tmp_path / "vault", None, log=lambda *a: None)
