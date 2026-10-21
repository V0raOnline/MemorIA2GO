# -*- coding: utf-8 -*-
"""Galeria de las imagenes generadas de ChatGPT, con miniaturas.

Las miniaturas las genera una herramienta externa: `thmbnail_<nombre>.png` por cada
imagen, y el mismo nombre cuando la original es .webp. Con la carpeta presente, el
pipeline escribe ademas `CHATGPT/_indice_imagenes.md`: por mes, cada conversacion con
sus miniaturas (cada una enlaza al original) y la ruta de cada fichero como enlace.
El indice general (`_index_chatgpt.md`) NO cambia.

Lo que se vigila: que NO se incruste ningun original (es justo lo que pesaba, 782
imagenes y 1,7 GB en una sola nota), que cada enlace apunte a un fichero que existe
(Obsidian resuelve las rutas desde la raiz de SU vault: la galeria vive en CHATGPT/ y se
abre desde `02 Obsidian_vaults`, no desde MERGED_VAULT), y que ninguna imagen se pierda.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import content_index as ci
import MemorIA2GO

RAIZ = Path(__file__).resolve().parent.parent
BANCO = "CHATGPT/GENERADAS"
MINI = "CHATGPT/GENERADAS_Thmbnails"


def _nota(merged: Path, nombre: str, titulo: str, fecha: str, cuerpo: str):
    p = merged / "Conversaciones" / nombre
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'---\ntitle: "{titulo}"\ndate: {fecha}\n---\n\n{cuerpo}', encoding="utf-8")


def _vault(tmp_path: Path, imagenes, miniaturas, fecha="2026-07-01"):
    """Vault con una conversacion que referencia `imagenes`; `miniaturas` = nombres que existen."""
    base = tmp_path / "base"
    merged = base / "MERGED_VAULT"
    (base / BANCO).mkdir(parents=True)
    (base / MINI).mkdir(parents=True)
    for n in imagenes:
        (base / BANCO / n).write_bytes(b"original-pesado")
    for n in miniaturas:
        (base / MINI / n).write_bytes(b"mini")
    _nota(merged, "a.md", "Con imagenes", fecha, "".join(f"![]({BANCO}/{n})\n" for n in imagenes))
    return base, merged


def _galeria(base, merged, **kw):
    banco = ci.BankSpec(prefix=BANCO, label="Generadas", bank_dir=base / BANCO)
    return ci.generate_gallery(merged, "Conversaciones", "ChatGPT", banco, base / MINI, MINI,
                               kw.get("vault_prefix", "MERGED_VAULT"))


# ---- como se busca la miniatura --------------------------------------------------
def test_la_miniatura_de_un_png_lleva_el_prefijo():
    assert ci.miniatura_de("abc.png", {"thmbnail_abc.png": "thmbnail_abc.png"}) == "thmbnail_abc.png"


def test_la_de_una_webp_tiene_el_mismo_nombre():
    assert ci.miniatura_de("abc.webp", {"abc.webp": "abc.webp"}) == "abc.webp"


def test_el_prefijo_vale_para_cualquier_extension_de_la_original():
    assert ci.miniatura_de("abc.jpg", {"thmbnail_abc.png": "thmbnail_abc.png"}) == "thmbnail_abc.png"


def test_no_distingue_mayusculas_y_devuelve_el_nombre_real():
    assert ci.miniatura_de("ABC.png", {"thmbnail_abc.png": "Thmbnail_ABC.png"}) == "Thmbnail_ABC.png"


def test_sin_miniatura_es_none():
    assert ci.miniatura_de("abc.png", {"thmbnail_otra.png": "thmbnail_otra.png"}) is None
    assert ci.miniatura_de("abc.png", {}) is None


def test_la_carpeta_de_miniaturas_ausente_no_rompe(tmp_path):
    assert ci.miniaturas_existentes(None) == {}
    assert ci.miniaturas_existentes(tmp_path / "no_existe") == {}


# ---- la galeria ---------------------------------------------------------------------
def test_la_imagen_sale_como_miniatura_enlazada_al_original(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    md = _galeria(base, merged)["markdown"]
    assert f"[![]({MINI}/thmbnail_abc.png)]({BANCO}/abc.png)" in md


def test_no_se_incrusta_ningun_original(tmp_path):
    """Es la razon de ser de todo esto."""
    base, merged = _vault(tmp_path, ["a.png", "b.png"], ["thmbnail_a.png", "thmbnail_b.png"])
    md = _galeria(base, merged)["markdown"]
    assert re.findall(rf"(?<!\[)!\[\]\({re.escape(BANCO)}/", md) == []


def test_la_ubicacion_de_cada_fichero_va_como_enlace(tmp_path):
    base, merged = _vault(tmp_path, ["a.png", "b.png"], ["thmbnail_a.png", "thmbnail_b.png"])
    md = _galeria(base, merged)["markdown"]
    assert f"📂 [a.png]({BANCO}/a.png) · [b.png]({BANCO}/b.png)" in md


def test_la_conversacion_va_enlazada_con_la_ruta_desde_la_raiz_del_vault_de_obsidian(tmp_path):
    """La galeria vive en CHATGPT/, fuera de MERGED_VAULT: un wikilink sin el prefijo no resolveria."""
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    md = _galeria(base, merged)["markdown"]
    assert "[[MERGED_VAULT/Conversaciones/a|Con imagenes]]" in md
    assert "2026-07-01 — [[" in md


def test_las_imagenes_se_agrupan_por_mes_con_su_cuenta(tmp_path):
    base, merged = _vault(tmp_path, ["a.png", "b.png"], ["thmbnail_a.png", "thmbnail_b.png"], fecha="2026-07-01")
    _nota(merged, "b.md", "Otra", "2026-03-15", f"![]({BANCO}/c.png)\n")
    (base / BANCO / "c.png").write_bytes(b"x")
    (base / MINI / "thmbnail_c.png").write_bytes(b"x")
    md = _galeria(base, merged)["markdown"]
    assert "<summary><strong>2026-07 (2)</strong></summary>" in md
    assert "<summary><strong>2026-03 (1)</strong></summary>" in md
    assert md.index("2026-07 (2)") < md.index("2026-03 (1)"), "lo mas reciente va primero"


def test_una_imagen_sin_miniatura_no_se_cuela_a_tamano_completo(tmp_path):
    base, merged = _vault(tmp_path, ["con.png", "sin.png"], ["thmbnail_con.png"])
    r = _galeria(base, merged)
    assert f"[sin.png]({BANCO}/sin.png) _(sin miniatura)_" in r["markdown"]
    assert f"![]({BANCO}/sin.png)" not in r["markdown"]
    assert "thmbnail_sin" not in r["markdown"]
    assert "1 sin miniatura" in r["markdown"]
    assert r["stats"]["sin_miniatura"] == 1 and r["stats"]["con_miniatura"] == 1


def test_las_imagenes_del_banco_que_ninguna_nota_enlaza_no_se_pierden(tmp_path):
    base, merged = _vault(tmp_path, ["a.png"], ["thmbnail_a.png", "thmbnail_huerfana.png"])
    (base / BANCO / "huerfana.png").write_bytes(b"x")
    r = _galeria(base, merged)
    assert "<summary><strong>Sin conversacion (1)</strong></summary>" in r["markdown"]
    assert f"[![]({MINI}/thmbnail_huerfana.png)]({BANCO}/huerfana.png)" in r["markdown"]
    assert r["stats"]["sin_conversacion"] == 1 and r["stats"]["imagenes"] == 2


def test_lo_que_no_es_imagen_no_entra_en_la_galeria(tmp_path):
    base, merged = _vault(tmp_path, ["a.png"], ["thmbnail_a.png"])
    (base / BANCO / "_image_manifest.json").write_text("{}", encoding="utf-8")
    (base / BANCO / "notas.txt").write_text("x", encoding="utf-8")
    r = _galeria(base, merged)
    assert r["stats"]["imagenes"] == 1 and "notas.txt" not in r["markdown"]


def test_un_enlace_a_un_fichero_que_no_es_imagen_no_entra_ni_cuenta_como_conversacion(tmp_path):
    base, merged = _vault(tmp_path, ["a.png"], ["thmbnail_a.png"])
    (base / BANCO / "informe.pdf").write_bytes(b"x")
    _nota(merged, "b.md", "Con un pdf", "2026-07-02", f"[informe]({BANCO}/informe.pdf)\n")
    r = _galeria(base, merged)
    assert "informe.pdf" not in r["markdown"]
    assert r["stats"]["conversaciones"] == 1 and r["stats"]["imagenes"] == 1


def test_todos_los_enlaces_apuntan_a_ficheros_que_existen(tmp_path):
    nombres = ["a.png", "b.webp", "c.png"]
    base, merged = _vault(tmp_path, nombres, ["thmbnail_a.png", "b.webp", "thmbnail_c.png"])
    md = _galeria(base, merged)["markdown"]
    pares = re.findall(r"\[!\[\]\(([^)]+)\)\]\(([^)]+)\)", md)
    assert len(pares) == 3
    for mini, orig in pares:
        assert (base / mini).is_file(), mini
        assert (base / orig).is_file(), orig
    for ubicacion in re.findall(r"📂 (.+)", md):
        for ruta in re.findall(r"\]\(([^)]+)\)", ubicacion):
            assert (base / ruta).is_file(), ruta


def test_una_ruta_con_espacios_no_corta_el_enlace(tmp_path):
    base, merged = _vault(tmp_path, ["mi foto.png"], ["thmbnail_mi foto.png"])
    md = _galeria(base, merged)["markdown"]
    assert f"[![]({MINI}/thmbnail_mi%20foto.png)]({BANCO}/mi%20foto.png)" in md


def test_el_resumen_cuenta_imagenes_y_conversaciones(tmp_path):
    base, merged = _vault(tmp_path, ["a.png", "b.png"], ["thmbnail_a.png", "thmbnail_b.png"])
    assert "_2 imagenes · 1 conversaciones_" in _galeria(base, merged)["markdown"]


def test_una_conversacion_sin_fecha_va_a_su_propio_grupo(tmp_path):
    base, merged = _vault(tmp_path, ["a.png"], ["thmbnail_a.png"], fecha="")
    assert "<summary><strong>sin fecha (1)</strong></summary>" in _galeria(base, merged)["markdown"]


# ---- el indice general no cambia -------------------------------------------------------
def test_el_indice_general_sigue_incrustando_como_siempre(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    banco = ci.BankSpec(prefix=BANCO, label="Generadas", bank_dir=base / BANCO)
    md = ci.generate_provider_index(merged, "Conversaciones", "ChatGPT", [banco])["markdown"]
    assert f"![]({BANCO}/abc.png)" in md
    assert "📂" not in md and "thmbnail" not in md


# ---- la linea de comandos -------------------------------------------------------------
def _cli(base, merged, *extra, banco=f"{BANCO}:Generadas"):
    return subprocess.run(
        [sys.executable, str(RAIZ / "content_index.py"), str(merged), "--base-vault", str(base),
         "--conversations-dir", "Conversaciones", "--proveedor", "ChatGPT", "--out", "_indice_imagenes.md",
         "--banco", banco, *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RAIZ)


def test_cli_escribe_la_galeria_en_la_carpeta_pedida_y_no_en_el_vault(tmp_path):
    base, merged = _vault(tmp_path, ["a.png", "b.png"], ["thmbnail_a.png"])
    r = _cli(base, merged, "--galeria", "--miniaturas", f"{BANCO}={MINI}", "--out-dir", str(base / "CHATGPT"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (base / "CHATGPT" / "_indice_imagenes.md").is_file()
    assert not (merged / "_indice_imagenes.md").exists()
    assert "2 imagenes en 1 conversaciones (1 con miniatura, 1 sin ella, 0 sin conversacion)" in r.stdout
    md = (base / "CHATGPT" / "_indice_imagenes.md").read_text(encoding="utf-8")
    assert "[[MERGED_VAULT/Conversaciones/a|Con imagenes]]" in md


def test_cli_galeria_sin_miniaturas_pide_el_argumento(tmp_path):
    base, merged = _vault(tmp_path, ["a.png"], ["thmbnail_a.png"])
    r = _cli(base, merged, "--galeria")
    assert r.returncode != 0 and "--miniaturas" in (r.stdout + r.stderr)


def test_cli_galeria_con_una_carpeta_que_no_existe_se_niega(tmp_path):
    base, merged = _vault(tmp_path, ["a.png"], [])
    r = _cli(base, merged, "--galeria", "--miniaturas", f"{BANCO}=CHATGPT/NO_EXISTE")
    assert r.returncode != 0 and "no existe la carpeta de miniaturas" in (r.stdout + r.stderr)
    assert not (merged / "_indice_imagenes.md").exists()


def test_cli_galeria_de_un_banco_que_no_esta_entre_los_banco_se_niega(tmp_path):
    base, merged = _vault(tmp_path, ["a.png"], ["thmbnail_a.png"])
    r = _cli(base, merged, "--galeria", "--miniaturas", f"OTRO/BANCO={MINI}")
    assert r.returncode != 0 and "no esta entre los --banco" in (r.stdout + r.stderr)


def test_cli_sin_galeria_escribe_en_el_vault_como_siempre(tmp_path):
    base, merged = _vault(tmp_path, ["a.png"], ["thmbnail_a.png"])
    r = _cli(base, merged)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (merged / "_indice_imagenes.md").is_file()


# ---- el pipeline ------------------------------------------------------------------------
def test_el_paso_4_escribe_la_galeria_si_existe_la_carpeta_de_miniaturas(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    MemorIA2GO.paso4_indices(base, merged, None, tmp_path / "log.txt")
    galeria = base / "CHATGPT" / "_indice_imagenes.md"
    assert galeria.is_file()
    assert f"[![]({MINI}/thmbnail_abc.png)]({BANCO}/abc.png)" in galeria.read_text(encoding="utf-8")


def test_el_paso_4_deja_el_indice_general_como_siempre(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    MemorIA2GO.paso4_indices(base, merged, None, tmp_path / "log.txt")
    general = (merged / "_index_chatgpt.md").read_text(encoding="utf-8")
    assert f"![]({BANCO}/abc.png)" in general and "thmbnail" not in general


def test_el_paso_4_sin_la_carpeta_de_miniaturas_no_escribe_galeria(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], [])
    shutil.rmtree(base / MINI)
    log = tmp_path / "log.txt"
    MemorIA2GO.paso4_indices(base, merged, None, log)
    assert not (base / "CHATGPT" / "_indice_imagenes.md").exists()
    assert "miniaturas" not in (log.read_text(encoding="utf-8") if log.exists() else "")


def test_el_paso_4_no_escribe_la_galeria_dentro_del_vault_de_conversaciones(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    MemorIA2GO.paso4_indices(base, merged, None, tmp_path / "log.txt")
    assert not (merged / "_indice_imagenes.md").exists()


def test_el_paso_4_con_vault_de_proyectos_escribe_la_galeria_una_sola_vez(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    prj = base / "PRJ_VAULT"
    (prj / "P" / "2026" / "07").mkdir(parents=True)
    (prj / "P" / "2026" / "07" / "a.md").write_text(
        '---\ntitle: "Con imagenes"\ndate: 2026-07-01\n---\n\n![](CHATGPT/GENERADAS/abc.png)\n', encoding="utf-8")
    MemorIA2GO.paso4_indices(base, merged, prj, tmp_path / "log.txt")
    md = (base / "CHATGPT" / "_indice_imagenes.md").read_text(encoding="utf-8")
    assert "[[MERGED_VAULT/Conversaciones/a|Con imagenes]]" in md, "la galeria debe salir del vault fusionado"
    assert "PRJ_VAULT" not in md
