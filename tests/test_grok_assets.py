# -*- coding: utf-8 -*-
"""Tests de regresion de la extraccion de binarios de Grok (backlog CONTEXT.md
seccion 3, paso 4/6): file_attachments (adjuntos reales, viajan en el zip) y
media_posts/Imagine (generadas, solo ~18% trae binario local en exports
reales -- el resto son pendientes de descarga, nunca se auto-descargan).
"""
import io
import zipfile

import split_chatgpt_export as sce

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"resto-de-bytes-png"
JPEG_MAGIC = b"\xff\xd8\xff" + b"resto-de-bytes-jpeg"
UNKNOWN_BYTES = b"no-es-un-formato-reconocido"


def test_sniff_ext_reconoce_formatos_comunes():
    assert sce.sniff_ext(PNG_MAGIC) == ".png"
    assert sce.sniff_ext(JPEG_MAGIC) == ".jpg"
    assert sce.sniff_ext(UNKNOWN_BYTES) == ".bin"


def _zip_con_asset(tmp_path, uuid: str, data: bytes):
    """El path real trae DOS uuids (el del usuario y el del asset) -- usar
    un uuid autentico tambien para el segmento de usuario es a proposito:
    asi el test cubre el bug real 2026-07-22 (se indexaba el primer uuid
    del path, que es el de usuario, no el del asset)."""
    zpath = tmp_path / "grok_export.zip"
    user_uuid = "18f22baa-d2c2-491a-b3d0-c3e3f2c9a7b2"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(
            f"ttl/30d/export_data/{user_uuid}/prod-mc-asset-server//{uuid}/content",
            data,
        )
    return zpath


def test_grok_asset_index_encuentra_blob_por_uuid(tmp_path):
    uuid = "7027b36c-88d3-4166-b85c-5c3364e123e7"
    zpath = _zip_con_asset(tmp_path, uuid, PNG_MAGIC)
    with zipfile.ZipFile(zpath) as zf:
        idx = sce.GrokAssetIndex(zf)
        assert uuid in idx.by_uuid
        assert idx.get_bytes(uuid) == PNG_MAGIC
        assert idx.get_bytes("uuid-inexistente") is None


def test_render_grok_file_tokens_con_binario_disponible(tmp_path):
    uuid = "7027b36c-88d3-4166-b85c-5c3364e123e7"
    zpath = _zip_con_asset(tmp_path, uuid, PNG_MAGIC)
    out_dir = tmp_path / "GROK_ADJUNTOS"
    with zipfile.ZipFile(zpath) as zf:
        idx = sce.GrokAssetIndex(zf)
        writer = sce.AssetWriter(str(out_dir))
        content = f"texto antes \x00GROKFILE:{uuid}\x00 texto despues"
        rendered = sce.render_grok_file_tokens(content, idx, writer, "GROK/ADJUNTOS")
    assert "GROK/ADJUNTOS/" in rendered
    assert rendered.startswith("texto antes ![](GROK/ADJUNTOS/")
    assert (out_dir / list(writer.hash_to_filename.values())[0]).exists()


def test_render_grok_file_tokens_sin_banco_degrada_a_texto():
    content = "\x00GROKFILE:algun-uuid\x00"
    rendered = sce.render_grok_file_tokens(content, None, None, None)
    assert "algun-uuid" in rendered
    assert "binario en el zip original" in rendered


def test_render_grok_file_tokens_binario_no_encontrado(tmp_path):
    """asset_index existe pero el uuid no esta en el zip -- degradado
    distinto del caso 'sin banco configurado' (mensaje mas preciso)."""
    class _IndiceVacio:
        def get_bytes(self, uid):
            return None
    writer = sce.AssetWriter(str(tmp_path / "GROK_ADJUNTOS"))
    rendered = sce.render_grok_file_tokens(
        "\x00GROKFILE:uuid-perdido\x00", _IndiceVacio(), writer, "GROK/ADJUNTOS"
    )
    assert "no disponible en el export" in rendered


def test_process_grok_media_posts_separa_extraidas_de_pendientes(tmp_path):
    class _IndiceParcial:
        def __init__(self, disponibles):
            self.disponibles = disponibles

        def get_bytes(self, uid):
            return self.disponibles.get(uid)

    media_posts = [
        {"id": "img-1", "media_type": "image", "original_prompt": "un gato", "link": "https://grok.com/x"},
        {"id": "vid-1", "media_type": "video", "original_prompt": "un perro", "link": "https://grok.com/y"},
        {"id": "img-sin-binario", "media_type": "image", "original_prompt": "sin binario", "link": "https://grok.com/z"},
    ]
    idx = _IndiceParcial({"img-1": PNG_MAGIC, "vid-1": PNG_MAGIC})
    imagen_writer = sce.AssetWriter(str(tmp_path / "GENERADAS_IMAGEN"))
    video_writer = sce.AssetWriter(str(tmp_path / "GENERADAS_VIDEO"))

    n_extraidas, pendientes = sce.process_grok_media_posts(
        media_posts, idx, imagen_writer, "GROK/GENERADAS_IMAGEN", video_writer, "GROK/GENERADAS_VIDEO",
    )

    assert n_extraidas == 2
    assert len(pendientes) == 1
    assert pendientes[0]["id"] == "img-sin-binario"
    assert pendientes[0]["prompt"] == "sin binario"
    assert len(imagen_writer.hash_to_filename) == 1
    assert len(video_writer.hash_to_filename) == 1
