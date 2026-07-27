#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chatgpt_markers.py — Resuelve los marcadores internos de ChatGPT (PUA) que
hasta ahora se colaban en crudo dentro de las notas.

ChatGPT delimita sus widgets internos con caracteres de area de uso privado
(Private Use Area) que ningun cliente de markdown entiende:

    U+E200  abre        U+E202  separa campos        U+E201  cierra

Ejemplo real tal como aparecia en una nota:

    ...39,90 EUR / anio (pack completo) citeturn0search12

Investigacion 2026-07-27 contra los 47 exports reales de V0ra: 613 notas
afectadas, 8310 marcadores, 26 tipos distintos (cite 2902, filecite 2681,
entity 1870, image_group 493...). Los datos SI viajan en el export, en
`message.metadata.content_references` -- el parser simplemente nunca los
miraba.

TRAMPA IMPORTANTE (deriva de formato confirmada entre exports):
    campo            export 2025-11    export 2026-07
    matched_text        100%              0%
    start_idx/end_idx   100%              0%
Un resolutor apoyado en `matched_text` (lo obvio) funcionaria con los
exports viejos y fallaria EN SILENCIO con los nuevos. Por eso aqui el
emparejamiento se hace por identificador (`turn0search12` ->
{turn_index:0, ref_type:"search", ref_index:12}), que existe en ambos
formatos, con dos respaldos posicionales para los marcadores que no llevan
identificador. Ver CONTEXT.md, seccion de marcadores PUA.

Contrato de diseno (cerrado con V0ra 2026-07-27):
- Nunca se deja pasar un marcador crudo. Si no se puede recuperar nada, se
  escribe un aviso honesto en la nota en vez de esconderlo.
- Las imagenes de busqueda web NO se descargan: se registran como
  pendientes para que V0ra decida (mismo principio que Grok Imagine).
- El estado de triaje (rescatada/descartada) vive FUERA de la nota, porque
  las notas se regeneran en cada reproceso.
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

# ---------- Anatomia del marcador ----------

MARK_OPEN = ""
MARK_SEP = ""
MARK_CLOSE = ""

MARKER_RE = re.compile(f"{MARK_OPEN}(.*?){MARK_CLOSE}", re.DOTALL)

# "turn0search12" -> (0, "search", 12). El tipo va en medio y es alfabetico,
# los dos numeros son el turno y el indice dentro del turno.
REF_ID_RE = re.compile(r"^turn(\d+)([a-z_]+)(\d+)$")

# Marcadores PUA sueltos que pueden quedar fuera de un par abre/cierra
# (vistos en notas reales: U+E203, U+E204, U+E206 sin pareja). Se limpian
# al final para no dejar basura invisible en la nota.
STRAY_PUA_RE = re.compile(r"[-]")

# ---------- Clasificacion de tipos (medida contra datos reales) ----------

# Citan una fuente externa: se resuelven a enlace markdown real.
LINK_TYPES = frozenset({"cite", "link", "url", "link_title", "navlist"})

# Citan un fichero que el usuario subio a la conversacion.
FILE_TYPES = frozenset({"filecite"})

# Muestran imagenes de busqueda web (terceros, no generadas ni subidas).
IMAGE_TYPES = frozenset({"image_group", "image_v2", "i"})

# Widgets con texto legible recuperable desde `alt`.
TEXT_TYPES = frozenset({
    "entity", "entity_group", "entity_metadata", "products", "product",
    "product_entity", "product0", "video", "movie", "tv_show", "video_game",
    "businesses_map", "explore_more", "forecast", "genui", "memcite", "map",
})


def parse_ref_id(raw: str) -> Optional[Tuple[int, str, int]]:
    """'turn0search12' -> (0, 'search', 12). None si no tiene esa forma."""
    m = REF_ID_RE.match((raw or "").strip())
    if not m:
        return None
    return int(m.group(1)), m.group(2), int(m.group(3))


def split_marker(body: str) -> Tuple[str, List[str]]:
    """Separa el cuerpo del marcador en (tipo, campos restantes)."""
    partes = body.split(MARK_SEP)
    return partes[0].strip(), [p for p in partes[1:]]


def build_ref_lookup(refs: List[dict]) -> Dict[Tuple[int, str, int], dict]:
    """Indexa content_references por el identificador que usan los
    marcadores. Dos caminos, porque el export no es homogeneo:

    1. Refs con `items[].refs[]` (grouped_webpages y similares): cada item
       declara explicitamente que identificadores cubre. Es el camino fiable.
    2. Refs sin esa lista (file, image_group...): el `ref_index` del
       marcador se interpreta como la posicion dentro de las refs de ese
       mismo tipo, que es como las numera ChatGPT.
    """
    lookup: Dict[Tuple[int, str, int], dict] = {}

    # Camino 1: declaracion explicita
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        for item in (ref.get("items") or []):
            if not isinstance(item, dict):
                continue
            for r in (item.get("refs") or []):
                if not isinstance(r, dict):
                    continue
                clave = (r.get("turn_index"), r.get("ref_type"), r.get("ref_index"))
                if None not in clave:
                    lookup.setdefault(clave, ref)

    # Camino 2: posicion dentro del tipo. `ref_type` del marcador no siempre
    # coincide literalmente con `type` de la referencia (search ->
    # grouped_webpages, file -> file), asi que se indexa por ambos nombres.
    por_tipo: Dict[str, List[dict]] = {}
    for ref in refs:
        if isinstance(ref, dict) and ref.get("type"):
            por_tipo.setdefault(str(ref["type"]), []).append(ref)

    ALIAS = {"search": "grouped_webpages", "file": "file", "image": "image_group"}
    for ref_type_marcador, tipo_real in ALIAS.items():
        for idx, ref in enumerate(por_tipo.get(tipo_real, [])):
            lookup.setdefault((0, ref_type_marcador, idx), ref)

    return lookup


def _urls_de_imagen(ref: dict) -> List[str]:
    """URLs de imagen de una referencia, sin duplicados y en orden."""
    urls: List[str] = []
    for u in (ref.get("safe_urls") or []):
        if isinstance(u, str) and u.startswith("http") and u not in urls:
            urls.append(u)
    if not urls:
        # Respaldo: extraer de `alt`, que viene como markdown ya montado.
        for m in re.finditer(r"!\[[^\]]*\]\((https?://[^)]+)\)", str(ref.get("alt") or "")):
            if m.group(1) not in urls:
                urls.append(m.group(1))
    return urls


def _queries_de_marcador(campos: List[str]) -> List[str]:
    """Las queries de busqueda que el payload JSON del marcador declara.
    Son el contexto que hace util un pendiente: dicen QUE se buscaba."""
    for campo in campos:
        campo = campo.strip()
        if not campo.startswith("{"):
            continue
        try:
            payload = json.loads(campo)
        except (ValueError, TypeError):
            continue
        q = payload.get("query")
        if isinstance(q, list):
            return [str(x) for x in q if x]
        if isinstance(q, str):
            return [q]
    return []


def _texto_enlace(ref: dict) -> str:
    """Convierte una referencia de fuente externa en markdown legible.
    Prefiere `alt`, que ChatGPT ya trae montado con el mismo formato que
    usaba al renderizar ('([Dribo](https://...))')."""
    alt = (ref.get("alt") or "").strip()
    if alt:
        return alt
    trozos = []
    for item in (ref.get("items") or []):
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not url:
            continue
        nombre = item.get("title") or item.get("attribution") or url
        trozos.append(f"[{nombre}]({url})")
    return f"({' · '.join(trozos)})" if trozos else ""


def _texto_fichero(ref: dict) -> str:
    nombre = (ref.get("name") or "").strip()
    return f"(fuente: {nombre})" if nombre else ""


def _texto_widget(ref: dict) -> str:
    return (ref.get("alt") or "").strip()


def _nombre_de_payload(campos: List[str]) -> str:
    """Nombre legible que el propio marcador lleva dentro, sin necesitar
    content_references.

    Muchos widgets inline traen el texto que sustituyen en su propio
    payload, y son justo los que rompen la frase si se pierden:
        entity["place", "Siruela", 0]        -> Siruela
        product_entity["turn0product0","T5"] -> T5
        movieThe Predator                    -> The Predator
    Cazado verificando contra una nota real: sin esto, "visitar desde
    Siruela (Badajoz)" quedaba como "visitar desde *[entity no
    recuperable]* (Badajoz)", que es peor que no tocar nada.
    """
    for campo in campos:
        campo = (campo or "").strip()
        if not campo:
            continue

        if campo.startswith("[") or campo.startswith("{"):
            try:
                payload = json.loads(campo)
            except (ValueError, TypeError):
                continue
            candidatos: List[Any] = []
            if isinstance(payload, list):
                candidatos = payload
            elif isinstance(payload, dict):
                for sel in (payload.get("selections") or []):
                    if isinstance(sel, list):
                        candidatos.extend(sel)
            # El primer elemento suele ser la categoria ("place") o un
            # identificador ("turn0product0"); el nombre es el siguiente.
            textos = [x for x in candidatos
                      if isinstance(x, str) and x and not parse_ref_id(x)]
            if len(textos) >= 2:
                return textos[1]
            if textos:
                return textos[0]
            continue

        # Payload en texto plano: es directamente el nombre.
        if not parse_ref_id(campo):
            return campo
    return ""


def resolve_markers(
    texto: str,
    refs: Optional[List[dict]] = None,
    *,
    pendientes_out: Optional[List[dict]] = None,
    estado_imagenes: Optional[Dict[str, dict]] = None,
    conv_titulo: Optional[str] = None,
) -> str:
    """Sustituye los marcadores PUA de `texto` por markdown legible.

    refs             -- message.metadata.content_references del mensaje
    pendientes_out   -- si se pasa, se le anaden las imagenes de busqueda web
                        encontradas (dicts con url/query/conversacion) para
                        que el llamante monte la lista de pendientes
    estado_imagenes  -- {url: {"estado": "rescatada"|"descartada",
                        "fichero": "nombre.jpg"}} con el triaje ya hecho por
                        V0ra. Vive fuera de la nota a proposito: las notas se
                        regeneran en cada reproceso y la curacion no debe
                        perderse (mismo principio que gizmo_map.json).
    conv_titulo      -- solo para dar contexto a los pendientes
    """
    # Se comprueba el rango PUA entero, no solo MARK_OPEN: hay notas reales
    # con marcadores sueltos (U+E203/E204/E206) sin pareja de apertura, y
    # tambien hay que limpiarlas.
    if not texto or not STRAY_PUA_RE.search(texto):
        return texto

    refs = refs or []
    estado_imagenes = estado_imagenes or {}
    lookup = build_ref_lookup(refs)

    # Respaldo posicional para marcadores sin identificador (image_group
    # lleva un payload JSON, no un turnNimageM): se emparejan en orden con
    # las referencias del mismo tipo. Medido contra datos reales: coincide
    # en 309 de 317 mensajes (97,5%); los casos que no, degradan a aviso.
    refs_imagen = [r for r in refs if isinstance(r, dict)
                   and str(r.get("type")) in ("image_group", "image_v2")]
    contador_imagen = {"i": 0}

    def _refs_de(campos: List[str]) -> List[dict]:
        """Referencias citadas por los identificadores del marcador."""
        vistas: List[dict] = []
        for campo in campos:
            for trozo in campo.split(","):
                clave = parse_ref_id(trozo)
                if not clave:
                    continue
                ref = lookup.get(clave)
                if ref is not None and not any(ref is v for v in vistas):
                    vistas.append(ref)
        return vistas

    def _sustituir(m: "re.Match[str]") -> str:
        tipo, campos = split_marker(m.group(1))

        if tipo in LINK_TYPES:
            trozos = [t for t in (_texto_enlace(r) for r in _refs_de(campos)) if t]
            return " ".join(trozos) if trozos else "*[fuente web citada, no recuperable del export]*"

        if tipo in FILE_TYPES:
            trozos = [t for t in (_texto_fichero(r) for r in _refs_de(campos)) if t]
            if trozos:
                return " ".join(trozos)
            # Limite real del export, no un fallo del parser: la numeracion
            # `turnNfileM` es global de la conversacion y el export no
            # incluye la tabla para reconstruirla (medido: solo el 16% de
            # los filecite tienen su referencia en el mismo mensaje;
            # acumular por conversacion apenas mejora, 87%->84% de fallo).
            # Adivinar por posicion atribuiria la cita al fichero
            # equivocado, que es peor que decir la verdad.
            return "*[cita de un adjunto]*"

        if tipo in IMAGE_TYPES:
            encontradas = _refs_de(campos)
            if not encontradas:
                idx = contador_imagen["i"]
                if idx < len(refs_imagen):
                    encontradas = [refs_imagen[idx]]
                contador_imagen["i"] += 1

            urls: List[str] = []
            for r in encontradas:
                for u in _urls_de_imagen(r):
                    if u not in urls:
                        urls.append(u)
            if not urls:
                return "*[busqueda de imagenes web no recuperable del export]*"

            queries = _queries_de_marcador(campos)
            rescatadas, descartadas, pendientes = [], 0, []
            for u in urls:
                est = estado_imagenes.get(u) or {}
                if est.get("estado") == "rescatada" and est.get("fichero"):
                    rescatadas.append(est["fichero"])
                elif est.get("estado") == "descartada":
                    descartadas += 1
                else:
                    pendientes.append(u)
                    if pendientes_out is not None:
                        pendientes_out.append({
                            "url": u,
                            "queries": queries,
                            "conversacion": conv_titulo,
                        })

            salida = [f"![](CHATGPT/WEB/{f})" for f in rescatadas]
            if pendientes:
                ctx = f': "{queries[0]}"' if queries else ""
                salida.append(
                    f"*[{len(pendientes)} imagen(es) de busqueda web{ctx} — no vienen en el "
                    "export, pendientes de descarga]*"
                )
            elif descartadas and not rescatadas:
                salida.append("*[busqueda de imagenes descartada]*")
            return "\n\n".join(salida)

        if tipo in TEXT_TYPES:
            trozos = [t for t in (_texto_widget(r) for r in _refs_de(campos)) if t]
            if trozos:
                return " ".join(trozos)
            # Muchos de estos widgets van inline dentro de una frase y
            # llevan su propio texto: recuperarlo importa mas que avisar.
            nombre = _nombre_de_payload(campos)
            if nombre:
                return nombre
            return f"*[{tipo} no recuperable del export]*"

        # Tipo nunca visto: aviso honesto en vez de dejar pasar el marcador
        # crudo. ChatGPT anade widgets nuevos cada pocos meses.
        return f"*[contenido no recuperable del export: {tipo or 'desconocido'}]*"

    resuelto = MARKER_RE.sub(_sustituir, texto)
    return STRAY_PUA_RE.sub("", resuelto)
