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


def _localizar(exports_dir) -> Path:
    if not exports_dir:
        return None
    d = Path(exports_dir)
    if not d.is_dir():
        return None
    return bsv.localizar_export(d)


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


# Memo en proceso, invalidado por (ruta, mtime, tamaño) del zip.
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
_memo = {}


def compute_substack_stats(exports_dir) -> dict:
    """Tarjeta del Observatorio: posts, palabras, publicados y borradores.

    Los cuatro salen del ZIP a proposito (decision de V0ra 2026-07-31), no
    del CSV de estadisticas: asi la tarjeta esta siempre completa aunque no
    se haya descargado el CSV. Pintar a cero lo que no se sabe seria mentir
    -- misma regla que en la tarjeta de musica.

    Devuelve {} si no hay export: la tarjeta entonces no se pinta.
    """
    export = _localizar(exports_dir)
    if export is None:
        return {}
    try:
        st = export.stat()
        firma = (str(export), st.st_mtime, st.st_size)
        if _memo.get("firma") == firma:
            return _memo["datos"]
        with zipfile.ZipFile(export) as zf:
            posts = bsv.cargar_posts(zf)
            cuenta, _ = _recuento_por_estado(posts, {})
            palabras = 0
            for n in zf.namelist():
                if n.startswith("posts/") and n.endswith(".html"):
                    palabras += len(bsv.html_a_markdown(zf.read(n).decode("utf-8")).split())
    except (zipfile.BadZipFile, OSError, KeyError):
        return {}
    datos = {
        "export": export.name,
        "posts": len(posts),
        "palabras": palabras,
        "publicados": cuenta["published"],
        "borradores": cuenta["draft"],
        "retirados": cuenta["retired"],
    }
    _memo["firma"], _memo["datos"] = firma, datos
    return datos


def verificar_export(exports_dir, stats_csv=None) -> dict:
    """Payload de la tarjeta de verificacion: que hay, que cruza, que se
    ignora y que NO viene en el export.

    Lo ultimo es deliberado y fue decision de V0ra: es informacion que solo
    se puede dar aqui. Una vez construido el vault, lo que falta no se ve
    por ninguna parte, y alguien lo descubriria dentro de un año creyendo
    que lo perdio la herramienta.
    """
    export = _localizar(exports_dir)
    if export is None:
        return {"encontrado": False}

    stats_path = Path(stats_csv) if stats_csv else None
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
    if indice:
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
        "encontrado": True,
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
