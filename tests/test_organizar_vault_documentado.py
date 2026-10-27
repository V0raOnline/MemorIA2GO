# -*- coding: utf-8 -*-
"""Cada regla que VAULT_LAYOUT.md afirma, fijada por un test.

Como test_cartografia_documentada.py: el documento cuenta las tres organizaciones del vault, cuando se
puede cambiar de una a otra, como se mueve el RAW y por que el pipeline se niega a seguir. Una
documentacion que nada vigila deja de ser cierta en silencio cuando alguien toca el codigo. Si uno de
estos tests falla, o se corrige el codigo o se corrige el documento.

Lo que necesita el pipeline entero (cada nota en su carpeta, la galeria y la recuperacion siguiendo al
layout) ya lo prueban test_presets_de_punta_a_punta.py y test_layout_galeria_y_recuperar.py; aqui
se fija lo que el documento dice con palabras.
"""
from pathlib import Path

import pytest

import layout as lay
import mover_raw as mr
from layout import Layout

DOC = Path(__file__).resolve().parent.parent / "VAULT_LAYOUT.md"


def _nota(carpeta: Path, nombre="n.md", proveedor="chatgpt"):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / nombre).write_text(f'---\ntitle: "T"\nprovider: {proveedor}\n---\n\nhola\n', encoding="utf-8")


def test_el_documento_existe_y_dice_que_lo_vigila_este_test():
    assert "tests/test_organizar_vault_documentado.py" in DOC.read_text(encoding="utf-8")


# ---- las tres organizaciones ---------------------------------------------------------------------
@pytest.mark.parametrize("preset,conversaciones,proyectos", [
    ("proyectos", "MERGED_VAULT/Conversations", True),
    ("unico", "MERGED_VAULT/Conversations", False),
    ("proveedor", "MERGED_VAULT/ChatGPT/Conversations", False),
])
def test_la_tabla_de_las_tres_organizaciones(preset, conversaciones, proyectos):
    L = Layout(preset=preset)
    assert f"{L.rel('merged')}/{L.conv_rel('chatgpt')}" == conversaciones
    assert L.proyectos is proyectos
    assert preset in DOC.read_text(encoding="utf-8")


def test_la_de_siempre_es_todo_junto_con_proyectos_y_un_vault_sin_marcador_es_de_esa(tmp_path):
    assert lay.PRESET_DEFECTO == "proyectos"
    assert lay.cargar(tmp_path, usar_entorno=False).preset == "proyectos"


def test_cada_proveedor_a_su_carpeta_y_las_sesiones_con_su_casa():
    assert lay.carpeta_proveedor("claude") == "Claude"
    assert lay.carpeta_proveedor("claude-code") == "Claude"
    assert lay.carpeta_proveedor("codex") == "ChatGPT"
    # un proveedor desconocido no se pierde: recibe una carpeta con su nombre
    assert lay.carpeta_proveedor("mistral") == "Mistral"


def test_solo_cuentan_las_carpetas_de_proveedores_que_tienen_conversaciones(tmp_path):
    _nota(tmp_path / "Claude" / "Conversations", proveedor="claude")
    assert Layout(preset="proveedor").conv_dirs(tmp_path) == ["Claude/Conversations"]


def test_los_temas_son_comunes_y_el_raw_no_se_parte():
    L = Layout(preset="proveedor")
    assert L.rel("temas") == "MERGED_VAULT/_Topics"
    assert L.rel("raw") == "RAW_VAULT" and L.rel("conversaciones") == "Conversations"


@pytest.mark.parametrize("preset,donde", [
    ("proyectos", "PRJ_VAULT"),
    ("unico", "MERGED_VAULT/CLAUDE_WEB/PROJECTS"),
    ("proveedor", "MERGED_VAULT/Claude/CLAUDE_WEB/PROJECTS"),
])
def test_sin_vault_de_proyectos_los_de_claude_van_junto_a_sus_artefactos(preset, donde):
    assert Layout(preset=preset).rel("claude.proyectos") == donde
    assert donde in DOC.read_text(encoding="utf-8") or preset == "proyectos"


# ---- cuando se puede cambiar -------------------------------------------------------------------
def _vault_con_notas(tmp_path, preset="proyectos"):
    actual = Layout(preset=preset)
    lay.escribir_marcador(tmp_path, actual)
    merged = actual.ruta(tmp_path, "merged")
    _nota(merged / actual.conv_rel("chatgpt"))
    return tmp_path


def _pedido(base, preset):
    return lay.pedido(base, preset=preset)


def test_sin_conversaciones_se_puede_cambiar_a_cualquiera(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="proyectos"))
    for p in lay.PRESETS:
        assert lay.conflictos(tmp_path, _pedido(tmp_path, p)) == [], p


def test_entre_todo_junto_y_con_proyectos_es_libre(tmp_path):
    base = _vault_con_notas(tmp_path)
    assert lay.conflictos(base, _pedido(base, "unico")) == []


def test_con_proyectos_de_claude_escritos_apagar_el_vault_de_proyectos_se_niega(tmp_path):
    base = _vault_con_notas(tmp_path)
    proyecto = Layout(preset="proyectos").ruta(base, "claude.proyectos") / "P"
    proyecto.mkdir(parents=True)
    (proyecto / "00_project.md").write_text("x", encoding="utf-8")
    assert lay.conflictos(base, _pedido(base, "unico"))


def test_pasar_a_una_carpeta_por_proveedor_con_notas_se_niega(tmp_path):
    base = _vault_con_notas(tmp_path)
    assert lay.conflictos(base, _pedido(base, "proveedor"))


def test_y_al_reves_tambien(tmp_path):
    base = _vault_con_notas(tmp_path, "proveedor")
    assert lay.conflictos(base, _pedido(base, "unico"))


# ---- el RAW ----------------------------------------------------------------------------------------
def _vault_con_raw(tmp_path):
    base = tmp_path / "vault"
    _nota(base / "RAW_VAULT" / "Conversations")
    return base


def test_mover_raw_copia_verifica_no_borra_el_original_y_anota_el_marcador(tmp_path):
    base, destino = _vault_con_raw(tmp_path), tmp_path / "fuera"
    assert mr.mover(base, destino, log=lambda *_: None) == 0
    assert (base / "RAW_VAULT" / "Conversations" / "n.md").is_file(), "el original no se borra"
    assert (destino / "Conversations" / "n.md").read_bytes() == (base / "RAW_VAULT" / "Conversations" / "n.md").read_bytes()
    assert lay.leer_marcador(base).ruta(base, "raw") == destino


def test_dry_run_no_escribe_nada(tmp_path):
    base, destino = _vault_con_raw(tmp_path), tmp_path / "fuera"
    mr.mover(base, destino, dry_run=True, log=lambda *_: None)
    assert not destino.exists() and lay.leer_marcador(base) is None


def test_repetirlo_no_vuelve_a_copiar_lo_que_ya_esta(tmp_path):
    base, destino = _vault_con_raw(tmp_path), tmp_path / "fuera"
    mr.mover(base, destino, log=lambda *_: None)
    (base / lay.MARCADOR).unlink()          # como si se hubiera cortado antes de escribir el marcador
    lineas = []
    mr.mover(base, destino, log=lineas.append)
    assert any("to copy 0" in l for l in lineas), lineas


def test_se_niega_con_un_destino_con_ficheros_ajenos(tmp_path):
    base, destino = _vault_con_raw(tmp_path), tmp_path / "fuera"
    destino.mkdir()
    (destino / "otra_cosa.txt").write_text("x", encoding="utf-8")
    with pytest.raises(mr.ErrorDeMovimiento):
        mr.mover(base, destino, log=lambda *_: None)


def test_el_pipeline_se_niega_si_config_y_vault_no_coinciden_en_el_raw(tmp_path):
    base = _vault_con_raw(tmp_path)
    pedido = lay.pedido(base, raw_vault=str(tmp_path / "otro_sitio"))
    assert any("mover_raw.py" in m for m in lay.conflictos(base, pedido))


def test_y_si_la_fuente_externa_no_esta(tmp_path):
    base, fuera = tmp_path / "vault", tmp_path / "disco"
    base.mkdir()
    lay.escribir_marcador(base, Layout(externas={"raw": str(fuera)}))
    assert lay.conflictos(base, lay.pedido(base, raw_vault=str(fuera)))


# ---- el marcador -------------------------------------------------------------------------------------
def test_el_marcador_se_llama_como_dice_el_documento():
    assert lay.MARCADOR == ".m3m0ria_layout.json"
    assert lay.MARCADOR in DOC.read_text(encoding="utf-8")


# ---- desde la edicion espanola (solo en esta edicion) ------------------------------------------------
def test_la_migracion_desde_la_espanola_sale_de_comparar_las_tablas_y_cubre_las_sesiones():
    import layout_migration as lm
    assert ("MERGED_VAULT/Conversaciones", "MERGED_VAULT/Conversations") in lm.CARPETAS
    assert ("MERGED_VAULT/CLAUDE_CODE/SESIONES", "MERGED_VAULT/CLAUDE_CODE/SESSIONS") in lm.CARPETAS
    assert ("MERGED_VAULT/CODEX/SESIONES", "MERGED_VAULT/CODEX/SESSIONS") in lm.CARPETAS
    assert "layout_migration.py" in DOC.read_text(encoding="utf-8")
