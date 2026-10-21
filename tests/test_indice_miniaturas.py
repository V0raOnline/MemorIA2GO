# -*- coding: utf-8 -*-
"""Indice de ChatGPT con miniaturas de las imagenes generadas.

Las miniaturas las genera una herramienta externa: `thmbnail_<nombre>.png` por cada
imagen, y el mismo nombre cuando la original es .webp. Con la carpeta presente, el
banco de Generadas muestra la miniatura enlazada al original y su ubicacion como
enlace; sin ella, todo sigue como siempre.

Lo que se vigila: que NO se incruste el original (es justo lo que pesaba, 782 imagenes
y 1,7 GB en una sola nota), que cada enlace apunte a un fichero que existe, y que lo
que no tiene miniatura no se cuele a tamano completo.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

import content_index as ci
import MemorIA2GO

RAIZ = Path(__file__).resolve().parent.parent
BANCO = "CHATGPT/GENERADAS"
MINI = "CHATGPT/GENERADAS_Thmbnails"


def _nota(vault: Path, nombre: str, titulo: str, fecha: str, cuerpo: str):
    p = vault / "Conversaciones" / nombre
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'---\ntitle: "{titulo}"\ndate: {fecha}\n---\n\n{cuerpo}', encoding="utf-8")


def _vault(tmp_path: Path, imagenes, miniaturas):
    """Vault con una conversacion que referencia `imagenes`; `miniaturas` = nombres que existen."""
    base = tmp_path / "base"
    merged = base / "MERGED_VAULT"
    (base / BANCO).mkdir(parents=True)
    (base / MINI).mkdir(parents=True)
    for n in imagenes:
        (base / BANCO / n).write_bytes(b"original-pesado")
    for n in miniaturas:
        (base / MINI / n).write_bytes(b"mini")
    _nota(merged, "a.md", "Con imagenes", "2026-07-01", "".join(f"![]({BANCO}/{n})\n" for n in imagenes))
    return base, merged


def _banco(base: Path, con_miniaturas=True):
    return ci.BankSpec(prefix=BANCO, label="Generadas", bank_dir=base / BANCO,
                       thumbs_dir=base / MINI if con_miniaturas else None,
                       thumbs_prefix=MINI if con_miniaturas else None)


def _generar(base, merged, con_miniaturas=True):
    return ci.generate_provider_index(merged, "Conversaciones", "ChatGPT", [_banco(base, con_miniaturas)])


# ---- como se busca la miniatura --------------------------------------------------
def test_la_miniatura_de_un_png_lleva_el_prefijo():
    assert ci.miniatura_de("abc.png", {"thmbnail_abc.png": "thmbnail_abc.png"}) == "thmbnail_abc.png"


def test_la_de_una_webp_tiene_el_mismo_nombre():
    assert ci.miniatura_de("abc.webp", {"abc.webp": "abc.webp"}) == "abc.webp"


def test_el_prefijo_vale_para_cualquier_extension_de_la_original():
    """Una .jpg o .webp cuya miniatura se genero como png con prefijo."""
    assert ci.miniatura_de("abc.jpg", {"thmbnail_abc.png": "thmbnail_abc.png"}) == "thmbnail_abc.png"


def test_no_distingue_mayusculas_y_devuelve_el_nombre_real():
    assert ci.miniatura_de("ABC.png", {"thmbnail_abc.png": "Thmbnail_ABC.png"}) == "Thmbnail_ABC.png"


def test_sin_miniatura_es_none():
    assert ci.miniatura_de("abc.png", {"thmbnail_otra.png": "thmbnail_otra.png"}) is None
    assert ci.miniatura_de("abc.png", {}) is None


def test_la_carpeta_de_miniaturas_ausente_no_rompe(tmp_path):
    assert ci.miniaturas_existentes(None) == {}
    assert ci.miniaturas_existentes(tmp_path / "no_existe") == {}


# ---- el indice -----------------------------------------------------------------
def test_la_imagen_sale_como_miniatura_enlazada_al_original(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    md = _generar(base, merged)["markdown"]
    assert f"[![]({MINI}/thmbnail_abc.png)]({BANCO}/abc.png)" in md


def test_no_se_incrusta_el_original(tmp_path):
    """Es la razon de ser de todo esto."""
    base, merged = _vault(tmp_path, ["a.png", "b.png"], ["thmbnail_a.png", "thmbnail_b.png"])
    md = _generar(base, merged)["markdown"]
    assert f"![]({BANCO}/" not in md.replace(f"[![]({MINI}/", "")
    assert re.findall(rf"(?<!\[)!\[\]\({re.escape(BANCO)}/", md) == []


def test_la_ubicacion_va_como_enlace_al_fichero(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    md = _generar(base, merged)["markdown"]
    assert f"📂 [{BANCO}/abc.png]({BANCO}/abc.png)" in md


def test_el_pie_conserva_la_descripcion_de_la_imagen(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    (base / BANCO / "_image_manifest.json").write_text(
        '{"abc.png": {"origen": "generada", "width": 1536, "height": 1024}}', encoding="utf-8")
    md = _generar(base, merged)["markdown"]
    assert f"*Generada · 1536×1024* · 📂 [{BANCO}/abc.png]" in md


def test_la_conversacion_sigue_enlazada(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    md = _generar(base, merged)["markdown"]
    assert "[[Conversaciones/a|Con imagenes]]" in md


def test_una_imagen_sin_miniatura_no_se_cuela_a_tamano_completo(tmp_path):
    base, merged = _vault(tmp_path, ["con.png", "sin.png"], ["thmbnail_con.png"])
    r = _generar(base, merged)
    md = r["markdown"]
    assert f"📂 [{BANCO}/sin.png]({BANCO}/sin.png) _(sin miniatura)_" in md
    assert f"![]({BANCO}/sin.png)" not in md
    assert "thmbnail_sin" not in md


def test_las_estadisticas_cuentan_las_que_tienen_y_las_que_no(tmp_path):
    base, merged = _vault(tmp_path, ["a.png", "b.png", "c.png"], ["thmbnail_a.png", "thmbnail_b.png"])
    assert _generar(base, merged)["stats"]["Generadas"]["miniaturas"] == {"con": 2, "sin": 1}


def test_los_enlaces_apuntan_a_ficheros_que_existen(tmp_path):
    nombres = ["a.png", "b.webp", "c.png"]
    base, merged = _vault(tmp_path, nombres, ["thmbnail_a.png", "b.webp", "thmbnail_c.png"])
    md = _generar(base, merged)["markdown"]
    pares = re.findall(r"\[!\[\]\(([^)]+)\)\]\(([^)]+)\)", md)
    assert len(pares) == 3
    for mini, orig in pares:
        assert (base / mini).is_file(), mini
        assert (base / orig).is_file(), orig


def test_una_ruta_con_espacios_no_corta_el_enlace(tmp_path):
    base, merged = _vault(tmp_path, ["mi foto.png"], ["thmbnail_mi foto.png"])
    md = _generar(base, merged)["markdown"]
    assert f"[![]({MINI}/thmbnail_mi%20foto.png)]({BANCO}/mi%20foto.png)" in md


# ---- sin miniaturas: todo como siempre --------------------------------------------
def test_sin_carpeta_de_miniaturas_el_indice_es_el_de_siempre(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    r = _generar(base, merged, con_miniaturas=False)
    assert f"![]({BANCO}/abc.png)" in r["markdown"]
    assert "📂" not in r["markdown"] and "miniaturas" not in r["stats"]["Generadas"]


def test_los_bancos_sin_miniaturas_no_cambian(tmp_path):
    """Los adjuntos y todos los demas proveedores siguen incrustando como antes."""
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    (base / "CHATGPT" / "ADJUNTOS").mkdir(parents=True)
    _nota(merged, "b.md", "Con adjunto", "2026-07-02", "![](CHATGPT/ADJUNTOS/foto.png)\n")
    adj = ci.BankSpec(prefix="CHATGPT/ADJUNTOS", label="Adjuntos", bank_dir=base / "CHATGPT/ADJUNTOS")
    md = ci.generate_provider_index(merged, "Conversaciones", "ChatGPT", [_banco(base), adj])["markdown"]
    assert "![](CHATGPT/ADJUNTOS/foto.png)" in md


# ---- la linea de comandos -------------------------------------------------------------
def _cli(base, merged, *extra):
    return subprocess.run(
        [sys.executable, str(RAIZ / "content_index.py"), str(merged), "--base-vault", str(base),
         "--conversations-dir", "Conversaciones", "--proveedor", "ChatGPT", "--out", "_index_chatgpt.md",
         "--banco", f"{BANCO}:Generadas", *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RAIZ)


def test_cli_con_miniaturas(tmp_path):
    base, merged = _vault(tmp_path, ["a.png", "b.png"], ["thmbnail_a.png"])
    r = _cli(base, merged, "--miniaturas", f"{BANCO}={MINI}")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 con miniatura, 1 sin ella" in r.stdout
    md = (merged / "_index_chatgpt.md").read_text(encoding="utf-8")
    assert f"[![]({MINI}/thmbnail_a.png)]({BANCO}/a.png)" in md


def test_cli_con_una_carpeta_que_no_existe_avisa_y_sigue_como_siempre(tmp_path):
    base, merged = _vault(tmp_path, ["a.png"], [])
    r = _cli(base, merged, "--miniaturas", f"{BANCO}=CHATGPT/NO_EXISTE")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no existe la carpeta de miniaturas" in r.stdout
    assert f"![]({BANCO}/a.png)" in (merged / "_index_chatgpt.md").read_text(encoding="utf-8")


# ---- el pipeline ------------------------------------------------------------------------
def test_el_paso_4_usa_las_miniaturas_de_chatgpt_si_la_carpeta_existe(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    MemorIA2GO.paso4_indices(base, merged, None, tmp_path / "log.txt")
    md = (merged / "_index_chatgpt.md").read_text(encoding="utf-8")
    assert f"[![]({MINI}/thmbnail_abc.png)]({BANCO}/abc.png)" in md
    assert f"![]({BANCO}/abc.png)" not in md


def test_el_paso_4_sin_la_carpeta_de_miniaturas_indexa_como_siempre(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], [])
    import shutil
    shutil.rmtree(base / MINI)
    log = tmp_path / "log.txt"
    MemorIA2GO.paso4_indices(base, merged, None, log)
    assert f"![]({BANCO}/abc.png)" in (merged / "_index_chatgpt.md").read_text(encoding="utf-8")
    # quien no usa miniaturas no tiene por que ver un aviso en cada importacion
    assert "miniaturas" not in (log.read_text(encoding="utf-8") if log.exists() else "")


def test_el_paso_4_no_aplica_miniaturas_a_los_demas_proveedores(tmp_path):
    base, merged = _vault(tmp_path, ["abc.png"], ["thmbnail_abc.png"])
    (base / "GROK" / "ADJUNTOS").mkdir(parents=True)
    _nota(merged, "g.md", "Con adjunto de Grok", "2026-07-03", "![](GROK/ADJUNTOS/x.png)\n")
    MemorIA2GO.paso4_indices(base, merged, None, tmp_path / "log.txt")
    grok = (merged / "_index_grok.md").read_text(encoding="utf-8")
    assert "![](GROK/ADJUNTOS/x.png)" in grok and "📂" not in grok
