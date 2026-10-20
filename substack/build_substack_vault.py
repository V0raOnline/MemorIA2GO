#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_substack_vault.py — Convierte el export de Substack (zip) en un vault
de Obsidian independiente. Es el motor de Tintero / Inkwell.

USO:
    python build_substack_vault.py --export ruta/al/export.zip --vault-dir ./tintero_vault
    python build_substack_vault.py --exports-dir ./exports --vault-dir ./tintero_vault

    Opcional, y muy recomendable:
    --stats ruta/al/v0raonline_email_stats_YYYY-MM-DD.csv

POR QUE NO ES UN PROVEEDOR DEL PIPELINE (decision de V0ra, 2026-07-31):
un post es una publicacion, no un dialogo. El pipeline conversacional lo
RECHAZA a proposito (ver el guard en preflight.validate_export_file) y esta
herramienta lo recoge por la otra puerta. Misma carpeta de entrada, dos
puertas distintas.

QUE TRAE EL EXPORT Y QUE NO (medido contra el export real, 2026-07-31):
  - Trae: posts.csv (indice), posts/<id>.<slug>.html (cuerpo), y los
    borradores tambien.
  - NO trae: comentarios (ninguno), likes, Notes, el audio de los podcast
    (podcast_url viene vacio) ni los binarios de las imagenes (solo URLs
    remotas a S3). El backfill de imagenes es otra fase y sale a la red
    solo si se le pide.

DATOS DE TERCEROS: el zip incluye email_list.*.csv y, por post,
delivers.csv/opens.csv con emails de suscriptores (y los de opens, ademas,
pais/ciudad/dispositivo/user-agent). Este script NO los lee nunca: solo los
cuenta para decirlo en voz alta. No son memoria de V0ra, son datos
personales de otras personas bajo su responsabilidad.

EL CSV DE ESTADISTICAS es una fuente secundaria opcional (mismo patron que
gizmo_map.json): si esta, enriquece; si no, la nota se construye igual.
Cruza por (titulo normalizado + dia), NO por titulo solo -- hay titulos
repetidos en el export y el titulo solo deja 102 de 104. Aporta dos cosas
que el export no tiene: section_name y tags.
"""

import argparse
import csv
import io
import os
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

try:
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError:
    print("[error] falta beautifulsoup4 (pip install -r requirements.txt)")
    sys.exit(1)

# Componentes de Substack que son cascaron de la web, no obra: el widget de
# suscripcion, los botones de restack y el boton de suscribirse. Se
# identifican por data-component-name, que es estable, en vez de por clases
# de CSS, que Substack cambia cuando quiere.
COMPONENTES_DESCARTADOS = {
    "SubscribeWidgetToDOM",
    "ButtonCreateButton",
}

# Etiqueta OCULTA que Substack mete dentro de CADA bloque preformateado
# (<label class="hide-text">, hermana del <pre>, invisible en la web). No es
# contenido: es ayuda del editor. Solo aflora cuando alguien quita etiquetas
# a lo bruto -- que es exactamente lo que hacia el import degradado del
# pipeline conversacional, convirtiendola en turnos de "user" (ver 3j).
# Se descarta por la etiqueta <label>, no por el texto: el texto es ingles
# fijo hoy, pero la etiqueta es estructura y aguanta mejor un cambio de
# idioma o de redaccion por parte de Substack.
PLACEHOLDER_PRE = "Text within this block will maintain its original spacing when published"

# Columnas del CSV de stats que van al frontmatter normal porque son obra,
# no telemetria: la seccion y las etiquetas son taxonomia de la autora y no
# envejecen. Todo lo demas es una foto de un dia y va al bloque de
# instantanea, fechado, para que no mienta seis meses despues.
METRICAS_INSTANTANEA = ["views", "likes", "comments", "restacks", "shares", "opens", "clicks"]

# Placeholder de Substack para "esta metrica no aplica". No es vacio ni
# cero: revienta cualquier int() ingenuo. Mismo genero que la trampa de
# `duration` en Suno, y por eso hay test con senuelo.
NO_APLICA = "_-"


def normaliza_titulo(t: str) -> str:
    """Clave de cruce con el CSV de stats. NFC + casefold porque los
    acentos pueden venir descompuestos de un lado y compuestos del otro."""
    return unicodedata.normalize("NFC", (t or "").strip()).casefold()


def slugify(texto: str, fallback: str = "sin-titulo") -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^\w\s-]", "", t).strip().lower()
    t = re.sub(r"[\s_-]+", "-", t)
    return t[:80] or fallback


def yaml_escape(valor) -> str:
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return str(valor)
    return '"{}"'.format(str(valor).replace('"', '\\"'))


def etiqueta_obsidian(t: str) -> str:
    """Etiqueta de Substack -> etiqueta valida de Obsidian.

    Obsidian NO admite espacios dentro de una etiqueta: la marca en rojo y
    tachada en el panel de propiedades, y deja de existir para el panel de
    etiquetas y para el grafo. Verificado por V0ra sobre su vault real
    (2026-08-01) despues de que la primera version escribiera el texto tal
    cual: 16 de sus 46 etiquetas estaban muertas.

    Se sustituye por guion en vez de partir o descartar: la transformacion
    es reversible de un vistazo y no pierde informacion. Los acentos SI se
    conservan -- Obsidian los admite, y "bitacora" no es lo que ella
    escribio. Medido: hoy el espacio es el unico caracter que rompe en su
    vocabulario, pero la limpieza va general para que un punto o dos puntos
    en una etiqueta futura no vuelvan a colarse en silencio.
    """
    limpio = re.sub(r"[^\w/\-]+", "-", (t or "").strip(), flags=re.UNICODE)
    return re.sub(r"-{2,}", "-", limpio).strip("-")


def a_numero(valor):
    """Devuelve int/float, o None si la celda esta vacia o trae el
    placeholder NO_APLICA. Nunca lanza: una metrica ilegible no debe tumbar
    la construccion de un vault."""
    v = (valor or "").strip()
    if not v or v == NO_APLICA:
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


# ─────────────────────────────────────────
# Lectura del export
# ─────────────────────────────────────────

def es_export_substack(nombres) -> bool:
    """Mismo predicado que el guard de preflight, a proposito: si los dos
    divergen, un zip podria ser rechazado por el pipeline y no recogido por
    aqui, y quedarse sin puerta."""
    return any(n.lower() == "posts.csv" for n in nombres) and \
           any(n.lower().startswith("posts/") and n.lower().endswith(".html") for n in nombres)


def localizar_export(exports_dir: Path):
    """Busca en la carpeta el primer .zip que sea un export de Substack.
    Detecta por estructura interna, nunca por nombre de archivo -- misma
    regla que el pipeline conversacional."""
    for z in sorted(exports_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with zipfile.ZipFile(z) as zf:
                if es_export_substack(zf.namelist()):
                    return z
        except (zipfile.BadZipFile, OSError):
            continue
    return None


# ─────────────────────────────────────────
# Varias publicaciones en la misma carpeta de exports
#
# Cada publicacion de Substack tiene su propio export (su propio zip). Hasta
# aqui Tintero cogia UNO -- el mas reciente --, y los demas no existian. La
# identidad de cada publicacion esta dentro de los ficheros, no hay que
# adivinarla: el zip trae `email_list.<slug>.csv` y el CSV de estadisticas
# empieza por `<slug>_`.
# ─────────────────────────────────────────

LAYOUT_ANTIGUO = ("Posts", "Borradores", "Drafts", "_indice.md", "_secciones.md")
INDICE_PUBLICACIONES = "_publicaciones.md"


class LayoutAntiguoError(ValueError):
    """El vault tiene el layout de un solo export y ahora hay varias publicaciones."""


def es_csv_de_stats(ruta: Path) -> bool:
    """Se reconoce por la cabecera, no por el nombre: en esa carpeta puede haber
    otros CSV y meter uno equivocado daria un cruce silencioso de 0 filas.

    Hay MAS DE UN ESQUEMA. El de V0raOnline trae section_name, tags, likes, comments...;
    el de una publicacion con menos historial (BitacoraClandestina, 2026-10-20) solo
    title, post_date, audience, views, engagement_rate, signups... Exigir section_name
    descartaba el segundo, que cruzaba 45 de 45 con su zip. Se piden las columnas de
    cruce (title y post_date, como columnas enteras: 'subtitle' no es 'title') y al
    menos una metrica."""
    try:
        with open(ruta, "r", encoding="utf-8-sig", newline="") as f:
            columnas = set(next(csv.reader(f), []))
    except (OSError, UnicodeDecodeError, csv.Error):
        return False
    return {"title", "post_date"} <= columnas and bool(columnas & {"views", "section_name"})


def slug_de_publicacion(nombres, zip_path: Path) -> str:
    """El slug de la publicacion: el de `email_list.<slug>.csv` dentro del zip. Si
    no hay (un export recortado), el nombre del zip reducido a letras y numeros."""
    encontrados = sorted(m.group(1).lower() for n in nombres if "/" not in n
                         for m in [re.fullmatch(r"email_list\.(.+)\.csv", n, re.I)] if m)
    if encontrados:
        return encontrados[0]
    return re.sub(r"[^a-z0-9]", "", Path(zip_path).stem.lower()) or "publicacion"


def exports_por_publicacion(exports_dir: Path):
    """({slug: zip}, [zips ignorados]). De cada publicacion se usa el export mas
    reciente; los demas se devuelven aparte para poder decirlo, no se descartan
    en silencio."""
    publicaciones, repetidos = {}, []
    zips = sorted(Path(exports_dir).glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for z in zips:
        try:
            with zipfile.ZipFile(z) as zf:
                nombres = zf.namelist()
        except (zipfile.BadZipFile, OSError):
            continue
        if not es_export_substack(nombres):
            continue
        slug = slug_de_publicacion(nombres, z)
        if slug in publicaciones:
            repetidos.append(z)
        else:
            publicaciones[slug] = z
    return publicaciones, repetidos


def localizar_stats(exports_dir: Path, slug: str, unica: bool):
    """El CSV de estadisticas de UNA publicacion: el mas reciente cuyo nombre empieza
    por `<slug>_`. Una publicacion sin CSV propio NO se lleva el de otra.

    Con una sola publicacion se acepta ademas cualquier CSV valido (compatibilidad: quien
    ya lo usaba con el CSV renombrado no se queda sin estadisticas)."""
    validos = [p for p in sorted(Path(exports_dir).glob("*.csv"), reverse=True) if es_csv_de_stats(p)]
    propios = [p for p in validos if p.name.lower().startswith(slug + "_")]
    if propios:
        return propios[0]
    return validos[0] if (unica and validos) else None


def nombre_visible(slug: str, zip_path: Path) -> str:
    """Como se muestra una publicacion: el nombre del zip sin el sufijo de fecha
    (`BitacoraClandestina201026` -> `BitacoraClandestina`) cuando casa con el slug,
    y si no, el propio slug."""
    limpio = re.sub(r"[\d\W_]+$", "", Path(zip_path).stem).strip(" ._-")
    if limpio and re.sub(r"[^a-z0-9]", "", limpio.lower()) == slug \
            and not re.search(r'[<>:"/\\|?*]', limpio):
        return limpio
    return slug


def nombre_de_carpeta(vault: Path, slug: str, zip_path: Path) -> str:
    """Nombre de la carpeta de una publicacion dentro del vault. Estable: una carpeta
    que ya existe se reutiliza (renombrar el zip no puede duplicar la publicacion)."""
    vault = Path(vault)
    if vault.is_dir():
        for hijo in vault.iterdir():
            if hijo.is_dir() and hijo.name.casefold() == slug.casefold():
                return hijo.name
    return nombre_visible(slug, zip_path)


def layout_antiguo(vault: Path) -> list:
    """Lo que hay en la raiz del vault del layout de un solo export."""
    vault = Path(vault)
    if not vault.is_dir():
        return []
    return [n for n in LAYOUT_ANTIGUO if (vault / n).exists()]


def cargar_posts(zf: zipfile.ZipFile) -> list:
    datos = zf.read("posts.csv").decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(datos)))


def cargar_stats(ruta: Path) -> dict:
    """Indice del CSV de estadisticas por (titulo normalizado, dia)."""
    if not ruta or not ruta.exists():
        return {}
    datos = ruta.read_text(encoding="utf-8-sig")
    indice = {}
    for fila in csv.DictReader(io.StringIO(datos)):
        clave = (normaliza_titulo(fila.get("title")), (fila.get("post_date") or "")[:10])
        indice[clave] = fila
    return indice


def contar_csv_de_terceros(nombres) -> int:
    """Solo los cuenta. No los abre. Ver la nota de datos de terceros en la
    cabecera del modulo."""
    return sum(1 for n in nombres if n.lower().endswith(".csv") and n.lower() != "posts.csv")


# ─────────────────────────────────────────
# HTML -> Markdown
# ─────────────────────────────────────────

def _texto_inline(nodo) -> str:
    partes = []
    for hijo in nodo.children:
        if isinstance(hijo, NavigableString):
            partes.append(str(hijo))
        elif isinstance(hijo, Tag):
            partes.append(_render_inline(hijo))
    return "".join(partes)


def _render_inline(tag: Tag) -> str:
    nombre = tag.name
    if nombre == "br":
        return "\n"
    if nombre in ("strong", "b"):
        return f"**{_texto_inline(tag).strip()}**"
    if nombre in ("em", "i"):
        return f"*{_texto_inline(tag).strip()}*"
    if nombre == "code":
        return f"`{_texto_inline(tag)}`"
    if nombre == "a":
        texto = _texto_inline(tag).strip()
        href = tag.get("href", "")
        return f"[{texto}]({href})" if href else texto
    if nombre in ("svg", "button"):
        return ""  # cromo de la interfaz (restack, compartir): no es obra
    return _texto_inline(tag)


def _es_descartable(tag: Tag) -> bool:
    comp = tag.get("data-component-name")
    if comp and comp in COMPONENTES_DESCARTADOS:
        return True
    clases = tag.get("class") or []
    return any("subscription-widget" in c for c in clases)


def _render_bloque(tag: Tag) -> str:
    nombre = tag.name

    if _es_descartable(tag):
        return ""

    if nombre in ("script", "style", "svg", "button", "label"):
        # <label> solo aparece como la ayuda oculta de los bloques
        # preformateados (221 en el export real, una por bloque): cromo del
        # editor, nunca obra.
        return ""

    if nombre in ("h1", "h2", "h3", "h4", "h5", "h6"):
        nivel = int(nombre[1])
        return "#" * nivel + " " + _texto_inline(tag).strip()

    if nombre == "p":
        return _texto_inline(tag).strip()

    if nombre == "hr":
        return "---"

    if nombre == "blockquote":
        interior = "\n\n".join(f for f in (_render_bloque(h) for h in tag.find_all(recursive=False)) if f)
        if not interior:
            interior = _texto_inline(tag).strip()
        return "\n".join(f"> {ln}" if ln else ">" for ln in interior.split("\n"))

    if nombre in ("ul", "ol"):
        lineas = []
        for i, li in enumerate(tag.find_all("li", recursive=False), start=1):
            marca = f"{i}." if nombre == "ol" else "-"
            lineas.append(f"{marca} {_texto_inline(li).strip()}")
        return "\n".join(lineas)

    if nombre == "pre":
        texto = tag.get_text("\n")
        # Bloque de codigo vacio: Substack mete su texto de ejemplo y no es
        # contenido de V0ra. Se descarta.
        if PLACEHOLDER_PRE in texto:
            return ""
        return "```\n" + texto.strip("\n") + "\n```"

    if nombre in ("figure", "picture"):
        img = tag.find("img")
        if img is None:
            return ""
        return _render_imagen(img, tag)

    if nombre == "img":
        return _render_imagen(tag, tag.parent)

    if nombre == "div":
        comp = tag.get("data-component-name")
        if comp == "CommentPlaceholder":
            return _render_comentario_incrustado(tag)
        # Contenedor generico: bajar un nivel
        return _render_hijos(tag)

    return _render_hijos(tag)


def _render_imagen(img: Tag, contenedor: Tag) -> str:
    """Las imagenes NO viajan en el zip: son URLs remotas a S3. Se dejan
    como enlace remoto y el backfill (otra fase, explicita) las bajara."""
    src = img.get("src") or ""
    alt = (img.get("alt") or "").strip()
    pie = ""
    if contenedor is not None:
        fc = contenedor.find("figcaption")
        if fc is not None:
            pie = fc.get_text(" ", strip=True)
    salida = f"![{alt}]({src})"
    if pie:
        salida += f"\n*{pie}*"
    return salida


def _render_comentario_incrustado(tag: Tag) -> str:
    """PROVISIONAL, pendiente de politica de V0ra. Un post lleva un
    comentario de otra persona serializado entero en su HTML (cuerpo,
    fecha, restacks, y la identidad: name/user_id/photo_url). Aqui se
    renderiza como cita limpia con la autoria, y se DESCARTA el bloque de
    metadatos del tercero -- que es la opcion menos invasiva mientras no
    haya decision."""
    import json as _json
    import html as _html
    crudo = tag.get("data-attrs") or ""
    try:
        datos = _json.loads(_html.unescape(crudo))
        comentario = datos.get("comment") or {}
        cuerpo = (comentario.get("body") or "").strip()
        autor = (comentario.get("name") or "").strip()
    except (ValueError, AttributeError):
        return ""
    if not cuerpo:
        return ""
    cita = "\n".join(f"> {ln}" if ln else ">" for ln in cuerpo.split("\n"))
    return cita + (f"\n> \n> — {autor}" if autor else "")


def _render_hijos(tag: Tag) -> str:
    bloques = []
    sueltos = []
    for hijo in tag.children:
        if isinstance(hijo, NavigableString):
            t = str(hijo).strip()
            if t:
                sueltos.append(t)
        elif isinstance(hijo, Tag):
            if hijo.name in ("strong", "b", "em", "i", "code", "a", "br", "span"):
                sueltos.append(_render_inline(hijo))
            else:
                if sueltos:
                    bloques.append("".join(sueltos).strip())
                    sueltos = []
                b = _render_bloque(hijo)
                if b:
                    bloques.append(b)
    if sueltos:
        bloques.append("".join(sueltos).strip())
    return "\n\n".join(b for b in bloques if b)


def html_a_markdown(html: str) -> str:
    sopa = BeautifulSoup(html, "html.parser")
    md = _render_hijos(sopa)
    # Normaliza CRLF/CR ANTES de colapsar: el HTML puede traer \r\n y en
    # Windows escribirlo sin normalizar duplica los saltos de linea (misma
    # cicatriz que write_md en el pipeline conversacional).
    md = md.replace("\r\n", "\n").replace("\r", "\n")
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


# ─────────────────────────────────────────
# Notas
# ─────────────────────────────────────────

def clasificar_estado(post: dict, tiene_stats: bool) -> str:
    """publicado / retirado / borrador.

    'retirado' NO esta en el export: se deduce. Un post con is_published a
    false pero CON fecha y estadisticas estuvo publicado y se retiro despues
    (decision de V0ra 2026-07-31: los dos 'Versos EreKtos' son de estos).
    Un borrador de verdad no tiene ni titulo ni fecha ni metricas."""
    if (post.get("is_published") or "").strip().lower() == "true":
        return "published"
    if tiene_stats or (post.get("post_date") or "").strip():
        return "retired"
    return "draft"


def construir_frontmatter(post: dict, stats: dict, estado: str, slug: str,
                          fecha_stats: str, palabras: int, publicacion: str = "") -> str:
    lineas = ["---"]
    titulo = (post.get("title") or "").strip() or slug.replace("-", " ")
    lineas.append(f"title: {yaml_escape(titulo)}")
    fecha = (post.get("post_date") or "")[:10]
    if fecha:
        lineas.append(f"date: {fecha}")
    lineas.append("source: substack_export")
    if publicacion:
        lineas.append(f"publication: {yaml_escape(publicacion)}")
    lineas.append(f"post_id: {yaml_escape(post.get('post_id', '').split('.', 1)[0])}")
    lineas.append(f"slug: {yaml_escape(slug)}")
    lineas.append(f"status: {yaml_escape(estado)}")
    lineas.append(f"type: {yaml_escape(post.get('type'))}")
    if (post.get("subtitle") or "").strip():
        lineas.append(f"subtitle: {yaml_escape(post['subtitle'].strip())}")
    lineas.append(f"word_count: {palabras}")

    # Seccion y tags son obra, no telemetria: van al frontmatter normal.
    if stats:
        seccion = (stats.get("section_name") or "").strip()
        if seccion:
            lineas.append(f"section: {yaml_escape(seccion)}")
        etiquetas = [etiqueta_obsidian(t) for t in (stats.get("tags") or "").split(",")]
        etiquetas = [t for t in etiquetas if t]
        if etiquetas:
            lineas.append("tags:")
            for t in etiquetas:
                lineas.append(f"  - {yaml_escape(t)}")

    # Las metricas SI envejecen: van fechadas o mienten con aplomo.
    if stats:
        lineas.append(f"stats_snapshot: {fecha_stats}")
        for col in METRICAS_INSTANTANEA:
            valor = a_numero(stats.get(col))
            if valor is not None:
                lineas.append(f"{col}: {valor}")

    lineas.append("---")
    return "\n".join(lineas)


def construir_nota(post: dict, stats: dict, cuerpo_md: str, estado: str,
                   slug: str, fecha_stats: str, publicacion: str = "") -> str:
    palabras = len(cuerpo_md.split())
    partes = [construir_frontmatter(post, stats, estado, slug, fecha_stats, palabras, publicacion), ""]

    titulo = (post.get("title") or "").strip() or slug.replace("-", " ")
    partes.append(f"# {titulo}")
    if (post.get("subtitle") or "").strip():
        partes.append(f"*{post['subtitle'].strip()}*")

    if estado == "retired":
        partes.append("> [!warning] Retirado\n> Este post estuvo publicado y se retiro despues.")

    # La perdida se anota en la nota, no en silencio: los podcast del export
    # no traen audio ni enlace (podcast_url viene vacio en los cuatro).
    if (post.get("type") or "").strip().lower() == "podcast":
        partes.append("> [!info] Audio no incluido\n"
                      "> Este post es un episodio y el export de Substack no trae el audio "
                      "ni un enlace a el (`podcast_url` viene vacio).")

    partes.append(cuerpo_md)
    texto = "\n\n".join(p for p in partes if p)
    return re.sub(r"\n{3,}", "\n\n", texto).rstrip() + "\n"


def escribir(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # newline="" y normalizado previo: sin esto, Windows convierte \n en
    # \r\n sobre un texto que ya podia traer \r\n, y salen dobles saltos.
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(contenido.replace("\r\n", "\n").replace("\r", "\n"))


MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _linea(e: dict) -> str:
    """Un post en una lista de indice. El wikilink apunta al nombre del
    fichero sin extension, que es como resuelve Obsidian, y el titulo va
    fuera del enlace porque los nombres llevan fecha y slug: dentro del
    corchete se leerian fatal."""
    marca = " · retirado" if e["estado"] == "retired" else ""
    return f"- [[{e['nombre']}]] — {e['titulo']}{marca}"


def construir_indice(entradas: list, palabras: int) -> str:
    publicados = [e for e in entradas if e["estado"] != "draft"]
    borradores = [e for e in entradas if e["estado"] == "draft"]
    retirados = [e for e in entradas if e["estado"] == "retired"]
    fechas = sorted(e["fecha"] for e in publicados if e["fecha"])

    lineas = ["# Índice — Tintero", ""]
    resumen = f"{len(entradas)} publicaciones · {palabras:,} palabras".replace(",", ".")
    if fechas:
        resumen += f" · del {fechas[0]} al {fechas[-1]}"
    lineas += [resumen, ""]

    secciones = {}
    for e in publicados:
        if e["seccion"]:
            secciones.setdefault(e["seccion"], []).append(e)
    if secciones:
        lineas += [f"## Secciones ({len(secciones)})", "",
                   "Cada una con sus publicaciones en [[_secciones]].", ""]
        for nombre, items in sorted(secciones.items(), key=lambda x: -len(x[1])):
            lineas.append(f"- {nombre}: {len(items)}")
        lineas.append("")

    # Cronologia inversa: lo ultimo primero, que es como se mira un archivo
    # de publicaciones. Sin el CSV de estadisticas esto sigue funcionando
    # igual -- la fecha viene de posts.csv, no de las metricas.
    por_anio = {}
    for e in publicados:
        if e["fecha"]:
            por_anio.setdefault(e["fecha"][:4], {}).setdefault(e["fecha"][5:7], []).append(e)
    for anio in sorted(por_anio, reverse=True):
        total = sum(len(v) for v in por_anio[anio].values())
        lineas += [f"## {anio} ({total})", ""]
        for mes in sorted(por_anio[anio], reverse=True):
            lineas += [f"### {MESES[int(mes)]}", ""]
            for e in sorted(por_anio[anio][mes], key=lambda x: x["fecha"], reverse=True):
                lineas.append(_linea(e))
            lineas.append("")

    if retirados:
        lineas += [f"## Retirados ({len(retirados)})", "",
                   "Estuvieron publicados y se retiraron después. Siguen en su año y mes.", ""]
        lineas += [_linea(e) for e in sorted(retirados, key=lambda x: x["fecha"], reverse=True)]
        lineas.append("")

    if borradores:
        lineas += [f"## Borradores ({len(borradores)})", "",
                   "Nunca publicados: no tienen fecha, por eso viven aparte.", ""]
        lineas += [f"- [[{e['nombre']}]]" for e in sorted(borradores, key=lambda x: x["nombre"])]
        lineas.append("")

    return "\n".join(lineas).rstrip() + "\n"


def construir_indice_secciones(entradas: list) -> str:
    """Solo existe si hay secciones, y las secciones solo vienen del CSV de
    estadisticas. Sin el, este fichero NO se escribe: inventar una seccion
    "sin clasificar" pintaria como dato lo que en realidad es una fuente
    que no se descargo."""
    secciones = {}
    for e in entradas:
        if e["seccion"]:
            secciones.setdefault(e["seccion"], []).append(e)
    if not secciones:
        return ""
    lineas = ["# Secciones — Tintero", "",
              "La taxonomía es de V0ra, no del pipeline: sale de las secciones de su "
              "publicación en Substack.", ""]
    for nombre, items in sorted(secciones.items(), key=lambda x: -len(x[1])):
        lineas += [f"## {nombre} ({len(items)})", ""]
        for e in sorted(items, key=lambda x: x["fecha"], reverse=True):
            lineas.append(_linea(e))
        lineas.append("")
    sin_seccion = [e for e in entradas if not e["seccion"] and e["estado"] != "draft"]
    if sin_seccion:
        lineas += [f"## Sin sección ({len(sin_seccion)})", ""]
        lineas += [_linea(e) for e in sorted(sin_seccion, key=lambda x: x["fecha"], reverse=True)]
        lineas.append("")
    return "\n".join(lineas).rstrip() + "\n"


def construir_vault(export: Path, vault: Path, stats_path=None, dry_run: bool = False,
                    log=print, publicacion=None) -> dict:
    """Nucleo, separado de main() para poder probarlo de punta a punta y
    para que la interfaz web pueda llamarlo sin pasar por argparse.
    Devuelve el resumen; no imprime nada por su cuenta salvo via `log`."""
    fecha_stats = ""
    if stats_path:
        stats_path = Path(stats_path)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", stats_path.name)
        fecha_stats = m.group(1) if m else "desconocida"

    indice_stats = cargar_stats(stats_path)
    if stats_path:
        log(f"[info] estadisticas: {len(indice_stats)} filas ({fecha_stats})")
    else:
        log("[info] sin CSV de estadisticas: las notas iran sin seccion, tags ni metricas")

    with zipfile.ZipFile(export) as zf:
        nombres = zf.namelist()
        if not es_export_substack(nombres):
            raise ValueError("ese zip no tiene la estructura de un export de Substack "
                             "(falta posts.csv o los posts/*.html)")

        publicacion = publicacion or slug_de_publicacion(nombres, export)
        ajenos = contar_csv_de_terceros(nombres)
        log(f"[info] {ajenos} CSV con datos de suscriptores IGNORADOS (no se leen nunca)")

        posts = cargar_posts(zf)
        log(f"[info] {len(posts)} posts en el indice")

        html_por_id = {}
        for n in nombres:
            if n.startswith("posts/") and n.endswith(".html"):
                html_por_id[Path(n).name.split(".")[0]] = n

        cuenta = {"published": 0, "retired": 0, "draft": 0}
        cruzados = 0
        sin_html = []
        entradas = []      # lo que necesitan los indices, recogido de paso
        palabras_total = 0

        for post in posts:
            pid = (post.get("post_id") or "").split(".", 1)[0]
            slug = (post.get("post_id") or "").split(".", 1)[-1]
            nombre_html = html_por_id.get(pid)
            if not nombre_html:
                sin_html.append(pid)
                continue

            clave = (normaliza_titulo(post.get("title")), (post.get("post_date") or "")[:10])
            stats = indice_stats.get(clave, {})
            if stats:
                cruzados += 1

            estado = clasificar_estado(post, bool(stats))
            cuenta[estado] += 1

            cuerpo = html_a_markdown(zf.read(nombre_html).decode("utf-8"))
            nota = construir_nota(post, stats, cuerpo, estado, slug, fecha_stats, publicacion)

            fecha = (post.get("post_date") or "")[:10]
            if estado == "draft" or not fecha:
                # Los borradores de verdad no tienen fecha: por eso van a su
                # propia carpeta y no al arbol año/mes. La decision de V0ra
                # de darles categoria propia disuelve el problema.
                destino = vault / "Borradores" / f"{slugify(slug)}.md"
            else:
                anio, mes = fecha[:4], fecha[5:7]
                destino = vault / "Posts" / anio / mes / f"{fecha}_{slugify(slug)}.md"

            if not dry_run:
                escribir(destino, nota)

            palabras_total += len(cuerpo.split())
            entradas.append({
                "nombre": destino.stem,
                "titulo": (post.get("title") or "").strip() or slug.replace("-", " "),
                "fecha": fecha,
                "estado": estado,
                "seccion": (stats.get("section_name") or "").strip(),
            })

        if not dry_run and entradas:
            escribir(vault / "_indice.md", construir_indice(entradas, palabras_total))
            secciones = construir_indice_secciones(entradas)
            if secciones:
                escribir(vault / "_secciones.md", secciones)
                log("[info] indices: _indice.md y _secciones.md")
            else:
                motivo = "el CSV no trae secciones" if stats_path else "no hay CSV de estadisticas"
                log(f"[info] indice: _indice.md (sin _secciones.md: {motivo})")

    return {
        "posts": len(posts),
        "csv_ignorados": ajenos,
        "notas": len(entradas),
        "palabras": palabras_total,
        "cruzados": cruzados,
        "sin_html": sin_html,
        **cuenta,
    }


def construir_indice_publicaciones(resultados: list) -> str:
    lineas = ["---", 'title: "Publicaciones"', "generado_por: m3m0ria", "---", "", "# Publicaciones", ""]
    for r in sorted(resultados, key=lambda r: r["carpeta"].casefold()):
        res = r["resumen"]
        # Enlace con ruta: todas las carpetas tienen un `_indice.md`, y el nombre
        # a secas seria ambiguo para Obsidian.
        nombre = f"[[{r['carpeta']}/_indice|{r['carpeta']}]]" if res["notas"] else r["carpeta"]
        palabras = f"{res['palabras']:,}".replace(",", ".")
        lineas.append(f"- {nombre} — {res['posts']} posts · {res['published']} publicados · "
                      f"{res['draft']} borradores · {res['retired']} retirados · {palabras} palabras")
    return "\n".join(lineas) + "\n"


def construir_publicaciones(exports_dir: Path, vault: Path, dry_run: bool = False,
                            permitir_legado: bool = False, log=print, stats_forzado=None) -> dict:
    """Construye TODAS las publicaciones de la carpeta de exports.

    Con varias (o si el vault ya esta organizado asi), una carpeta por publicacion. Con
    una sola, el vault sigue plano, como hasta ahora: no se rompe a quien ya lo usa.

    Se NIEGA a construir por carpetas encima de un vault con el layout de un solo
    export: la publicacion de la raiz quedaria duplicada en su carpeta, sin error.
    `permitir_legado` construye igualmente las carpetas nuevas y no toca lo antiguo."""
    exports_dir, vault = Path(exports_dir), Path(vault)
    publicaciones, repetidos = exports_por_publicacion(exports_dir)
    if not publicaciones:
        raise ValueError(f"no se encontro ningun export de Substack en {exports_dir}")
    for z in repetidos:
        log(f"[aviso] {z.name} se ignora: hay otro export mas reciente de la misma publicacion")

    por_carpetas = len(publicaciones) > 1 or (vault / INDICE_PUBLICACIONES).exists()
    if por_carpetas:
        legado = layout_antiguo(vault)
        if legado and not permitir_legado:
            raise LayoutAntiguoError(
                f"el vault ya tiene el layout de un solo export ({', '.join(legado)}) y hay "
                f"{len(publicaciones)} publicaciones. Construir encima dejaria duplicada la que ya esta en "
                "la raiz, sin ningun error. Muevelo a la carpeta de su publicacion con --migrar-legado (o el boton "
                "de Tintero), o usa "
                "--permitir-legado para construir las carpetas nuevas sin tocar lo antiguo.")
    if stats_forzado and len(publicaciones) > 1:
        raise ValueError("--stats solo vale con una publicacion; con varias, cada una busca su CSV "
                         "(<slug>_email_stats_AAAA-MM-DD.csv) en la carpeta de exports")

    resultados = []
    for slug, z in publicaciones.items():
        carpeta = nombre_de_carpeta(vault, slug, z) if por_carpetas else ""
        stats = Path(stats_forzado) if stats_forzado else \
            localizar_stats(exports_dir, slug, unica=len(publicaciones) == 1)
        log(f"[publicacion] {slug}: {z.name}" + (f" -> {carpeta}/" if carpeta else "")
            + (f" · estadisticas: {stats.name}" if stats else " · sin CSV de estadisticas"))
        resumen = construir_vault(z, vault / carpeta if carpeta else vault, stats,
                                  dry_run=dry_run, log=log, publicacion=slug)
        resultados.append({"slug": slug, "carpeta": carpeta, "export": z.name,
                           "stats": stats.name if stats else None, "resumen": resumen})

    if por_carpetas and not dry_run:
        escribir(vault / INDICE_PUBLICACIONES, construir_indice_publicaciones(resultados))
        log(f"[info] indice de publicaciones: {INDICE_PUBLICACIONES}")
    return {"modo": "carpetas" if por_carpetas else "plano", "publicaciones": resultados,
            "ignorados": [z.name for z in repetidos]}


class MigracionError(ValueError):
    """No se puede migrar con seguridad; el mensaje dice por que y que hacer."""


_ID_RX = re.compile(r'^post_id:\s*"?([^"\s]+)"?\s*$', re.M)
_CARPETAS_DE_NOTAS = ("Posts", "Borradores", "Drafts")


def _censo(ruta: Path):
    """(numero de ficheros, bytes) de un fichero o de todo lo que cuelga de una carpeta."""
    if ruta.is_file():
        return 1, ruta.stat().st_size
    ficheros = [p for p in ruta.rglob("*") if p.is_file()]
    return len(ficheros), sum(p.stat().st_size for p in ficheros)


def _ids_de_notas_antiguas(vault: Path) -> list:
    """El `post_id` de cada nota de Posts/Borradores/Drafts (None si no lo trae)."""
    ids = []
    for carpeta in _CARPETAS_DE_NOTAS:
        base = Path(vault) / carpeta
        if not base.is_dir():
            continue
        for nota in sorted(base.rglob("*.md")):
            try:
                cabecera = nota.read_text(encoding="utf-8", errors="ignore")[:2000]
            except OSError:
                cabecera = ""
            m = _ID_RX.search(cabecera)
            ids.append(m.group(1) if m else None)
    return ids


def migrar_layout_antiguo(exports_dir: Path, vault: Path, aplicar: bool = False,
                          publicacion=None, log=print) -> dict:
    """Mueve el layout de un solo export (Posts/, Borradores/, Drafts/, _indice.md,
    _secciones.md en la RAIZ del vault) a la carpeta de su publicacion.

    La publicacion no se adivina: cada nota lleva `post_id` y se cruza con el posts.csv de
    cada export. Si no hay una respuesta clara, se niega y pide `publicacion`. No borra nada
    (es un renombrado dentro del mismo vault), no pisa una carpeta que ya existe, comprueba
    ficheros y bytes antes y despues y, si algo falla a mitad, deshace lo movido.

    Sin `aplicar` solo devuelve el plan."""
    exports_dir, vault = Path(exports_dir), Path(vault)
    presentes = layout_antiguo(vault)
    if not presentes:
        raise MigracionError("no hay nada que migrar: la raiz del vault no tiene el layout de un solo export.")
    pubs, _ = exports_por_publicacion(exports_dir)
    if not pubs:
        raise MigracionError(f"no hay ningun export de Substack en {exports_dir}: sin el no se puede saber "
                             "a que publicacion pertenece lo antiguo.")

    notas = _ids_de_notas_antiguas(vault)
    ids = {i for i in notas if i}
    ids_de = {}
    for slug, z in pubs.items():
        with zipfile.ZipFile(z) as zf:
            ids_de[slug] = {(p.get("post_id") or "").split(".", 1)[0] for p in cargar_posts(zf)}
    coinciden = {slug: len(ids & s) for slug, s in ids_de.items()}
    opciones = ", ".join(sorted(pubs))

    if publicacion:
        slug = publicacion.strip().lower()
        if slug not in pubs:
            raise MigracionError(f"la publicacion '{publicacion}' no esta entre los exports ({opciones}).")
    else:
        if not ids:
            raise MigracionError("las notas antiguas no traen post_id: no puedo saber a que publicacion pertenecen. "
                                 f"Indicala con --publicacion <slug> ({opciones}).")
        orden = sorted(coinciden.items(), key=lambda kv: (-kv[1], kv[0]))
        slug, mejor = orden[0]
        segundo = orden[1][1] if len(orden) > 1 else 0
        if mejor == 0 or mejor <= 2 * segundo or mejor * 2 < len(ids):
            detalle = ", ".join(f"{s}: {n}" for s, n in orden)
            raise MigracionError("no queda claro a que publicacion pertenece lo antiguo (ids que coinciden con cada "
                                 f"export -> {detalle}). Indicala con --publicacion <slug> ({opciones}).")

    carpeta = nombre_de_carpeta(vault, slug, pubs[slug])
    movimientos = [(n, f"{carpeta}/{n}") for n in presentes]
    choques = [d for _o, d in movimientos if (vault / d).exists()]
    if choques:
        raise MigracionError(f"ya existe {', '.join(choques)}: no piso nada. Si ya construiste esa carpeta, lo "
                             "antiguo y lo nuevo conviven; muevelo o borralo tu a mano.")

    resumen = {"publicacion": slug, "carpeta": carpeta, "movimientos": movimientos, "aplicado": False,
               "notas": len(notas), "ids_coinciden": len(ids & ids_de[slug]),
               "ids_ausentes": len(ids - ids_de[slug])}
    log(f"[migracion] lo antiguo pertenece a '{slug}' ({resumen['ids_coinciden']} de {len(ids)} post_id coinciden "
        f"con su export) -> {carpeta}/")
    for origen, destino in movimientos:
        n, b = _censo(vault / origen)
        log(f"[migracion]   {origen}  ->  {destino}  ({n} ficheros, {b} bytes)")
    if resumen["ids_ausentes"]:
        log(f"[aviso] {resumen['ids_ausentes']} post(s) antiguos ya no estan en el export: se mueven igualmente, no se pierden")
    if not aplicar:
        log("[migracion] Solo es el plan: no se ha movido nada. Para hacerlo, repite con --aplicar.")
        return resumen

    antes = {o: _censo(vault / o) for o, _d in movimientos}
    creada = not (vault / carpeta).exists()
    hechos = []
    try:
        (vault / carpeta).mkdir(parents=True, exist_ok=True)
        for origen, destino in movimientos:
            os.replace(vault / origen, vault / destino)
            hechos.append((origen, destino))
    except OSError as e:
        for origen, destino in reversed(hechos):
            os.replace(vault / destino, vault / origen)
        if creada and (vault / carpeta).is_dir() and not any((vault / carpeta).iterdir()):
            (vault / carpeta).rmdir()
        raise MigracionError(f"no se pudo mover ({e}). Se ha deshecho lo movido: el vault esta como estaba. "
                             "Si Obsidian tiene el vault abierto, cierralo y repite.") from e
    for origen, destino in movimientos:
        if _censo(vault / destino) != antes[origen] or (vault / origen).exists():
            raise MigracionError(f"la comprobacion ha fallado en {destino}: no coincide con lo que habia en {origen}.")
    resumen["aplicado"] = True
    log(f"[ok] migrado: {len(movimientos)} elementos movidos a {carpeta}/ y comprobados (ficheros y bytes iguales).")
    return resumen


def main():
    ap = argparse.ArgumentParser(
        description="Construye el vault de Tintero/Inkwell desde un export de Substack.")
    origen = ap.add_mutually_exclusive_group(required=True)
    origen.add_argument("--export", help="Ruta al .zip del export de Substack")
    origen.add_argument("--exports-dir", help="Carpeta donde buscar los exports (detecta por estructura); "
                                              "construye TODAS las publicaciones que haya")
    ap.add_argument("--vault-dir", required=True, help="Carpeta de salida del vault de Obsidian")
    ap.add_argument("--stats", help="CSV de estadisticas descargado del panel (opcional)")
    ap.add_argument("--dry-run", action="store_true", help="No escribe nada, solo informa")
    ap.add_argument("--permitir-legado", action="store_true",
                    help="Con --exports-dir: construir las carpetas por publicacion aunque la raiz del vault "
                         "tenga el layout de un solo export. No toca lo antiguo (y esa publicacion quedara "
                         "duplicada hasta que lo muevas o lo borres tu).")
    ap.add_argument("--migrar-legado", action="store_true",
                    help="Con --exports-dir: mueve el layout de un solo export (Posts/, Borradores/, Drafts/, "
                         "_indice.md, _secciones.md en la raiz del vault) a la carpeta de su publicacion. "
                         "Sin --aplicar solo ensena el plan. No borra nada.")
    ap.add_argument("--aplicar", action="store_true", help="Con --migrar-legado: hacer el movimiento de verdad")
    ap.add_argument("--publicacion", help="Con --migrar-legado: slug de la publicacion a la que pertenece lo "
                                          "antiguo (solo si no se puede deducir de los post_id)")
    args = ap.parse_args()
    vault = Path(args.vault_dir)

    if args.migrar_legado:
        if not args.exports_dir:
            print("[error] --migrar-legado necesita --exports-dir (los exports dicen a que publicacion pertenece lo antiguo)")
            sys.exit(1)
        try:
            migrar_layout_antiguo(Path(args.exports_dir), vault, aplicar=args.aplicar,
                                  publicacion=args.publicacion)
        except ValueError as e:      # incluye MigracionError
            print(f"[error] {e}")
            sys.exit(1)
        return

    if args.exports_dir:
        try:
            r = construir_publicaciones(Path(args.exports_dir), vault, dry_run=args.dry_run,
                                        permitir_legado=args.permitir_legado, stats_forzado=args.stats)
        except ValueError as e:      # incluye LayoutAntiguoError
            print(f"[error] {e}")
            sys.exit(1)
        for p in r["publicaciones"]:
            s = p["resumen"]
            print(f"[info] {p['carpeta'] or p['slug']}: publicados {s['published']} | retirados {s['retired']} "
                  f"| borradores {s['draft']} | cruzados {s['cruzados']}/{s['posts']}")
            if s["sin_html"]:
                print(f"[aviso] {p['slug']}: {len(s['sin_html'])} post(s) del indice sin HTML en el zip: {s['sin_html'][:5]}")
        print("[info] --dry-run: no se ha escrito nada" if args.dry_run else f"[ok] vault construido en {vault}")
        return

    export = Path(args.export)
    if not export.exists():
        print(f"[error] no existe {export}")
        sys.exit(1)

    try:
        r = construir_vault(export, vault, args.stats, dry_run=args.dry_run)
    except ValueError as e:
        print(f"[error] {e}")
        sys.exit(1)

    print(f"[info] publicados: {r['published']} | retirados: {r['retired']} "
          f"| borradores: {r['draft']}")
    print(f"[info] cruzados con estadisticas: {r['cruzados']}/{r['posts']}")
    if r["sin_html"]:
        print(f"[aviso] {len(r['sin_html'])} post(s) del indice sin HTML en el zip: {r['sin_html'][:5]}")
    if args.dry_run:
        print("[info] --dry-run: no se ha escrito nada")
    else:
        print(f"[ok] vault construido en {vault}")


if __name__ == "__main__":
    main()
