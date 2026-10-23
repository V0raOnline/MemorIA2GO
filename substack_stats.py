#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
substack_stats.py — Cifras de Tintero para el Observatorio y para la tarjeta
de verificacion de su pestaña.

LEE DEL EXPORT, NUNCA DEL VAULT CONSTRUIDO. Misma decision que
suno_stats.py y por el mismo motivo: el zip es la fuente de verdad y tiene
que poder mirarse justo despues de descargarlo, ANTES de construir nada.
Si dependiera del vault, la tarjeta estaria vacia exactamente en el momento
en que mas quieres verla.

Calculado EN VIVO, fuera del cache de vault_stats: ese cache lo escribe el
paso 4 del pipeline conversacional, y el export de Substack aparece en la
carpeta por su cuenta, en otro momento. Cachearlo ahi lo dejaria rancio.
Medido sobre el export real de V0ra (109 posts): 0,29 s convirtiendo los
109 HTML con el conversor de verdad. Se usa el conversor real y no un
recuento aproximado con regex (que seria 15 veces mas rapido pero se
desvia un 0,8%) porque la cifra tiene que cuadrar con la suma de los
`word_count` de las notas; si no, alguien perdera una tarde buscando por
que no cuadran.
"""

import csv
import io
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "substack"))

import build_substack_vault as bsv  # noqa: E402


def _publicaciones(exports_dir):
    """({slug: zip}, [zips repetidos]) de la carpeta de exports; vacio si no hay carpeta."""
    if not exports_dir:
        return {}, []
    d = Path(exports_dir)
    if not d.is_dir():
        return {}, []
    return bsv.exports_por_publicacion(d)


def _recuento_por_estado(posts: list, indice_stats: dict) -> dict:
    cuenta = {"published": 0, "retired": 0, "draft": 0}
    cruzados = 0
    for p in posts:
        clave = (bsv.normaliza_titulo(p.get("title")), (p.get("post_date") or "")[:10])
        tiene = clave in indice_stats
        if tiene:
            cruzados += 1
        cuenta[bsv.clasificar_estado(p, tiene)] += 1
    return cuenta, cruzados


# Memo en proceso, invalidado por (ruta, mtime, tamaño) de cada zip.
#
# Sin esto, la tarjeta cuesta ~1,2 s POR CARGA del dashboard: convertir los
# 109 HTML para contar palabras es lo caro. Y el dashboard de esta app tiene
# la propiedad, ganada a pulso con el cache del paso 4, de cargar instantaneo
# a cualquier escala -- no se puede romper por una tarjeta.
#
# Memo en memoria y no fichero de cache a proposito: el proceso de Flask es
# largo, asi que la primera carga paga y las demas van gratis, y la
# invalidacion es trivialmente correcta (si el zip cambia, cambia mtime o
# tamaño). Un segundo cache en disco significaria una segunda invalidacion
# que mantener, que es justo donde se cuelan los errores que no avisan.
# Una entrada por zip: con varias publicaciones, cambiar una no invalida las otras.
_memo = {}


def _cifras_de(slug: str, export: Path):
    """Las cifras de UNA publicacion, o None si el zip no se puede leer."""
    try:
        st = export.stat()
        firma = (str(export), st.st_mtime, st.st_size)
        if firma in _memo:
            return _memo[firma]
        with zipfile.ZipFile(export) as zf:
            posts = bsv.cargar_posts(zf)
            cuenta, _ = _recuento_por_estado(posts, {})
            palabras = 0
            for n in zf.namelist():
                if n.startswith("posts/") and n.endswith(".html"):
                    palabras += len(bsv.html_a_markdown(zf.read(n).decode("utf-8")).split())
    except (zipfile.BadZipFile, OSError, KeyError):
        return None
    datos = {
        "publicacion": bsv.nombre_visible(slug, export),
        "export": export.name,
        "posts": len(posts),
        "palabras": palabras,
        "publicados": cuenta["published"],
        "borradores": cuenta["draft"],
        "retirados": cuenta["retired"],
    }
    _memo[firma] = datos
    return datos


def compute_substack_stats(exports_dir) -> dict:
    """Tarjeta del Observatorio: posts, palabras, publicados y borradores.

    Los cuatro salen del ZIP a proposito (decision de V0ra 2026-07-31), no
    del CSV de estadisticas: asi la tarjeta esta siempre completa aunque no
    se haya descargado el CSV. Pintar a cero lo que no se sabe seria mentir
    -- misma regla que en la tarjeta de musica.

    Con varias publicaciones (un zip cada una) las cifras son la SUMA, y cada una
    viaja aparte en `publicaciones`. Hasta el 2026-10-20 solo se contaba el zip mas
    reciente, y las otras publicaciones no existian para la tarjeta.

    Devuelve {} si no hay export: la tarjeta entonces no se pinta.
    """
    pubs, _ = _publicaciones(exports_dir)
    lista = [d for d in (_cifras_de(slug, z) for slug, z in pubs.items()) if d]
    if not lista:
        return {}
    return {
        "export": lista[0]["export"] if len(lista) == 1 else f"{len(lista)} publications",
        "posts": sum(d["posts"] for d in lista),
        "palabras": sum(d["palabras"] for d in lista),
        "publicados": sum(d["publicados"] for d in lista),
        "borradores": sum(d["borradores"] for d in lista),
        "retirados": sum(d["retirados"] for d in lista),
        "publicaciones": sorted(lista, key=lambda d: d["publicacion"].casefold()),
    }


def _verificar_una(slug: str, export: Path, stats_path, nombre: str) -> dict:
    """Payload de UNA publicacion: que hay, que cruza, que se ignora y que NO viene."""
    indice = bsv.cargar_stats(stats_path) if stats_path else {}

    with zipfile.ZipFile(export) as zf:
        nombres = zf.namelist()
        posts = bsv.cargar_posts(zf)
        cuenta, cruzados = _recuento_por_estado(posts, indice)
        # Las imagenes NO viajan en el zip: solo su URL remota. Se cuentan
        # sobre el HTML crudo porque es un recuento, no una conversion.
        imagenes = sum(len(re.findall(r"<img[^>]+src=", zf.read(n).decode("utf-8")))
                       for n in nombres if n.startswith("posts/") and n.endswith(".html"))

    podcasts = sum(1 for p in posts
                   if (p.get("type") or "").strip().lower() == "podcast"
                   and not (p.get("podcast_url") or "").strip())

    ausencias = {"imagenes": imagenes, "podcasts_sin_audio": podcasts}
    # Cuantos comentarios existieron solo se puede saber por el CSV. Sin el,
    # la clave NO viaja: decir "0 comentarios" seria afirmar algo que no
    # sabemos, y es justo el error que este repo ya ha cazado dos veces.
    #
    # Tampoco si el CSV no tiene la columna `comments` (hay un esquema reducido): sin la
    # columna no se sabe cuantos hubo, y contarlos daria 0.
    if indice and any("comments" in f for f in indice.values()):
        con_com = [f for f in indice.values() if (bsv.a_numero(f.get("comments")) or 0) > 0]
        ausencias["comentarios"] = sum(int(bsv.a_numero(f.get("comments")) or 0) for f in con_com)
        ausencias["posts_con_comentarios"] = len(con_com)

    bloque_stats = None
    if stats_path and stats_path.exists():
        secciones = {(f.get("section_name") or "").strip() for f in indice.values()}
        secciones.discard("")
        bloque_stats = {
            "nombre": stats_path.name,
            "filas": len(indice),
            "cruzan": cruzados,
            "secciones": len(secciones),
            "con_tags": sum(1 for f in indice.values() if (f.get("tags") or "").strip()),
        }

    return {
        "slug": slug,
        "publicacion": nombre,
        "export": {
            "nombre": export.name,
            "posts": len(posts),
            "publicados": cuenta["published"],
            "retirados": cuenta["retired"],
            "borradores": cuenta["draft"],
        },
        "stats": bloque_stats,
        "csv_de_terceros": bsv.contar_csv_de_terceros(nombres),
        "ausencias": ausencias,
    }


def verificar_export(exports_dir, stats_csv=None, vault=None) -> dict:
    """Payload de la tarjeta de verificacion: una entrada por publicacion con que hay,
    que cruza, que se ignora y que NO viene en el export, mas los `avisos` que conviene
    ver ANTES de construir (zips repetidos, layout antiguo en el vault).

    Lo de lo que NO viene es deliberado y fue decision de V0ra: es informacion que solo
    se puede dar aqui. Una vez construido el vault, lo que falta no se ve
    por ninguna parte, y alguien lo descubriria dentro de un año creyendo
    que lo perdio la herramienta.

    `stats_csv` fuerza el CSV solo si hay una unica publicacion; con varias, cada una
    busca el suyo por el slug. `vault` (opcional) permite avisar del layout antiguo.
    """
    pubs, repetidos = _publicaciones(exports_dir)
    if not pubs:
        return {"encontrado": False}

    unica = len(pubs) == 1
    bloques = []
    for slug, z in pubs.items():
        sp = Path(stats_csv) if (stats_csv and unica) else bsv.localizar_stats(Path(exports_dir), slug, unica)
        nombre = bsv.nombre_de_carpeta(vault, slug, z) if vault else bsv.nombre_visible(slug, z)
        bloques.append(_verificar_una(slug, z, sp, nombre))

    avisos = [{"tipo": "repetido",
               "texto": f"{z.name}: there is a newer export of the same publication; it is ignored."}
              for z in repetidos]
    if vault:
        v = Path(vault)
        legado = bsv.layout_antiguo(v)
        if legado and (not unica or bsv.ya_por_publicaciones(v)):
            avisos.append({"tipo": "layout_antiguo",
                           "texto": f"The Inkwell vault has the single-export layout ({', '.join(legado)}) "
                                    f"and there are {len(pubs)} publications. Building will refuse until you move it "
                                    "to its own folder (Tools \u2192 Workshop \u2192 \u201cMove Inkwell's old layout\u201d): "
                                    "it would leave that publication duplicated."})
    return {"encontrado": True, "publicaciones": bloques, "avisos": avisos}
