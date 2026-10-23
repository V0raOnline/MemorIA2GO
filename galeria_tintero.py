#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
galeria_tintero.py — Galeria de los posts de Substack que construye Tintero: una pagina HTML con una
tarjeta por post (portada, titulo, subtitulo, las primeras palabras), busqueda y filtros (estado,
tipo, publicacion, seccion, etiqueta, mes). Hermana de galeria.py, que hace lo mismo con las imagenes.

ES UN COMPLEMENTO, NO PARTE DEL PIPELINE
────────────────────────────────────────
Se ejecuta cuando quieras, nunca al construir el vault. Lee las notas que ya escribio Tintero y
escribe solo en su propia carpeta (`.gallery/` dentro del vault de Tintero, por defecto): la pagina
y las portadas. No toca ni una nota. El punto delante hace que Obsidian no la indexe.

LA PORTADA
──────────
El export de Substack NO la trae (posts.csv no tiene esa columna) y las imagenes del texto son
enlaces remotos. Por eso, por orden:
  1. la portada que Substack da en la API publica de su archivo (`/api/v1/archive`, sin credencial;
     solo existe para lo publicado);
  2. si no hay, la primera imagen del texto del post;
  3. si tampoco, la inicial del titulo (la pone la pagina, sin fichero).
Las dos primeras se bajan UNA vez, como miniatura JPEG, y se reutilizan: solo se vuelve a bajar una
portada si Substack la cambia. Con --sin-red no se sale a Internet: se usa lo ya bajado.

Uso:
  python galeria_tintero.py                    (vault de Tintero de memoria_config.yaml)
  python galeria_tintero.py --vault <carpeta> [--salida <carpeta>] [--sin-red]
"""
import argparse
import datetime
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
PLANTILLA = HERE / "galeria_tintero_plantilla.html"
ESTILO_APP = HERE / "web" / "style.css"
ICONO = HERE / "web" / "assets" / "tintero.png"        # la mascota de Tintero
CARPETA_SALIDA = ".gallery"
CARPETA_PORTADAS = "covers"
LADO_PORTADA = 640
PALABRAS_EXTRACTO = 50
# Las carpetas de notas que escribe Tintero dentro de cada publicacion (las de las dos ediciones: un
# vault construido alguna vez con la otra puede tener las dos).
CARPETAS_NOTAS = ("Posts", "Borradores", "Drafts")
LIMITE_DESCARGA = 25 * 1024 * 1024                     # una portada de mas de 25 MB no es una portada
MAX_PAGINAS_API = 200                                  # tope por si el servidor no deja nunca de devolver
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
IMAGEN_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")

ETIQUETAS = {
    "estado": {"published": "published", "retired": "retired", "draft": "draft"},
}


class ErrorGaleria(Exception):
    pass


# ---------------------------------------------------------------- lectura del vault
def _valor(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1].replace('\\"', '"')
    return v


def frontmatter(texto: str) -> Tuple[dict, str]:
    """El frontmatter que escribe Tintero: claves sueltas y una lista de etiquetas."""
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?", texto, re.S)
    if not m:
        return {}, texto
    datos: Dict[str, object] = {}
    etiquetas: List[str] = []
    en_tags = False
    for linea in m.group(1).splitlines():
        if linea.startswith("tags:"):
            en_tags = True
            continue
        if en_tags and linea.startswith("  - "):
            etiquetas.append(_valor(linea[4:]))
            continue
        en_tags = False
        if ":" in linea and not linea.startswith(" "):
            k, v = linea.split(":", 1)
            datos[k.strip()] = _valor(v)
    datos["tags"] = etiquetas
    return datos, texto[m.end():]


def extracto(cuerpo: str, subtitulo: str = "", n: int = PALABRAS_EXTRACTO) -> str:
    """Las primeras `n` palabras del texto del post: sin el titulo, el subtitulo, los avisos de
    Tintero (citas), las imagenes ni sus pies, las tablas ni las rayas; los enlaces, solo su texto."""
    lineas: List[str] = []
    tras_imagen = False
    for linea in cuerpo.splitlines():
        s = linea.strip()
        if not s:
            continue
        if s.startswith("!["):
            tras_imagen = True
            continue
        es_cursiva = len(s) > 2 and s[0] == s[-1] == "*" and s[1] != "*"
        if es_cursiva and (tras_imagen or (subtitulo and s == f"*{subtitulo}*")):
            tras_imagen = False
            continue
        tras_imagen = False
        if s.startswith(("#", ">", "|", "---", "```")):
            continue
        lineas.append(s)
    texto = IMAGEN_RE.sub("", " ".join(lineas))
    texto = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", texto)
    texto = re.sub(r"[*_`]", "", texto)
    palabras = texto.split()
    return " ".join(palabras[:n]) + ("…" if len(palabras) > n else "")


def _vault_de_obsidian(ruta: Path) -> Optional[Path]:
    """La carpeta de Obsidian que contiene `ruta`: la mas cercana hacia arriba con `.obsidian`."""
    for carpeta in [ruta, *ruta.parents]:
        if (carpeta / ".obsidian").is_dir():
            return carpeta
    return None


def enlace_obsidian(nota: Path) -> str:
    """obsidian://open al vault mas cercano que contiene la nota; si no hay ninguno, por ruta absoluta."""
    vault = _vault_de_obsidian(nota.parent)
    if vault is not None:
        rel = nota.relative_to(vault).with_suffix("").as_posix()
        return f"obsidian://open?vault={quote(vault.name, safe='')}&file={quote(rel, safe='')}"
    return f"obsidian://open?path={quote(str(nota), safe='')}"


def leer_posts(vault: Path) -> List[dict]:
    """Un dict por post de las notas de Tintero. Un post repetido (misma publicacion y post_id, p. ej.
    en Borradores y en Drafts) cuenta una vez: la nota modificada mas recientemente."""
    vault = Path(vault)
    elegidos: Dict[Tuple[str, str], Tuple[float, dict]] = {}
    for nota in sorted(vault.rglob("*.md")):
        rel = nota.relative_to(vault)
        if nota.name.startswith("_") or any(p.startswith(".") for p in rel.parts):
            continue
        try:
            texto = nota.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fm, cuerpo = frontmatter(texto)
        if fm.get("source") != "substack_export" or not fm.get("post_id"):
            continue
        carpeta = rel.parts[0] if len(rel.parts) > 1 and rel.parts[0] not in CARPETAS_NOTAS else ""
        publicacion = carpeta or str(fm.get("publication") or vault.name)
        subtitulo = str(fm.get("subtitle") or "")
        primera = IMAGEN_RE.search(cuerpo)
        post = {
            "pub": publicacion, "pubslug": str(fm.get("publication") or ""), "id": str(fm["post_id"]),
            "titulo": str(fm.get("title") or nota.stem), "sub": subtitulo,
            "fecha": str(fm.get("date") or "")[:10], "estado": str(fm.get("status") or ""),
            "tipo": str(fm.get("type") or ""), "seccion": str(fm.get("section") or ""),
            "tags": list(fm.get("tags") or []), "slug": str(fm.get("slug") or ""),
            "ext": extracto(cuerpo, subtitulo), "imagen_texto": primera.group(1) if primera else "",
            "stats": {k: fm[k] for k in ("views", "likes", "comments") if k in fm},
            "nota": nota,
        }
        clave = (post["pubslug"] or publicacion, post["id"])
        fecha_mod = nota.stat().st_mtime
        if clave not in elegidos or fecha_mod > elegidos[clave][0]:
            elegidos[clave] = (fecha_mod, post)
    posts = [p for _, p in elegidos.values()]
    posts.sort(key=lambda p: (p["fecha"] or "", p["titulo"]), reverse=True)
    return posts


# ---------------------------------------------------------------- portadas
def _leer_url(url: str, limite: int = LIMITE_DESCARGA, timeout: int = 30) -> bytes:
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"not a web URL: {url[:60]}")
    req = Request(url, headers={"User-Agent": "M3M0R-IA (Inkwell gallery)"})
    with urlopen(req, timeout=timeout) as r:
        datos = r.read(limite + 1)
    if len(datos) > limite:
        raise ValueError("too large")
    return datos


def portadas_de_la_api(pubslug: str, leer: Callable[[str], bytes] = _leer_url) -> Dict[str, str]:
    """{slug: url de la portada} de los posts publicados, de la API publica del archivo."""
    if not SLUG_RE.match(pubslug or ""):
        return {}
    portadas: Dict[str, str] = {}
    offset = 0
    # Se piden 50 pero el servidor sirve menos (12 en la prueba real): se sigue hasta una pagina vacia.
    # Cortar en la primera pagina corta dejaba fuera 77 de 100 portadas de V0raOnline.
    for _ in range(MAX_PAGINAS_API):
        url = f"https://{pubslug}.substack.com/api/v1/archive?sort=new&offset={offset}&limit=50"
        lote = json.loads(leer(url).decode("utf-8"))
        if not isinstance(lote, list) or not lote:
            break
        for p in lote:
            if isinstance(p, dict) and p.get("slug") and p.get("cover_image"):
                portadas[p["slug"]] = p["cover_image"]
        offset += len(lote)
    return portadas


def _miniatura(datos: bytes, destino: Path) -> None:
    from PIL import Image
    from galeria import _sin_transparencia
    destino.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(datos)) as im:
        im.seek(0)
        im = _sin_transparencia(im)
        im.thumbnail((LADO_PORTADA, LADO_PORTADA))
        tmp = destino.with_name(destino.name + ".part")
        im.save(tmp, "JPEG", quality=82)
    os.replace(tmp, destino)


def poner_portadas(posts: List[dict], salida: Path, con_red: bool = True,
                   leer: Callable[[str], bytes] = _leer_url, log=print) -> dict:
    """Pone en cada post `portada` (ruta del fichero) y `origen` ("api", "texto" o ""). Baja solo lo
    que falta o lo que Substack ha cambiado; lo apunta en portadas/_origen.json."""
    carpeta = salida / CARPETA_PORTADAS
    ruta_origen = carpeta / "_origen.json"
    try:
        origenes = json.loads(ruta_origen.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        origenes = {}
    r = {"api": 0, "texto": 0, "inicial": 0, "bajadas": 0, "reutilizadas": 0, "fallidas": 0, "api_caida": []}
    de_la_api: Dict[str, Dict[str, str]] = {}
    if con_red:
        try:
            import PIL  # noqa: F401
        except ImportError:
            raise ErrorGaleria("Pillow is needed for the covers: pip install pillow (or run with --sin-red)")
        for pubslug in sorted({p["pubslug"] for p in posts if p["pubslug"]}):
            try:
                de_la_api[pubslug] = portadas_de_la_api(pubslug, leer)
            except Exception as e:                       # sin API, se sigue con la primera imagen
                log(f"  [warning] could not ask Substack for the covers of {pubslug}: {e}")
                r["api_caida"].append(pubslug)
    for p in posts:
        clave = f"{p['pubslug'] or p['pub']}|{p['id']}"
        destino = carpeta / _carpeta_segura(p["pub"]) / f"{re.sub(r'[^0-9A-Za-z_-]', '_', p['id'])}.jpg"
        candidatas = []
        if p["estado"] == "published" and de_la_api.get(p["pubslug"], {}).get(p["slug"]):
            candidatas.append(("api", de_la_api[p["pubslug"]][p["slug"]]))
        if p["imagen_texto"]:
            candidatas.append(("texto", p["imagen_texto"]))
        p["portada"], p["origen"] = None, ""
        previo = origenes.get(clave) or {}
        for origen, url in candidatas:
            if destino.is_file() and previo.get("url") == url:
                p["portada"], p["origen"] = destino, origen
                r["reutilizadas"] += 1
                break
            if not con_red:
                continue
            try:
                _miniatura(leer(url), destino)
            except Exception as e:                       # una portada rota no tumba la galeria
                log(f"  [warning] could not download the cover of \"{p['titulo'][:50]}\": {e}")
                r["fallidas"] += 1
                continue
            origenes[clave] = {"url": url, "origen": origen}
            p["portada"], p["origen"] = destino, origen
            r["bajadas"] += 1
            break
        if p["portada"] is None and not con_red and destino.is_file():
            p["portada"], p["origen"] = destino, previo.get("origen", "")
            r["reutilizadas"] += 1
        r[p["origen"] or "inicial"] = r.get(p["origen"] or "inicial", 0) + 1
    if r["bajadas"]:
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta_origen.write_text(json.dumps(origenes, ensure_ascii=False, indent=1), encoding="utf-8")
    return r


def _carpeta_segura(nombre: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nombre).strip(" .") or "_"


# ---------------------------------------------------------------- pagina
def _url(destino: Path, desde: Path) -> str:
    try:
        return quote(Path(os.path.relpath(destino, desde)).as_posix(), safe="/._-~")
    except ValueError:
        return Path(destino).resolve().as_uri()


def construir_pagina(posts: List[dict], salida: Path, tema: str = "warm") -> str:
    from galeria import tokens_de_la_app
    datos = {"tema": tema, "etiquetas": ETIQUETAS, "generado": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
             "posts": []}
    for p in posts:
        url = (f"https://{p['pubslug']}.substack.com/p/{quote(p['slug'], safe='-_')}"
               if p["estado"] == "published" and SLUG_RE.match(p["pubslug"]) and p["slug"] else "")
        datos["posts"].append({k: v for k, v in {
            "pub": p["pub"], "titulo": p["titulo"], "sub": p["sub"], "fecha": p["fecha"], "estado": p["estado"],
            "tipo": p["tipo"], "seccion": p["seccion"], "tags": p["tags"], "ext": p["ext"],
            "portada": _url(p["portada"], salida) if p.get("portada") else "", "stats": p["stats"],
            "obs": enlace_obsidian(p["nota"]), "web": url,
        }.items() if v not in (None, "", [], {})})
    plantilla = PLANTILLA.read_text(encoding="utf-8")
    json_datos = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    return plantilla.replace("/*__TOKENS__*/", tokens_de_la_app()).replace("/*__DATOS__*/null", json_datos)


def copiar_icono(salida: Path) -> None:
    destino = salida / "tintero.png"
    if not ICONO.is_file():
        return
    try:
        from PIL import Image
        with Image.open(ICONO) as im:
            im.thumbnail((96, 96))
            im.save(destino, "PNG")
    except Exception:
        destino.write_bytes(ICONO.read_bytes())


def generar(vault: Path, salida: Optional[Path] = None, con_red: bool = True, tema: Optional[str] = None,
            leer: Callable[[str], bytes] = _leer_url, log=print) -> dict:
    vault = Path(vault)
    if not vault.is_dir():
        raise ErrorGaleria(f"the Inkwell vault folder does not exist: {vault}")
    salida = Path(salida) if salida else vault / CARPETA_SALIDA
    log(f"Reading the posts in {vault} ...")
    posts = leer_posts(vault)
    if not posts:
        raise ErrorGaleria(f"no Inkwell posts found in {vault}")
    salida.mkdir(parents=True, exist_ok=True)
    log("Covers" + (" (asking Substack; only what is missing is downloaded) ..." if con_red else " (offline: only what was already downloaded) ..."))
    portadas = poner_portadas(posts, salida, con_red=con_red, leer=leer, log=log)
    if tema is None:
        from galeria import tema_configurado
        tema = tema_configurado()
    copiar_icono(salida)
    pagina = salida / "index.html"
    tmp = pagina.with_name("index.html.part")
    tmp.write_text(construir_pagina(posts, salida, tema), encoding="utf-8")
    os.replace(tmp, pagina)
    r = {"posts": len(posts), "pagina": str(pagina), "portadas": portadas,
         "borradores": sum(1 for p in posts if p["estado"] == "draft"),
         "por_publicacion": {pub: sum(1 for p in posts if p["pub"] == pub) for pub in sorted({p["pub"] for p in posts})}}
    from galeria import escribir_estado
    escribir_estado(salida, {"posts": r["posts"], "borradores": r["borradores"], "por_publicacion": r["por_publicacion"]})
    return r


def _config_vault() -> Optional[str]:
    try:
        from config_loader import load_config, get_path
        from galeria import _ruta_config
        ruta = get_path(load_config(_ruta_config()), "substack_vault")
        return str(ruta) if ruta else None
    except Exception:
        return None


def main(argv=None) -> int:
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Builds the HTML gallery of your Inkwell Substack posts.")
    ap.add_argument("--vault", help="Inkwell vault (default: substack_vault from memoria_config.yaml)")
    ap.add_argument("--salida", help=f"Gallery folder (default: <vault>/{CARPETA_SALIDA})")
    ap.add_argument("--sin-red", action="store_true", help="Do not go online: only the covers already downloaded")
    ap.add_argument("--tema", choices=["warm", "cool", "light"], help="Default theme (otherwise, the one in the configuration)")
    args = ap.parse_args(argv)
    vault = args.vault or _config_vault()
    if not vault:
        ap.error("--vault is required (there is no substack_vault in memoria_config.yaml)")
    try:
        r = generar(Path(vault), Path(args.salida) if args.salida else None, con_red=not args.sin_red, tema=args.tema)
    except ErrorGaleria as e:
        print(f"[error] {e}")
        return 2
    po = r["portadas"]
    print()
    print(f"Inkwell gallery: {r['pagina']}")
    print(f"  {r['posts']} posts ({r['borradores']} drafts) | by publication: {r['por_publicacion']}")
    print(f"  covers: {po['api']} from Substack, {po['texto']} from the first image, {po['inicial']} with the initial "
          f"| {po['bajadas']} downloaded, {po['reutilizadas']} already there, {po['fallidas']} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
