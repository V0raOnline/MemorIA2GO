# -*- coding: utf-8 -*-
"""Tests del rescate automatico de pendientes (rescue_pending.py, 2026-08-30).

Todo el recorrido se prueba con un `fetch` inyectado: estos tests NO salen a
la red, ni deben hacerlo nunca. Lo que se verifica es el contrato con el resto
de la casa, que es lo que se rompe sin que nada avise:

  - el activo cae en el banco que le toca, con el nombre hash+extension que
    usa la extraccion automatica (si diverge, el paso 1 no lo encuentra),
  - la entrada se CONSERVA marcada `rescatada` con su `fichero` (borrarla hacia
    que el siguiente --reprocess-all la volviera a listar: bug real b8a9c82),
  - que un fallo deja la entrada intacta y sin `estado`, para que siga saliendo
    en Reconexion -- marcarla la esconderia, que es el contrario exacto de lo
    que hace falta,
  - y que en un post de VIDEO nunca se archiva og:image, que es la miniatura.
    Ese es el fallo silencioso que acecha aqui: el fichero existiria, el
    manifest lo daria por bueno y la nota enlazaria un poster llamandolo video.
"""
import hashlib
import json

import pytest

import rescue_pending as rp

PNG = b"\x89PNG\r\n\x1a\n" + b"bytes-de-un-png"
JPEG = b"\xff\xd8\xff" + b"bytes-de-un-jpeg"
MP4 = b"....ftypisom" + b"bytes-de-un-mp4"
MINIATURA = b"\xff\xd8\xff" + b"soy-el-poster-no-el-video"
HTML = b"<!DOCTYPE html><html><body>404 Not Found</body></html>"

ID_IMG = "11111111-2222-3333-4444-555555555555"
ID_VID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _post(ident, media_type):
    """Un pendiente de Grok tal y como lo escribe el pipeline: `link` es la
    pagina compartible del post, NO el activo."""
    return {"id": ident, "media_type": media_type,
            "link": "https://grok.com/imagine/post/%s" % ident}


def _vault(tmp_path, proveedor, entradas):
    path = rp.ruta_pendientes(tmp_path, proveedor)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entradas, ensure_ascii=False), encoding="utf-8")
    return path


def _mudo(*_a, **_k):
    """Los tests no imprimen: el resumen se comprueba por stats, no por texto."""


def _servidor(mapa):
    """fetch que sirve un mapa url->bytes y da 404 para lo demas."""
    def fetch(url):
        if url in mapa:
            return mapa[url]
        raise rp.ErrorDeRescate("HTTP 404")
    return fetch


# ── Resolver donde esta el activo ──────────────────────────────────────────

def test_la_url_derivada_depende_del_tipo_de_medio():
    assert rp.url_derivada(_post(ID_VID, "video")) == \
        "https://imagine-public.x.ai/imagine-public/share-videos/%s.mp4" % ID_VID
    assert rp.url_derivada(_post(ID_IMG, "image")) == \
        "https://grok.com/imagine/post/%s/image" % ID_IMG
    assert rp.url_derivada({"media_type": "image"}) is None


def test_en_un_post_de_video_se_lee_og_video_y_nunca_og_image():
    """og:image existe en los posts de video y es la miniatura. Cogerla seria
    archivar un poster creyendo que es el video, sin que nada avise."""
    pagina = (
        '<meta property="og:image" content="https://grok.com/miniatura.jpg">'
        '<meta property="og:video" content="https://x.ai/de-verdad.mp4">'
    )
    assert rp.url_desde_pagina(pagina, _post(ID_VID, "video")) == \
        "https://x.ai/de-verdad.mp4"


def test_un_video_sin_og_video_no_cae_en_la_miniatura():
    pagina = '<meta property="og:image" content="https://grok.com/miniatura.jpg">'
    assert rp.url_desde_pagina(pagina, _post(ID_VID, "video")) is None


def test_la_metaetiqueta_se_lee_con_los_atributos_en_cualquier_orden():
    assert rp.meta_contenido(
        '<meta content="https://x/a.jpg" name="og:image" />', "og:image"
    ) == "https://x/a.jpg"
    assert rp.meta_contenido(
        '<meta property="og:image" content="https://x/a.jpg?a=1&amp;b=2">',
        "og:image") == "https://x/a.jpg?a=1&b=2"


def test_si_la_url_derivada_falla_se_le_pregunta_a_la_pagina(tmp_path):
    """La derivada es un patron; la pagina es lo que el sitio dice de si
    mismo. Si el patron cambia algun dia, esto lo salva."""
    _vault(tmp_path, "grok", [_post(ID_VID, "video")])
    real = "https://imagine-public.x.ai/otra-forma-nueva/%s.mp4" % ID_VID
    fetch = _servidor({real: MP4})
    pagina = '<meta property="og:video" content="%s">' % real

    stats = rp.rescatar(tmp_path, "grok", fetch=fetch,
                        fetch_pagina=lambda u: pagina, pausa=0, log=_mudo)

    assert stats["rescatados"] == 1
    assert list((tmp_path / "GROK" / "GENERADAS_VIDEO").glob("*.mp4"))


def test_sin_red_de_seguridad_por_pagina_el_fallo_se_anota(tmp_path):
    path = _vault(tmp_path, "grok", [_post(ID_VID, "video")])
    stats = rp.rescatar(tmp_path, "grok", fetch=_servidor({}),
                        pausa=0, log=_mudo)
    assert stats["fallidos"] == 1
    assert "estado" not in json.loads(path.read_text(encoding="utf-8"))[0]


# ── Camino feliz ───────────────────────────────────────────────────────────

def test_rescata_una_imagen_a_su_banco_y_marca_la_entrada(tmp_path):
    entrada = dict(_post(ID_IMG, "image"), prompt="un gato",
                   create_time="2026-01-02")
    path = _vault(tmp_path, "grok", [entrada])
    fetch = _servidor({rp.URL_IMAGEN % ID_IMG: PNG})

    stats = rp.rescatar(tmp_path, "grok", fetch=fetch, pausa=0, log=_mudo)

    assert stats["rescatados"] == 1 and stats["fallidos"] == 0

    banco = tmp_path / "GROK" / "GENERADAS_IMAGEN"
    fname = [f.name for f in banco.glob("*.png")][0]
    assert (banco / fname).read_bytes() == PNG
    # Mismo esquema de nombre que la extraccion automatica del export.
    assert fname == hashlib.sha1(PNG).hexdigest()[:16] + ".png"

    guardada = json.loads(path.read_text(encoding="utf-8"))[0]
    assert guardada["estado"] == "rescatada"
    assert guardada["fichero"] == fname

    manifest = json.loads((banco / "_image_manifest.json").read_text(encoding="utf-8"))
    assert manifest[fname]["origen"] == "generada"
    assert manifest[fname]["prompt"] == "un gato"
    assert manifest[fname]["create_time"] == "2026-01-02"


def test_el_video_va_a_su_propio_banco(tmp_path):
    _vault(tmp_path, "grok", [_post(ID_VID, "video")])
    rp.rescatar(tmp_path, "grok", fetch=_servidor({rp.URL_VIDEO % ID_VID: MP4}),
                pausa=0, log=_mudo)

    assert list((tmp_path / "GROK" / "GENERADAS_VIDEO").glob("*.mp4"))
    assert not (tmp_path / "GROK" / "GENERADAS_IMAGEN").exists()


def test_un_video_nunca_acaba_archivando_la_miniatura(tmp_path):
    """El servidor sirve la miniatura en la ruta de imagen y el video en la
    suya: si el resolutor se equivocara de etiqueta, aqui se ve."""
    _vault(tmp_path, "grok", [_post(ID_VID, "video")])
    fetch = _servidor({rp.URL_VIDEO % ID_VID: MP4,
                       rp.URL_IMAGEN % ID_VID: MINIATURA})

    rp.rescatar(tmp_path, "grok", fetch=fetch, pausa=0, log=_mudo)

    guardado = list((tmp_path / "GROK" / "GENERADAS_VIDEO").glob("*"))[0]
    assert guardado.read_bytes() == MP4
    assert not list(tmp_path.rglob("*%s*" % "poster"))


def test_chatgpt_usa_su_url_directa_y_su_banco_web(tmp_path):
    """En ChatGPT la entrada YA guarda la URL del activo: no hay pagina que
    resolver, y pedirla seria una peticion de mas por imagen."""
    _vault(tmp_path, "chatgpt", [
        {"url": "https://ejemplo/img.png", "queries": ["gatos"],
         "conversaciones": ["2026-01-01_algo"]},
    ])
    rp.rescatar(tmp_path, "chatgpt",
                fetch=_servidor({"https://ejemplo/img.png": JPEG}),
                pausa=0, log=_mudo)

    banco = tmp_path / "CHATGPT" / "WEB"
    fname = [f.name for f in banco.glob("*.jpg")][0]
    manifest = json.loads((banco / "_image_manifest.json").read_text(encoding="utf-8"))
    assert manifest[fname]["origen"] == "web"
    assert manifest[fname]["url_original"] == "https://ejemplo/img.png"
    assert manifest[fname]["queries"] == ["gatos"]
    assert manifest[fname]["conversaciones"] == ["2026-01-01_algo"]


# ── La garantia que importa: un fallo no puede esconder un pendiente ───────

def test_un_fallo_deja_la_entrada_intacta_y_sin_estado(tmp_path):
    path = _vault(tmp_path, "grok", [_post(ID_IMG, "image")])

    def revienta(_url):
        raise rp.ErrorDeRescate("HTTP 404")

    stats = rp.rescatar(tmp_path, "grok", fetch=revienta, pausa=0, log=_mudo)

    assert stats["rescatados"] == 0 and stats["fallidos"] == 1
    entrada = json.loads(path.read_text(encoding="utf-8"))[0]
    assert "estado" not in entrada, "marcarla la sacaria de Reconexion"
    assert "fichero" not in entrada
    assert rp.sin_triar([entrada]) == [entrada]


def test_una_pagina_de_error_no_se_archiva_como_activo(tmp_path):
    """Caso real de la primera pasada del 2026-08-30: el `link` devolvia HTML.
    Sin este guardia habriamos archivado 209 paginas de error."""
    path = _vault(tmp_path, "grok", [_post(ID_IMG, "image")])
    stats = rp.rescatar(tmp_path, "grok", fetch=lambda u: HTML,
                        pausa=0, log=_mudo)

    assert stats["rescatados"] == 0 and stats["fallidos"] == 1
    assert not (tmp_path / "GROK" / "GENERADAS_IMAGEN").exists()
    assert "estado" not in json.loads(path.read_text(encoding="utf-8"))[0]


def test_una_respuesta_vacia_tambien_falla(tmp_path):
    _vault(tmp_path, "grok", [_post(ID_IMG, "image")])
    stats = rp.rescatar(tmp_path, "grok", fetch=lambda u: b"",
                        pausa=0, log=_mudo)
    assert stats["fallidos"] == 1


def test_una_entrada_sin_id_ni_enlace_se_cuenta_y_no_revienta(tmp_path):
    _vault(tmp_path, "grok", [{"media_type": "image"}])
    stats = rp.rescatar(tmp_path, "grok", fetch=lambda u: PNG,
                        pausa=0, log=_mudo)
    assert stats["fallidos"] == 1 and stats["rescatados"] == 0


# ── Reanudable e idempotente ───────────────────────────────────────────────

def test_no_vuelve_a_bajar_lo_ya_triado(tmp_path):
    _vault(tmp_path, "grok", [
        dict(_post("ya", "image"), estado="rescatada", fichero="loquesea.png"),
        dict(_post("no", "image"), estado="descartada"),
        _post(ID_IMG, "image"),
    ])
    pedidas = []

    def fetch(url):
        pedidas.append(url)
        return PNG

    stats = rp.rescatar(tmp_path, "grok", fetch=fetch, pausa=0, log=_mudo)

    assert pedidas == [rp.URL_IMAGEN % ID_IMG]
    assert stats["intentados"] == 1 and stats["rescatados"] == 1


def test_la_segunda_pasada_no_pide_nada(tmp_path):
    _vault(tmp_path, "grok", [_post(ID_IMG, "image")])
    fetch = _servidor({rp.URL_IMAGEN % ID_IMG: PNG})
    rp.rescatar(tmp_path, "grok", fetch=fetch, pausa=0, log=_mudo)

    pedidas = []
    stats = rp.rescatar(tmp_path, "grok",
                        fetch=lambda u: pedidas.append(u) or PNG,
                        pausa=0, log=_mudo)
    assert pedidas == [] and stats["intentados"] == 0


def test_el_limite_solo_intenta_los_primeros(tmp_path):
    _vault(tmp_path, "grok", [_post("id-%d" % i, "image") for i in range(5)])
    stats = rp.rescatar(tmp_path, "grok", fetch=lambda u: PNG,
                        limite=2, pausa=0, log=_mudo)
    assert stats["intentados"] == 2 and stats["rescatados"] == 2
    assert len(rp.sin_triar(rp.leer_pendientes(
        rp.ruta_pendientes(tmp_path, "grok")))) == 3


def test_lo_rescatado_sobrevive_a_un_corte_a_mitad(tmp_path):
    """Ctrl-C despues de varios rescates no puede perderlos: el finally
    escribe lo que llevaba. Es la diferencia entre reanudar y empezar."""
    path = _vault(tmp_path, "grok",
                  [_post("id-%d" % i, "image") for i in range(4)])
    llamadas = {"n": 0}

    def fetch(url):
        llamadas["n"] += 1
        if llamadas["n"] > 2:
            raise KeyboardInterrupt
        # Bytes distintos por entrada: si compartieran hash, el test no
        # distinguiria "se guardaron dos" de "se guardo uno dos veces".
        return PNG + bytes([llamadas["n"]])

    rp.rescatar(tmp_path, "grok", fetch=fetch, pausa=0, log=_mudo)

    guardados = [p for p in json.loads(path.read_text(encoding="utf-8"))
                 if p.get("estado") == "rescatada"]
    assert len(guardados) == 2
    assert len(list((tmp_path / "GROK" / "GENERADAS_IMAGEN").glob("*.png"))) == 2


# ── Detalles del disco ─────────────────────────────────────────────────────

def test_dry_run_no_toca_nada(tmp_path):
    path = _vault(tmp_path, "grok", [_post(ID_IMG, "image")])
    antes = path.read_text(encoding="utf-8")

    def no_debe_llamarse(_u):
        raise AssertionError("dry-run no puede salir a la red")

    rp.rescatar(tmp_path, "grok", fetch=no_debe_llamarse,
                fetch_pagina=no_debe_llamarse, dry_run=True,
                pausa=0, log=_mudo)

    assert path.read_text(encoding="utf-8") == antes
    assert not (tmp_path / "GROK" / "GENERADAS_IMAGEN").exists()


def test_dos_entradas_con_el_mismo_contenido_comparten_fichero(tmp_path):
    """Dedup por hash del contenido, igual que el resto de bancos."""
    path = _vault(tmp_path, "grok",
                  [_post("id-a", "image"), _post("id-b", "image")])
    rp.rescatar(tmp_path, "grok", fetch=lambda u: PNG, pausa=0, log=_mudo)

    assert len(list((tmp_path / "GROK" / "GENERADAS_IMAGEN").glob("*.png"))) == 1
    entradas = json.loads(path.read_text(encoding="utf-8"))
    assert entradas[0]["fichero"] == entradas[1]["fichero"]


def test_el_bom_del_json_no_rompe_la_lectura(tmp_path):
    path = rp.ruta_pendientes(tmp_path, "grok")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([_post(ID_IMG, "image")]), encoding="utf-8-sig")
    assert len(rp.leer_pendientes(path)) == 1


def test_sin_fichero_de_pendientes_no_revienta(tmp_path):
    stats = rp.rescatar(tmp_path, "grok", fetch=lambda u: PNG,
                        pausa=0, log=_mudo)
    assert stats == {"total": 0, "sin_triar": 0, "intentados": 0,
                     "rescatados": 0, "fallidos": 0, "desconocidos": 0,
                     "fallos": []}


def test_proveedor_desconocido_se_rechaza(tmp_path):
    with pytest.raises(ValueError):
        rp.rescatar(tmp_path, "gemini", fetch=lambda u: PNG, log=_mudo)
