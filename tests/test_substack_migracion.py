# -*- coding: utf-8 -*-
"""Migrar el layout antiguo de Tintero a la carpeta de su publicacion.

Caso real (V0ra, 2026-10-20): su vault de Tintero tiene 114 notas de V0raOnline en la RAIZ
(Posts/, Borradores/, Drafts/, _indice.md, _secciones.md), construidas cuando solo habia un
export. Con tres publicaciones, el constructor se niega a construir encima para no duplicar
V0raOnline. Esta herramienta lo MUEVE a V0raOnline/, sin borrar nada.

La publicacion a la que pertenece lo antiguo no se adivina: cada nota lleva `post_id`, y esos
ids se cruzan con el posts.csv de cada export. En el vault real, 109 de 109 ids coinciden con
V0raOnline y 0 con las otras dos.

Lo que no puede pasar:
  - mover lo antiguo a la publicacion equivocada;
  - perder o alterar una nota (se compara numero de ficheros y bytes antes y despues);
  - dejar el vault a medias si algo falla a mitad del movimiento;
  - pisar una carpeta que ya existe.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_substack_publicaciones import tres, _zip, _csv_stats, _tree, _log, bsv, substack_stats  # noqa: E402,F401


@pytest.fixture
def legado(tres, tmp_path):
    """Un vault con el layout de un solo export, construido de verdad con el constructor
    (solo el export de V0raOnline, como en julio), mas un Drafts/ duplicado como el real y una
    carpeta .obsidian que no se debe tocar."""
    unico = tmp_path / "solo_v0ra"
    unico.mkdir()
    for z in ("V0raOnline.zip",):
        (unico / z).write_bytes((tres / z).read_bytes())
    for c in tres.glob("v0raonline_*.csv"):
        (unico / c.name).write_bytes(c.read_bytes())
    vault = tmp_path / "TINTERO_VAULT"
    bsv.construir_publicaciones(unico, vault, log=_log)             # una sola publicacion: plano
    assert (vault / "Posts").is_dir() and not (vault / "_publicaciones.md").exists()
    # un duplicado de borradores como el Drafts/ real (build de la edicion inglesa)
    (vault / "Drafts").mkdir()
    (vault / "Drafts" / "borrador-duplicado.md").write_text(
        '---\npost_id: "V1"\n---\nduplicado\n', encoding="utf-8")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "app.json").write_text('{"x": 1}', encoding="utf-8")
    return vault


def _bytes(vault: Path):
    return {p.relative_to(vault).as_posix(): p.read_bytes() for p in vault.rglob("*") if p.is_file()}


NOMBRES = ("Posts", "Borradores", "Drafts", "_indice.md", "_secciones.md")


# ---- el plan (en seco) ------------------------------------------------------------------------

def test_en_seco_identifica_la_publicacion_por_los_post_id_y_no_mueve_nada(tres, legado):
    antes = _tree(legado)
    r = bsv.migrar_layout_antiguo(tres, legado, aplicar=False, log=_log)
    assert r["publicacion"] == "v0raonline" and r["carpeta"] == "V0raOnline"
    assert r["aplicado"] is False
    assert {m[0] for m in r["movimientos"]} == {n for n in NOMBRES if (legado / n).exists()}
    assert _tree(legado) == antes, "el plan en seco ha tocado el vault"


def test_el_plan_dice_cuantas_notas_y_cuantos_ids_coinciden(tres, legado):
    r = bsv.migrar_layout_antiguo(tres, legado, log=_log)
    assert r["notas"] >= 3 and r["ids_coinciden"] >= 1
    assert r["ids_ausentes"] == 0


# ---- aplicar ------------------------------------------------------------------------------------

def test_aplicar_lo_mueve_todo_a_la_carpeta_de_su_publicacion(tres, legado):
    antes = _bytes(legado)
    r = bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    assert r["aplicado"] is True
    for n in NOMBRES:
        assert not (legado / n).exists(), f"{n} sigue en la raiz"
    despues = _bytes(legado)
    esperado = {}
    for ruta, cuerpo in antes.items():
        primero = ruta.split("/")[0]
        esperado[f"V0raOnline/{ruta}" if primero in NOMBRES else ruta] = cuerpo
    assert despues == esperado, "algun fichero se ha perdido, alterado o movido a donde no toca"


def test_no_se_toca_lo_que_no_es_del_layout_antiguo(tres, legado):
    (legado / "mi_nota_personal.md").write_text("mia", encoding="utf-8")
    bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    assert (legado / "mi_nota_personal.md").read_text(encoding="utf-8") == "mia"
    assert (legado / ".obsidian" / "app.json").read_text(encoding="utf-8") == '{"x": 1}'


def test_tras_migrar_se_pueden_construir_las_tres_sin_duplicar(tres, legado):
    bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    r = bsv.construir_publicaciones(tres, legado, log=_log)      # antes lanzaba LayoutAntiguoError
    assert r["modo"] == "carpetas"
    assert not (legado / "Posts").exists()
    notas = sorted(p.name for p in (legado / "V0raOnline" / "Posts").rglob("*.md"))
    assert len(notas) == 2 and len(set(notas)) == 2, "V0raOnline duplicada o incompleta"


def test_migrar_y_volver_a_migrar_no_hace_dano(tres, legado):
    bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    with pytest.raises(bsv.MigracionError, match="nada que migrar"):
        bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)


# ---- no adivinar -----------------------------------------------------------------------------------

def _quitar_ids(vault):
    for f in vault.rglob("*.md"):
        t = f.read_text(encoding="utf-8")
        f.write_text("\n".join(l for l in t.split("\n") if not l.startswith("post_id:")), encoding="utf-8")


def test_si_las_notas_no_traen_post_id_no_adivina_y_pide_la_publicacion(tres, legado):
    _quitar_ids(legado)
    antes = _tree(legado)
    with pytest.raises(bsv.MigracionError, match="--publicacion"):
        bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    assert _tree(legado) == antes


def test_con_publicacion_explicita_se_migra_aunque_no_haya_ids(tres, legado):
    _quitar_ids(legado)
    r = bsv.migrar_layout_antiguo(tres, legado, aplicar=True, publicacion="v0raonline", log=_log)
    assert r["carpeta"] == "V0raOnline" and (legado / "V0raOnline" / "Posts").is_dir()


def test_una_publicacion_explicita_que_no_existe_se_rechaza(tres, legado):
    with pytest.raises(bsv.MigracionError, match="inventada"):
        bsv.migrar_layout_antiguo(tres, legado, aplicar=True, publicacion="inventada", log=_log)


def test_si_el_legado_se_reparte_entre_dos_publicaciones_se_niega(tres, legado):
    """Notas con ids de dos publicaciones: no hay una respuesta unica y no se elige una."""
    (legado / "Posts" / "ajena.md").write_text('---\npost_id: "B1"\n---\nde bitacora\n', encoding="utf-8")
    (legado / "Posts" / "ajena2.md").write_text('---\npost_id: "M1"\n---\nde mas alla\n', encoding="utf-8")
    # 2 notas de V0raOnline (V1, V2 + duplicado V1) frente a 1 de cada otra: no domina con claridad
    for f in list((legado / "Posts").rglob("*.md")):
        if f.name not in ("ajena.md", "ajena2.md"):
            f.unlink()
    for f in (legado / "Drafts").glob("*.md"):
        f.unlink()
    antes = _tree(legado)
    with pytest.raises(bsv.MigracionError, match="--publicacion"):
        bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    assert _tree(legado) == antes


def test_notas_antiguas_cuyo_post_ya_no_esta_en_el_export_no_impiden_migrar(tres, legado):
    (legado / "Posts" / "vieja.md").write_text('---\npost_id: "9999"\n---\nya no esta\n', encoding="utf-8")
    r = bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    assert r["ids_ausentes"] == 1
    assert (legado / "V0raOnline" / "Posts" / "vieja.md").is_file(), "no se pierde, se mueve con el resto"


# ---- seguridad ------------------------------------------------------------------------------------------

def test_no_pisa_una_carpeta_que_ya_existe(tres, legado):
    (legado / "V0raOnline" / "Posts").mkdir(parents=True)
    (legado / "V0raOnline" / "Posts" / "ya_estaba.md").write_text("ya estaba", encoding="utf-8")
    antes = _tree(legado)
    with pytest.raises(bsv.MigracionError, match="ya existe"):
        bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    assert _tree(legado) == antes


def test_si_falla_a_mitad_se_deshace_y_el_vault_queda_como_estaba(tres, legado, monkeypatch):
    antes = _tree(legado)
    llamadas = {"n": 0}
    real = os.replace

    def falla_a_la_tercera(origen, destino):
        llamadas["n"] += 1
        if llamadas["n"] == 3:
            raise PermissionError("fichero en uso (Obsidian lo tiene abierto)")
        return real(origen, destino)

    monkeypatch.setattr(bsv.os, "replace", falla_a_la_tercera)
    with pytest.raises(bsv.MigracionError, match="deshecho"):
        bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    monkeypatch.setattr(bsv.os, "replace", real)
    assert _tree(legado) == antes, "el vault no ha quedado como estaba"
    assert not (legado / "V0raOnline").exists() or not any((legado / "V0raOnline").rglob("*"))


def test_si_el_movimiento_deja_copia_en_el_origen_se_detecta(tres, legado, monkeypatch):
    """La comprobacion posterior no es decorativa: si lo 'movido' sigue en el origen, o el destino
    no coincide con lo que habia, no se da por bueno."""
    import shutil
    real = os.replace

    def copia_en_vez_de_mover(origen, destino):
        if Path(origen).is_dir():
            shutil.copytree(origen, destino)
        else:
            shutil.copy2(origen, destino)

    monkeypatch.setattr(bsv.os, "replace", copia_en_vez_de_mover)
    with pytest.raises(bsv.MigracionError, match="comprobacion"):
        bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    monkeypatch.setattr(bsv.os, "replace", real)


def test_sin_exports_no_hay_publicacion_a_la_que_asignar(tmp_path, legado):
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    with pytest.raises(bsv.MigracionError, match="ningun export"):
        bsv.migrar_layout_antiguo(vacia, legado, aplicar=True, log=_log)


def test_un_vault_sin_layout_antiguo_no_tiene_nada_que_migrar(tres, tmp_path):
    (tmp_path / "limpio").mkdir()
    with pytest.raises(bsv.MigracionError, match="nada que migrar"):
        bsv.migrar_layout_antiguo(tres, tmp_path / "limpio", aplicar=True, log=_log)


# ---- linea de ordenes y endpoint ---------------------------------------------------------------------------

def _cli(*args):
    import subprocess
    raiz = Path(__file__).resolve().parent.parent
    return subprocess.run([sys.executable, str(raiz / "substack" / "build_substack_vault.py"), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def test_cli_sin_aplicar_solo_ensena_el_plan(tres, legado):
    antes = _tree(legado)
    r = _cli("--migrar-legado", "--exports-dir", tres, "--vault-dir", legado)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "V0raOnline" in r.stdout and "--aplicar" in r.stdout
    assert _tree(legado) == antes


def test_cli_con_aplicar_mueve(tres, legado):
    r = _cli("--migrar-legado", "--aplicar", "--exports-dir", tres, "--vault-dir", legado)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (legado / "V0raOnline" / "Posts").is_dir() and not (legado / "Posts").exists()


def test_cli_devuelve_1_si_se_niega(tres, tmp_path):
    (tmp_path / "limpio").mkdir()
    assert _cli("--migrar-legado", "--exports-dir", tres, "--vault-dir", tmp_path / "limpio").returncode == 1


@pytest.fixture
def web(tres, legado, tmp_path, monkeypatch):
    import launcher
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(f"paths:\n  base_vault: '{(tmp_path / 'b').as_posix()}'\n  exports_dir: '{tres.as_posix()}'\n"
                   f"  substack_vault: '{legado.as_posix()}'\noptions:\n  by_month: true\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)
    launcher.app.config["TESTING"] = True
    return {"cliente": launcher.app.test_client(), "vault": legado}


def test_el_endpoint_por_defecto_solo_ensena_el_plan(web):
    antes = _tree(web["vault"])
    r = web["cliente"].post("/api/substack/migrar", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert "V0raOnline" in r.get_json()["salida"] and r.get_json()["aplicado"] is False
    assert _tree(web["vault"]) == antes


def test_el_endpoint_aplica_solo_si_se_le_pide(web):
    r = web["cliente"].post("/api/substack/migrar", json={"aplicar": True})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["aplicado"] is True
    assert (web["vault"] / "V0raOnline" / "Posts").is_dir() and not (web["vault"] / "Posts").exists()


def test_el_endpoint_dice_por_que_se_niega(web):
    web["cliente"].post("/api/substack/migrar", json={"aplicar": True})
    r = web["cliente"].post("/api/substack/migrar", json={"aplicar": True})
    assert r.status_code == 400 and "nada que migrar" in r.get_json()["error"]


def test_tras_migrar_el_boton_de_construir_ya_no_se_niega(web):
    web["cliente"].post("/api/substack/migrar", json={"aplicar": True})
    r = web["cliente"].post("/api/substack/build", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert (web["vault"] / "MasAlladelPrompt" / "_indice.md").is_file()


def test_la_verificacion_ofrece_migrar_y_deja_de_avisar_al_migrar(web):
    d = web["cliente"].post("/api/substack/verify").get_json()
    assert any(a["tipo"] == "layout_antiguo" for a in d["avisos"])
    web["cliente"].post("/api/substack/migrar", json={"aplicar": True})
    d = web["cliente"].post("/api/substack/verify").get_json()
    assert not any(a["tipo"] == "layout_antiguo" for a in d["avisos"])


# ---- compatibilidad entre ediciones ---------------------------------------------------------------------
# Un vault construido con la edicion inglesa usa Drafts/, _index.md, _sections.md y _publications.md.
# Debe tratarse igual que uno de la espanola: detectarse, migrarse y no confundirse.

def test_el_layout_antiguo_de_la_edicion_inglesa_se_detecta_entero(legado):
    (legado / "_indice.md").rename(legado / "_index.md")
    (legado / "_secciones.md").rename(legado / "_sections.md")
    assert bsv.layout_antiguo(legado) == ["Posts", "Drafts", "_index.md", "_sections.md"]


def test_se_mueve_tambien_lo_que_dejo_la_edicion_inglesa(tres, legado):
    (legado / "_indice.md").rename(legado / "_index.md")
    (legado / "_secciones.md").rename(legado / "_sections.md")
    antes = _bytes(legado)
    bsv.migrar_layout_antiguo(tres, legado, aplicar=True, log=_log)
    assert not any((legado / n).exists() for n in ("Posts", "Drafts", "_index.md", "_sections.md"))
    assert (legado / "V0raOnline" / "_index.md").is_file() and (legado / "V0raOnline" / "_sections.md").is_file()
    assert sorted(_bytes(legado).values()) == sorted(antes.values()), "se ha perdido o alterado algun fichero"


def test_un_vault_organizado_por_la_edicion_inglesa_sigue_organizado(tres, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "_publications.md").write_text("# Publications\n", encoding="utf-8")
    (tres / "BitacoraClandestina201026.zip").unlink()
    (tres / "MasAlladelPrompt.zip").unlink()
    assert bsv.ya_por_publicaciones(vault)
    r = bsv.construir_publicaciones(tres, vault, log=_log)
    assert r["modo"] == "carpetas" and not (vault / "Posts").exists()
