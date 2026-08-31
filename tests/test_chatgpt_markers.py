# -*- coding: utf-8 -*-
"""Tests de chatgpt_markers.py — resolucion de los marcadores PUA internos
de ChatGPT (cite, filecite, entity, image_group...) que hasta 2026-07-27 se
colaban en crudo dentro de las notas (613 notas reales afectadas, 8310
marcadores).

Los fixtures reproducen la forma REAL de `content_references` verificada
contra los exports de V0ra, incluyendo la deriva de formato entre exports
(el nuevo no trae `matched_text` ni `start_idx`/`end_idx`).
"""
import chatgpt_markers as cm
from pendientes import ref_pendiente as _ref

A = cm.MARK_OPEN
S = cm.MARK_SEP
C = cm.MARK_CLOSE


def marcador(cuerpo: str) -> str:
    return f"{A}{cuerpo}{C}"


# ---------- identificadores ----------

def test_parse_ref_id_descompone_turno_tipo_indice():
    assert cm.parse_ref_id("turn0search12") == (0, "search", 12)
    assert cm.parse_ref_id("turn2file3") == (2, "file", 3)


def test_parse_ref_id_rechaza_lo_que_no_lo_es():
    assert cm.parse_ref_id("Siruela") is None
    assert cm.parse_ref_id("") is None
    assert cm.parse_ref_id("turnXsearch1") is None


# ---------- citas de fuentes externas ----------

def test_cite_se_resuelve_a_enlace_real():
    """Caso que motivo todo el fix: un precio con su fuente citada."""
    texto = f"39,90 EUR / anio {marcador(f'cite{S}turn0search12')}"
    refs = [{
        "type": "grouped_webpages",
        "alt": "([TodoTest](https://todotest.com/precios))",
        "items": [{"url": "https://todotest.com/precios", "title": "TodoTest",
                   "refs": [{"turn_index": 0, "ref_type": "search", "ref_index": 12}]}],
    }]
    out = cm.resolve_markers(texto, refs)
    assert "([TodoTest](https://todotest.com/precios))" in out
    assert A not in out


def test_cite_con_varias_fuentes_en_un_solo_marcador():
    """Un marcador puede citar varias refs: cite<SEP>turn0search0<SEP>turn0search4."""
    texto = marcador(f"cite{S}turn0search0{S}turn0search4")
    refs = [
        {"type": "grouped_webpages", "alt": "([A](https://a.es))",
         "items": [{"refs": [{"turn_index": 0, "ref_type": "search", "ref_index": 0}]}]},
        {"type": "grouped_webpages", "alt": "([B](https://b.es))",
         "items": [{"refs": [{"turn_index": 0, "ref_type": "search", "ref_index": 4}]}]},
    ]
    out = cm.resolve_markers(texto, refs)
    assert "([A](https://a.es))" in out and "([B](https://b.es))" in out


def test_cite_sin_alt_se_construye_desde_items():
    texto = marcador(f"cite{S}turn0search1")
    refs = [{"type": "grouped_webpages", "alt": None,
             "items": [{"url": "https://x.es", "title": "Equis",
                        "refs": [{"turn_index": 0, "ref_type": "search", "ref_index": 1}]}]}]
    assert "[Equis](https://x.es)" in cm.resolve_markers(texto, refs)


def test_cite_sin_referencia_avisa_en_vez_de_dejar_el_marcador():
    """Nunca se deja pasar un marcador crudo: si no hay dato, se avisa."""
    out = cm.resolve_markers(marcador(f"cite{S}turn9search9"), [])
    assert A not in out and C not in out
    assert "no recuperable" in out or "cita de un adjunto" in out


# ---------- ficheros citados ----------

def test_filecite_recupera_el_nombre_del_fichero():
    texto = marcador(f"filecite{S}turn0file0")
    refs = [{"type": "file", "name": "bitacora.txt", "alt": None}]
    out = cm.resolve_markers(texto, refs)
    assert "bitacora.txt" in out
    assert A not in out


def test_filecite_fuera_de_rango_no_inventa_el_fichero():
    """Limite real del export (medido 2026-07-27: el 84% de los filecite
    citan un indice que no esta en el mensaje, porque la numeracion
    `turnNfileM` es global de la conversacion y el export no trae la tabla).
    Adivinar por posicion atribuiria la cita al fichero EQUIVOCADO, que es
    peor que reconocer el limite."""
    texto = marcador(f"filecite{S}turn1file11")
    refs = [{"type": "file", "name": "primero.txt"},
            {"type": "file", "name": "segundo.txt"}]
    out = cm.resolve_markers(texto, refs)
    assert "primero.txt" not in out and "segundo.txt" not in out
    assert out.strip() == "*[cita de un adjunto]*"


# ---------- widgets inline con texto propio ----------

def test_entity_recupera_el_nombre_desde_su_propio_payload():
    """Regresion real (cazada verificando contra nota real 2026-07-27):
    'visitar desde Siruela' quedaba como 'visitar desde *[entity no
    recuperable]*'. El nombre viaja en el payload del marcador."""
    texto = f'visitar desde {marcador(chr(0xe202).join(["entity", chr(34)+"place"+chr(34)+", "]))}'
    texto = "visitar desde " + marcador(f'entity{S}["place", "Siruela", 0]') + " (Badajoz)"
    out = cm.resolve_markers(texto, [])
    assert "visitar desde Siruela (Badajoz)" in out


def test_entity_prefiere_alt_de_la_referencia_cuando_existe():
    texto = marcador(f"entity{S}turn0search0")
    refs = [{"type": "entity", "alt": "Massachusetts Institute of Technology",
             "items": [{"refs": [{"turn_index": 0, "ref_type": "search", "ref_index": 0}]}]}]
    assert "Massachusetts Institute of Technology" in cm.resolve_markers(texto, refs)


def test_widget_con_payload_de_texto_plano():
    out = cm.resolve_markers(marcador(f"movie{S}The Predator"), [])
    assert "The Predator" in out


def test_product_entity_salta_el_identificador_y_coge_el_nombre():
    texto = marcador(f'product_entity{S}["turn0product0","Samsung T5 EVO 2 TB"]')
    assert "Samsung T5 EVO 2 TB" in cm.resolve_markers(texto, [])


# ---------- imagenes de busqueda web ----------

def _refs_imagen():
    return [{
        "type": "image_group",
        "safe_urls": ["https://a.es/1.jpg", "https://b.es/2.jpg"],
        "alt": "![Image](https://a.es/1.jpg)\n\n![Image](https://b.es/2.jpg)",
    }]


def test_image_group_sin_triar_avisa_y_registra_pendientes():
    texto = marcador(f'image_group{S}{{"layout":"carousel","query":["iglesia siruela"]}}')
    pend = []
    out = cm.resolve_markers(texto, _refs_imagen(), pendientes_out=pend,
                             conv_titulo="Olor despues de llover")
    assert "pendientes de descarga" in out
    assert "iglesia siruela" in out
    assert len(pend) == 2
    assert pend[0]["url"] == "https://a.es/1.jpg"
    assert pend[0]["queries"] == ["iglesia siruela"]
    assert pend[0]["conversacion"] == "Olor despues de llover"


def test_image_group_rescatada_se_pinta_como_imagen_real():
    texto = marcador(f'image_group{S}{{"query":["x"]}}')
    # El mapa de estado va indexado por `ref`, no por URL (ver pendientes.py):
    # una entrada ya triada no guarda su URL, asi que la clave no puede ser
    # ella. El renderizador hashea al vuelo la URL que le trae el export.
    estado = {
        _ref("https://a.es/1.jpg"): {"estado": "rescatada", "fichero": "abc123.jpg"},
        _ref("https://b.es/2.jpg"): {"estado": "rescatada", "fichero": "def456.jpg"},
    }
    out = cm.resolve_markers(texto, _refs_imagen(), estado_imagenes=estado)
    assert "![](CHATGPT/WEB/abc123.jpg)" in out
    assert "![](CHATGPT/WEB/def456.jpg)" in out
    assert "pendientes" not in out


def test_image_group_descartada_deja_marca_discreta():
    """Decision V0ra: marca discreta, ni borrado silencioso ni ruido."""
    texto = marcador(f'image_group{S}{{"query":["auriculares"]}}')
    estado = {_ref(u): {"estado": "descartada"} for u in
              ("https://a.es/1.jpg", "https://b.es/2.jpg")}
    out = cm.resolve_markers(texto, _refs_imagen(), estado_imagenes=estado)
    assert out.strip() == "*[busqueda de imagenes descartada]*"


def test_image_group_no_registra_pendiente_lo_ya_triado():
    """El triaje sobrevive a un reproceso: lo descartado no vuelve a la lista."""
    texto = marcador(f'image_group{S}{{"query":["x"]}}')
    estado = {_ref("https://a.es/1.jpg"): {"estado": "descartada"}}
    pend = []
    cm.resolve_markers(texto, _refs_imagen(), pendientes_out=pend, estado_imagenes=estado)
    assert [p["url"] for p in pend] == ["https://b.es/2.jpg"]


def test_image_group_sin_urls_avisa():
    texto = marcador(f'image_group{S}{{"query":["x"]}}')
    out = cm.resolve_markers(texto, [{"type": "image_group", "safe_urls": [], "alt": ""}])
    assert "no recuperable" in out or "cita de un adjunto" in out


def test_urls_se_extraen_de_alt_si_no_hay_safe_urls():
    texto = marcador(f'image_group{S}{{"query":["x"]}}')
    refs = [{"type": "image_group", "alt": "![Image](https://solo.es/1.jpg)"}]
    pend = []
    cm.resolve_markers(texto, refs, pendientes_out=pend)
    assert [p["url"] for p in pend] == ["https://solo.es/1.jpg"]


# ---------- deriva de formato y robustez ----------

def test_funciona_sin_matched_text_ni_indices():
    """LA trampa: el export de 2026-07 no trae matched_text ni start_idx.
    Un resolutor apoyado en esos campos fallaria en silencio con los
    exports nuevos. Este fixture los omite a proposito."""
    texto = f"precio {marcador(f'cite{S}turn0search3')} fin"
    refs = [{"type": "grouped_webpages", "alt": "([Fuente](https://f.es))",
             "items": [{"refs": [{"turn_index": 0, "ref_type": "search", "ref_index": 3}]}]}]
    out = cm.resolve_markers(texto, refs)
    assert "([Fuente](https://f.es))" in out
    assert "matched_text" not in out


def test_emparejamiento_posicional_cuando_no_hay_items_refs():
    """`file` no declara items[].refs: el indice del marcador es la
    posicion dentro de las referencias de ese mismo tipo."""
    texto = marcador(f"filecite{S}turn0file1")
    refs = [{"type": "file", "name": "primero.txt"},
            {"type": "file", "name": "segundo.txt"}]
    assert "segundo.txt" in cm.resolve_markers(texto, refs)


def test_tipo_desconocido_avisa_sin_reventar():
    """ChatGPT anade widgets nuevos cada pocos meses."""
    out = cm.resolve_markers(marcador(f"widget_del_futuro{S}algo"), [])
    assert A not in out
    assert "no recuperable" in out and "widget_del_futuro" in out


def test_limpia_marcadores_pua_sueltos_sin_pareja():
    """Vistos en notas reales: U+E203/E204/E206 sin abrir/cerrar."""
    out = cm.resolve_markers("texto  con  basura", [])
    assert out == "texto  con  basura"


def test_texto_sin_marcadores_pasa_intacto():
    texto = "Una nota normal con [enlace](https://x.es) y **negrita**."
    assert cm.resolve_markers(texto, []) == texto


def test_texto_vacio_no_revienta():
    assert cm.resolve_markers("", []) == ""
    assert cm.resolve_markers(None, []) is None


def test_refs_ausentes_no_revientan():
    out = cm.resolve_markers(marcador(f"cite{S}turn0search0"), None)
    assert A not in out
