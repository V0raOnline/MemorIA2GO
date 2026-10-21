# -*- coding: utf-8 -*-
"""El pipeline entero con cada preset de organizacion: unico, proveedor, proyectos.

Ejecuta el pipeline REAL como subproceso (el mismo camino que el launcher) sobre
exports de tres proveedores -- ChatGPT, Claude y Grok -- y comprueba lo que ninguna
prueba de API ve:

  * cada nota fusionada cae en la carpeta de SU proveedor (leyendo el `provider` de la
    nota, no el nombre del fichero), y con MERGED unico no aparece ninguna carpeta de
    proveedor;
  * no se pierde ni se duplica ninguna conversacion: 7 notas en RAW, 7 en MERGED, 7 en
    el indice, 7 en las estadisticas, 7 en Cartografia, con cualquier preset;
  * PRJ_VAULT existe solo con el preset que lo pide;
  * los enlaces a assets siguen resolviendo a un fichero (es vault-relativo: partir
    MERGED no debe romperlos, y si lo hiciera ninguna verificacion de texto lo vería);
  * reejecutar no duplica, y cambiar de preset sobre un vault con notas se rechaza
    SIN escribir nada, en vez de partir cada conversacion en dos sitios.
"""
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import layout as lay
from test_layout_de_punta_a_punta import _enlaces_a_ficheros, _export_grok

RAIZ = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Lo que hay en los fixtures: 3 de ChatGPT, 2 de Claude, 2 de Grok (+1 de Grok con adjuntos).
NOTAS_POR_PROVEEDOR = {"chatgpt": 3, "claude": 2, "grok": 3}
CARPETA = {"chatgpt": "ChatGPT", "claude": "Claude", "grok": "Grok"}
TOTAL = sum(NOTAS_POR_PROVEEDOR.values())


def _exports(destino: Path):
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "claude_export.zip", destino / "claude_export.zip")
    shutil.copy(FIXTURES / "grok_export.zip", destino / "grok_fixture.zip")
    with zipfile.ZipFile(destino / "chatgpt_export.zip", "w") as z:
        z.writestr("conversations.json", (FIXTURES / "chatgpt_classic.json").read_text(encoding="utf-8"))
    _export_grok(destino)     # el de los otros tests de layout: trae adjuntos, para comprobar enlaces


def _config(tmp: Path, preset=None) -> Path:
    cfg = tmp / "memoria_config.yaml"
    opciones = "options:\n  by_year: true\n  by_month: true\n  make_index: true\n"
    if preset:
        opciones += f"  layout_preset: '{preset}'\n"
    cfg.write_text("paths:\n"
                   f"  base_vault: '{(tmp / 'vault').as_posix()}'\n"
                   f"  exports_dir: '{(tmp / 'exports').as_posix()}'\n" + opciones, encoding="utf-8")
    return cfg


def _ejecutar(cfg: Path, *extra):
    entorno = {k: v for k, v in os.environ.items() if k != lay.ENV_LAYOUT}
    entorno["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(RAIZ / "MemorIA2GO.py"), "--config", str(cfg), "--yes", "--no-wizard", *extra],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=entorno, timeout=300)


def _montar_y_ejecutar(tmp_path_factory, nombre, preset):
    tmp = tmp_path_factory.mktemp(nombre)
    (tmp / "vault").mkdir()
    _exports(tmp / "exports")
    cfg = _config(tmp, preset)
    return tmp, tmp / "vault", cfg, _ejecutar(cfg)


@pytest.fixture(scope="module", params=["unico", "proveedor", "proyectos"])
def construido(request, tmp_path_factory):
    tmp, base, cfg, r = _montar_y_ejecutar(tmp_path_factory, f"preset_{request.param}", request.param)
    return request.param, tmp, base, cfg, r


def _notas(carpeta: Path):
    indices = ("_tree_index.md", "scaffolding_index.md")
    return [p for p in carpeta.rglob("*.md")
            if p.name not in indices and not p.name.startswith("_")]


def _provider(nota: Path) -> str:
    for linea in nota.read_text(encoding="utf-8").splitlines():
        if linea.startswith("provider:"):
            return linea.split(":", 1)[1].strip().strip('"').lower()
    return "chatgpt"          # las notas anteriores al multi-proveedor no traen el campo


def _foto(base: Path):
    return {p.relative_to(base).as_posix(): p.stat().st_size for p in base.rglob("*") if p.is_file()}


# ---- cada preset ------------------------------------------------------------------
def test_el_pipeline_termina_bien(construido):
    _, _, _, _, r = construido
    assert r.returncode == 0, f"salida {r.returncode}\n{r.stdout[-2500:]}\n{r.stderr[-1500:]}"


def test_el_marcador_recoge_el_preset(construido):
    preset, _, base, _, _ = construido
    m = lay.leer_marcador(base)
    assert m is not None and m.preset == preset
    assert (m.particion, m.proyectos) == lay.PRESETS[preset]


def test_no_se_pierde_ni_se_duplica_ninguna_conversacion(construido):
    _, _, base, _, _ = construido
    assert len(_notas(base / "RAW_VAULT" / "Conversaciones")) == TOTAL
    fusionadas = _notas(base / "MERGED_VAULT")
    assert len(fusionadas) == TOTAL, [p.relative_to(base).as_posix() for p in fusionadas]
    assert len({p.name for p in fusionadas}) == TOTAL, "dos notas con el mismo nombre"


def test_cada_nota_esta_en_la_carpeta_que_toca(construido):
    preset, _, base, _, _ = construido
    merged = base / "MERGED_VAULT"
    for nota in _notas(merged):
        rel = nota.relative_to(merged).parts
        if lay.PRESETS[preset][0] == "proveedor":
            assert rel[:2] == (CARPETA[_provider(nota)], "Conversaciones"), (rel, _provider(nota))
        else:
            assert rel[0] == "Conversaciones", rel


def test_con_merged_partido_hay_una_carpeta_por_proveedor_y_ninguna_mas(construido):
    preset, _, base, _, _ = construido
    hijos = {p.name for p in (base / "MERGED_VAULT").iterdir() if p.is_dir()}
    if lay.PRESETS[preset][0] == "proveedor":
        assert {"ChatGPT", "Claude", "Grok"} <= hijos
        assert "Conversaciones" not in hijos, "carpeta de conversaciones de siempre, vacia, al lado de las buenas"
        for prov, n in NOTAS_POR_PROVEEDOR.items():
            assert len(_notas(base / "MERGED_VAULT" / CARPETA[prov])) == n, prov
    else:
        assert not hijos & {"ChatGPT", "Claude", "Grok"}, hijos
        assert "Conversaciones" in hijos


def test_el_vault_de_proyectos_existe_solo_si_el_preset_lo_pide(construido):
    preset, _, base, _, _ = construido
    prj = base / "PRJ_VAULT"
    if lay.PRESETS[preset][1]:
        assert prj.is_dir() and len(_notas(prj)) == TOTAL
    else:
        assert not prj.exists(), "el preset no pide vault de proyectos y se ha creado"


def test_los_enlaces_a_assets_siguen_apuntando_a_un_fichero(construido):
    _, _, base, _, _ = construido
    enlaces = _enlaces_a_ficheros(base, base / "MERGED_VAULT")
    assert enlaces, "no hay ningun enlace a assets: el test no probaria nada"
    rotos = [f"{n.relative_to(base).as_posix()} -> {r}" for n, r in enlaces if not (base / r).is_file()]
    assert not rotos, "enlaces que no resuelven a un fichero:\n  " + "\n  ".join(rotos)


def test_el_indice_de_proyectos_ve_todas_las_notas(construido):
    _, _, base, _, _ = construido
    arbol = (base / "MERGED_VAULT" / "_tree_index.md").read_text(encoding="utf-8")
    assert f"_Notas:_ **{TOTAL}**" in arbol, arbol[:300]


def test_el_indice_de_contenido_ve_las_conversaciones_de_su_proveedor(construido):
    _, _, base, _, _ = construido
    grok = (base / "MERGED_VAULT" / "_index_grok.md").read_text(encoding="utf-8")
    assert "[[" in grok and "Grok" in grok
    # el enlace del indice tiene que resolver a una nota que existe, esté donde esté
    import re
    for destino in re.findall(r"\[\[([^\]|]+)", grok):
        assert (base / "MERGED_VAULT" / f"{destino}.md").is_file() or (base / f"{destino}.md").is_file(), destino


def test_las_estadisticas_cuentan_lo_mismo_con_cualquier_preset(construido):
    preset, _, base, _, _ = construido
    import vault_stats
    s = vault_stats.compute_stats(base)
    assert s["layout"]["preset"] == preset
    assert s["vaults"]["MERGED_VAULT"]["notas"] == TOTAL
    assert s["vaults"]["MERGED_VAULT"]["notas_por_proveedor"] == NOTAS_POR_PROVEEDOR
    assert ("PRJ_VAULT" in s["vaults"]) is lay.PRESETS[preset][1]


def test_cartografia_ve_las_huerfanas_de_todos_los_proveedores(construido, monkeypatch):
    """`iter_orphans` recorre la carpeta de conversaciones del layout: con el vault
    partido tiene que recorrer las tres, no solo una (o ninguna)."""
    import orphan_cloud
    _, _, base, _, _ = construido
    monkeypatch.setenv(lay.ENV_LAYOUT, lay.entorno(lay.leer_marcador(base))[lay.ENV_LAYOUT])
    huerfanas = list(orphan_cloud.iter_orphans(base / "MERGED_VAULT"))
    assert len(huerfanas) == TOTAL


def test_reejecutar_no_duplica_nada(construido):
    _, _, base, cfg, _ = construido
    antes = _foto(base)
    r = _ejecutar(cfg)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
    despues = _foto(base)
    nuevos = set(despues) - set(antes)
    assert not [n for n in nuevos if not n.startswith(("_", "logs/"))], sorted(nuevos)
    assert len(_notas(base / "MERGED_VAULT")) == TOTAL


# ---- cambiar de preset ---------------------------------------------------------------
@pytest.mark.parametrize("de,a", [("unico", "proveedor"), ("proveedor", "unico"), ("proveedor", "proyectos")])
def test_cambiar_la_particion_de_un_vault_con_notas_se_rechaza_sin_escribir_nada(tmp_path_factory, de, a):
    tmp, base, cfg, r = _montar_y_ejecutar(tmp_path_factory, f"cambio_{de}_{a}", de)
    assert r.returncode == 0, r.stdout[-1500:]
    antes = _foto(base)
    cfg2 = _config(tmp, a)
    r2 = _ejecutar(cfg2)
    assert r2.returncode == 2, r2.stdout[-1500:] + r2.stderr[-800:]
    assert "layout_preset" in (r2.stdout + r2.stderr)
    despues = _foto(base)
    assert {k: v for k, v in despues.items() if not k.startswith("logs/")} == antes, \
        "el pipeline escribio algo antes de negarse"


def test_cambiar_entre_unico_y_proyectos_es_libre(tmp_path_factory):
    """No parte nada: solo enciende o apaga PRJ_VAULT, que es una vista."""
    tmp, base, cfg, r = _montar_y_ejecutar(tmp_path_factory, "cambio_unico_proyectos", "unico")
    assert r.returncode == 0 and not (base / "PRJ_VAULT").exists()
    r2 = _ejecutar(_config(tmp, "proyectos"))
    assert r2.returncode == 0, r2.stdout[-1500:] + r2.stderr[-800:]
    assert len(_notas(base / "PRJ_VAULT")) == TOTAL
    assert len(_notas(base / "MERGED_VAULT")) == TOTAL


def test_en_un_vault_nuevo_se_puede_elegir_cualquier_preset_aunque_la_carpeta_exista_vacia(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("nuevo_vacio")
    (tmp / "vault" / "MERGED_VAULT" / "Conversaciones").mkdir(parents=True)
    _exports(tmp / "exports")
    r = _ejecutar(_config(tmp, "proveedor"))
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]


def test_un_preset_desconocido_en_la_config_se_rechaza_con_los_validos(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("preset_raro")
    (tmp / "vault").mkdir()
    _exports(tmp / "exports")
    r = _ejecutar(_config(tmp, "por-colores"))
    assert r.returncode != 0
    assert not (tmp / "vault" / "MERGED_VAULT").exists()
    assert "unico, proveedor, proyectos" in (r.stdout + r.stderr)


def test_solo_se_crean_las_carpetas_de_los_proveedores_que_tienen_notas(tmp_path_factory):
    """Quien solo importa Claude no quiere ver un ChatGPT/Conversaciones vacio al lado."""
    tmp = tmp_path_factory.mktemp("solo_claude")
    (tmp / "vault").mkdir()
    (tmp / "exports").mkdir()
    shutil.copy(FIXTURES / "claude_export.zip", tmp / "exports" / "claude_export.zip")
    r = _ejecutar(_config(tmp, "proveedor"))
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
    hijos = {p.name for p in (tmp / "vault" / "MERGED_VAULT").iterdir() if p.is_dir()}
    assert hijos == {"Claude"}, hijos


def test_reindexar_no_toca_un_vault_de_proyectos_que_el_preset_ya_no_pide(tmp_path_factory):
    """Con 'proyectos' se creo PRJ_VAULT; al pasar a 'unico' queda en disco, pero ya no es
    parte de este vault: reindexar no debe volver a escribirle indices."""
    tmp, base, cfg, r = _montar_y_ejecutar(tmp_path_factory, "reindex_sin_prj", "proyectos")
    assert r.returncode == 0 and (base / "PRJ_VAULT" / "_tree_index.md").is_file()
    (base / "PRJ_VAULT" / "_tree_index.md").unlink()
    (base / "MERGED_VAULT" / "_tree_index.md").unlink()
    r2 = _ejecutar(_config(tmp, "unico"), "--reindex-only")
    assert r2.returncode == 0, r2.stdout[-1500:] + r2.stderr[-800:]
    assert (base / "MERGED_VAULT" / "_tree_index.md").is_file(), "no reindexo el vault fusionado"
    assert not (base / "PRJ_VAULT" / "_tree_index.md").exists(), "reindexo un vault de proyectos apagado"


# ---- los interruptores por separado --------------------------------------------------
def test_partido_por_proveedor_y_con_vault_de_proyectos_las_dos_cosas_a_la_vez(tmp_path_factory):
    """No es un preset con nombre, pero los interruptores son independientes: el vault de
    proyectos junta las notas de todos los proveedores aunque MERGED este partido."""
    tmp = tmp_path_factory.mktemp("combinado")
    (tmp / "vault").mkdir()
    _exports(tmp / "exports")
    lay.escribir_marcador(tmp / "vault", lay.Layout(preset="a-mano", particion="proveedor", proyectos=True))
    r = _ejecutar(_config(tmp))                       # sin layout_preset: manda el marcador
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
    base = tmp / "vault"
    assert len(_notas(base / "PRJ_VAULT")) == TOTAL
    for prov, n in NOTAS_POR_PROVEEDOR.items():
        assert len(_notas(base / "MERGED_VAULT" / CARPETA[prov])) == n
    assert not (base / "MERGED_VAULT" / "Conversaciones").exists()
