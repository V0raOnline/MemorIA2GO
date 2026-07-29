# -*- coding: utf-8 -*-
"""orphan_cloud.py — Nube de palabras de las conversaciones huérfanas (Fase 1).

Escanea las notas de MERGED_VAULT cuyo frontmatter dice Project_name: none
(o no lo dice) y cuenta en cuántas notas aparece cada término (frecuencia
documental, no bruta: así una conversación gigante no secuestra la nube).

El vocabulario de proyectos se siembra desde TRES fuentes:
  1. Carpetas de primer nivel de PRJ_VAULT (proyectos ya curados)
  2. Valores de gizmo_map.json (nombres humanos de gizmos de ChatGPT)
  3. Los projects/workspaces declarados dentro de los zips de Claude y Grok
     presentes en exports_dir (sus conversaciones no los referencian, pero
     los nombres viajan en el export y son la mejor pista de clasificación)

Los términos que coinciden con ese vocabulario se marcan es_proyecto=True y
se muestran SIEMPRE que aparezcan en alguna huérfana, aunque queden fuera de
la banda de frecuencia — son los candidatos naturales a regla de la Fase 2.

Fase 1 = solo lectura. Este módulo no escribe nada en ningún vault.

Uso CLI (diagnóstico):
  python orphan_cloud.py RUTA_BASE_VAULT [--prj-vault-name PRJ_VAULT]
                         [--gizmo-map ruta.json] [--exports-dir carpeta]
                         [--top 40] [--term palabra]
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from tree_index import read_frontmatter, INDEX_FILENAMES, iter_markdown_files

# Términos de 3+ caracteres con letras (acentos y ñ incluidos), dígitos o guiones
TOKEN_RX = re.compile(r"[a-z0-9áéíóúüñ][a-z0-9áéíóúüñ_-]{2,}")

_DIACRITICOS_RX = re.compile("[\u0300-\u036f]")


def _sin_acentos(s: str) -> str:
    """Descompone y descarta diacriticos: fisica==física, ensenanza==enseñanza.
    Solo para COMPARAR: el texto real de las notas nunca se toca."""
    return _DIACRITICOS_RX.sub("", unicodedata.normalize("NFD", s))

# Stopwords ES + EN + dominio (roles de nota, artefactos de markdown/exports).
# Lista corta a propósito: mejor quedarse corto y ver ruido en la nube que
# filtrar de más y perder señal. Se ampliará con lo que la nube enseñe.
STOPWORDS = frozenset("""
los las unos unas del con por para como más mas pero sus les nos vos este esta
estos estas ese esa esos esas aquel aquella todo toda todos todas otro otra
otros otras algo alguien nada nadie cada cual cuales quien quienes cuyo cuya
donde cuando cuanto cuanta cuantos cuantas porque aunque mientras entonces
luego antes despues después ahora aqui aquí alli allí ahi ahí asi así bien mal
muy poco mucho mucha muchos muchas tan tanto tanta tantos tantas solo sólo
también tambien tampoco si sí no ni que qué the and for not you your with this
that from they them their there here what when where which who whom whose why
how all any both each few more most other some such nor only own same than too
very can will just should could would may might must shall about into over
under again further then once during before after above below between out off
down una uno son ser estar estoy estas está están era eran fue fueron sido
siendo soy eres somos sois tengo tienes tiene tenemos teneis tienen tenia
tenía había habia hay has han hemos habeis he ha me te se le lo la mi tu su
es al en un de a y o u e it is are was were been being have has had having do
does did doing would user assistant archivo adjunto adjuntos export exports
http https www com org net html json md png jpg jpeg webp zip file files
imagen imagenes imágenes referenciado incluido binario asset claude chatgpt
grok gpt vale okay hola gracias sean parezca viendo cuánto cuanto cualquiera
debajo propios propias juntas juntos menor mayor breve exacta exacto debería
podría habría quisiera dime dame haz pon mira oye venga
""".split())

# Las stopwords pasan por el mismo aro que los tokens: sin esto, al quitar
# acentos de los tokens, las stopwords acentuadas dejarian de filtrar.
STOPWORDS = frozenset(_sin_acentos(w) for w in STOPWORDS)


def _norm(text: str) -> str:
    """minusculas + sin acentos (decision V0ra 2026-07-18): ambos lados de
    cualquier comparacion pasan por aqui, asi que 'fisica' y 'física' pescan
    lo mismo se escriba como se escriba. Sensible solo al contenido, nunca a
    la grafia del momento."""
    return _sin_acentos(text.lower())


def _raw_tokens(text: str):
    """Todos los términos, sin filtro de stopwords (el filtro se aplica solo
    al ranking genérico; el vocabulario de proyectos se cuenta siempre)."""
    for t in TOKEN_RX.findall(_norm(text)):
        if t.isdigit():
            continue
        yield t


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def _add_name_tokens(vocab: Dict[str, str], name: str):
    for tok in TOKEN_RX.findall(_norm(name)):
        # Los nombres multi-palabra sueltan tokens funcionales ("del" en
        # "Mas alla del prompt", "use" en "How to use Claude") que saldrian
        # magenta gigantes apuntando a falsos positivos. Solo tokens con
        # capacidad de discriminar; el nombre compuesto completo (abajo)
        # conserva la senal integra.
        if tok in STOPWORDS:
            continue
        vocab.setdefault(tok, name)
    vocab.setdefault(_norm(name), name)


def provider_project_names(exports_dir: Optional[Path]) -> List[str]:
    """Nombres de projects/workspaces declarados en los zips de Claude y Grok
    de exports_dir. Lectura tolerante: un zip corrupto no rompe la nube."""
    names: List[str] = []
    if not exports_dir or not Path(exports_dir).exists():
        return names
    for z in Path(exports_dir).glob("*.zip"):
        try:
            with zipfile.ZipFile(z) as zf:
                entries = zf.namelist()
                # Claude: projects/*.json con campo name
                for e in entries:
                    if e.startswith("projects/") and e.endswith(".json"):
                        try:
                            with zf.open(e) as f:
                                prj = json.load(f)
                            n = (prj.get("name") or "").strip()
                            if n:
                                names.append(n)
                        except (json.JSONDecodeError, OSError, KeyError):
                            continue
                # Grok: prod-grok-backend.json con projects[].name
                for e in entries:
                    if e.endswith("prod-grok-backend.json"):
                        try:
                            with zf.open(e) as f:
                                data = json.loads(f.read().decode("utf-8-sig"))
                            for p in data.get("projects") or []:
                                n = ((p.get("project") or p).get("name") or "").strip() \
                                    if isinstance(p, dict) else ""
                                if n:
                                    names.append(n)
                        except (json.JSONDecodeError, OSError, KeyError, AttributeError):
                            continue
        except (zipfile.BadZipFile, OSError):
            continue
    return names


def project_vocabulary(prj_vault: Path,
                       gizmo_map_path: Optional[Path] = None,
                       exports_dir: Optional[Path] = None) -> Dict[str, str]:
    """token -> nombre de proyecto, desde las tres fuentes de siembra."""
    vocab: Dict[str, str] = {}

    # 1. Carpetas de PRJ_VAULT (excluyendo infraestructura: .obsidian,
    #    _assets y similares no son proyectos, son fontaneria)
    if prj_vault.exists():
        for d in prj_vault.iterdir():
            if not d.is_dir():
                continue
            if d.name.startswith((".", "_")):
                continue
            if d.name.lower() in ("none", "(sin proyecto)", "conversaciones"):
                continue
            _add_name_tokens(vocab, d.name)

    # 2. gizmo_map.json (valores = nombres humanos)
    if gizmo_map_path and Path(gizmo_map_path).exists():
        try:
            gm = json.loads(Path(gizmo_map_path).read_text(encoding="utf-8"))
            for name in (gm or {}).values():
                if isinstance(name, str) and name.strip():
                    _add_name_tokens(vocab, name.strip())
        except (json.JSONDecodeError, OSError):
            pass

    # 3. Projects declarados en exports de Claude/Grok
    for name in provider_project_names(exports_dir):
        _add_name_tokens(vocab, name)

    return vocab


def iter_orphans(merged_vault: Path):
    """(ruta, frontmatter) de cada nota huérfana de MERGED_VAULT."""
    conv = merged_vault / "Conversaciones"
    if not conv.exists():
        return
    for f in iter_markdown_files(conv):
        if f.name in INDEX_FILENAMES:
            continue
        fm = read_frontmatter(f)
        prj = (fm.get("Project_name") or "none").strip().strip('"').lower()
        if prj in ("none", ""):
            yield f, fm


def build_cloud(base_vault: Path, prj_vault_name: str = "PRJ_VAULT",
                gizmo_map_path: Optional[Path] = None,
                exports_dir: Optional[Path] = None,
                top: int = 100, max_df_ratio: float = 0.25,
                min_df: int = 3) -> dict:
    """max_df_ratio: los terminos presentes en mas de esa fraccion de las
    huerfanas son fondo conversacional (quieres, puede, hacer...) y se
    descartan del ranking generico — lo que discrimina proyectos vive en la
    franja media de frecuencia documental. min_df descarta apariciones
    anecdoticas. Los terminos del vocabulario de proyectos IGNORAN la banda:
    se muestran siempre que aparezcan en alguna huerfana.
    Calibrado contra datos reales: sin el techo, el top-30 era 100%% ruido."""
    base_vault = Path(base_vault)
    merged = base_vault / "MERGED_VAULT"
    vocab = project_vocabulary(base_vault / prj_vault_name, gizmo_map_path, exports_dir)

    df: Dict[str, int] = {}
    total = 0
    for f, _fm in iter_orphans(merged):
        total += 1
        try:
            body = _strip_frontmatter(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        titulo = (_fm.get("title") or "").strip().strip('"')
        # El titulo participa en el conteo, igual que en los temas (coherencia:
        # lo que la nube muestra y lo que un tema pesca juegan con las mismas reglas)
        for tok in set(_raw_tokens(body)) | set(_raw_tokens(titulo)):
            df[tok] = df.get(tok, 0) + 1

    techo = max(int(total * max_df_ratio), min_df)

    # Ranking generico: sin stopwords, dentro de la banda de frecuencia
    genericos = [(t, n) for t, n in df.items()
                 if t not in STOPWORDS and min_df <= n <= techo]
    genericos.sort(key=lambda kv: (-kv[1], kv[0]))
    genericos = genericos[:top]

    # Terminos de proyecto: siempre que existan en alguna huerfana
    ya = {t for t, _ in genericos}
    de_proyecto = [(t, df[t]) for t in vocab
                   if t in df and t not in ya]
    de_proyecto.sort(key=lambda kv: (-kv[1], kv[0]))

    todos = sorted(genericos + de_proyecto, key=lambda kv: (-kv[1], kv[0]))
    return {
        "total_huerfanas": total,
        "techo_df": techo,
        "proyectos_sembrados": sorted(set(vocab.values())),
        "terminos": [
            {
                "t": t,
                "n": n,
                "es_proyecto": t in vocab,
                "proyecto": vocab.get(t),
            }
            for t, n in todos
        ],
    }


def notes_for_term(base_vault: Path, term: str, limit: int = 200) -> dict:
    """Notas huérfanas que contienen el término. Para el panel de detalle."""
    base_vault = Path(base_vault)
    merged = base_vault / "MERGED_VAULT"
    term_n = _norm(term.strip())
    notas: List[dict] = []
    total = 0
    for f, fm in iter_orphans(merged):
        try:
            body = _strip_frontmatter(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        titulo_fm = (fm.get("title") or f.stem).strip().strip('"')
        if term_n in (set(_raw_tokens(body)) | set(_raw_tokens(titulo_fm))):
            total += 1
            if len(notas) < limit:
                notas.append({
                    "titulo": (fm.get("title") or f.stem).strip().strip('"'),
                    "fecha": (fm.get("date") or "").strip(),
                    "provider": (fm.get("provider") or "chatgpt").strip().strip('"'),
                    "ruta": str(f.relative_to(merged)),
                })
    notas.sort(key=lambda x: x["fecha"], reverse=True)
    return {"termino": term, "total": total, "notas": notas}


def load_topic_map(path: Path) -> Dict[str, List[str]]:
    """{tema: [palabras/frases]}. Tolerante: si falta o esta corrupto,
    devuelve {} y el generador simplemente no produce nada."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
        return {
            str(k).strip(): [str(w).strip() for w in v if str(w).strip()]
            for k, v in raw.items()
            if isinstance(v, list) and str(k).strip()
        }
    except (OSError, ValueError):
        return {}


def _slug_tema(nombre: str) -> str:
    s = _norm(nombre)
    s = re.sub(r"[^a-z0-9\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1]+", "-", s).strip("-")
    return s or "tema"


def generate_topic_index(base_vault: Path, topic_map_path: Path,
                         subdir: str = "_Temas") -> dict:
    """Genera una nota por tema en MERGED_VAULT/_Temas con wiki-links a las
    huerfanas que contienen alguna de sus palabras (token exacto) o frases
    (subcadena sobre texto normalizado).

    Todo lo generado es DERIVADO y regenerable: las notas de conversacion no
    se tocan, y solo se borran notas de tema que lleven la marca
    generated_by: m3m0ria (jamas material propio de V0ra que viva en la
    misma carpeta).

    OJO (i18n fase 3a): esa marca es un par escritor<->lector con la limpieza
    del final de esta misma funcion. Si se traduce una y no la otra, la
    limpieza deja de reconocer sus propias notas y quedan colgando para
    siempre. Las notas escritas por la edicion espanola llevan la marca
    vieja (generado_por:) y esta version ya no las reconoce -- documentado
    en el README: hay que borrar el arbol viejo a mano."""
    base_vault = Path(base_vault)
    merged = base_vault / "MERGED_VAULT"
    out_dir = merged / subdir
    temas = load_topic_map(topic_map_path)
    stats = {"temas": 0, "enlaces": 0, "borradas": 0, "sin_coincidencias": []}
    if not temas:
        return stats
    out_dir.mkdir(parents=True, exist_ok=True)

    # Un solo escaneo de huerfanas: tokens exactos (cuerpo + titulo),
    # cuerpo normalizado y frontmatter normalizado para reglas campo=valor
    huerfanas = []  # (stem, fecha, provider, titulo, tokens, cuerpo_norm, fm_norm)
    for f, fm in iter_orphans(merged):
        try:
            body = _strip_frontmatter(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        titulo = (fm.get("title") or f.stem).strip().strip('"')
        toks = set(_raw_tokens(body))
        # El titulo participa en el matching (decision V0ra 2026-07-18):
        # es senal densa y el cuerpo no lo repite. Solo title; el resto del
        # frontmatter entra unicamente via reglas explicitas campo=valor.
        toks.update(_raw_tokens(titulo))
        fm_norm = {
            str(k).strip().lower(): _norm(str(v).strip().strip('"'))
            for k, v in fm.items()
        }
        huerfanas.append((
            f.stem,
            (fm.get("date") or "").strip(),
            (fm.get("provider") or "chatgpt").strip().strip('"'),
            titulo,
            toks,
            _norm(body) + " " + _norm(titulo),
            fm_norm,
        ))

    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    generadas = set()
    stems_con_tema = set()
    stems_contenido = set()
    temas_detalle: Dict[str, dict] = {}
    for tema, palabras in sorted(temas.items()):
        # Tema estructural: TODAS sus palabras son reglas campo=valor (redes
        # por metadatos). Los mixtos cuentan como contenido.
        es_estructural = all("=" in _norm(p) for p in palabras)
        matches = []
        for stem, fecha, prov, titulo, toks, cuerpo, fm_norm in huerfanas:
            for p in palabras:
                pn = _norm(p)
                if "=" in pn:
                    # Regla estructural campo=valor contra el frontmatter
                    # (p.ej. source=claude_export, provider=grok)
                    campo, _, valor = pn.partition("=")
                    if fm_norm.get(campo.strip()) == valor.strip():
                        matches.append((fecha, prov, titulo, stem))
                        stems_con_tema.add(stem)
                        break
                elif (" " in pn and pn in cuerpo) or (" " not in pn and pn in toks):
                    matches.append((fecha, prov, titulo, stem))
                    stems_con_tema.add(stem)
                    stems_contenido.add(stem)
                    break
        matches.sort(reverse=True)
        slug = _slug_tema(tema)
        generadas.add(slug)
        lineas = [
            "---",
            f'title: "Topic: {tema}"',
            "type: topic",
            "generated_by: m3m0ria",
            f"generated: {ahora}",
            f'keywords: "{", ".join(palabras)}"',
            "---",
            "",
            f"# Topic: {tema}",
            "",
            f"{len(matches)} related orphan conversations "
            f"(keywords: {', '.join(palabras)}).",
            "",
        ]
        for fecha, prov, titulo, stem in matches:
            lineas.append(f"- [[{stem}]] — {fecha} · {prov} · {titulo}")
        (out_dir / f"{slug}.md").write_text(
            "\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
        stats["temas"] += 1
        stats["enlaces"] += len(matches)
        temas_detalle[tema] = {"enlaces": len(matches), "estructural": es_estructural}
        if not matches:
            stats["sin_coincidencias"].append(tema)

    # Puntos ciegos de la cartografia, en dos capas (decision V0ra 2026-07-19):
    # - "sin ningun tema": ni contenido ni estructural. Con redes por proveedor
    #   deberia rondar cero -> funciona como detector de anomalias de frontmatter.
    # - "solo estructural": pescadas unicamente por redes campo=valor. Es la
    #   lista de trabajo real: se sabe de donde vienen pero no de que hablan.
    sin_nada = [(fecha, prov, titulo, stem)
                for stem, fecha, prov, titulo, _t, _c, _f in huerfanas
                if stem not in stems_con_tema]
    sin_nada.sort(reverse=True)
    solo_estructural = [(fecha, prov, titulo, stem)
                        for stem, fecha, prov, titulo, _t, _c, _f in huerfanas
                        if stem in stems_con_tema and stem not in stems_contenido]
    solo_estructural.sort(reverse=True)
    total_h = len(huerfanas)
    stats["huerfanas_sin_tema"] = len(sin_nada)
    stats["huerfanas_solo_estructural"] = len(solo_estructural)
    stats["total_huerfanas"] = total_h
    stats["cobertura_contenido_pct"] = round(
        100.0 * len(stems_contenido & {h[0] for h in huerfanas}) / total_h, 1) if total_h else 0.0
    lineas = [
        "---",
        'title: "No topic (pending orphans)"',
        "type: topic",
        "generated_by: m3m0ria",
        f"generated: {ahora}",
        "---",
        "",
        "# Blind spots in the cartography",
        "",
        f"## Caught by nothing at all ({len(sin_nada)})",
        "",
        "Neither content topics nor structural nets catch these. With per-provider",
        "nets active this should be close to zero: anything showing up here is",
        "usually a frontmatter anomaly worth a look.",
        "",
    ]
    for fecha, prov, titulo, stem in sin_nada:
        lineas.append(f"- [[{stem}]] — {fecha} · {prov} · {titulo}")
    lineas += [
        "",
        f"## Caught only by structural nets ({len(solo_estructural)})",
        "",
        "We know which provider they came from, but no content topic touches them:",
        "the cartography that is genuinely still pending.",
        "",
    ]
    for fecha, prov, titulo, stem in solo_estructural:
        lineas.append(f"- [[{stem}]] — {fecha} · {prov} · {titulo}")
    (out_dir / "_sin-tema.md").write_text(
        "\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
    generadas.add("_sin-tema")

    # Resumen legible por maquina para vault_stats/dashboard (atomico, oculto
    # de Obsidian por el punto inicial)
    resumen = {
        "generado": ahora,
        "temas": temas_detalle,
        "total_huerfanas": total_h,
        "huerfanas_sin_tema": len(sin_nada),
        "huerfanas_solo_estructural": len(solo_estructural),
        "cobertura_contenido_pct": stats["cobertura_contenido_pct"],
    }
    p_stats = out_dir / ".temas_stats.json"
    tmp = p_stats.with_name(p_stats.name + ".tmp")
    tmp.write_text(json.dumps(resumen, ensure_ascii=False, indent=2),
                   encoding="utf-8", newline="\n")
    tmp.replace(p_stats)


    # Retirar notas de tema generadas por m3m0ria que ya no esten en el mapa
    for f in out_dir.glob("*.md"):
        if f.stem in generadas:
            continue
        fm = read_frontmatter(f)
        if (fm.get("generated_by") or "").strip().strip('"') == "m3m0ria":
            try:
                f.unlink()
                stats["borradas"] += 1
            except OSError:
                pass
    return stats


def main():
    ap = argparse.ArgumentParser(description="Nube de palabras de conversaciones huérfanas (Fase 1, solo lectura).")
    ap.add_argument("base_vault")
    ap.add_argument("--prj-vault-name", default="PRJ_VAULT")
    ap.add_argument("--gizmo-map", default=None)
    ap.add_argument("--exports-dir", default=None)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--term", help="En vez de la nube, lista las notas que contienen este término")
    ap.add_argument("--generate-topics", action="store_true",
                    help="Genera el indice de temas en MERGED_VAULT/_Temas a partir del topic map")
    ap.add_argument("--topic-map", default="topic_map.json",
                    help="Ruta al topic_map.json (por defecto, junto al script)")
    args = ap.parse_args()

    if args.generate_topics:
        stats = generate_topic_index(Path(args.base_vault), Path(args.topic_map))
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return

    if args.term:
        print(json.dumps(notes_for_term(Path(args.base_vault), args.term), ensure_ascii=False, indent=2))
    else:
        gm = Path(args.gizmo_map) if args.gizmo_map else None
        ed = Path(args.exports_dir) if args.exports_dir else None
        print(json.dumps(build_cloud(Path(args.base_vault), args.prj_vault_name, gm, ed, args.top),
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
