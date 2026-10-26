# -*- coding: utf-8 -*-
"""El pipeline entero, con un layout que NO es el clasico.

Los demas tests prueban cada pieza con los nombres de siempre, y con esos
nombres un modulo que siguiera escribiendo "MERGED_VAULT" a mano pasaria igual.
Este monta un vault cuyo layout no se parece en nada al clasico, ejecuta el
pipeline REAL como subproceso (el mismo camino que usa el launcher) y comprueba
dos cosas que ninguna verificacion de API ve:

  1. No aparece NINGUNA carpeta con un nombre clasico. Un fichero que escribiera
     a mano "RAW_VAULT" habria creado una carpeta hermana, sin error.
  2. Todos los enlaces a assets de las notas apuntan a un fichero que existe.
     Es la comprobacion que faltaba cuando 654 de 666 enlaces de linaje
     estaban rotos con la verificacion en verde: comprobar que el texto del
     enlace "casa" no es lo mismo que comprobar que el enlace funciona.
"""
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import layout as lay

RAIZ = Path(__file__).resolve().parent.parent

PNG = b"\x89PNG\r\n\x1a\n" + b"contenido-de-prueba"
PNG2 = b"\x89PNG\r\n\x1a\n" + b"otra-imagen-distinta"
USER = "00000000-0000-0000-0000-000000000000"
U_ADJ = "11111111-1111-4111-8111-111111111111"
U_IMG = "22222222-2222-4222-8222-222222222222"
U_PEND = "33333333-3333-4333-8333-333333333333"

# Un layout que no se parece al clasico en nada: ni vaults, ni bancos, ni subcarpeta.
OTRO = lay.Layout({
    "raw": "CRUDO",
    "merged": "FUSION",
    "prj": "PROJECTS",
    "conversaciones": "Charlas",
    "grok.raiz": "XAI",
    "grok.adjuntos": "{grok.raiz}/subidas",
    "grok.generadas_imagen": "{grok.raiz}/imagenes",
    "grok.generadas_video": "{grok.raiz}/videos",
    "grok.pendientes": "{grok.raiz}/por_bajar.json",
    "grok.imagine": "{grok.raiz}/descargas_imagine",
    "chatgpt.raiz": "OAI",
    "chatgpt.generadas": "{chatgpt.raiz}/hechas",
    "chatgpt.adjuntos": "{chatgpt.raiz}/mis_subidas",
    "chatgpt.web": "{chatgpt.raiz}/de_la_web",
    "chatgpt.pendientes": "{chatgpt.raiz}/por_bajar.json",
    "chatgpt.generadas_miniaturas": "{chatgpt.raiz}/miniaturas",
    "copilot.raiz": "MSFT",
    "copilot.generadas_imagen": "{copilot.raiz}/imagenes",
    "claude.raiz": "ANT",
    "claude.artefactos": "{claude.raiz}/piezas",
    "claude.memorias": "Memorias",
}, preset="de-prueba")


def _componentes(layout_):
    return {c for v in layout_.a_dict().values() for c in v.split("/")}


# Las carpetas que el layout clasico crearia y este NO usa. Ninguna puede aparecer.
# (Se calcula, no se escribe a mano: si alguien reutiliza un nombre clasico en OTRO,
# deja de estar prohibido y el test lo deja de buscar -- por eso se comprueba abajo
# que siguen estando los que importan.)
NOMBRES_CLASICOS = sorted(_componentes(lay.CLASICO) - _componentes(OTRO) - {"_pendientes_descarga.json"})


def test_el_layout_de_prueba_no_comparte_ningun_nombre_importante_con_el_clasico():
    """Guarda del propio test: sin esto, renombrar mal un banco en OTRO dejaria
    de vigilar justo ese nombre y el test seguiria en verde."""
    for n in ("RAW_VAULT", "MERGED_VAULT", "PRJ_VAULT", "CHATGPT", "GROK", "CLAUDE", "Conversations",
              "GENERATED", "ATTACHMENTS", "ARTIFACTS", "GENERATED_IMAGE", "GENERATED_VIDEO", "WEB",
              "IMAGINE", "Claude_Mem", "COPILOT", "GENERATED_Thmbnails"):
        assert n in NOMBRES_CLASICOS, f"'{n}' ya no esta prohibido: OTRO lo reutiliza"


def _export_grok(destino: Path) -> Path:
    cuerpo = {
        "conversations": [{
            "conversation": {"id": "c1", "title": "Con un adjunto",
                              "create_time": "2026-06-10T08:00:00Z",
                              "modify_time": "2026-06-10T08:10:00Z", "leaf_response_id": None},
            "responses": [
                {"response": {"_id": "r1", "parent_response_id": None, "sender": "human",
                              "message": "Mira este fichero",
                              "create_time": {"$date": {"$numberLong": "1770000000000"}},
                              "model": "", "file_attachments": [U_ADJ]}, "share_link": None},
                {"response": {"_id": "r2", "parent_response_id": "r1", "sender": "ASSISTANT",
                              "message": "Lo veo.",
                              "create_time": {"$date": {"$numberLong": "1770000300000"}},
                              "model": "grok-4"}, "share_link": None},
            ],
        }],
        "projects": [], "tasks": [],
        "media_posts": [
            {"id": U_IMG, "media_type": "image", "original_prompt": "un gato", "link": "https://x/1",
             "create_time": "2026-06-10T08:00:00Z"},
            {"id": U_PEND, "media_type": "image", "original_prompt": "sin binario", "link": "https://x/2",
             "create_time": "2026-06-10T08:00:00Z"},
        ],
    }
    z = destino / "grok_export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(f"ttl/30d/export_data/{USER}/prod-grok-backend.json", json.dumps(cuerpo))
        zf.writestr(f"ttl/30d/export_data/{USER}/prod-mc-asset-server//{U_ADJ}/content", PNG)
        zf.writestr(f"ttl/30d/export_data/{USER}/prod-mc-asset-server//{U_IMG}/content", PNG2)
    return z


def _montar(tmp_path: Path, layout_: lay.Layout):
    exports = tmp_path / "exports"
    base = tmp_path / "vault"
    exports.mkdir()
    base.mkdir()
    _export_grok(exports)
    # El marcador es "el layout con el que se construye este vault".
    lay.escribir_marcador(base, layout_)
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(
        "paths:\n"
        f"  base_vault: '{base.as_posix()}'\n"
        f"  exports_dir: '{exports.as_posix()}'\n"
        "options:\n  by_year: true\n  by_month: true\n  make_index: true\n",
        encoding="utf-8")
    return base, cfg


def _ejecutar(cfg: Path):
    import os
    entorno = {k: v for k, v in os.environ.items() if k != lay.ENV_LAYOUT}
    entorno["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(RAIZ / "MemorIA2GO.py"), "--config", str(cfg), "--yes", "--no-wizard"],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=entorno, timeout=300)


def _enlaces_a_ficheros(base: Path, carpeta: Path):
    """[(nota, ruta_del_enlace)] de cada ![](...) o [](...) no web de las notas."""
    rx = re.compile(r"\]\(([^)\s]+)\)")
    salida = []
    for nota in carpeta.rglob("*.md"):
        for ruta in rx.findall(nota.read_text(encoding="utf-8", errors="ignore")):
            if not ruta.startswith(("http://", "https://", "#", "mailto:")):
                salida.append((nota, ruta))
    return salida


@pytest.fixture(scope="module")
def vault_otro(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("layout_otro")
    base, cfg = _montar(tmp, OTRO)
    r = _ejecutar(cfg)
    return base, r


def test_el_pipeline_termina_bien_con_otro_layout(vault_otro):
    base, r = vault_otro
    assert r.returncode == 0, f"salida {r.returncode}\n{r.stdout[-2500:]}\n{r.stderr[-1500:]}"


def test_se_crean_las_carpetas_del_layout_pedido(vault_otro):
    base, _ = vault_otro
    for clave in ("raw", "merged", "prj", "grok.adjuntos", "grok.generadas_imagen"):
        assert OTRO.ruta(base, clave).is_dir(), f"falta {OTRO.rel(clave)} ({clave})"
    assert any(OTRO.ruta(base, "raw").joinpath("Charlas").rglob("*.md")), "no hay notas en la subcarpeta pedida"
    assert OTRO.ruta(base, "grok.pendientes").is_file(), "falta la lista de pendientes en su sitio"


def test_no_aparece_ninguna_carpeta_con_nombre_clasico(vault_otro):
    """Un modulo con un nombre escrito a mano crearia aqui una carpeta hermana y
    no daria error. Este es el test que lo caza."""
    base, _ = vault_otro
    nombres = {p.name for p in base.rglob("*") if p.is_dir()}
    sobran = [n for n in NOMBRES_CLASICOS if n in nombres]
    assert not sobran, f"carpetas con nombre clasico en un vault de otro layout: {sobran}"


def test_todos_los_enlaces_de_las_notas_apuntan_a_un_fichero_que_existe(vault_otro):
    base, _ = vault_otro
    enlaces = _enlaces_a_ficheros(base, OTRO.ruta(base, "merged"))
    # No vacio: sin esto, un enlace que desaparece por completo "pasaria".
    assert enlaces, "no hay ningun enlace a assets en las notas: el test no estaria probando nada"
    rotos = [f"{n.relative_to(base).as_posix()} -> {r}" for n, r in enlaces if not (base / r).is_file()]
    assert not rotos, "enlaces que no resuelven a un fichero:\n  " + "\n  ".join(rotos)


def test_los_enlaces_usan_el_nombre_del_banco_del_layout(vault_otro):
    base, _ = vault_otro
    rutas = [r for _, r in _enlaces_a_ficheros(base, OTRO.ruta(base, "merged"))]
    assert any(r.startswith(OTRO.rel("grok.adjuntos") + "/") for r in rutas), rutas


def test_los_indices_se_generan_en_el_vault_fusionado_del_layout(vault_otro):
    base, _ = vault_otro
    assert (OTRO.ruta(base, "merged") / "_index_grok.md").is_file()


def test_las_estadisticas_cuentan_lo_que_hay_con_ese_layout(vault_otro):
    base, _ = vault_otro
    import vault_stats
    s = vault_stats.compute_stats(base)
    assert s["layout"]["merged"] == "FUSION"
    assert s["vaults"]["FUSION"]["notas"] >= 1
    assert s["assets"]["por_proveedor"]["grok"]["items"] >= 2  # el adjunto y la imagen


def test_el_marcador_no_se_toca(vault_otro):
    base, _ = vault_otro
    assert lay.leer_marcador(base) == OTRO


def test_un_vault_clasico_sigue_creando_exactamente_lo_de_siempre(tmp_path):
    """El otro lado de la moneda: sin marcador, el resultado es el de siempre
    y el pipeline deja el marcador clasico para la proxima vez."""
    exports = tmp_path / "exports"
    base = tmp_path / "vault"
    exports.mkdir()
    base.mkdir()
    _export_grok(exports)
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(f"paths:\n  base_vault: '{base.as_posix()}'\n  exports_dir: '{exports.as_posix()}'\n"
                   "options:\n  by_year: true\n  by_month: true\n  make_index: true\n", encoding="utf-8")
    r = _ejecutar(cfg)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]
    for clave in ("raw", "merged", "prj", "grok.adjuntos", "grok.generadas_imagen"):
        assert lay.CLASICO.ruta(base, clave).is_dir(), clave
    assert lay.leer_marcador(base) == lay.CLASICO
    enlaces = _enlaces_a_ficheros(base, lay.CLASICO.ruta(base, "merged"))
    assert enlaces and all((base / r_).is_file() for _, r_ in enlaces)
