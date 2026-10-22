#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
galeria.py — Galeria de las imagenes y videos de tus IAs: una pagina HTML que se abre en el
navegador, con una tira por conversacion, conversaciones plegables, busqueda por palabras clave y
filtros (proveedor, generadas o subidas, imagen o video, generador, modelo, proyecto, mes).

ES UN COMPLEMENTO, NO PARTE DEL PIPELINE
────────────────────────────────────────
Se ejecuta cuando quieras (o desde la app), nunca en una importacion. Lee lo que ya hay en el vault
y escribe solo en su propia carpeta (`.galeria/` en la base, por defecto): la pagina y sus miniaturas.
No toca ni una nota ni un banco. El punto delante del nombre hace que Obsidian no la indexe: miles
de miniaturas en el arbol de ficheros del vault serian solo ruido.

DE DONDE SALE CADA COSA
───────────────────────
  - Los ficheros: los bancos de cada proveedor (CHATGPT/GENERADAS y ADJUNTOS, GROK/..., COPILOT/...).
  - Con que se genero (generador, modelo, si es una edicion): el manifiesto de cada banco.
  - La conversacion, su fecha y proyecto, lo que pediste y el prompt: las notas de MERGED_VAULT
    que enlazan cada imagen. Las de Copilot no tienen conversacion: tienen una nota por imagen, y se
    agrupan por prompt y dia (Copilot genera varias variantes por peticion).
  - Lo que ninguna nota enlaza (Grok Imagine, huerfanas...) se agrupa por dia y proveedor.

MINIATURAS
──────────
Con Pillow: 480 px de lado, JPEG, en `.galeria/miniaturas/`, y solo las que faltan o cuyo original
cambio. Si ya hay miniaturas propias junto a un banco (CHATGPT/GENERADAS_Thmbnails), se parte de
ellas, que es mas rapido. Los videos no tienen miniatura: la pagina muestra su primer fotograma.

Uso:
  python galeria.py                       (base del vault de memoria_config.yaml)
  python galeria.py --base-vault G:\\vaults [--salida <carpeta>] [--sin-miniaturas]
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
PLANTILLA = HERE / "galeria_plantilla.html"
ESTILO_APP = HERE / "web" / "style.css"
ICONO = HERE / "web" / "assets" / "imageIA.png"      # el cerebrito de image.ia
CARPETA_SALIDA = ".galeria"
LADO_MINIATURA = 480
# Sube cuando cambia como se hacen las miniaturas: rehace todas aunque el original no haya cambiado.
# v2: la transparencia va sobre blanco (antes salia negra en las capturas y los PNG con alfa).
VERSION_MINIATURAS = "2"

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VID_EXTS = {".mp4", ".webm", ".mov"}

# (carpeta del banco bajo la base, proveedor, origen, generador si el manifiesto no lo dice)
BANCOS = [
    ("CHATGPT/GENERADAS", "chatgpt", "generada", None),
    ("CHATGPT/ADJUNTOS", "chatgpt", "subida", None),
    ("GROK/GENERADAS_IMAGEN", "grok", "generada", "grok-chat"),
    ("GROK/GENERADAS_VIDEO", "grok", "generada", "grok-chat"),
    ("GROK/IMAGINE", "grok", "generada", "grok-imagine"),
    ("GROK/ADJUNTOS", "grok", "subida", None),
]
# Copilot: su vault lo construye image.ia donde diga `paths.copilot_images_vault`; si no se dice, se
# busca en el sitio de siempre dentro de la base. Notas en una subcarpeta, ficheros en otra.
COPILOT = "COPILOT/GENERADAS_IMAGEN"
COPILOT_NOTAS = "Imágenes"
COPILOT_FICHEROS = "Archivos"
MINIATURAS_PROPIAS = {"CHATGPT/GENERADAS": ("CHATGPT/GENERADAS_Thmbnails", "thmbnail_")}

ETIQUETAS = {
    "proveedor": {"chatgpt": "ChatGPT", "grok": "Grok", "copilot": "Copilot", "claude": "Claude"},
    "origen": {"generada": "generada", "subida": "subida"},
    "generador": {
        "chatgpt-imagen": "ChatGPT · generación nativa", "chatgpt-dalle": "ChatGPT · DALL·E",
        "chatgpt-biblioteca": "ChatGPT · biblioteca", "grok-chat": "Grok · chat",
        "grok-imagine": "Grok · Imagine", "copilot": "Copilot",
    },
}

ENLACE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
BLOQUE_RE = re.compile(r"(?m)^###\s+([A-Za-z]+)\s*$")
TITULO_TOOL_RE = re.compile(r"^\*(.+?)\*(?: · (\d{4}-\d{2}-\d{2} \d{2}:\d{2}))?\s*$", re.M)
FECHA_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class ErrorGaleria(Exception):
    pass


# ---------------------------------------------------------------- lectura del vault
def _frontmatter(texto: str):
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", texto, re.S)
    datos: Dict[str, str] = {}
    if not m:
        return datos, texto
    for linea in m.group(1).splitlines():
        if ":" in linea and not linea.startswith(" "):
            k, v = linea.split(":", 1)
            datos[k.strip()] = v.strip().strip('"')
    return datos, texto[m.end():]


def _limpiar(txt, n=300) -> str:
    txt = txt if isinstance(txt, str) else ""
    txt = ENLACE_RE.sub("", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:n] + ("…" if len(txt) > n else "")


def _prompt_de(txt: str) -> str:
    """El prompt que el asistente mandaba a la herramienta de imagen (JSON `{"prompt": ...}`)."""
    s = txt.strip()
    if not s.startswith('{"prompt"'):
        return ""
    try:
        return json.loads(s).get("prompt") or ""
    except ValueError:
        m = re.search(r'"prompt":\s*"(.*?)"(?:,|\s*})', s, re.S)
        return m.group(1) if m else ""


def leer_conversaciones(base: Path) -> Dict[str, dict]:
    """{ruta del fichero relativa a la base: contexto de su primera aparicion en MERGED}. El contexto es
    la conversacion (titulo, fecha, nota, proveedor, proyecto), lo que pediste justo antes, el prompt
    si lo hubo y el titulo/hora que dejan los bloques de la biblioteca."""
    contexto: Dict[str, dict] = {}
    raiz = base / "MERGED_VAULT" / "Conversaciones"
    if not raiz.is_dir():
        return contexto
    for nota in sorted(raiz.rglob("*.md")):
        try:
            texto = nota.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "](" not in texto:
            continue
        fm, cuerpo = _frontmatter(texto)
        conv = {"titulo": fm.get("title") or nota.stem, "fecha": fm.get("date", ""),
                "nota": nota.relative_to(base).with_suffix("").as_posix(),
                "proveedor": (fm.get("provider") or "chatgpt").lower(),
                "proyecto": fm.get("Project_name") or ""}
        partes = BLOQUE_RE.split(cuerpo)
        peticion = prompt = ""
        for i in range(1, len(partes), 2):
            rol, txt = partes[i].lower(), partes[i + 1]
            if rol == "user":
                peticion = _limpiar(txt) or peticion
                prompt = ""
            elif rol == "assistant" and _prompt_de(txt):
                prompt = _prompt_de(txt)
            enlaces = ENLACE_RE.findall(txt)
            if not enlaces:
                continue
            tt = TITULO_TOOL_RE.search(txt) if rol == "tool" else None
            for ruta in enlaces:
                if ruta.startswith(("http://", "https://")):
                    continue
                ruta = ruta.replace("%20", " ")
                if ruta in contexto:
                    continue
                contexto[ruta] = {"conv": conv, "peticion": peticion, "prompt": _limpiar(prompt, 1200),
                                  "titulo": tt.group(1) if tt else "", "hora": (tt.group(2) or "") if tt else ""}
    return contexto


def _leer_manifiesto(carpeta: Path) -> Dict[str, dict]:
    p = carpeta / "_image_manifest.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _tipo(nombre: str) -> Optional[str]:
    ext = os.path.splitext(nombre)[1].lower()
    return "imagen" if ext in IMG_EXTS else "video" if ext in VID_EXTS else None


def recoger(base: Path, copilot: Optional[Path] = None) -> List[dict]:
    """Todas las imagenes y videos de los bancos, con todo lo que se sabe de cada uno. `copilot` es el
    vault de imagenes de Copilot (por defecto, el sitio de siempre dentro de la base)."""
    base = Path(base)
    contexto = leer_conversaciones(base)
    items: List[dict] = []
    for rel, prov, origen, gen_defecto in BANCOS:
        carpeta = base / rel
        if not carpeta.is_dir():
            continue
        manifiesto = _leer_manifiesto(carpeta)
        for f in sorted(carpeta.rglob("*")):
            if not f.is_file() or f.name.startswith("_"):
                continue
            tipo = _tipo(f.name)
            if not tipo:
                continue
            ruta = f.relative_to(base).as_posix()
            meta = manifiesto.get(f.name) or manifiesto.get(f.relative_to(carpeta).as_posix()) or {}
            ctx = contexto.get(ruta) or {}
            conv = ctx.get("conv")
            fecha = (conv or {}).get("fecha") or (meta.get("creada") or meta.get("create_time") or "")[:10]
            items.append({
                "ruta": ruta, "abs": str(f), "banco": rel, "prov": prov, "origen": origen, "tipo": tipo,
                "gen": (meta.get("generador") or gen_defecto) if origen == "generada" else None,
                "modelo": meta.get("modelo"), "ed": bool(meta.get("edicion")),
                "titulo": ctx.get("titulo") or meta.get("titulo_biblioteca") or
                          (meta.get("adjunto_nombre") if origen == "subida" else "") or "",
                "prompt": ctx.get("prompt") or _limpiar(meta.get("prompt"), 1200),
                "pet": ctx.get("peticion") or "", "hora": ctx.get("hora") or "",
                "fecha": fecha or _fecha_fichero(f), "conv": conv,
            })
    items.extend(_recoger_copilot(base, Path(copilot) if copilot else base / COPILOT))
    return items


def _fecha_fichero(f: Path) -> str:
    try:
        return datetime.date.fromtimestamp(f.stat().st_mtime).isoformat()
    except OSError:
        return ""


def _recoger_copilot(base: Path, raiz: Path) -> List[dict]:
    """Copilot no asocia sus imagenes a conversaciones: cada imagen tiene su nota (la que construye
    image.ia) con el prompt y la fecha, y el fichero esta en su carpeta de ficheros. El vault puede
    estar fuera de la base: entonces no hay enlace a Obsidian (es otro vault)."""
    notas = raiz / COPILOT_NOTAS
    if not notas.is_dir():
        return []
    items = []
    for nota in sorted(notas.rglob("*.md")):
        texto = nota.read_text(encoding="utf-8", errors="ignore")
        fm, cuerpo = _frontmatter(texto)
        m = re.search(r"!\[\[([^\]|]+)", cuerpo)
        if not m:
            continue
        fichero = raiz / COPILOT_FICHEROS / m.group(1)
        if not fichero.is_file() or not _tipo(fichero.name):
            continue
        prompt = fm.get("prompt", "")
        fecha = (fm.get("created_at") or "")[:10]
        dentro = _dentro_de(fichero, base)
        items.append({
            "ruta": fichero.relative_to(base).as_posix() if dentro else
                    f"COPILOT/{fichero.relative_to(raiz).as_posix()}",
            "abs": str(fichero), "banco": COPILOT, "prov": "copilot", "origen": "generada",
            "tipo": _tipo(fichero.name), "gen": "copilot", "modelo": None, "ed": False,
            "titulo": "", "prompt": _limpiar(prompt, 1200), "pet": "", "hora": "", "fecha": fecha,
            "nota": nota.relative_to(base).with_suffix("").as_posix() if _dentro_de(nota, base) else None,
            "conv": {"titulo": _limpiar(prompt, 90) or fm.get("title", "Copilot"), "fecha": fecha, "nota": None,
                     "proveedor": "copilot", "proyecto": "", "clave": f"copilot|{fecha}|{prompt}"},
        })
    return items


def _dentro_de(ruta: Path, base: Path) -> bool:
    try:
        Path(ruta).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- agrupar
def agrupar(items: List[dict]) -> List[dict]:
    """Una tira por conversacion; lo que no tiene conversacion, una tira por dia y proveedor."""
    grupos: Dict[str, dict] = {}
    for it in items:
        conv = it.get("conv")
        if conv:
            clave = conv.get("clave") or conv.get("nota") or conv["titulo"]
            g = grupos.setdefault(clave, {"titulo": conv["titulo"], "fecha": conv.get("fecha", ""),
                                          "nota": conv.get("nota"), "proyecto": conv.get("proyecto", ""), "imgs": []})
        else:
            clave = f"sin|{it['prov']}|{it['fecha']}"
            nombre = ETIQUETAS["proveedor"].get(it["prov"], it["prov"])
            g = grupos.setdefault(clave, {"titulo": f"{nombre} · sin conversación", "fecha": it["fecha"],
                                          "nota": None, "proyecto": "", "imgs": []})
        g["imgs"].append(it)
    lista = list(grupos.values())
    lista.sort(key=lambda g: (g["fecha"] or "", g["titulo"]), reverse=True)
    return lista


# ---------------------------------------------------------------- miniaturas
def _url(destino: Path, desde: Path) -> str:
    """Enlace de la pagina a un fichero: relativo si se puede (la galeria se puede mover con el vault),
    absoluto (file:///) si estan en unidades distintas."""
    try:
        return quote(Path(os.path.relpath(destino, desde)).as_posix(), safe="/._-~")
    except ValueError:
        return Path(destino).resolve().as_uri()


def generar_miniaturas(items: List[dict], base: Path, salida: Path, log=print) -> dict:
    """Miniaturas JPEG de las imagenes, solo las que faltan o estan viejas. Devuelve el recuento."""
    try:
        from PIL import Image
    except ImportError:
        raise ErrorGaleria("falta Pillow para hacer las miniaturas: pip install pillow "
                           "(o ejecuta con --sin-miniaturas)")
    hechas = reutilizadas = fallidas = 0
    marca = salida / "miniaturas" / ".version"
    al_dia = marca.is_file() and marca.read_text(encoding="utf-8").strip() == VERSION_MINIATURAS
    for it in items:
        if it["tipo"] != "imagen":
            continue
        original = Path(it["abs"])
        destino = salida / "miniaturas" / Path(it["ruta"]).with_suffix(".jpg")
        it["mini"] = destino
        if al_dia and destino.is_file() and destino.stat().st_mtime >= original.stat().st_mtime:
            reutilizadas += 1
            continue
        fuente = original
        propias = MINIATURAS_PROPIAS.get(it["banco"])
        if propias:
            p = base / propias[0] / f"{propias[1]}{Path(it['ruta']).stem}.png"
            if p.is_file():
                fuente = p
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(fuente) as im:
                im.seek(0)
                im = _sin_transparencia(im)
                im.thumbnail((LADO_MINIATURA, LADO_MINIATURA))
                im.save(destino, "JPEG", quality=80)
            hechas += 1
        except Exception as e:                       # un fichero roto no tumba la galeria
            log(f"  [aviso] no he podido hacer la miniatura de {it['ruta']}: {e}")
            it["mini"] = None
            fallidas += 1
    marca.parent.mkdir(parents=True, exist_ok=True)
    marca.write_text(VERSION_MINIATURAS, encoding="utf-8")
    return {"hechas": hechas, "reutilizadas": reutilizadas, "fallidas": fallidas}


def _sin_transparencia(im):
    """RGB para el JPEG. Lo transparente va sobre blanco: convertir sin mas lo deja negro, y una
    captura o un PNG con fondo transparente salia como un cuadro oscuro vacio."""
    from PIL import Image
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        fondo = Image.new("RGB", im.size, (255, 255, 255))
        fondo.paste(im, mask=im.getchannel("A"))
        return fondo
    return im.convert("RGB")


# ---------------------------------------------------------------- pagina
def tokens_de_la_app() -> str:
    """Los bloques de tokens de color de la app (warm, cool, light), copiados de web/style.css para
    que la galeria tenga exactamente los mismos temas."""
    try:
        css = ESTILO_APP.read_text(encoding="utf-8")
    except OSError:
        return ""
    bloques = re.findall(r"(:root(?:,\s*:root\[data-theme=\"warm\"\])?|:root\[data-theme=\"(?:warm|cool|light)\"\])\s*\{([^}]*)\}", css)
    return "\n".join(f"{sel} {{{cuerpo}}}" for sel, cuerpo in bloques)


def copiar_icono(salida: Path) -> None:
    """El cerebrito de image.ia junto a la pagina (cabecera e icono de la pestana). Pequeno si hay
    Pillow; si no, tal cual. La galeria no depende de la carpeta de la app."""
    destino = salida / "imageIA.png"
    if not ICONO.is_file():
        return
    try:
        from PIL import Image
        with Image.open(ICONO) as im:
            im.thumbnail((96, 96))
            im.save(destino, "PNG")
    except Exception:
        destino.write_bytes(ICONO.read_bytes())


def tema_configurado() -> str:
    try:
        from config_loader import load_config, get_opt
        return get_opt(load_config(_ruta_config()), "theme", "warm") or "warm"
    except Exception:
        return "warm"


def construir_pagina(grupos: List[dict], base: Path, salida: Path, tema: str = "warm") -> str:
    datos = {"vault": base.name, "tema": tema, "etiquetas": ETIQUETAS,
             "generado": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "grupos": []}
    for g in grupos:
        imgs = []
        for it in g["imgs"]:
            mini = it.get("mini")
            imgs.append({k: v for k, v in {
                "t": _url(mini, salida) if mini else "", "o": _url(Path(it["abs"]), salida),
                "tipo": it["tipo"], "prov": it["prov"], "origen": it["origen"], "gen": it.get("gen"),
                "modelo": it.get("modelo"), "ed": it.get("ed") or None, "titulo": it.get("titulo"),
                "prompt": it.get("prompt"), "pet": it.get("pet"), "hora": it.get("hora"), "fecha": it.get("fecha"),
                "nota": it.get("nota"),
            }.items() if v not in (None, "", False)})
        datos["grupos"].append({k: v for k, v in {"titulo": g["titulo"], "fecha": g["fecha"], "nota": g["nota"],
                                                  "proyecto": g["proyecto"], "imgs": imgs}.items() if v not in (None, "")})
    plantilla = PLANTILLA.read_text(encoding="utf-8")
    json_datos = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    return plantilla.replace("/*__TOKENS__*/", tokens_de_la_app()).replace("/*__DATOS__*/null", json_datos)


def generar(base: Path, salida: Optional[Path] = None, miniaturas: bool = True, tema: Optional[str] = None,
            copilot: Optional[Path] = None, log=print) -> dict:
    base = Path(base)
    if not base.is_dir():
        raise ErrorGaleria(f"no existe la carpeta base: {base}")
    salida = Path(salida) if salida else base / CARPETA_SALIDA
    log(f"Recogiendo imagenes y videos de {base} ...")
    items = recoger(base, copilot)
    if not items:
        raise ErrorGaleria(f"no he encontrado imagenes en los bancos de {base}")
    salida.mkdir(parents=True, exist_ok=True)
    r = {"items": len(items), "miniaturas": None}
    if miniaturas:
        log(f"Miniaturas en {salida / 'miniaturas'} (solo las que faltan) ...")
        r["miniaturas"] = generar_miniaturas(items, base, salida, log=log)
    else:
        for it in items:                          # sin miniaturas, la pagina tira de los originales
            if it["tipo"] == "imagen":
                it["mini"] = Path(it["abs"])
    grupos = agrupar(items)
    copiar_icono(salida)
    pagina = salida / "index.html"
    tmp = pagina.with_name("index.html.part")
    tmp.write_text(construir_pagina(grupos, base, salida, tema or tema_configurado()), encoding="utf-8")
    os.replace(tmp, pagina)
    r.update({"grupos": len(grupos), "pagina": str(pagina),
              "con_conversacion": sum(1 for it in items if it.get("conv") and it["prov"] != "copilot"),
              "por_proveedor": {p: sum(1 for it in items if it["prov"] == p) for p in sorted({i["prov"] for i in items})}})
    return r


def _ruta_config() -> str:
    """La configuracion: la de MEMORIA_CONFIG si esta puesta (como en el resto de scripts), si no la de
    junto a la app."""
    return os.environ.get("MEMORIA_CONFIG") or str(HERE / "memoria_config.yaml")


def _config_ruta(clave: str) -> Optional[str]:
    try:
        from config_loader import load_config, get_path
        ruta = get_path(load_config(_ruta_config()), clave)
        return str(ruta) if ruta else None
    except Exception:
        return None


def _config_base() -> Optional[str]:
    return _config_ruta("base_vault")


def main(argv=None) -> int:
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Genera la galeria HTML de las imagenes y videos de tus IAs.")
    ap.add_argument("--base-vault", help="Carpeta base del vault (por defecto, la de memoria_config.yaml)")
    ap.add_argument("--salida", help=f"Carpeta de la galeria (por defecto <base>/{CARPETA_SALIDA})")
    ap.add_argument("--sin-miniaturas", action="store_true", help="No hacer miniaturas (la pagina usa los originales)")
    ap.add_argument("--tema", choices=["warm", "cool", "light"], help="Tema por defecto (si no, el de la configuracion)")
    ap.add_argument("--copilot-vault", help="Vault de imagenes de Copilot (por defecto, copilot_images_vault de la configuracion)")
    args = ap.parse_args(argv)
    base = args.base_vault or _config_base()
    if not base:
        ap.error("hace falta --base-vault (no hay base_vault en memoria_config.yaml)")
    try:
        copilot = args.copilot_vault or _config_ruta("copilot_images_vault")
        r = generar(Path(base), Path(args.salida) if args.salida else None, miniaturas=not args.sin_miniaturas,
                    copilot=Path(copilot) if copilot else None,
                    tema=args.tema)
    except ErrorGaleria as e:
        print(f"[error] {e}")
        return 2
    print()
    print(f"Galeria: {r['pagina']}")
    print(f"  {r['items']} imagenes y videos en {r['grupos']} grupos | por proveedor: {r['por_proveedor']}")
    if r["miniaturas"]:
        m = r["miniaturas"]
        print(f"  miniaturas: {m['hechas']} nuevas, {m['reutilizadas']} ya estaban, {m['fallidas']} fallidas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
