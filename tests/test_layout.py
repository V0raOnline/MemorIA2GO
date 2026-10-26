# -*- coding: utf-8 -*-
"""Tests de layout.py: la tabla unica de nombres de carpeta del vault.

Lo que mas importa aqui es el primero: el layout clasico tiene que seguir
siendo EXACTAMENTE el que ya existe en disco, letra por letra. Si cambiara una
sola, cada vault construido hasta hoy dejaria de encontrar sus carpetas y sus
enlaces sin que ningun test de API lo notara.
"""
import json

import pytest

import layout as lay
from layout import Layout, LayoutError


# Los nombres tal como estaban escritos a mano antes de existir layout.py.
CLASICO_TAL_CUAL = {
    "raw": "RAW_VAULT",
    "merged": "MERGED_VAULT",
    "prj": "PRJ_VAULT",
    "conversaciones": "Conversaciones",
    "chatgpt.raiz": "CHATGPT",
    "chatgpt.generadas": "CHATGPT/GENERADAS",
    "chatgpt.adjuntos": "CHATGPT/ADJUNTOS",
    "chatgpt.web": "CHATGPT/WEB",
    "chatgpt.pendientes": "CHATGPT/_pendientes_descarga.json",
    "grok.raiz": "GROK",
    "grok.adjuntos": "GROK/ADJUNTOS",
    "grok.generadas_imagen": "GROK/GENERADAS_IMAGEN",
    "grok.generadas_video": "GROK/GENERADAS_VIDEO",
    "grok.imagine": "GROK/IMAGINE",
    "grok.pendientes": "GROK/_pendientes_descarga.json",
    "claude.raiz": "CLAUDE",
    "claude.artefactos": "CLAUDE/ARTEFACTOS",
    "claude.memorias": "Claude_Mem",
    "claude.web_raiz": "MERGED_VAULT/CLAUDE_WEB",
    "claude.web_frames": "MERGED_VAULT/CLAUDE_WEB/FRAMES",
    "claude.proyectos": "PRJ_VAULT",
    "sesiones.claude_code": "MERGED_VAULT/CLAUDE_CODE/SESIONES",
    "sesiones.codex": "MERGED_VAULT/CODEX/SESIONES",
    "temas": "MERGED_VAULT/_Temas",
}


def test_el_clasico_es_exactamente_lo_que_ya_existe_en_disco():
    assert lay.CLASICO.a_dict() == CLASICO_TAL_CUAL


def test_el_clasico_es_valido():
    assert lay.CLASICO.problemas() == []


def test_ruta_y_enlace_distinguen_disco_de_nota(tmp_path):
    L = lay.CLASICO
    # En disco es absoluta bajo base_vault...
    assert L.ruta(tmp_path, "chatgpt.generadas") == tmp_path / "CHATGPT" / "GENERADAS"
    # ...y dentro de la nota es relativa y con '/', como la resuelve Obsidian.
    assert L.enlace("chatgpt.generadas", "84f5.webp") == "CHATGPT/GENERADAS/84f5.webp"
    assert "\\" not in L.enlace("grok.generadas_imagen", "a.png")


def test_renombrar_merged_arrastra_lo_que_cuelga_de_el():
    L = Layout({"merged": "FUSIONADO"})
    assert L.rel("merged") == "FUSIONADO"
    assert L.rel("claude.web_frames") == "FUSIONADO/CLAUDE_WEB/FRAMES"
    assert L.rel("sesiones.codex") == "FUSIONADO/CODEX/SESIONES"
    assert L.rel("temas") == "FUSIONADO/_Temas"
    # y no mueve lo que no cuelga de el
    assert L.rel("raw") == "RAW_VAULT"
    assert L.rel("chatgpt.generadas") == "CHATGPT/GENERADAS"


def test_renombrar_la_raiz_de_un_proveedor_arrastra_sus_bancos():
    L = Layout({"grok.raiz": "XAI"})
    assert L.rel("grok.imagine") == "XAI/IMAGINE"
    assert L.rel("grok.adjuntos") == "XAI/ADJUNTOS"
    assert L.rel("grok.pendientes") == "XAI/_pendientes_descarga.json"


def test_relativa_da_el_banco_dentro_de_la_raiz_de_su_proveedor():
    assert lay.CLASICO.relativa("grok.imagine", "grok.raiz") == "IMAGINE"
    assert Layout({"grok.raiz": "XAI"}).relativa("grok.imagine", "grok.raiz") == "IMAGINE"
    # un banco que NO cuelga de la raiz es un layout que esa herramienta no soporta: error claro
    with pytest.raises(LayoutError, match="no cuelga"):
        Layout({"grok.imagine": "OTRO/IMAGINE"}).relativa("grok.imagine", "grok.raiz")


def test_clave_desconocida_se_rechaza_en_vez_de_ignorarse():
    with pytest.raises(LayoutError, match="desconocidas"):
        Layout({"merjed": "X"})  # un typo no puede pasar por "ya lo cogera"
    with pytest.raises(KeyError):
        lay.CLASICO.rel("no.existe")


def test_referencia_circular_o_rota_se_rechaza():
    with pytest.raises(LayoutError, match="circular"):
        Layout({"raw": "{merged}/x", "merged": "{raw}/y"})
    with pytest.raises(LayoutError, match="no existe"):
        Layout({"raw": "{nada}/x"})


@pytest.mark.parametrize("nombre,fragmento", [
    ("C:/abs", "relativo"),
    ("/abs", "relativo"),
    ("a/../b", "'..'"),
    ("a\\b", "separador"),
    ("a:b", "caracteres no validos"),
    (" espacio", "espacios"),
])
def test_nombres_invalidos_se_detectan(nombre, fragmento):
    malos = Layout({"merged": nombre}).problemas()
    assert any(fragmento in m for m in malos), malos
    with pytest.raises(LayoutError):
        Layout({"merged": nombre}).validar()


def test_dos_carpetas_que_solo_difieren_en_mayusculas_son_la_misma_en_windows():
    malos = Layout({"merged": "raw_vault"}).problemas()
    assert any("misma carpeta" in m for m in malos), malos


def test_marcador_ida_y_vuelta(tmp_path):
    L = Layout({"merged": "FUSIONADO"}, preset="mio")
    lay.escribir_marcador(tmp_path, L)
    leido = lay.leer_marcador(tmp_path)
    assert leido == L
    assert leido.preset == "mio"
    assert not list(tmp_path.glob("*.part")), "la escritura atomica no debe dejar restos"


def test_marcador_ausente_o_corrupto_es_none_no_una_excepcion(tmp_path):
    assert lay.leer_marcador(tmp_path) is None
    (tmp_path / lay.MARCADOR).write_text("{ esto no es json", encoding="utf-8")
    assert lay.leer_marcador(tmp_path) is None
    (tmp_path / lay.MARCADOR).write_text(json.dumps({"nombres": {"merjed": "X"}}), encoding="utf-8")
    assert lay.leer_marcador(tmp_path) is None  # clave desconocida: tampoco se fia


def test_cargar_prioridad_entorno_marcador_clasico(tmp_path, monkeypatch):
    monkeypatch.delenv(lay.ENV_LAYOUT, raising=False)
    # sin nada: clasico
    assert lay.cargar(tmp_path) == lay.CLASICO
    # con marcador: el del vault
    delvault = Layout({"merged": "DELVAULT"})
    lay.escribir_marcador(tmp_path, delvault)
    assert lay.cargar(tmp_path).rel("merged") == "DELVAULT"
    # con entorno: manda sobre el marcador
    delentorno = Layout({"merged": "DELENTORNO"})
    monkeypatch.setenv(lay.ENV_LAYOUT, lay.entorno(delentorno)[lay.ENV_LAYOUT])
    assert lay.cargar(tmp_path).rel("merged") == "DELENTORNO"


def test_entorno_corrupto_cae_al_siguiente_nivel_sin_romper(tmp_path, monkeypatch):
    monkeypatch.setenv(lay.ENV_LAYOUT, "no es json")
    assert lay.cargar(tmp_path) == lay.CLASICO


def test_la_opcion_prj_vault_name_de_siempre_se_sigue_respetando(tmp_path, monkeypatch):
    monkeypatch.delenv(lay.ENV_LAYOUT, raising=False)
    assert lay.cargar(tmp_path, prj_vault_name="MIS_PROYECTOS").rel("prj") == "MIS_PROYECTOS"
    # y el valor por defecto de la config no cambia nada
    assert lay.cargar(tmp_path, prj_vault_name="PRJ_VAULT") == lay.CLASICO
