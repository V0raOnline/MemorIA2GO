# -*- coding: utf-8 -*-
"""Presets de organizacion del vault: unico / proveedor / proyectos.

Son dos interruptores independientes (como se parte MERGED, y si hay vault de
proyectos); un preset es una combinacion con nombre. Lo que se prueba aqui es el
modelo; el pipeline entero con cada preset esta en test_presets_de_punta_a_punta.

Lo que mas importa: un vault sin marcador, o con un marcador de antes de los
presets, sigue siendo EXACTAMENTE lo de siempre.
"""
import json

import pytest

import layout as lay
from layout import Layout, LayoutError


# ---- el modelo ------------------------------------------------------------
def test_los_tres_presets_son_combinaciones_de_los_dos_interruptores():
    assert lay.PRESETS == {"unico": ("unico", False), "proveedor": ("proveedor", False),
                           "proyectos": ("unico", True)}


def test_sin_preset_es_lo_de_siempre():
    L = Layout()
    assert (L.preset, L.particion, L.proyectos) == ("proyectos", "unico", True)
    assert L == lay.CLASICO
    assert L.a_dict() == lay.CLASICO.a_dict()


def test_el_alias_antiguo_clasico_es_el_preset_proyectos():
    assert Layout(preset="clasico").preset == "proyectos"
    assert lay.normalizar_preset("clasico") == "proyectos"
    assert lay.normalizar_preset("") == "proyectos"
    assert lay.normalizar_preset(None) == "proyectos"
    assert lay.normalizar_preset(" Proveedor ") == "proveedor"


def test_un_preset_desconocido_se_rechaza_con_los_validos():
    with pytest.raises(LayoutError, match="unico, proveedor, proyectos"):
        lay.normalizar_preset("por-colores")


@pytest.mark.parametrize("nombre,particion,proyectos", [
    ("unico", "unico", False), ("proveedor", "proveedor", False), ("proyectos", "unico", True)])
def test_cada_preset_fija_sus_interruptores(nombre, particion, proyectos):
    L = Layout(preset=nombre)
    assert (L.particion, L.proyectos) == (particion, proyectos)


def test_una_etiqueta_cualquiera_no_cambia_los_interruptores():
    """Los tests y el marcador usan etiquetas libres ("mio", "de-prueba")."""
    L = Layout(preset="mio")
    assert (L.particion, L.proyectos) == ("unico", True)


def test_los_interruptores_se_pueden_combinar_a_mano():
    L = Layout(preset="mio", particion="proveedor", proyectos=True)
    assert (L.particion, L.proyectos) == ("proveedor", True)


def test_una_particion_desconocida_falla():
    with pytest.raises(LayoutError):
        Layout(particion="por-colores")


# ---- la tabla segun los interruptores --------------------------------------
def test_unico_con_proyectos_es_la_tabla_clasica_sin_cambios():
    from test_layout import CLASICO_TAL_CUAL      # los nombres escritos a mano antes de layout.py
    assert Layout(preset="proyectos").a_dict() == CLASICO_TAL_CUAL


def test_partir_por_proveedor_mete_lo_de_cada_proveedor_en_su_carpeta():
    L = Layout(preset="proveedor")
    assert L.rel("claude.web_frames") == "MERGED_VAULT/Claude/CLAUDE_WEB/FRAMES"
    assert L.rel("sesiones.claude_code") == "MERGED_VAULT/Claude/CLAUDE_CODE/SESIONES"
    assert L.rel("sesiones.codex") == "MERGED_VAULT/ChatGPT/CODEX/SESIONES"
    # lo transversal no se parte: un tema cruza proveedores
    assert L.rel("temas") == "MERGED_VAULT/_Temas"
    # y el RAW es la fuente: no se parte nunca
    assert L.rel("raw") == "RAW_VAULT"
    assert L.rel("conversaciones") == "Conversaciones"


def test_renombrar_merged_arrastra_tambien_las_carpetas_de_proveedor():
    L = Layout({"merged": "FUSION"}, preset="proveedor")
    assert L.rel("claude.web_frames") == "FUSION/Claude/CLAUDE_WEB/FRAMES"
    assert L.rel("sesiones.codex") == "FUSION/ChatGPT/CODEX/SESIONES"


def test_con_vault_de_proyectos_los_proyectos_de_claude_van_dentro_de_el():
    assert Layout(preset="proyectos").rel("claude.proyectos") == "PRJ_VAULT"
    assert Layout({"prj": "PROYECTOS"}, preset="proyectos").rel("claude.proyectos") == "PROYECTOS"


def test_sin_vault_de_proyectos_los_de_claude_van_a_merged_junto_a_los_frames():
    assert Layout(preset="unico").rel("claude.proyectos") == "MERGED_VAULT/CLAUDE_WEB/PROYECTOS"
    assert Layout(preset="proveedor").rel("claude.proyectos") == "MERGED_VAULT/Claude/CLAUDE_WEB/PROYECTOS"


@pytest.mark.parametrize("nombre", ["unico", "proveedor", "proyectos"])
def test_todos_los_presets_son_validos(nombre):
    assert Layout(preset=nombre).problemas() == []


# ---- carpeta de cada proveedor ---------------------------------------------
@pytest.mark.parametrize("valor,carpeta", [
    ("chatgpt", "ChatGPT"), ("claude", "Claude"), ("grok", "Grok"), ("copilot", "Copilot"),
    ("claude-code", "Claude"), ("codex", "ChatGPT"),
    ("CLAUDE", "Claude"), ('"grok"', "Grok"), (" claude ", "Claude"),
    (None, "ChatGPT"), ("", "ChatGPT"),
])
def test_carpeta_de_cada_proveedor(valor, carpeta):
    assert lay.carpeta_proveedor(valor) == carpeta


def test_un_proveedor_desconocido_no_se_pierde_ni_rompe_el_nombre():
    assert lay.carpeta_proveedor("mistral") == "Mistral"
    assert lay.carpeta_proveedor("le chat/2") == "Le Chat2"
    assert lay.carpeta_proveedor("???") == "Otros"
    assert lay.carpeta_proveedor("con") == "_Con"      # nombre reservado de Windows


# ---- carpeta de conversaciones ---------------------------------------------
def test_con_merged_unico_las_conversaciones_son_siempre_la_misma_carpeta():
    L = Layout(preset="unico")
    for prov in (None, "chatgpt", "claude", "grok"):
        assert L.conv_rel(prov) == "Conversaciones"


def test_partido_cada_proveedor_tiene_la_suya():
    L = Layout(preset="proveedor")
    assert L.conv_rel("chatgpt") == "ChatGPT/Conversaciones"
    assert L.conv_rel("claude") == "Claude/Conversaciones"
    assert L.conv_rel(None) == "ChatGPT/Conversaciones"
    assert L.conv_rel("claude-code") == "Claude/Conversaciones"


def test_conv_rel_respeta_el_nombre_de_la_subcarpeta():
    assert Layout({"conversaciones": "Charlas"}, preset="proveedor").conv_rel("grok") == "Grok/Charlas"


def test_conv_dirs_unico_es_una_aunque_no_exista(tmp_path):
    assert Layout(preset="unico").conv_dirs(tmp_path) == ["Conversaciones"]


def test_conv_dirs_partido_son_las_que_hay_en_disco_incluidos_proveedores_desconocidos(tmp_path):
    for d in ("ChatGPT/Conversaciones", "Mistral/Conversaciones", "Claude/Otra", "_Temas", "CLAUDE_CODE"):
        (tmp_path / d).mkdir(parents=True)
    assert Layout(preset="proveedor").conv_dirs(tmp_path) == [
        "ChatGPT/Conversaciones", "Mistral/Conversaciones"]


def test_conv_dirs_partido_sin_vault_es_vacio(tmp_path):
    assert Layout(preset="proveedor").conv_dirs(tmp_path / "no_existe") == []


# ---- marcador ----------------------------------------------------------------
def test_el_marcador_guarda_y_devuelve_los_interruptores(tmp_path):
    original = Layout(preset="proveedor", externas={"raw": str(tmp_path / "fuente")})
    lay.escribir_marcador(tmp_path, original)
    datos = json.loads((tmp_path / lay.MARCADOR).read_text(encoding="utf-8"))
    assert datos["version"] == 3 and datos["particion"] == "proveedor" and datos["proyectos"] is False
    leido = lay.leer_marcador(tmp_path)
    assert leido == original and leido.particion == "proveedor" and leido.proyectos is False


def test_un_marcador_anterior_a_los_presets_es_el_layout_de_siempre(tmp_path):
    for version, preset in ((1, "clasico"), (2, "clasico")):
        viejo = {"version": version, "preset": preset, "nombres": lay.CLASICO.a_dict()}
        (tmp_path / lay.MARCADOR).write_text(json.dumps(viejo), encoding="utf-8")
        leido = lay.leer_marcador(tmp_path)
        assert (leido.particion, leido.proyectos) == ("unico", True)
        assert leido == lay.CLASICO


def test_el_estado_viaja_por_el_entorno(monkeypatch):
    monkeypatch.setenv(lay.ENV_LAYOUT, lay.entorno(Layout(preset="proveedor"))[lay.ENV_LAYOUT])
    L = lay.cargar()
    assert (L.particion, L.proyectos) == ("proveedor", False)
    assert L.conv_rel("grok") == "Grok/Conversaciones"


def test_clonar_conserva_los_interruptores():
    L = Layout(preset="proveedor")
    assert L.con(externas={"raw": "/x"}).particion == "proveedor"
    assert L.con(externas={"raw": "/x"}).proyectos is False
    assert L.con(nombres={"prj": "P"}).rel("prj") == "P"


def test_dos_layouts_con_distinta_particion_no_son_iguales():
    assert Layout(preset="unico") != Layout(preset="proveedor")
    assert Layout(preset="unico") != Layout(preset="proyectos")


def test_con_la_misma_tabla_pero_otros_interruptores_tampoco_son_iguales():
    """Los interruptores deciden donde se buscan las conversaciones aunque la tabla coincida."""
    tabla = Layout(preset="proveedor").a_dict()
    assert Layout(tabla, preset="x", particion="proveedor", proyectos=False)         != Layout(tabla, preset="x", particion="unico", proyectos=False)
    assert Layout(tabla, preset="x", particion="proveedor", proyectos=False)         != Layout(tabla, preset="x", particion="proveedor", proyectos=True)


# ---- pedido (lo que la config pide) -------------------------------------------
def test_pedido_sin_preset_y_sin_marcador_es_lo_de_siempre(tmp_path):
    assert lay.pedido(tmp_path) == lay.CLASICO


def test_pedido_con_preset_fija_los_interruptores(tmp_path):
    L = lay.pedido(tmp_path, preset="proveedor")
    assert (L.preset, L.particion, L.proyectos) == ("proveedor", "proveedor", False)


def test_pedido_sin_preset_conserva_los_del_marcador(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="proveedor"))
    assert lay.pedido(tmp_path).particion == "proveedor"


def test_pedido_otro_preset_no_arrastra_las_carpetas_del_anterior(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="proveedor"))
    L = lay.pedido(tmp_path, preset="unico")
    assert L.rel("claude.web_frames") == "MERGED_VAULT/CLAUDE_WEB/FRAMES"
    assert L.rel("sesiones.codex") == "MERGED_VAULT/CODEX/SESIONES"
    assert L.rel("claude.proyectos") == "MERGED_VAULT/CLAUDE_WEB/PROYECTOS"


def test_pedido_conserva_los_nombres_propios_del_marcador(tmp_path):
    lay.escribir_marcador(tmp_path, Layout({"merged": "FUSION", "grok.raiz": "XAI"}, preset="proveedor"))
    L = lay.pedido(tmp_path, preset="proyectos")
    assert L.rel("merged") == "FUSION" and L.rel("grok.adjuntos") == "XAI/ADJUNTOS"
    assert L.rel("claude.web_frames") == "FUSION/CLAUDE_WEB/FRAMES"


def test_pedido_un_preset_desconocido_falla(tmp_path):
    with pytest.raises(LayoutError):
        lay.pedido(tmp_path, preset="por-colores")


def test_cargar_sin_marcador_obedece_el_preset_de_la_config(tmp_path):
    assert lay.cargar(tmp_path, preset="proveedor").particion == "proveedor"
    assert lay.cargar(tmp_path) == lay.CLASICO


def test_cargar_con_marcador_manda_el_marcador_no_la_config(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="unico"))
    assert lay.cargar(tmp_path, preset="proveedor").particion == "unico"


# ---- conflictos -----------------------------------------------------------------
def _nota(base, rel):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\ntitle: x\n---\n", encoding="utf-8")


def test_cambiar_la_particion_de_un_vault_con_notas_se_rechaza(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="unico"))
    _nota(tmp_path, "MERGED_VAULT/Conversaciones/2026/01/a.md")
    malos = lay.conflictos(tmp_path, lay.pedido(tmp_path, preset="proveedor"))
    assert len(malos) == 1
    assert "dos veces" in malos[0] and "layout_preset" in malos[0] and "'unico'" in malos[0]


def test_el_rechazo_vale_tambien_en_sentido_contrario(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="proveedor"))
    _nota(tmp_path, "MERGED_VAULT/Claude/Conversaciones/2026/01/a.md")
    assert lay.conflictos(tmp_path, lay.pedido(tmp_path, preset="proyectos"))


def test_un_vault_sin_marcador_con_notas_es_unico_y_no_se_parte(tmp_path):
    """Es justo el vault real de V0ra: sin marcador, con notas en Conversaciones."""
    _nota(tmp_path, "MERGED_VAULT/Conversaciones/2026/01/a.md")
    assert lay.conflictos(tmp_path, lay.pedido(tmp_path, preset="proveedor"))
    assert lay.conflictos(tmp_path, lay.pedido(tmp_path, preset="proyectos")) == []
    assert lay.conflictos(tmp_path, lay.pedido(tmp_path)) == []


def test_sin_notas_fusionadas_se_puede_cambiar_de_particion(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="unico"))
    (tmp_path / "MERGED_VAULT" / "Conversaciones").mkdir(parents=True)
    assert lay.conflictos(tmp_path, lay.pedido(tmp_path, preset="proveedor")) == []


def test_un_vault_nuevo_adopta_cualquier_preset(tmp_path):
    for nombre in lay.PRESETS:
        assert lay.conflictos(tmp_path, lay.pedido(tmp_path, preset=nombre)) == []


def test_repetir_el_mismo_preset_nunca_es_un_conflicto(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="proveedor"))
    _nota(tmp_path, "MERGED_VAULT/Grok/Conversaciones/2026/01/a.md")
    assert lay.conflictos(tmp_path, lay.pedido(tmp_path, preset="proveedor")) == []
    assert lay.conflictos(tmp_path, lay.pedido(tmp_path)) == []


def test_apagar_el_vault_de_proyectos_con_proyectos_de_claude_escritos_se_rechaza(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="proyectos"))
    _nota(tmp_path, "PRJ_VAULT/MiProyecto/00_proyecto.md")
    malos = lay.conflictos(tmp_path, lay.pedido(tmp_path, preset="unico"))
    assert len(malos) == 1 and "proyectos de Claude" in malos[0]


def test_encender_el_vault_de_proyectos_con_proyectos_de_claude_ya_escritos_en_merged_se_rechaza(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="unico"))
    _nota(tmp_path, "MERGED_VAULT/CLAUDE_WEB/PROYECTOS/MiProyecto/00_proyecto.md")
    assert lay.conflictos(tmp_path, lay.pedido(tmp_path, preset="proyectos"))


def test_apagar_el_vault_de_proyectos_con_solo_vistas_de_conversaciones_es_libre(tmp_path):
    """PRJ_VAULT es una vista que se regenera: sus conversaciones no son la unica copia."""
    lay.escribir_marcador(tmp_path, Layout(preset="proyectos"))
    _nota(tmp_path, "PRJ_VAULT/Algo/2026/01/a.md")
    assert lay.conflictos(tmp_path, lay.pedido(tmp_path, preset="unico")) == []


def test_el_conflicto_de_raw_sigue_funcionando_con_los_presets(tmp_path):
    lay.escribir_marcador(tmp_path, Layout(preset="proveedor"))
    (tmp_path / "RAW_VAULT").mkdir()
    pedido = lay.pedido(tmp_path, raw_vault=str(tmp_path.parent / "otro_raw"), preset="proveedor")
    assert any("RAW" in m for m in lay.conflictos(tmp_path, pedido))


# ---- los consumidores ------------------------------------------------------------
def _escribir_sesion(tmp_path, nombre="s.jsonl"):
    import test_session_ingest as t
    return t._escribir_jsonl(tmp_path / nombre, t._sesion_con_todo())


def test_las_sesiones_de_claude_code_van_a_la_carpeta_de_claude(tmp_path):
    import session_ingest as si
    base = tmp_path / "vault"
    base.mkdir()
    lay.escribir_marcador(base, Layout(preset="proveedor"))
    escritas = si.ingest_sesion(_escribir_sesion(tmp_path), base, nivel=2)
    madre = escritas["madre"].relative_to(base).as_posix()
    assert madre.startswith("MERGED_VAULT/Claude/Conversaciones/Sesiones-Code/2026/08/"), madre
    for rol in ("razonamientos", "herramientas"):
        hija = escritas[rol].relative_to(base).as_posix()
        assert hija.startswith("MERGED_VAULT/Claude/CLAUDE_CODE/SESIONES/"), hija
    assert not (base / "MERGED_VAULT" / "Conversaciones").exists()


def test_las_sesiones_con_merged_unico_siguen_donde_siempre(tmp_path):
    import session_ingest as si
    base = tmp_path / "vault"
    base.mkdir()
    lay.escribir_marcador(base, Layout(preset="unico"))
    escritas = si.ingest_sesion(_escribir_sesion(tmp_path), base, nivel=2)
    assert escritas["madre"].relative_to(base).as_posix().startswith(
        "MERGED_VAULT/Conversaciones/Sesiones-Code/2026/08/")


def _export_de_claude_con_un_proyecto(tmp_path):
    import test_newclaude_writers as w
    return w._crear_layout(tmp_path, con_projects=[w._proyecto_minimo(uuid="pu", name="P")])


@pytest.mark.parametrize("preset,esperado", [
    ("proyectos", "PRJ_VAULT/P/00_proyecto.md"),
    ("unico", "MERGED_VAULT/CLAUDE_WEB/PROYECTOS/P/00_proyecto.md"),
    ("proveedor", "MERGED_VAULT/Claude/CLAUDE_WEB/PROYECTOS/P/00_proyecto.md"),
])
def test_los_proyectos_de_claude_van_donde_dice_el_preset(tmp_path, preset, esperado):
    from providers import newclaude_adapter as nc
    export = _export_de_claude_con_un_proyecto(tmp_path)
    base = tmp_path / "vault"
    base.mkdir()
    lay.escribir_marcador(base, Layout(preset=preset))
    stats = nc.ingest_extras(export, base)
    assert stats["projects"]["proyectos"] == 1
    assert (base / esperado).is_file(), f"no esta {esperado}"
    if preset != "proyectos":
        assert not (base / "PRJ_VAULT").exists(), "sin vault de proyectos no se debe crear PRJ_VAULT"


def test_los_frames_siguen_a_la_carpeta_de_claude(tmp_path):
    import test_newclaude_writers as w
    from providers import newclaude_adapter as nc
    export = w._crear_layout(tmp_path, con_frames=[{
        "id": "af", "kind": "artifact", "visibility": "private", "owner_account": "u", "active_version": "v",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "versions": [{"id": "v", "title": "t", "description": "", "created_at": "2026-01-01T00:00:00+00:00"}],
        "_versions_html": {"v": "<html/>"}}])
    base = tmp_path / "vault"
    base.mkdir()
    lay.escribir_marcador(base, Layout(preset="proveedor"))
    nc.ingest_extras(export, base)
    assert (base / "MERGED_VAULT" / "Claude" / "CLAUDE_WEB" / "FRAMES" / "af" / "00_frame.md").is_file()
