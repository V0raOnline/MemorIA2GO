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
    _importar(_export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG}), base / "RAW" / "Conversations", base)
    (m,) = json.loads((base / "CHATGPT" / "GENERATED" / "_image_manifest.json").read_text(encoding="utf-8")).values()
    assert (m["generador"], m["modelo"], m["edicion"]) == ("chatgpt-imagen", "gpt-5-2", True)


def test_las_de_la_biblioteca_se_marcan_como_biblioteca(tmp_path):
    base = tmp_path / "vault"
    z = _export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG, "file_lib.dat": JPG},
                [_entrada("file_lib", "De la biblioteca.png")])
    _importar(z, base / "RAW" / "Conversations", base)
    man = json.loads((base / "CHATGPT" / "GENERATED" / "_image_manifest.json").read_text(encoding="utf-8"))
    assert sorted(m["generador"] for m in man.values()) == ["chatgpt-biblioteca", "chatgpt-imagen"]


# ---- completar lo ya importado (recuperar_imagenes.py --metadatos) ------------------------------------
import hashlib
from pathlib import Path

import pytest

import recuperar_imagenes as rec


def _vault_viejo(tmp_path, entradas: dict):
    """Un banco de GENERATED como lo dejaba el importador antes: sin generador en el manifiesto."""
    base = tmp_path / "vault"
    gen = base / "CHATGPT" / "GENERATED"
    gen.mkdir(parents=True)
    man = {}
    for datos, extra in entradas.items():
        fname = _nombre(datos)
        (gen / fname).write_bytes(datos)
        man[fname] = {"origen": "generada", "width": 1024, "height": 1024, **extra}
    (gen / "_image_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    return base, gen / "_image_manifest.json"


def _nombre(datos):
    return hashlib.sha1(datos).hexdigest()[:16] + sce.sniff_ext(datos)


def _completar(base, z, tmp_path, aplicar=False):
    return rec.completar_metadatos(z, base, aplicar=aplicar, carpeta_logs=tmp_path / "logs", log=lambda *_: None)


def test_completar_en_simulacion_cuenta_y_no_escribe(tmp_path):
    base, man = _vault_viejo(tmp_path, {PNG: {}})
    antes = man.read_bytes()
    r = _completar(base, _export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG}), tmp_path)
    assert (r["sin_generador"], r["completables"], r["copia"]) == (1, 1, None)
    assert man.read_bytes() == antes and not (tmp_path / "logs").exists()


def test_completar_anade_generador_modelo_y_edicion_sin_tocar_lo_demas(tmp_path):
    base, man = _vault_viejo(tmp_path, {PNG: {"primera_conversacion": "Algo"}})
    _completar(base, _export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG}), tmp_path, aplicar=True)
    m = json.loads(man.read_text(encoding="utf-8"))[_nombre(PNG)]
    assert m == {"origen": "generada", "width": 1024, "height": 1024, "primera_conversacion": "Algo",
                 "generador": "chatgpt-imagen", "modelo": "gpt-5-2", "edicion": True}


def test_completar_no_toca_las_que_ya_tienen_generador(tmp_path):
    base, man = _vault_viejo(tmp_path, {PNG: {"generador": "chatgpt-dalle"}})
    r = _completar(base, _export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG}), tmp_path, aplicar=True)
    assert r["sin_generador"] == 0 and json.loads(man.read_text(encoding="utf-8"))[_nombre(PNG)]["generador"] == "chatgpt-dalle"


def test_completar_casa_por_huella_no_por_puntero(tmp_path):
    """Otra imagen con el mismo puntero pero otros bytes no completa la del vault."""
    base, man = _vault_viejo(tmp_path, {PNG: {}})
    r = _completar(base, _export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG2}), tmp_path, aplicar=True)
    assert r["completables"] == 0 and "generador" not in json.loads(man.read_text(encoding="utf-8"))[_nombre(PNG)]


def test_completar_marca_las_de_la_biblioteca(tmp_path):
    base, man = _vault_viejo(tmp_path, {JPG: {}})
    z = _export(tmp_path, [_conv_completa()], {"file_lib.dat": JPG}, [_entrada("file_lib", "De la biblioteca.png")])
    _completar(base, z, tmp_path, aplicar=True)
    assert json.loads(man.read_text(encoding="utf-8"))[_nombre(JPG)]["generador"] == "chatgpt-biblioteca"


def test_completar_no_toma_metadatos_de_subidas(tmp_path):
    base, man = _vault_viejo(tmp_path, {PNG: {}})
    conv = _conv_completa()
    conv["mapping"]["n1"]["message"]["author"]["role"] = "user"
    conv["mapping"]["n1"]["message"]["content"]["parts"] = [_parte("sediment://file_gen")]
    r = _completar(base, _export(tmp_path, [conv], {"file_gen.dat": PNG}), tmp_path, aplicar=True)
    assert r["completables"] == 0


def test_completar_es_idempotente_y_se_deshace(tmp_path):
    base, man = _vault_viejo(tmp_path, {PNG: {}})
    original = man.read_bytes()
    z = _export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG})
    r = _completar(base, z, tmp_path, aplicar=True)
    despues = man.read_bytes()
    r2 = _completar(base, z, tmp_path, aplicar=True)
    assert r2["sin_generador"] == 0 and r2["copia"] is None and man.read_bytes() == despues
    rec.deshacer(Path(r["copia"]), log=lambda *_: None)
    assert man.read_bytes() == original


def test_completar_sin_manifiesto_se_niega(tmp_path):
    (tmp_path / "vault").mkdir()
    with pytest.raises(rec.ErrorRecuperar, match="manifest"):
        _completar(tmp_path / "vault", _export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG}), tmp_path)


def test_completar_no_deja_temporales(tmp_path):
    base, man = _vault_viejo(tmp_path, {PNG: {}})
    _completar(base, _export(tmp_path, [_conv_completa()], {"file_gen.dat": PNG}), tmp_path, aplicar=True)
    assert not list(base.rglob("*.recuperar.part"))
