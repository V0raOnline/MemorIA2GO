#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
split_chatgpt_export.py — Export de ChatGPT → Markdown para Obsidian (Python 3.11+)

Incluye:
- --gizmo-map para mapear IDs a nombres (acepta claves g-*, g-p-* o HEX; lookup tolerante)
- --date-field create|update y --include-both-dates
- --force-project-id / --force-project y --project-tag
- Siempre escribe Project_name: "<nombre>" o "none"

Evita statements en una sola línea con ';' para máxima compatibilidad.
"""
import argparse
import datetime
import json
import os
import re
import sys
import zipfile
import hashlib
from typing import Any, Dict, List, Tuple

GENERIC_TITLES = {
    "", "conversación", "conversation", "new chat", "conversación nueva",
    "untitled", "sin título", "chat", "chatgpt conversation"
}

def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text or "sin-titulo"

def iso_date(ts: Any) -> str:
    try:
        if ts is None:
            return datetime.datetime.now().strftime("%Y-%m-%d")
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except Exception:
        return datetime.datetime.now().strftime("%Y-%m-%d")

def iso_date_or_none(ts: Any):
    try:
        if ts is None:
            return None
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except Exception:
        return None

def word_count(t: str) -> int:
    return len(re.findall(r"\w+", t or "", flags=re.UNICODE))

def smart_title(title: str, messages: List[Dict[str, str]], max_words: int = 8) -> str:
    t = (title or "").strip().lower()
    if not t or t in GENERIC_TITLES:
        for m in messages or []:
            if (m.get("role") or "").lower() == "user":
                txt = (m.get("content") or "").strip()
                if txt:
                    words = re.findall(r"\w+(?:['’]\w+)?|[^\w\s]", txt, flags=re.UNICODE)
                    cand = " ".join([w for w in words if w.strip()][:max_words]).strip()
                    return cand or "Conversación"
    return title or "Conversación"

def content_hash(s: str, n: int = 8) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()[:n]

def short_ts(dt: datetime.datetime) -> str:
    return dt.strftime("%Y%m%d%H%M")

def write_md(base_out_dir: str, title: str, date_str: str,
             messages: List[Dict[str, str]], tags: List[str],
             by_year: bool = False, by_month: bool = False,
             existing_policy: Dict[str, Any] | None = None,
             extra_front: Dict[str, Any] | None = None) -> Tuple[str, str]:
    y, m, _ = date_str.split("-")
    out_dir = base_out_dir
    if by_year:
        out_dir = os.path.join(out_dir, y)
    if by_month:
        out_dir = os.path.join(out_dir, m if by_year else f"{y}-{m}")
    ensure_dir(out_dir)

    fname = f"{date_str}_{slugify(title)[:80]}.md"
    path = os.path.join(out_dir, fname)

    lines: List[str] = []
    lines.append("---")
    safe_title = (title or "").replace('"', "'")
    lines.append(f'title: "{safe_title}"')
    lines.append(f"date: {date_str}")
    if tags:
        lines.append("tags: " + " ".join(tags))
    lines.append("source: chatgpt_export")
    if extra_front:
        for k, v in extra_front.items():
            if isinstance(v, str):
                lines.append(f'{k}: "{v}"')
            else:
                lines.append(f"{k}: {v}")
    lines.append("---\n")
    for msg in messages or []:
        role = (msg.get("role", "unknown") or "unknown").capitalize()
        content = (msg.get("content", "") or "").rstrip()
        lines.append(f"### {role}\n")
        lines.append(content + "\n")
    content_text = "\n".join(lines)

    policy = existing_policy or {}
    write_path = path

    if os.path.exists(write_path) and policy.get("skip_identical"):
        try:
            with open(write_path, "r", encoding="utf-8", errors="ignore") as f:
                before = f.read().strip()
            if before == content_text.strip():
                rel = os.path.relpath(write_path, base_out_dir).replace("\\", "/")
                return write_path, rel
        except Exception:
            pass

    if os.path.exists(write_path) and policy.get("keep_versions"):
        scheme = policy.get("version_scheme", "hash")
        if scheme == "timestamp":
            dt = policy.get("conv_dt") or datetime.datetime.now()
            base, ext = os.path.splitext(path)
            write_path = f"{base}-t{short_ts(dt)}{ext}"
            i = 2
            while os.path.exists(write_path):
                write_path = f"{base}-t{short_ts(dt)}-{i}{ext}"
                i += 1
        elif scheme == "hash":
            h = content_hash(content_text)
            base, ext = os.path.splitext(path)
            write_path = f"{base}-h{h}{ext}"
            i = 2
            while os.path.exists(write_path):
                write_path = f"{base}-h{h}-{i}{ext}"
                i += 1
        else:
            if policy.get("suffix_on_duplicate"):
                base, ext = os.path.splitext(path)
                i = 2
                while os.path.exists(write_path):
                    write_path = f"{base}-v{i}{ext}"
                    i += 1

    ensure_dir(os.path.dirname(write_path))
    with open(write_path, "w", encoding="utf-8") as f:
        f.write(content_text)

    rel = os.path.relpath(write_path, base_out_dir).replace("\\", "/")
    return write_path, rel

# ---------- parsing ----------

def norm_hex_id(s: str):
    if not s:
        return None
    s = s.strip().lower()
    m = re.search(r'(?:^g(?:-p)?-)?([0-9a-f]{32})$', s)
    return m.group(1) if m else None

def parse_json_conversations(obj: Any) -> List[Dict[str, Any]]:
    conversations: List[Dict[str, Any]] = []

    if isinstance(obj, dict) and "conversations" in obj and isinstance(obj["conversations"], list):
        raw = obj["conversations"]
    elif isinstance(obj, list):
        raw = obj
    else:
        raw = obj.get("items", []) if isinstance(obj, dict) else []

    for conv in raw:
        title = conv.get("title") or "Conversación"
        ct = conv.get("create_time") or conv.get("createTime")
        ut = conv.get("update_time") or conv.get("updateTime")
        gid = conv.get("gizmo_id") or conv.get("gizmoId")
        mapping = conv.get("mapping")
        messages: List[Dict[str, str]] = []

        if isinstance(mapping, dict):
            def node_time(n: Dict[str, Any]) -> float:
                try:
                    return float(n.get("message", {}).get("create_time") or 0)
                except Exception:
                    return 0.0

            nodes = [n for n in mapping.values() if isinstance(n, dict)]
            nodes.sort(key=node_time)
            for node in nodes:
                msg = node.get("message")
                if not msg:
                    continue
                author = (msg.get("author") or {}).get("role") or msg.get("role") or "unknown"
                c = msg.get("content")
                if isinstance(c, dict) and "parts" in c:
                    content = "\n".join(str(p) for p in c.get("parts") or [])
                elif isinstance(c, list):
                    content = "\n".join(str(p) for p in c)
                elif isinstance(c, str):
                    content = c
                else:
                    content = json.dumps(c, ensure_ascii=False)
                if (content or "").strip():
                    messages.append({"role": author, "content": content})
        else:
            msgs = conv.get("messages") or conv.get("items") or []
            for m in msgs:
                role = (m.get("author") or {}).get("role") or m.get("role") or "unknown"
                content = m.get("content") or ""
                if isinstance(content, dict) and "parts" in content:
                    content = "\n".join(content["parts"])
                messages.append({"role": role, "content": content})

        conversations.append({
            "title": title,
            "create_time": ct,
            "update_time": ut,
            "messages": messages,
            "gizmo_id": gid,
        })

    return conversations

def parse_html_export(html_text: str) -> List[Dict[str, Any]]:
    m = re.search(r'(\{.*?"conversations".*?\})', html_text, flags=re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            return parse_json_conversations(data)
        except Exception:
            pass

    try:
        from bs4 import BeautifulSoup  # type: ignore
        soup = BeautifulSoup(html_text, "htmlparser") if False else BeautifulSoup(html_text, "html.parser")
        convs: List[Dict[str, Any]] = []
        headers = soup.find_all(["h2", "h3"])
        for h in headers:
            title = h.get_text(strip=True) or "Conversación"
            body: List[str] = []
            for sib in h.find_all_next(["p", "pre", "code"]):
                if sib.name in ("h2", "h3"):
                    break
                body.append(sib.get_text("\n", strip=True))
            if body:
                alt = ["user", "assistant"]
                msgs = [{"role": alt[i % 2], "content": t} for i, t in enumerate(body)]
                convs.append({"title": title, "create_time": None, "update_time": None, "messages": msgs, "gizmo_id": None})
        if convs:
            return convs

        text = soup.get_text("\n", strip=True)
        parts = [p for p in text.splitlines() if p.strip()]
        alt = ["user", "assistant"]
        msgs = [{"role": alt[i % 2], "content": t} for i, t in enumerate(parts)]
        return [{"title": "Conversación", "create_time": None, "update_time": None, "messages": msgs, "gizmo_id": None}]
    except Exception:
        pass

    return []

def load_conversations(input_path: str) -> List[Dict[str, Any]]:
    p = os.path.abspath(input_path)
    if not os.path.exists(p):
        raise FileNotFoundError(f"No existe: {input_path}")

    ext = os.path.splitext(p)[1].lower()

    if ext == ".zip":
        with zipfile.ZipFile(p, "r") as z:
            json_name = None
            for name in z.namelist():
                if name.lower().endswith("conversations.json"):
                    json_name = name
                    break
            if json_name:
                with z.open(json_name) as f:
                    data = json.load(f)
                return parse_json_conversations(data)
            for name in z.namelist():
                if name.lower().endswith(".html"):
                    with z.open(name) as f:
                        html = f.read().decode("utf-8", errors="ignore")
                    return parse_html_export(html)
            raise RuntimeError("No se encontró conversations.json ni HTML dentro del ZIP.")

    if ext == ".json":
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return parse_json_conversations(data)

    if ext in (".html", ".htm"):
        with open(p, "r", encoding="utf-8") as f:
            html = f.read()
        return parse_html_export(html)

    raise RuntimeError("Formato no soportado. Usa .zip, .json o .html")

def main():
    ap = argparse.ArgumentParser(description="Divide exportaciones de ChatGPT en Markdown para Obsidian.")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--tag-map", default=None)
    ap.add_argument("--gizmo-map", default=None, help="JSON con id→nombre (g-*, g-p-* o hex) → slug/nombre")
    ap.add_argument("--make-index", action="store_true")
    ap.add_argument("--tag-indexes", action="store_true")
    ap.add_argument("--loose-html", action="store_true")
    ap.add_argument("--by-year", action="store_true")
    ap.add_argument("--by-month", action="store_true")
    ap.add_argument("--top-n", type=int, default=20)

    ap.add_argument("--date-field", choices=["create", "update"], default="create",
                    help="Elegir la fecha principal en el YAML (por defecto: create)")
    ap.add_argument("--include-both-dates", action="store_true",
                    help="Añade created/updated al YAML si existen")

    ap.add_argument("--keep-versions", action="store_true")
    ap.add_argument("--suffix-on-duplicate", action="store_true")
    ap.add_argument("--no-dedupe", action="store_true")
    ap.add_argument("--skip-identical", action="store_true",
                    help="Si el .md ya existe y el contenido sería idéntico, no crear versión nueva")
    ap.add_argument("--version-scheme", choices=["counter","timestamp","hash"], default="hash",
                    help="Esquema de versionado si colisiona el nombre (por defecto: hash)")
    ap.add_argument("--use-conv-timestamp", action="store_true",
                    help="En 'timestamp', usar create_time de la conversación si está disponible")

    ap.add_argument("--force-project-id", default=None, help="Forzar source_project_id si el export no trae gizmo_id")
    ap.add_argument("--force-project", default=None, help="Forzar source_project (nombre/slug)")
    ap.add_argument("--project-tag", action="store_true", help="Añade tag #project/<slug> si hay nombre")

    args = ap.parse_args()

    ensure_dir(args.output)

    tag_map: Dict[str, str] = {}
    if args.tag_map:
        try:
            with open(args.tag_map, "r", encoding="utf-8") as f:
                tag_map = json.load(f)
        except Exception as e:
            print("Advertencia: no pude cargar tag-map:", e)

    # Cargar mapa y expandir claves a todas las variantes (hex, g-, g-p-)
    gizmo_map: Dict[str, str] = {}
    if args.gizmo_map:
        try:
            with open(args.gizmo_map, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in raw.items():
                m = re.search(r'(?:^g(?:-p)?-)?([0-9a-f]{32})$', k.strip().lower())
                if not m:
                    continue
                hx = m.group(1)
                gizmo_map[hx] = v
                gizmo_map["g-" + hx] = v
                gizmo_map["g-p-" + hx] = v
        except Exception as e:
            print("Advertencia: no pude cargar gizmo_map:", e)

    conversations = load_conversations(args.input)
    if not conversations:
        print("No se encontraron conversaciones.")
        sys.exit(2)

    records: List[Dict[str, Any]] = []
    for conv in conversations:
        title = smart_title(conv.get("title"), conv.get("messages") or [])
        ct_raw = conv.get("create_time")
        ut_raw = conv.get("update_time")
        date_primary = iso_date(ct_raw)
        if args.date_field == "update" and ut_raw is not None:
            date_primary = iso_date(ut_raw)

        msgs = conv.get("messages") or []

        full_text = (title or "") + "\n" + "\n".join(m.get("content", "") for m in msgs)
        tags = []
        if tag_map:
            low = full_text.lower()
            for kw, tg in tag_map.items():
                if (kw or "").lower() in low:
                    tags.append(tg if str(tg).startswith("#") else f"#{tg}")

        # Resolver nombre de proyecto (si existe)
        gid = conv.get("gizmo_id") or conv.get("gizmoId")
        name_from_map = None
        if gid:
            hx = norm_hex_id(gid)
            name_from_map = gizmo_map.get(gid) or gizmo_map.get("g-" + (hx or "")) or gizmo_map.get("g-p-" + (hx or "")) or gizmo_map.get(hx or "")

        extra_front: Dict[str, Any] = {}
        # Añadir Project_name siempre
        extra_front["Project_name"] = name_from_map if name_from_map else "none"

        if args.force_project_id:
            extra_front["source_project_id"] = args.force_project_id
        elif gid:
            extra_front["source_project_id"] = gid

        if args.force_project:
            extra_front["source_project"] = args.force_project
        elif name_from_map:
            extra_front["source_project"] = name_from_map

        if args.include_both_dates:
            c = iso_date_or_none(ct_raw)
            u = iso_date_or_none(ut_raw)
            if c:
                extra_front["created"] = c
            if u:
                extra_front["updated"] = u

        if args.project_tag:
            slug = extra_front.get("source_project") or extra_front.get("Project_name")
            if slug and slug != "none":
                tg = f"#project/{slugify(slug)}"
                if tg not in tags:
                    tags.append(tg)

        existing_policy = {
            "keep_versions": args.keep_versions,
            "suffix_on_duplicate": args.suffix_on_duplicate,
            "skip_identical": args.skip_identical,
            "version_scheme": args.version_scheme,
            "conv_dt": datetime.datetime.fromtimestamp(float(ct_raw)) if (args.use_conv_timestamp and ct_raw) else None,
        }

        path, rel = write_md(
            args.output, title, date_primary, msgs, tags,
            by_year=args.by_year, by_month=args.by_month,
            existing_policy=existing_policy,
            extra_front=extra_front if extra_front else None,
        )

        words = sum(word_count(m.get("content", "")) for m in msgs)
        records.append({
            "date": date_primary, "title": title, "tags": tags,
            "relpath": rel, "count": len(msgs), "words": words
        })

    if args.make_index:
        path = os.path.join(args.output, "_index.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Índice de conversaciones\n\n")
            for r in records:
                f.write(f"- {r['date']} — [{r['title']}]({r['relpath']})\n")

    if args.tag_indexes:
        tag_dir = os.path.join(args.output, "_tags")
        ensure_dir(tag_dir)
        tag_map2: Dict[str, List[Dict[str, Any]]] = {}
        for r in records:
            for t in r.get("tags", []):
                key = t[1:] if t.startswith("#") else t
                tag_map2.setdefault(key, []).append(r)
        for tag, items in sorted(tag_map2.items()):
            p = os.path.join(tag_dir, f"{tag}.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# #{tag}\n\n")
                for it in items:
                    f.write(f"- [{it['title']}]({it['relpath']}) — {it['date']}\n")

    print(f"Listo. Exportadas {len(records)} conversaciones a: {args.output}")

if __name__ == "__main__":
    main()
