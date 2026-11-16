# -*- coding: utf-8 -*-
"""Test de regresion de vault_merge.py (backlog CONTEXT.md #1).

Cubre la resolucion de renombrados de hilo: dos notas RAW con el mismo
conv_id pero titulos distintos deben fusionarse en UNA sola nota MERGED,
con el titulo mas reciente y el viejo conservado en titulo_original.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import vault_merge as vm

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_raw_note(path: Path, *, conv_id, title, date, suffix, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    front = (
        "---\n"
        f'title: "{title}"\n'
        f"date: {date}\n"
        "source: chatgpt_export\n"
        f"conv_id: {conv_id}\n"
        "---\n\n"
    )
    body = (
        f"### User\n\nPregunta {suffix}\n\n"
        f"### Assistant\n\nRespuesta {suffix}\n"
    )
    path.write_text(front + body, encoding="utf-8", newline="")
    os.utime(path, (mtime, mtime))


def test_merge_resuelve_renombrado_y_conserva_titulo_original(tmp_path):
    raw_conv = tmp_path / "RAW_VAULT" / "Conversaciones"
    merged_dir = tmp_path / "MERGED_VAULT"

    now = time.time()
    _write_raw_note(
        raw_conv / "2026-06-01_titulo-viejo.md",
        conv_id="abc123", title="Titulo viejo", date="2026-06-01",
        suffix="uno", mtime=now - 1000,
    )
    _write_raw_note(
        raw_conv / "2026-06-01_titulo-nuevo.md",
        conv_id="abc123", title="Titulo nuevo", date="2026-06-01",
        suffix="dos", mtime=now - 500,
    )

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "vault_merge.py"),
         str(tmp_path / "RAW_VAULT"), str(merged_dir), "--merge"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    out_dir = merged_dir / "Conversaciones"
    notas = list(out_dir.glob("*.md"))
    assert len(notas) == 1, f"se esperaba 1 nota fusionada, hay: {[n.name for n in notas]}"

    front, messages = vm.read_note(str(notas[0]))
    assert front.get("title", "").strip('"') == "Titulo nuevo"
    assert front.get("titulo_original", "").strip('"') == "Titulo viejo"

    contenido = " ".join(m["content"] for m in messages)
    assert "Pregunta uno" in contenido
    assert "Pregunta dos" in contenido


def test_merge_no_pisa_dos_conversaciones_distintas_mismo_titulo(tmp_path):
    """Bug 1b: dos conversaciones DISTINTAS (conv_id distinto) con el mismo
    titulo y fecha producian el mismo nombre de salida y la segunda pisaba a
    la primera -- una no llegaba a MERGED (15 reales en el vault de V0ra). En
    RAW se distinguen por el sufijo de hash de contenido; base_name lo quita y
    ambas caian en el mismo fichero. Ahora la identidad (conv_id) llega al
    nombre via un fragmento: salen dos notas, ninguna se pierde."""
    raw_conv = tmp_path / "RAW_VAULT" / "Conversaciones"
    merged_dir = tmp_path / "MERGED_VAULT"

    now = time.time()
    # Mismos titulo y fecha, conv_id distinto; en RAW se distinguen por -hXXXX.
    _write_raw_note(
        raw_conv / "2026-06-01_formacion-de-la-tierra-h11111111.md",
        conv_id="conv-AAA", title="Formacion de la Tierra", date="2026-06-01",
        suffix="alfa", mtime=now - 1000,
    )
    _write_raw_note(
        raw_conv / "2026-06-01_formacion-de-la-tierra-h22222222.md",
        conv_id="conv-BBB", title="Formacion de la Tierra", date="2026-06-01",
        suffix="beta", mtime=now - 500,
    )

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "vault_merge.py"),
         str(tmp_path / "RAW_VAULT"), str(merged_dir), "--merge"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    notas = list((merged_dir / "Conversaciones").rglob("*.md"))
    assert len(notas) == 2, \
        f"las dos conversaciones deben sobrevivir, hay: {[n.name for n in notas]}"

    # Ningun contenido se pisa: los dos cuerpos estan presentes.
    contenidos = "\n".join(n.read_text(encoding="utf-8") for n in notas)
    assert "Pregunta alfa" in contenidos
    assert "Pregunta beta" in contenidos

    # Cada nota conserva su identidad real (conv_id) en el frontmatter.
    ids = {vm.read_note(str(n))[0].get("conv_id", "").strip('"') for n in notas}
    assert ids == {"conv-AAA", "conv-BBB"}

    # Y el desambiguador es un fragmento derivado de la identidad (misma familia
    # que el nombre-por-hash de RAW), no un contador dependiente del orden.
    assert all(" · " in n.stem for n in notas)


# ---------- avisos de imagen frente a enlaces (2026-11-16, ver REPARSEAME.md) ----------

def _nota_imagen(path: Path, conv_id, cuerpo_tool, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('---\ntitle: "Imagenes"\ndate: 2026-01-01\nsource: chatgpt_export\n'
                    f"conv_id: {conv_id}\n---\n\n### User\n\ndibuja\n\n### Tool\n\n{cuerpo_tool}\n",
                    encoding="utf-8", newline="")
    os.utime(path, (mtime, mtime))


def _fusionar(tmp_path):
    r = subprocess.run([sys.executable, str(REPO_ROOT / "vault_merge.py"), str(tmp_path / "RAW_VAULT"),
                        str(tmp_path / "MERGED_VAULT"), "--merge", "--base-vault", str(tmp_path)],
                       capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30)
    assert r.returncode == 0, r.stderr
    notas = list((tmp_path / "MERGED_VAULT" / "Conversaciones").glob("*.md"))
    assert len(notas) == 1
    return notas[0].read_text(encoding="utf-8")


def _banco(tmp_path, punteros):
    import json
    import layout
    lay = layout.cargar(tmp_path)
    raiz = lay.ruta(tmp_path, "chatgpt.raiz")
    for enlace in punteros.values():
        f = tmp_path.joinpath(*enlace.split("/"))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"png")
    raiz.mkdir(parents=True, exist_ok=True)
    (raiz / "_punteros_imagenes.json").write_text(json.dumps(punteros), encoding="utf-8")


def test_aviso_y_enlace_de_la_misma_imagen_son_el_mismo_mensaje(tmp_path):
    import layout
    enlace = layout.cargar(tmp_path).enlace("chatgpt.generadas", "abc.png")
    raw = tmp_path / "RAW_VAULT" / "Conversaciones"
    now = time.time()
    _nota_imagen(raw / "2026-01-01_imagenes.md", "c1", "*[imagen no disponible en el export: sediment://file_A]*", now)
    _nota_imagen(raw / "2026-01-01_imagenes-h1.md", "c1", f"![]({enlace})", now - 10)
    _banco(tmp_path, {"sediment://file_A": enlace})
    texto = _fusionar(tmp_path)
    assert texto.count("![](") == 1 and "imagen no disponible" not in texto


def test_sin_fichero_en_el_banco_el_aviso_se_queda(tmp_path):
    import json
    import layout
    lay = layout.cargar(tmp_path)
    raw = tmp_path / "RAW_VAULT" / "Conversaciones"
    _nota_imagen(raw / "2026-01-01_imagenes.md", "c1", "*[imagen no disponible en el export: sediment://file_A]*", time.time())
    lay.ruta(tmp_path, "chatgpt.raiz").mkdir(parents=True, exist_ok=True)
    (lay.ruta(tmp_path, "chatgpt.raiz") / "_punteros_imagenes.json").write_text(
        json.dumps({"sediment://file_A": lay.enlace("chatgpt.generadas", "noesta.png")}), encoding="utf-8")
    assert "imagen no disponible en el export: sediment://file_A" in _fusionar(tmp_path)


def test_dos_imagenes_distintas_no_se_funden(tmp_path):
    import layout
    lay = layout.cargar(tmp_path)
    a, b = lay.enlace("chatgpt.generadas", "a.png"), lay.enlace("chatgpt.generadas", "b.png")
    raw = tmp_path / "RAW_VAULT" / "Conversaciones"
    now = time.time()
    _nota_imagen(raw / "2026-01-01_imagenes.md", "c1", f"![]({a})", now)
    _nota_imagen(raw / "2026-01-01_imagenes-h1.md", "c1", "*[imagen no disponible en el export: sediment://file_B]*", now - 10)
    _banco(tmp_path, {"sediment://file_A": a, "sediment://file_B": b})
    texto = _fusionar(tmp_path)
    assert f"![]({a})" in texto and f"![]({b})" in texto
