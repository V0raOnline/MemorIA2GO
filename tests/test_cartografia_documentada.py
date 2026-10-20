# -*- coding: utf-8 -*-
"""Cada regla que CARTOGRAFIA.md afirma, fijada por un test.

La documentacion de Cartografia describe como decide el motor que nota va en que tema,
incluidas sus trampas (el plural, el guion, las palabras de dos letras). Una documentacion
que describe un comportamiento sin que nada lo vigile deja de ser cierta en silencio cuando
alguien toca el motor. Estos tests no definen como DEBERIA comportarse: dicen como se
comporta HOY, que es lo que el documento promete. Si uno falla, o se corrige el motor o se
corrige el documento -- pero no se puede cambiar uno sin enterarse del otro.

El motor es lexico y determinista: no hay heuristica de relevancia ni IA. Eso es lo que
afirma el documento, y por eso los tests usan notas minimas con palabras exactas.
"""
import json
from pathlib import Path

import pytest

import orphan_cloud as oc


def _nota(carpeta: Path, nombre, *, titulo="Sin titulo", cuerpo="", proyecto="none", proveedor="chatgpt",
          fecha="2026-06-01", extra=""):
    carpeta.mkdir(parents=True, exist_ok=True)
    proyecto_linea = f"Project_name: {proyecto}\n" if proyecto is not None else ""
    (carpeta / f"{nombre}.md").write_text(
        f'---\ntitle: "{titulo}"\ndate: {fecha}\n{proyecto_linea}provider: {proveedor}\n{extra}---\n\n'
        f"### User\n\n{cuerpo}\n", encoding="utf-8", newline="\n")


@pytest.fixture
def vault(tmp_path):
    return tmp_path


def _conv(vault):
    return vault / "MERGED_VAULT" / "Conversaciones" / "2026" / "06"


def _generar(vault, temas: dict):
    mapa = vault / "topic_map.json"
    mapa.write_text(json.dumps(temas, ensure_ascii=False), encoding="utf-8")
    oc.generate_topic_index(vault, mapa)
    salida = {}
    for f in (vault / "MERGED_VAULT" / "_Temas").glob("*.md"):
        salida[f.stem] = f.read_text(encoding="utf-8")
    return salida


def _pesca(salida, tema, nota) -> bool:
    return f"[[{nota}]]" in salida[oc._slug_tema(tema)]


# ---- que notas se miran -------------------------------------------------------------------------

def test_solo_se_miran_las_huerfanas(vault):
    _nota(_conv(vault), "huerfana", cuerpo="una receta")
    _nota(_conv(vault), "con-proyecto", cuerpo="una receta", proyecto="Arkinesis")
    s = _generar(vault, {"Cocina": ["receta"]})
    assert _pesca(s, "Cocina", "huerfana")
    assert not _pesca(s, "Cocina", "con-proyecto")


@pytest.mark.parametrize("proyecto", ["none", '"none"', "NONE", "", None])
def test_huerfana_es_proyecto_none_vacio_o_ausente(vault, proyecto):
    _nota(_conv(vault), "n", cuerpo="una receta", proyecto=proyecto)
    assert _pesca(_generar(vault, {"Cocina": ["receta"]}), "Cocina", "n")


def test_los_indices_y_las_notas_de_otras_carpetas_no_se_miran(vault):
    _nota(vault / "MERGED_VAULT" / "otra_carpeta", "fuera", cuerpo="una receta")
    _nota(_conv(vault), "dentro", cuerpo="una receta")
    s = _generar(vault, {"Cocina": ["receta"]})
    assert _pesca(s, "Cocina", "dentro") and not _pesca(s, "Cocina", "fuera")


# ---- que texto se mira ----------------------------------------------------------------------------

def test_el_titulo_cuenta_como_texto(vault):
    _nota(_conv(vault), "solo-titulo", titulo="Mi receta", cuerpo="nada relevante")
    assert _pesca(_generar(vault, {"Cocina": ["receta"]}), "Cocina", "solo-titulo")


def test_el_resto_del_frontmatter_solo_cuenta_por_campo_igual_valor(vault):
    _nota(_conv(vault), "n", cuerpo="nada relevante", proveedor="grok", extra="source: grok_export\n")
    s = _generar(vault, {"Palabra": ["grok"], "Campo": ["provider=grok"], "Otro": ["source=grok_export"]})
    assert not _pesca(s, "Palabra", "n"), "la palabra 'grok' solo esta en el frontmatter: no se mira"
    assert _pesca(s, "Campo", "n") and _pesca(s, "Otro", "n")


def test_campo_igual_valor_compara_el_valor_entero_no_un_trozo(vault):
    _nota(_conv(vault), "n", cuerpo="x", proveedor="claude")
    s = _generar(vault, {"Igual": ["provider=claude"], "Trozo": ["provider=clau"]})
    assert _pesca(s, "Igual", "n") and not _pesca(s, "Trozo", "n")


def test_mayusculas_y_acentos_no_importan(vault):
    _nota(_conv(vault), "n", cuerpo="La FÍSICA cuántica")
    assert _pesca(_generar(vault, {"Ciencia": ["fisica"]}), "Ciencia", "n")
    assert _pesca(_generar(vault, {"Ciencia": ["FÍSICA"]}), "Ciencia", "n")


# ---- que es una "palabra" (las trampas) -------------------------------------------------------------

def test_una_palabra_es_exacta_el_plural_no_es_lo_mismo(vault):
    _nota(_conv(vault), "singular", cuerpo="mi organoide crece")
    _nota(_conv(vault), "plural", cuerpo="mis organoides crecen")
    s = _generar(vault, {"Organoides": ["organoides"], "Organoide": ["organoide"]})
    assert _pesca(s, "Organoides", "plural") and not _pesca(s, "Organoides", "singular")
    assert _pesca(s, "Organoide", "singular") and not _pesca(s, "Organoide", "plural")


def test_una_palabra_no_es_un_trozo_de_otra(vault):
    _nota(_conv(vault), "n", cuerpo="la recetario de mi abuela")
    assert not _pesca(_generar(vault, {"Cocina": ["receta"]}), "Cocina", "n")


def test_el_guion_y_el_guion_bajo_no_separan_palabras(vault):
    _nota(_conv(vault), "n", cuerpo="el proyecto happypuking-lab avanza")
    s = _generar(vault, {"Suelta": ["happypuking"], "Entera": ["happypuking-lab"]})
    assert not _pesca(s, "Suelta", "n"), "'happypuking-lab' es UNA palabra, no dos"
    assert _pesca(s, "Entera", "n")


def test_las_palabras_de_menos_de_tres_letras_no_existen(vault):
    _nota(_conv(vault), "n", cuerpo="La IA y el ML")
    s = _generar(vault, {"Corta": ["ia"], "Otra": ["ml"]})
    assert not _pesca(s, "Corta", "n") and not _pesca(s, "Otra", "n")


def test_pero_dentro_de_una_frase_si_valen_las_cortas(vault):
    _nota(_conv(vault), "n", cuerpo="Hablamos de la ia generativa")
    assert _pesca(_generar(vault, {"Frase": ["de la ia"]}), "Frase", "n")


def test_los_numeros_sueltos_no_pescan(vault):
    _nota(_conv(vault), "n", cuerpo="en 2025 hubo cambios")
    assert not _pesca(_generar(vault, {"Anio": ["2025"]}), "Anio", "n")


def test_una_frase_es_una_subcadena_no_una_palabra_entera(vault):
    _nota(_conv(vault), "n", cuerpo="una casa decorada con flores")
    assert _pesca(_generar(vault, {"Frase": ["casa de"]}), "Frase", "n"), \
        "'casa de' esta dentro de 'casa decorada': las frases se buscan como texto, sin limite de palabra"


def test_las_stopwords_no_filtran_los_temas(vault):
    """Las stopwords solo limpian la NUBE. Un tema con una palabra de relleno la pesca igualmente."""
    _nota(_conv(vault), "n", cuerpo="si, pero no")
    assert "pero" in oc.STOPWORDS
    assert _pesca(_generar(vault, {"Relleno": ["pero"]}), "Relleno", "n")


# ---- como se combinan las reglas ----------------------------------------------------------------------

def test_basta_con_una_regla_y_una_nota_puede_estar_en_varios_temas(vault):
    _nota(_conv(vault), "n", cuerpo="receta de pan", proveedor="claude")
    s = _generar(vault, {"Cocina": ["xyzabc", "receta"], "Pan": ["pan"], "Claude": ["provider=claude"]})
    assert _pesca(s, "Cocina", "n") and _pesca(s, "Pan", "n") and _pesca(s, "Claude", "n")


def test_cada_tema_lista_sus_notas_de_la_mas_reciente_a_la_mas_antigua(vault):
    for nombre, fecha in (("a", "2026-01-01"), ("b", "2026-03-01"), ("c", "2026-02-01")):
        _nota(_conv(vault), nombre, cuerpo="receta", fecha=fecha)
    texto = _generar(vault, {"Cocina": ["receta"]})["cocina"]
    assert texto.index("[[b]]") < texto.index("[[c]]") < texto.index("[[a]]")


def test_un_tema_sin_coincidencias_se_crea_igual_y_se_avisa(vault):
    _nota(_conv(vault), "n", cuerpo="nada")
    mapa = vault / "topic_map.json"
    mapa.write_text(json.dumps({"Vacio": ["noexiste"]}), encoding="utf-8")
    stats = oc.generate_topic_index(vault, mapa)
    assert stats["sin_coincidencias"] == ["Vacio"]
    assert (vault / "MERGED_VAULT" / "_Temas" / "vacio.md").is_file()


# ---- puntos ciegos y cobertura ------------------------------------------------------------------------

def test_los_puntos_ciegos_tienen_dos_capas(vault):
    _nota(_conv(vault), "con-contenido", cuerpo="receta", proveedor="grok")
    _nota(_conv(vault), "solo-estructural", cuerpo="nada", proveedor="claude")
    _nota(_conv(vault), "sin-nada", cuerpo="nada", proveedor="chatgpt")
    s = _generar(vault, {"Cocina": ["receta"], "Claude": ["provider=claude"]})
    ciego = s["_sin-tema"]
    seccion_sin, seccion_estructural = ciego.split("## Solo pescadas por redes estructurales")
    assert "[[sin-nada]]" in seccion_sin and "[[solo-estructural]]" not in seccion_sin
    assert "[[solo-estructural]]" in seccion_estructural and "[[sin-nada]]" not in seccion_estructural
    assert "[[con-contenido]]" not in ciego


def test_la_cobertura_solo_cuenta_reglas_de_contenido(vault):
    _nota(_conv(vault), "uno", cuerpo="receta", proveedor="claude")
    _nota(_conv(vault), "dos", cuerpo="nada", proveedor="claude")
    mapa = vault / "topic_map.json"
    mapa.write_text(json.dumps({"Cocina": ["receta"], "Claude": ["provider=claude"]}), encoding="utf-8")
    stats = oc.generate_topic_index(vault, mapa)
    assert stats["total_huerfanas"] == 2
    assert stats["cobertura_contenido_pct"] == 50.0     # 'dos' esta en un tema, pero solo estructural


# ---- que borra y que no --------------------------------------------------------------------------------

def test_solo_se_retiran_las_notas_de_tema_generadas_y_que_ya_no_estan_en_el_mapa(vault):
    _nota(_conv(vault), "n", cuerpo="receta")
    _generar(vault, {"Cocina": ["receta"], "Antiguo": ["receta"]})
    temas = vault / "MERGED_VAULT" / "_Temas"
    assert (temas / "antiguo.md").is_file()
    (temas / "mia.md").write_text("---\ntitle: Mia\n---\nMaterial propio\n", encoding="utf-8")   # sin la marca

    mapa = vault / "topic_map.json"
    mapa.write_text(json.dumps({"Cocina": ["receta"]}), encoding="utf-8")
    stats = oc.generate_topic_index(vault, mapa)

    assert not (temas / "antiguo.md").exists() and stats["borradas"] == 1
    assert (temas / "mia.md").read_text(encoding="utf-8").endswith("Material propio\n"), "material propio intocable"


def test_las_conversaciones_no_se_tocan(vault):
    _nota(_conv(vault), "n", cuerpo="receta")
    antes = (_conv(vault) / "n.md").read_bytes()
    _generar(vault, {"Cocina": ["receta"]})
    assert (_conv(vault) / "n.md").read_bytes() == antes


def test_un_mapa_roto_se_dice_en_voz_alta_y_no_borra_los_indices(vault, capsys):
    _nota(_conv(vault), "n", cuerpo="receta")
    _generar(vault, {"Cocina": ["receta"]})
    mapa = vault / "topic_map.json"
    mapa.write_text("{ esto no es json", encoding="utf-8")
    assert oc.load_topic_map(mapa) == {}
    err = capsys.readouterr().err
    assert "SIN NINGUN tema" in err
    assert (vault / "MERGED_VAULT" / "_Temas" / "cocina.md").is_file()


# ---- la nube -------------------------------------------------------------------------------------------

def test_la_nube_solo_lee_no_escribe_nada(vault):
    for i in range(4):
        _nota(_conv(vault), f"n{i}", cuerpo="receta de cocina")
    antes = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    oc.build_cloud(vault)
    assert {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()} == antes


def test_la_nube_descarta_lo_demasiado_comun_y_lo_demasiado_raro(vault):
    """Banda de frecuencia: al menos 3 notas, y como mucho el 25% de las huerfanas (minimo 3)."""
    for i in range(12):
        # 'comun' en las 12 (fondo), 'medio' en 3 (dentro de la banda), 'raro' en 1 (anecdotico)
        cuerpo = "comun " + ("medio " if i < 3 else "") + ("raro " if i == 0 else "")
        _nota(_conv(vault), f"n{i}", cuerpo=cuerpo)
    terminos = {t["t"] for t in oc.build_cloud(vault)["terminos"]}
    assert "medio" in terminos
    assert "comun" not in terminos and "raro" not in terminos


def test_un_nombre_de_proyecto_aparece_en_la_nube_aunque_sea_raro_y_va_marcado(vault):
    _nota(_conv(vault), "n0", cuerpo="hablamos de arkinesis")
    for i in range(1, 6):
        _nota(_conv(vault), f"n{i}", cuerpo="otra cosa")
    (vault / "PRJ_VAULT" / "Arkinesis").mkdir(parents=True)
    t = {x["t"]: x for x in oc.build_cloud(vault)["terminos"]}
    assert t["arkinesis"]["es_proyecto"] is True and t["arkinesis"]["proyecto"] == "Arkinesis"
