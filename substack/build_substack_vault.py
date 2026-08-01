#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_substack_vault.py — Convierte el export de Substack (zip) en un vault
de Obsidian independiente. Es el motor de Inkwell / Tintero.

USO:
    python build_substack_vault.py --export ruta/al/export.zip --vault-dir ./inkwell_vault
    python build_substack_vault.py --exports-dir ./exports --vault-dir ./inkwell_vault

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
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

try:
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError:
    print("[error] missing beautifulsoup4 (pip install -r requirements.txt)")
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


def slugify(texto: str, fallback: str = "untitled") -> str:
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
                          fecha_stats: str, palabras: int) -> str:
    lineas = ["---"]
    titulo = (post.get("title") or "").strip() or slug.replace("-", " ")
    lineas.append(f"title: {yaml_escape(titulo)}")
    fecha = (post.get("post_date") or "")[:10]
    if fecha:
        lineas.append(f"date: {fecha}")
    lineas.append("source: substack_export")
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
                   slug: str, fecha_stats: str) -> str:
    palabras = len(cuerpo_md.split())
    partes = [construir_frontmatter(post, stats, estado, slug, fecha_stats, palabras), ""]

    titulo = (post.get("title") or "").strip() or slug.replace("-", " ")
    partes.append(f"# {titulo}")
    if (post.get("subtitle") or "").strip():
        partes.append(f"*{post['subtitle'].strip()}*")

    if estado == "retired":
        partes.append("> [!warning] Retired\n> This post was published and later taken down.")

    # La perdida se anota en la nota, no en silencio: los podcast del export
    # no traen audio ni enlace (podcast_url viene vacio en los cuatro).
    if (post.get("type") or "").strip().lower() == "podcast":
        partes.append("> [!info] Audio not included\n"
                      "> This post is an episode and the Substack export carries neither the "
                      "audio nor a link to it (`podcast_url` comes back empty).")

    partes.append(cuerpo_md)
    texto = "\n\n".join(p for p in partes if p)
    return re.sub(r"\n{3,}", "\n\n", texto).rstrip() + "\n"


def escribir(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # newline="" y normalizado previo: sin esto, Windows convierte \n en
    # \r\n sobre un texto que ya podia traer \r\n, y salen dobles saltos.
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(contenido.replace("\r\n", "\n").replace("\r", "\n"))


MESES = ["", "January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"]


def _linea(e: dict) -> str:
    """Un post en una lista de indice. El wikilink apunta al nombre del
    fichero sin extension, que es como resuelve Obsidian, y el titulo va
    fuera del enlace porque los nombres llevan fecha y slug: dentro del
    corchete se leerian fatal."""
    marca = " · retired" if e["estado"] == "retired" else ""
    return f"- [[{e['nombre']}]] — {e['titulo']}{marca}"


def construir_indice(entradas: list, palabras: int) -> str:
    publicados = [e for e in entradas if e["estado"] != "draft"]
    borradores = [e for e in entradas if e["estado"] == "draft"]
    retirados = [e for e in entradas if e["estado"] == "retired"]
    fechas = sorted(e["fecha"] for e in publicados if e["fecha"])

    lineas = ["# Index — Inkwell", ""]
    resumen = f"{len(entradas)} publications · {palabras:,} words"
    if fechas:
        resumen += f" · from {fechas[0]} to {fechas[-1]}"
    lineas += [resumen, ""]

    secciones = {}
    for e in publicados:
        if e["seccion"]:
            secciones.setdefault(e["seccion"], []).append(e)
    if secciones:
        lineas += [f"## Sections ({len(secciones)})", "",
                   "Each one with its publications in [[_sections]].", ""]
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
        lineas += [f"## Retired ({len(retirados)})", "",
                   "These were published and later taken down. They stay in their year and month.", ""]
        lineas += [_linea(e) for e in sorted(retirados, key=lambda x: x["fecha"], reverse=True)]
        lineas.append("")

    if borradores:
        lineas += [f"## Drafts ({len(borradores)})", "",
                   "Never published: they have no date, which is why they live apart.", ""]
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
    lineas = ["# Sections — Inkwell", "",
              "The taxonomy is V0ra's, not the pipeline's: it comes from the sections of "
              "her Substack publication.", ""]
    for nombre, items in sorted(secciones.items(), key=lambda x: -len(x[1])):
        lineas += [f"## {nombre} ({len(items)})", ""]
        for e in sorted(items, key=lambda x: x["fecha"], reverse=True):
            lineas.append(_linea(e))
        lineas.append("")
    sin_seccion = [e for e in entradas if not e["seccion"] and e["estado"] != "draft"]
    if sin_seccion:
        lineas += [f"## No section ({len(sin_seccion)})", ""]
        lineas += [_linea(e) for e in sorted(sin_seccion, key=lambda x: x["fecha"], reverse=True)]
        lineas.append("")
    return "\n".join(lineas).rstrip() + "\n"


def construir_vault(export: Path, vault: Path, stats_path=None, dry_run: bool = False,
                    log=print) -> dict:
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
        log(f"[info] stats: {len(indice_stats)} rows ({fecha_stats})")
    else:
        log("[info] no stats CSV: notes will have no section, tags or metrics")

    with zipfile.ZipFile(export) as zf:
        nombres = zf.namelist()
        if not es_export_substack(nombres):
            raise ValueError("that ZIP does not have the structure of a Substack export "
                             "(missing posts.csv or the posts/*.html)")

        ajenos = contar_csv_de_terceros(nombres)
        log(f"[info] {ajenos} CSV file(s) with subscriber data IGNORED (never read)")

        posts = cargar_posts(zf)
        log(f"[info] {len(posts)} posts in the index")

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
            nota = construir_nota(post, stats, cuerpo, estado, slug, fecha_stats)

            fecha = (post.get("post_date") or "")[:10]
            if estado == "draft" or not fecha:
                # Los borradores de verdad no tienen fecha: por eso van a su
                # propia carpeta y no al arbol año/mes. La decision de V0ra
                # de darles categoria propia disuelve el problema.
                destino = vault / "Drafts" / f"{slugify(slug)}.md"
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
            escribir(vault / "_index.md", construir_indice(entradas, palabras_total))
            secciones = construir_indice_secciones(entradas)
            if secciones:
                escribir(vault / "_sections.md", secciones)
                log("[info] indexes: _index.md and _sections.md")
            else:
                log("[info] index: _index.md (no _sections.md: there is no stats CSV)")

    return {
        "posts": len(posts),
        "csv_ignorados": ajenos,
        "cruzados": cruzados,
        "sin_html": sin_html,
        **cuenta,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Builds the Inkwell/Tintero vault from a Substack export.")
    origen = ap.add_mutually_exclusive_group(required=True)
    origen.add_argument("--export", help="Path to the Substack export .zip")
    origen.add_argument("--exports-dir", help="Folder to search for the export (detected by structure)")
    ap.add_argument("--vault-dir", required=True, help="Output folder for the Obsidian vault")
    ap.add_argument("--stats", help="Stats CSV downloaded from the dashboard (optional)")
    ap.add_argument("--dry-run", action="store_true", help="Writes nothing, only reports")
    args = ap.parse_args()

    if args.export:
        export = Path(args.export)
    else:
        export = localizar_export(Path(args.exports_dir))
        if export is None:
            print(f"[error] no Substack export found in {args.exports_dir}")
            sys.exit(1)
        print(f"[info] export detected: {export.name}")

    if not export.exists():
        print(f"[error] {export} does not exist")
        sys.exit(1)

    vault = Path(args.vault_dir)

    try:
        r = construir_vault(export, vault, args.stats, dry_run=args.dry_run)
    except ValueError as e:
        print(f"[error] {e}")
        sys.exit(1)

    print(f"[info] published: {r['published']} | retired: {r['retired']} "
          f"| drafts: {r['draft']}")
    print(f"[info] matched with stats: {r['cruzados']}/{r['posts']}")
    if r["sin_html"]:
        print(f"[warn] {len(r['sin_html'])} post(s) in the index with no HTML in the ZIP: {r['sin_html'][:5]}")
    if args.dry_run:
        print("[info] --dry-run: nothing was written")
    else:
        print(f"[ok] vault built at {vault}")


if __name__ == "__main__":
    main()
