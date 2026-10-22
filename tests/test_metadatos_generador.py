# -*- coding: utf-8 -*-
"""El manifiesto de cada imagen generada guarda con que se genero, exacto del export.

Medido en los exports reales de V0ra (jun-2025 a mar-2026): todas las generadas salen de la
herramienta nativa de ChatGPT (`t2uay3k.sj1i4kz`, bloque `generation`), ninguna de DALL-E. Lo que
si varia y viene exacto es el modelo del chat en ese turno (gpt-4o, gpt-5...) y si la imagen es
una edicion de otra (`parent_gen_id`). Las de la biblioteca nueva no traen modelo.
"""
import json
import zipfile

import split_chatgpt_export as sce
from test_recuperar_imagenes import JPG, PNG, PNG2, _importar
from test_biblioteca_generadas import _entrada


def _conv_con_parte(parte, rol="tool", metadata_msg=None):
    return {"title": "Generando", "conversation_id": "conv-gen-1", "current_node": "n1",
            "mapping": {"n1": {"message": {"author": {"role": rol, "name": "t2uay3k.sj1i4kz"},
                                           "content": {"content_type": "multimodal_text", "parts": [parte]},
                                           "metadata": metadata_msg or {}}, "parent": None}}}


def _parte(puntero="sediment://file_abc", **metadata):
    return {"content_type": "image_asset_pointer", "asset_pointer": puntero, "metadata": metadata}


def _meta(conv):
    m = {}
    sce.parse_json_conversations([conv], image_meta_out=m)
    return m["sediment://file_abc"]


def test_generacion_nativa_con_el_modelo_del_chat():
    m = _meta(_conv_con_parte(_parte(generation={"gen_id": "g1", "parent_gen_id": None}),
                              metadata_msg={"model_slug": "gpt-5"}))
    assert m["origen"] == "generada" and m["generador"] == "chatgpt-imagen" and m["modelo"] == "gpt-5"
    assert "edicion" not in m


def test_si_no_hay_model_slug_vale_el_modelo_por_defecto():
    m = _meta(_conv_con_parte(_parte(generation={"gen_id": "g1"}), metadata_msg={"default_model_slug": "gpt-4o"}))
    assert m["modelo"] == "gpt-4o"


def test_sin_modelo_no_se_inventa_ninguno():
    m = _meta(_conv_con_parte(_parte(generation={"gen_id": "g1"})))
    assert m["generador"] == "chatgpt-imagen" and "modelo" not in m


def test_una_edicion_de_otra_imagen_se_marca():
    m = _meta(_conv_con_parte(_parte(generation={"gen_id": "g2", "parent_gen_id": "g1"})))
    assert m["edicion"] is True


def test_dalle_con_prompt_es_dalle():
    m = _meta(_conv_con_parte(_parte(dalle={"gen_id": "g1", "prompt": "un gato"})))
    assert m["generador"] == "chatgpt-dalle" and m["prompt"] == "un gato"


def test_una_subida_no_lleva_generador_ni_modelo():
    m = _meta(_conv_con_parte(_parte(), rol="user", metadata_msg={"model_slug": "gpt-5"}))
    assert m["origen"] == "subida" and "generador" not in m and "modelo" not in m


def test_el_formato_de_mensajes_plano_tambien_lleva_el_modelo():
    conv = {"title": "Plano", "messages": [{"author": {"role": "tool"}, "metadata": {"model_slug": "gpt-5-1"},
                                            "content": {"content_type": "multimodal_text",
                                                        "parts": [_parte(generation={"gen_id": "g1"})]}}]}
    assert _meta(conv)["modelo"] == "gpt-5-1"


# ---- de punta a punta: lo que queda escrito en el manifiesto --------------------------------------
def _export(tmp_path, convs, ficheros, biblioteca=None):
    z = tmp_path / "e.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("conversations-000.json", json.dumps(convs))
        for n, d in ficheros.items():
            zf.writestr(n, d)
        if biblioteca is not None:
            zf.writestr("library_files.json", json.dumps(biblioteca))
    return z


def _conv_completa(cid="conv-rec-0001"):
    nodos = {
        "n0": {"id": "n0", "parent": None, "children": ["n1"], "message": {
            "id": "m0", "author": {"role": "user"}, "create_time": 1790000000.0,
            "content": {"content_type": "multimodal_text", "parts": ["dibuja un gato"]}, "metadata": {}}},
        "n1": {"id": "n1", "parent": "n0", "children": [], "message": {
            "id": "m1", "author": {"role": "tool", "name": "t2uay3k.sj1i4kz"}, "create_time": 1790000010.0,
            "content": {"content_type": "multimodal_text", "parts": [
                _parte("sediment://file_gen", generation={"gen_id": "g2", "parent_gen_id": "g1"})]},
            "metadata": {"model_slug": "gpt-5-2"}}},
    }
    return {"title": "Con imagenes", "conversation_id": cid, "create_time": 1790000000.0,
            "update_time": 1790000100.0, "current_node": "n1", "mapping": nodos}


def test_el_importador_escribe_generador_modelo_y_edicion_en_el_manifiesto(tmp_path):
    base = tmp_path / "vault"
    _importar(_export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG}), base / "RAW" / "Conversaciones", base)
    (m,) = json.loads((base / "CHATGPT" / "GENERADAS" / "_image_manifest.json").read_text(encoding="utf-8")).values()
    assert (m["generador"], m["modelo"], m["edicion"]) == ("chatgpt-imagen", "gpt-5-2", True)


def test_las_de_la_biblioteca_se_marcan_como_biblioteca(tmp_path):
    base = tmp_path / "vault"
    z = _export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG, "file_lib.dat": JPG},
                [_entrada("file_lib", "De la biblioteca.png")])
    _importar(z, base / "RAW" / "Conversaciones", base)
    man = json.loads((base / "CHATGPT" / "GENERADAS" / "_image_manifest.json").read_text(encoding="utf-8"))
    assert sorted(m["generador"] for m in man.values()) == ["chatgpt-biblioteca", "chatgpt-imagen"]
