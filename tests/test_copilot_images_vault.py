# -*- coding: utf-8 -*-
"""Tests de verify_copilot_images.py y build_copilot_images_vault.py.

Como en el resto de backups, se comprueba el estado del DISCO. Dos
invariantes importan especialmente: el build NUNCA borra nada del vault, y
un prompt con saltos de linea, comillas o Markdown no rompe la nota.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

CARPETA = Path(__file__).resolve().parent.parent / "copilot_images"
sys.path.insert(0, str(CARPETA))

import build_copilot_images_vault as bv
import verify_copilot_images as vf


def _meta(id_, prompt="un submarino", fecha="2025-05-04T11:55:26+00:00", size=5):
    return {"id": id_, "name": "x.jpeg", "prompt": prompt, "created_at": fecha,
            "modified_at": fecha, "size_bytes": size, "artifact_type": "Image"}


def _backup(tmp_path, metas, con_imagen=True, contenido=b"12345"):
    carpeta = tmp_path / "backup"
    carpeta.mkdir()
    indice = {m["id"]: m for m in metas}
    (carpeta / "_index.json").write_text(json.dumps(indice), encoding="utf-8")
    for m in metas:
        base = f"2025-05-04_x_{m['id']}"
        (carpeta / f"{base}.json").write_text(json.dumps(m), encoding="utf-8")
        if con_imagen:
            (carpeta / f"{base}.jpg").write_bytes(contenido)
    return carpeta


# ---------------------------------------------------------------- verify

def test_verify_backup_completo_sin_problemas(tmp_path):
    r = vf.verificar(_backup(tmp_path, [_meta("A1"), _meta("B2")]))
    assert not (r["faltan"] or r["vacias"] or r["tamano"] or r["json_falta"]
                or r["json_corrupto"] or r["parciales"])


def test_verify_detecta_imagen_faltante(tmp_path):
    carpeta = _backup(tmp_path, [_meta("A1"), _meta("B2")])
    next(carpeta.glob("*B2.jpg")).unlink()
    assert vf.verificar(carpeta)["faltan"] == ["B2"]


def test_verify_detecta_imagen_vacia_y_no_la_confunde_con_faltante(tmp_path):
    carpeta = _backup(tmp_path, [_meta("A1", size=None)])
    next(carpeta.glob("*A1.jpg")).write_bytes(b"")
    r = vf.verificar(carpeta)
    assert r["vacias"] == ["A1"] and r["faltan"] == []


def test_verify_detecta_tamano_distinto_al_de_la_api(tmp_path):
    carpeta = _backup(tmp_path, [_meta("A1", size=999)])
    assert len(vf.verificar(carpeta)["tamano"]) == 1


def test_verify_detecta_json_corrupto_y_part_suelto(tmp_path):
    carpeta = _backup(tmp_path, [_meta("A1")])
    next(carpeta.glob("*A1.json")).write_text("{no es json", encoding="utf-8")
    (carpeta / "algo.jpg.part").write_bytes(b"x")
    r = vf.verificar(carpeta)
    assert r["json_corrupto"] == ["A1"] and r["parciales"] == ["algo.jpg.part"]


def test_verify_lista_las_que_ya_no_estan_en_la_biblioteca_sin_tocarlas(tmp_path):
    carpeta = _backup(tmp_path, [_meta("A1")])
    huerfana = carpeta / "289_ZZZ.jpg"
    huerfana.write_bytes(b"x")
    r = vf.verificar(carpeta)
    assert r["fuera_de_biblioteca"] == ["289_ZZZ.jpg"]
    assert huerfana.exists()


# ----------------------------------------------------------------- build

def test_yaml_escape_resiste_comillas_barras_y_saltos_de_linea():
    valor = 'dice "hola"\\ y\nsigue'
    esc = bv.yaml_escape(valor)
    assert "\n" not in esc
    assert json.loads(esc) == valor


def test_citar_neutraliza_encabezados_y_reglas_del_prompt():
    c = bv.citar("## titulo\n---\n\ntexto")
    assert c.splitlines()[0] == "> \\## titulo"
    assert all(l.startswith(">") for l in c.splitlines())


def test_nota_con_prompt_multilinea_mantiene_frontmatter_valido():
    meta = _meta("A1", prompt="linea uno\n## linea dos con \"comillas\"")
    nota = bv.construir_nota(meta, "n", "n.jpg")
    cabecera = nota.split("---")[1]
    assert "\n## " not in cabecera
    assert nota.count("\n---\n") == 1
    assert "![[n.jpg]]" in nota and "linea uno" in nota


def test_nota_sin_prompt_ni_imagen_lo_dice_en_vez_de_dejar_vacio():
    nota = bv.construir_nota(_meta("A1", prompt=None), "n", None)
    assert bv.T["sin_prompt"] in nota and bv.T["sin_imagen"] in nota


def test_nota_sin_copiar_dice_donde_esta_la_imagen_y_no_que_falta():
    nota = bv.construir_nota(_meta("A1"), "n", None, en_backup="2025_A1.jpg")
    assert "2025_A1.jpg" in nota and bv.T["sin_imagen"] not in nota


def test_nombres_sin_corchetes_y_colision_de_mayusculas_se_desambigua():
    indice = {"X0000001": _meta("X0000001", prompt="Hola Mundo"),
              "X0000001".replace("X", "x"): _meta("x0000001", prompt="hola mundo")}
    nombres = bv.calcular_nombres(indice)
    assert len({n.lower() for n in nombres.values()}) == 2
    assert not any("[" in n or "]" in n for n in nombres.values())


def _lanzar_build(backup, vault, *extra):
    return subprocess.run(
        [sys.executable, str(CARPETA / "build_copilot_images_vault.py"),
         "--backup-dir", str(backup), "--vault-dir", str(vault), *extra],
        capture_output=True, text=True, encoding="utf-8")


def test_build_escribe_notas_copia_imagenes_e_indice(tmp_path):
    backup = _backup(tmp_path, [_meta("A0000001"), _meta("B0000002", fecha="2025-06-01T00:00:00+00:00")])
    vault = tmp_path / "vault"
    r = _lanzar_build(backup, vault)
    assert r.returncode == 0, r.stderr
    assert len(list((vault / "Imágenes").rglob("*.md"))) == 2
    assert len(list((vault / "Archivos").glob("*.jpg"))) == 2
    assert (vault / "_index.md").is_file()
    assert {p.parent.name for p in (vault / "Imágenes").rglob("*.md")} == {"2025-05", "2025-06"}


def test_build_nunca_borra_lo_que_ya_no_corresponde(tmp_path):
    backup = _backup(tmp_path, [_meta("A0000001")])
    vault = tmp_path / "vault"
    assert _lanzar_build(backup, vault).returncode == 0
    vieja = vault / "Imágenes" / "2020-01" / "nota vieja.md"
    vieja.parent.mkdir(parents=True)
    vieja.write_text("mia", encoding="utf-8")
    ajena = vault / "Archivos" / "ajena.jpg"
    ajena.write_bytes(b"x")
    r = _lanzar_build(backup, vault)
    assert r.returncode == 0
    assert vieja.read_text(encoding="utf-8") == "mia" and ajena.exists()
    assert "no se han tocado" in r.stdout


def test_build_no_copy_images_solo_escribe_notas(tmp_path):
    backup = _backup(tmp_path, [_meta("A0000001")])
    vault = tmp_path / "vault"
    assert _lanzar_build(backup, vault, "--no-copy-images").returncode == 0
    assert not list((vault / "Archivos").iterdir())
    assert len(list((vault / "Imágenes").rglob("*.md"))) == 1
