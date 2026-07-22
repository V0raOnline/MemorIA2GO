# -*- coding: utf-8 -*-
"""Test de regresion del bug real 2026-07-22: la clasificacion generada/subida
solo miraba dalle.prompt, y la generacion nativa (GPT-4o/GPT-5 in-context,
tool "t2uay3k.sj1i4kz" en el export crudo) deja ese campo vacio aunque SI es
una imagen generada por el modelo -- 830 imagenes reales de V0ra estaban mal
clasificadas como "subida" por este motivo.
"""
import split_chatgpt_export as sce


def _conv_con_imagen(metadata_parte: dict) -> dict:
    return {
        "title": "Conversacion con imagen",
        "conversation_id": "conv-img-0001",
        "current_node": "n1",
        "mapping": {
            "n1": {
                "message": {
                    "author": {"role": "assistant"},
                    "content": {
                        "content_type": "text",
                        "parts": [{
                            "content_type": "image_asset_pointer",
                            "asset_pointer": "sediment://file_abc123",
                            "metadata": metadata_parte,
                        }],
                    },
                    "metadata": {},
                },
                "parent": None,
            }
        },
    }


def test_dalle_clasico_con_prompt_se_clasifica_generada():
    conv = _conv_con_imagen({"dalle": {"gen_id": "g1", "prompt": "un gato pintando"}})
    image_meta = {}
    sce.parse_json_conversations([conv], image_meta_out=image_meta)
    meta = image_meta["sediment://file_abc123"]
    assert meta["origen"] == "generada"
    assert meta["prompt"] == "un gato pintando"


def test_generacion_nativa_sin_prompt_se_clasifica_generada():
    """El caso real que fallaba: dalle.prompt vacio pero dalle.gen_id (o el
    bloque generation) presente -- SI es una imagen generada, no una subida."""
    conv = _conv_con_imagen({
        "dalle": {"gen_id": "g2", "prompt": "", "serialization_title": "DALL-E generation metadata"},
        "generation": {"gen_id": "g2", "gen_size": "xlimage", "width": 1024, "height": 1024},
    })
    image_meta = {}
    sce.parse_json_conversations([conv], image_meta_out=image_meta)
    meta = image_meta["sediment://file_abc123"]
    assert meta["origen"] == "generada"
    assert "prompt" not in meta


def test_generation_sin_dalle_tambien_se_clasifica_generada():
    """Defensivo: si algun dia solo viaja el bloque generation sin dalle."""
    conv = _conv_con_imagen({"generation": {"gen_id": "g3"}})
    image_meta = {}
    sce.parse_json_conversations([conv], image_meta_out=image_meta)
    meta = image_meta["sediment://file_abc123"]
    assert meta["origen"] == "generada"


def test_subida_real_sin_metadata_de_generacion():
    conv = _conv_con_imagen({})
    image_meta = {}
    sce.parse_json_conversations([conv], image_meta_out=image_meta)
    meta = image_meta["sediment://file_abc123"]
    assert meta["origen"] == "subida"
