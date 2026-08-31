#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session_notes.py — Genera las tres notas enlazadas de una sesion de agente.

Consume el modelo que produce providers/claudecode_adapter.parse_* y escribe:
  - la NOTA MADRE: la conversacion, limpia y legible;
  - la NOTA DE RAZONAMIENTOS: los bloques de pensamiento, uno por turno;
  - la NOTA DE HERRAMIENTAS: cada llamada con su resultado.

Las hijas se enlazan desde la madre por BLOQUE (`^tN`), asi que el clic salta
al razonamiento o a las herramientas de ESE turno, no al principio de un muro.
Diseño cerrado en CONTEXT.md 3y.

Las hijas son CONDICIONALES: solo se crean si hay contenido. Una sesion sin
pensamiento visible no tiene nota de razonamientos, y la madre no la enlaza.

VERBOSIDAD (sobre el output de herramientas, no sobre la fuente):
  0 silencio · 1 traza (una linea por llamada) · 2 plegado (<details>) ·
  3 integro. La fuente cruda se preserva aparte (paso 3), asi que bajar la
  verbosidad no pierde nada: la nota es una vista regenerable.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

NIVEL_SILENCIO, NIVEL_TRAZA, NIVEL_PLEGADO, NIVEL_INTEGRO = 0, 1, 2, 3
_RECORTE_RESULTADO = 2000  # chars por resultado en nivel plegado


def _slug(texto: str, limite: int = 60) -> str:
    """Titulo -> nombre de fichero seguro y legible. Sin extension."""
    s = (texto or "sesion").strip().lower()
    s = s.replace("·", "").replace("/", "-")
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return (s or "sesion")[:limite]


def _fecha(epoch: Optional[float]) -> str:
    if not epoch:
        return "sin-fecha"
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")


def _recortar(s: str, n: int) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[:n] + "\n…[recortado; íntegro en la fuente de la sesión]"


def _primer_arg(inp: dict) -> str:
    """Un resumen de una linea de los argumentos de una herramienta, para la
    traza. Prioriza los campos que dicen 'que se toco'."""
    for k in ("command", "file_path", "pattern", "path", "url", "description"):
        v = inp.get(k)
        if v:
            return str(v).splitlines()[0][:100]
    for v in inp.values():
        if isinstance(v, str) and v.strip():
            return v.splitlines()[0][:100]
    return ""


def titulo(sesion: dict) -> str:
    """El titulo legible de una sesion. Muchas sesiones de Code no traen
    aiTitle; en ese caso, el primer prompt de la persona describe la sesion
    mejor que su UUID. Ultimo recurso: una etiqueta generica."""
    t = (sesion.get("title") or "").strip()
    if t:
        return t
    for turno in sesion.get("turns", []):
        if turno.get("role") == "user" and (turno.get("text") or "").strip():
            primero = turno["text"].strip().splitlines()[0]
            return primero[:70]
    return "Sesión de agente"


def nombres(sesion: dict) -> Dict[str, str]:
    """Los tres nombres de fichero (sin extension) de una sesion. Publico
    porque el que integre necesita saber como se llamaran para enlazar.

    El nombre lleva un trozo del session_id, y no es cosmetico: dos sesiones
    distintas del mismo dia con el mismo titulo (o sin titulo -- 4 sesiones de
    Codex del 2026-08-28 quedaban todas como 'sesion-de-agente') producirian el
    mismo nombre y una pisaria a la otra al escribir. La identidad es el
    session_id; que el nombre derive de ella evita la colision. Misma familia
    que el bug 1b del backlog."""
    sid = (sesion.get("session_id") or "").replace("-", "")[:8]
    base = "%s_%s" % (_fecha(sesion.get("create_time")), _slug(titulo(sesion)))
    if sid:
        base = "%s-%s" % (base, sid)
    return {
        "madre": base,
        "razonamientos": base + " · razonamientos",
        "herramientas": base + " · herramientas",
    }


def _turnos_asistente(sesion: dict):
    """Numera los turnos de asistente 1..N y dice si cada uno tiene
    pensamiento y/o herramientas. Es la numeracion compartida entre la madre y
    las hijas: el ancla ^tN tiene que coincidir en las tres notas."""
    n = 0
    for t in sesion.get("turns", []):
        if t.get("role") == "assistant":
            n += 1
            yield n, t


def _hay(sesion: dict, clave: str) -> bool:
    return any(t.get(clave) for _, t in _turnos_asistente(sesion))


def _fm(pares: List[tuple]) -> List[str]:
    out = ["---"]
    for k, v in pares:
        if v is None:
            continue
        out.append('%s: "%s"' % (k, str(v).replace('"', "'")))
    out.append("---")
    out.append("")
    return out


def _nota_madre(sesion: dict, nom: Dict[str, str], nivel: int,
                extra_madre: Optional[Dict[str, Any]] = None) -> str:
    # Nombres de campo del PIPELINE (title, date, provider), no propios, para
    # que la madre sea ciudadana de primera en Conversaciones/: Cartografia y
    # project_organizer leen esos campos. `extra_madre` lo rellena quien
    # ingesta (Project_name, source, conv_id): ver session_ingest.py.
    pares = [
        ("tipo", "sesion-agente"),
        ("title", titulo(sesion)),
        ("date", _fecha(sesion.get("create_time"))),
        ("provider", sesion.get("provider")),
        ("proyecto", sesion.get("project")),
        ("rama", sesion.get("git_branch")),
    ]
    for k, v in (extra_madre or {}).items():
        pares.append((k, v))
    L = _fm(pares)
    L += ["# %s" % titulo(sesion), "",
          "> Sesión de %s. La conversación va aquí; los razonamientos y las "
          "herramientas están en sus notas hermanas, enlazados turno a turno."
          % (sesion.get("provider") or "agente"), ""]

    an = 0
    for t in sesion.get("turns", []):
        if t.get("role") == "user":
            cuerpo = (t.get("text") or "").strip().replace("\n", "\n> ")
            L += ["> [!question] Prompt", "> " + cuerpo, ""]
            continue
        # asistente
        an += 1
        L.append((t.get("text") or "").strip())
        anclas = []
        if t.get("thinking"):
            anclas.append("[[%s#^t%d|pensó]]" % (nom["razonamientos"], an))
        if t.get("tools") and nivel > NIVEL_SILENCIO:
            anclas.append("[[%s#^t%d|%d herramienta(s)]]"
                          % (nom["herramientas"], an, len(t["tools"])))
        if anclas:
            L += ["", "`↳ " + "  ·  ".join(anclas) + "`"]
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def _nota_razonamientos(sesion: dict, nom: Dict[str, str]) -> str:
    L = _fm([("tipo", "razonamientos"), ("de", "[[%s]]" % nom["madre"])])
    L += ["# Razonamientos — %s" % titulo(sesion), "",
          "> Los bloques de pensamiento, por turno. Se llega desde la nota "
          "madre. Solo están los turnos en que el pensamiento estaba visible.",
          ""]
    for n, t in _turnos_asistente(sesion):
        if not t.get("thinking"):
            continue
        L += ["## Turno %d ^t%d" % (n, n), ""]
        for p in t["thinking"]:
            L += [p.strip(), ""]
    return "\n".join(L).rstrip() + "\n"


def _nota_herramientas(sesion: dict, nom: Dict[str, str], nivel: int) -> str:
    L = _fm([("tipo", "herramientas"), ("de", "[[%s]]" % nom["madre"])])
    etiqueta = {NIVEL_TRAZA: "una línea por llamada",
                NIVEL_PLEGADO: "resultado plegado",
                NIVEL_INTEGRO: "resultado íntegro"}.get(nivel, "")
    L += ["# Herramientas — %s" % titulo(sesion), "",
          "> Cada llamada con su resultado (%s). Se llega desde la nota madre."
          % etiqueta, ""]
    for n, t in _turnos_asistente(sesion):
        if not t.get("tools"):
            continue
        L += ["## Turno %d ^t%d" % (n, n), ""]
        for ll in t["tools"]:
            arg = _primer_arg(ll.get("input") or {})
            L.append("**`%s`** %s" % (ll.get("name") or "?", arg))
            res = (ll.get("result") or "").strip()
            if nivel == NIVEL_TRAZA or not res:
                L.append("")
            elif nivel == NIVEL_PLEGADO:
                L += ["", "<details><summary>resultado</summary>", "",
                      "```", _recortar(res, _RECORTE_RESULTADO), "```",
                      "", "</details>", ""]
            else:  # integro
                L += ["```", res, "```", ""]
    return "\n".join(L).rstrip() + "\n"


def generar_notas(sesion: dict, out_dir: Any, nivel: int = NIVEL_PLEGADO,
                  hijas_dir: Any = None,
                  extra_madre: Optional[Dict[str, Any]] = None) -> Dict[str, Path]:
    """Escribe las notas de una sesion. Devuelve {rol: ruta} de lo escrito (la
    madre siempre; las hijas si habia contenido).

    - out_dir: donde va la MADRE.
    - hijas_dir: donde van razonamientos y herramientas. Si es None, van a
      out_dir (comodo para pruebas). En el vault real se separan: la madre a
      Conversaciones/ y las hijas a un banco, para no contaminar el vocabulario
      de Cartografia con `git`, rutas y comandos (ver CONTEXT 3y).
    - extra_madre: frontmatter extra para la madre (Project_name, source...).
    """
    if not sesion or not sesion.get("turns"):
        return {}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dir_hijas = Path(hijas_dir) if hijas_dir is not None else out
    dir_hijas.mkdir(parents=True, exist_ok=True)
    nom = nombres(sesion)
    escritas: Dict[str, Path] = {}

    def _escribe(carpeta: Path, rol: str, texto: str):
        p = carpeta / (nom[rol] + ".md")
        p.write_text(texto, encoding="utf-8", newline="\n")
        escritas[rol] = p

    _escribe(out, "madre", _nota_madre(sesion, nom, nivel, extra_madre))
    if _hay(sesion, "thinking"):
        _escribe(dir_hijas, "razonamientos", _nota_razonamientos(sesion, nom))
    if _hay(sesion, "tools") and nivel > NIVEL_SILENCIO:
        _escribe(dir_hijas, "herramientas", _nota_herramientas(sesion, nom, nivel))
    return escritas
