# -*- coding: utf-8 -*-
"""Bug real 2026-10-21: el export de ChatGPT de octubre guarda las imagenes como
`file_XXXX.dat` (punteros `sediment://file_XXXX`) y `file-XXXX.dat` (`file-service://`),
sin el sufijo -<uuid> del formato anterior y con una extension que no dice el tipo.
AssetIndex solo conocia el formato viejo: indexaba 0 de 3.174 ficheros, ninguna imagen se
resolvia y 5.032 referencias de las notas de V0ra quedaron como "imagen no
disponible en el export", sin un solo error. Un hilo concreto ("Termino para latencia")
tenia 44 imagenes y las 44 estaban en el zip.
"""
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import split_chatgpt_export as sce

RAIZ = Path(__file__).resolve().parent.parent

PNG = b"\x89PNG\r\n\x1a\n" + b"png-de-prueba"
JPG = b"\xff\xd8\xff\xe0" + b"jpg-de-prueba"
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"webp-de-prueba"
GIF = b"GIF89a" + b"gif-de-prueba"
MP3 = b"ID3\x04\x00\x00" + b"audio"


def _zip(entradas: dict) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nombre, datos in entradas.items():
            z.writestr(nombre, datos)
    buf.seek(0)
    return zipfile.ZipFile(buf)


# ---- el indice ---------------------------------------------------------------------
def test_indexa_los_dat_del_esquema_sediment():
    idx = sce.AssetIndex(_zip({"file_00000000abc.dat": PNG}))
    assert idx.by_id == {"file_00000000abc": "file_00000000abc.dat"}


def test_indexa_los_dat_del_esquema_file_service():
    idx = sce.AssetIndex(_zip({"file-1zNVGzKhM9w9hA5asY7Ff2.dat": JPG}))
    assert "file-1zNVGzKhM9w9hA5asY7Ff2" in idx.by_id


def test_el_formato_anterior_con_uuid_sigue_funcionando():
    nombre = "file-AbCd1234-2c1f4b3e-1111-4222-8333-444455556666.png"
    idx = sce.AssetIndex(_zip({nombre: PNG}))
    assert idx.by_id == {"file-AbCd1234": nombre}


@pytest.mark.parametrize("dat_primero", [True, False])
def test_el_formato_con_uuid_manda_si_hay_dos_ficheros_para_el_mismo_id(dat_primero):
    viejo = "file-AbCd1234-2c1f4b3e-1111-4222-8333-444455556666.png"
    entradas = {"file-AbCd1234.dat": JPG, viejo: PNG} if dat_primero else {viejo: PNG, "file-AbCd1234.dat": JPG}
    assert sce.AssetIndex(_zip(entradas)).by_id["file-AbCd1234"] == viejo


def test_los_json_y_el_html_del_export_no_se_indexan_como_imagenes():
    idx = sce.AssetIndex(_zip({"conversations-000.json": b"[]", "chat.html": b"x", "user.json": b"{}",
                               "export_manifest.json": b"{}", "file_zzz.dat": PNG}))
    assert list(idx.by_id) == ["file_zzz"]


def test_un_fichero_con_pinta_de_asset_que_no_se_sabe_indexar_se_cuenta():
    """Si el export vuelve a cambiar de formato, que se note."""
    idx = sce.AssetIndex(_zip({"file_ok.dat": PNG, "file-raro-sin-extension": b"x"}))
    assert idx.sin_indexar == 1


def test_sin_zip_no_indexa_nada():
    assert sce.AssetIndex(None).by_id == {}


# ---- el tipo real, por los bytes -----------------------------------------------------
@pytest.mark.parametrize("datos,ext", [(PNG, ".png"), (JPG, ".jpg"), (WEBP, ".webp"), (GIF, ".gif")])
def test_un_dat_toma_la_extension_de_sus_bytes(datos, ext):
    idx = sce.AssetIndex(_zip({"file_x.dat": datos}))
    assert idx.get_bytes("sediment://file_x") == (datos, ext)


def test_un_dat_que_no_es_imagen_conserva_su_extension():
    idx = sce.AssetIndex(_zip({"file_x.dat": MP3}))
    assert idx.get_bytes("sediment://file_x")[1] == ".dat"


def test_una_extension_real_no_se_toca():
    nombre = "file-AbCd1234-2c1f4b3e-1111-4222-8333-444455556666.webp"
    idx = sce.AssetIndex(_zip({nombre: JPG}))
    assert idx.get_bytes("file-service://file-AbCd1234")[1] == ".webp"


def test_el_puntero_que_no_esta_en_el_zip_no_se_resuelve():
    idx = sce.AssetIndex(_zip({"file_x.dat": PNG}))
    assert idx.get_bytes("sediment://file_no_esta") is None


# ---- la sustitucion en la nota ----------------------------------------------------------
class _Banco:
    def __init__(self, tmp_path):
        self.writer = sce.AssetWriter(str(tmp_path / "GENERADAS"))
        self.rel_prefix = "CHATGPT/GENERADAS"


@pytest.fixture(autouse=True)
def _contadores_a_cero():
    for k in sce.IMAGE_STATS:
        sce.IMAGE_STATS[k] = 0
    yield


def test_el_marcador_se_sustituye_por_un_enlace_a_un_fichero_que_existe(tmp_path):
    idx = sce.AssetIndex(_zip({"file_x.dat": PNG}))
    banco = _Banco(tmp_path)
    md = sce.render_image_tokens("antes \x00IMG:sediment://file_x\x00 despues", idx, {"subida": banco})
    enlace = md.split("![](")[1].split(")")[0]
    assert enlace.startswith("CHATGPT/GENERADAS/") and enlace.endswith(".png")
    assert (tmp_path / "GENERADAS" / enlace.rsplit("/", 1)[1]).read_bytes() == PNG
    assert "no disponible" not in md


def test_un_puntero_ausente_sigue_dejando_el_aviso(tmp_path):
    idx = sce.AssetIndex(_zip({"file_x.dat": PNG}))
    md = sce.render_image_tokens("\x00IMG:sediment://file_otra\x00", idx, {"subida": _Banco(tmp_path)})
    assert "imagen no disponible en el export: sediment://file_otra" in md


def test_los_contadores_cuentan_resueltas_y_no_disponibles(tmp_path):
    idx = sce.AssetIndex(_zip({"file_a.dat": PNG, "file_b.dat": JPG}))
    banco = {"subida": _Banco(tmp_path)}
    sce.render_image_tokens("\x00IMG:sediment://file_a\x00\x00IMG:sediment://file_b\x00"
                            "\x00IMG:sediment://file_c\x00", idx, banco)
    sce.render_image_tokens("\x00IMG:sediment://file_a\x00", None, banco)
    assert sce.IMAGE_STATS == {"resueltas": 2, "no_disponibles": 1, "omitidas": 1}


# ---- de punta a punta: un export con el formato nuevo ----------------------------------
def _conv(pointer: str, generada: bool) -> dict:
    meta = {"dalle": {"gen_id": "g1", "prompt": "un gato"}} if generada else {}
    return {
        "title": "Con imagen", "conversation_id": "conv-dat-0001", "create_time": 1790000000.0,
        "update_time": 1790000100.0, "current_node": "n1",
        "mapping": {"n1": {"id": "n1", "parent": None, "children": [], "message": {
            "id": "m1", "author": {"role": "assistant"}, "create_time": 1790000050.0,
            "content": {"content_type": "text", "parts": [
                {"content_type": "image_asset_pointer", "asset_pointer": pointer, "metadata": meta}]},
            "metadata": {}}}}}


def _importar(tmp_path: Path, entradas: dict, conv: dict):
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("conversations-000.json", json.dumps([conv]))
        for n, d in entradas.items():
            zf.writestr(n, d)
    salida = tmp_path / "RAW" / "Conversaciones"
    gen, adj = tmp_path / "CHATGPT" / "GENERADAS", tmp_path / "CHATGPT" / "ADJUNTOS"
    r = subprocess.run(
        [sys.executable, str(RAIZ / "split_chatgpt_export.py"), str(z), str(salida),
         "--generadas-dir", str(gen), "--adjuntos-dir", str(adj)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RAIZ)
    return r, salida, gen, adj


def test_un_export_nuevo_con_dat_enlaza_la_imagen_y_la_deja_en_su_banco(tmp_path):
    r, salida, gen, adj = _importar(tmp_path, {"file_00000000abc.dat": PNG},
                                    _conv("sediment://file_00000000abc", generada=True))
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
    nota = next(salida.rglob("*.md")).read_text(encoding="utf-8")
    assert "imagen no disponible" not in nota
    enlace = nota.split("![](")[1].split(")")[0]
    assert enlace.startswith("CHATGPT/GENERADAS/") and enlace.endswith(".png")
    assert (gen / enlace.rsplit("/", 1)[1]).read_bytes() == PNG
    assert not list(adj.glob("*.png")), "una imagen generada no es una subida"
    assert "resueltas: 1 | no disponibles en el export: 0" in r.stdout


def test_una_subida_va_a_adjuntos_con_su_extension_real(tmp_path):
    r, salida, gen, adj = _importar(tmp_path, {"file-AbC123.dat": JPG},
                                    _conv("file-service://file-AbC123", generada=False))
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
    nota = next(salida.rglob("*.md")).read_text(encoding="utf-8")
    assert "CHATGPT/ADJUNTOS/" in nota and nota.split("![](")[1].split(")")[0].endswith(".jpg")
    assert len(list(adj.glob("*.jpg"))) == 1


def test_un_puntero_que_el_export_no_trae_se_cuenta_en_el_resumen(tmp_path):
    r, salida, gen, adj = _importar(tmp_path, {"file_otra.dat": PNG},
                                    _conv("sediment://file_que_no_esta", generada=True))
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
    assert "imagen no disponible en el export: sediment://file_que_no_esta" in next(salida.rglob("*.md")).read_text(encoding="utf-8")
    assert "resueltas: 0 | no disponibles en el export: 1" in r.stdout


def test_el_resumen_avisa_si_el_zip_trae_ficheros_que_no_sabe_indexar(tmp_path):
    r, *_ = _importar(tmp_path, {"file_ok.dat": PNG, "file-sin-extension": b"x"},
                      _conv("sediment://file_ok", generada=True))
    assert "ficheros con pinta de imagen" in r.stdout
