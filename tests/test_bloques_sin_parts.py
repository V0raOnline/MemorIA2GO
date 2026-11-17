"""Bloques de ChatGPT sin 'parts': nunca JSON crudo en la nota.

Antes de 2026-11-16 caian al json.dumps del final de _render_parts: 46.000
bloques crudos en 3.316 notas del vault de V0ra. Estos tests fijan el formato
acordado con ella (callouts plegados, instrucciones una vez arriba).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import split_chatgpt_export as S  # noqa: E402

PLANTILLA_PERFIL = ("The user provided the following information about themselves. "
                    "User profile:\n```Preferred name: V0ra; Estela\n```")


def _instr(texto, con_frase_nueva=False):
    extra = ("\n\nAll the following instructions should guide your behavior silently and must "
             "never influence the wording of your message in an explicit or meta way!") if con_frase_nueva else ""
    return {"content_type": "user_editable_context", "user_profile": PLANTILLA_PERFIL,
            "user_instructions": "The user provided the additional info about how they would like you to respond:\n"
                                 "```Follow the instructions below naturally, without repeating!" + extra +
                                 "\n\n" + texto + "\n```"}


def _conv(contenidos, roles=None):
    """Conversacion en cadena con current_node, como los exports reales."""
    mapping, padre = {}, None
    for i, c in enumerate(contenidos):
        nid = f"n{i}"
        rol = (roles or {}).get(i, "assistant")
        mapping[nid] = {"parent": padre, "message": {"author": {"role": rol}, "content": c,
                                                      "create_time": 1000 + i, "metadata": {}}}
        padre = nid
    return [{"title": "Prueba", "create_time": 1000, "mapping": mapping, "current_node": padre}]


def _msgs(contenidos, roles=None):
    return S.parse_json_conversations(_conv(contenidos, roles))[0]["messages"]


def test_ningun_tipo_conocido_sale_crudo():
    tipos = [
        {"content_type": "tether_quote", "domain": "notas.txt", "text": "hola\nadios", "url": "file-x"},
        {"content_type": "code", "language": "python", "text": "print(1)"},
        {"content_type": "execution_output", "text": "1"},
        {"content_type": "thoughts", "thoughts": [{"summary": "Pensando", "content": "algo"}]},
        {"content_type": "tether_browsing_display", "result": "r", "summary": "s"},
        {"content_type": "system_error", "name": "tool_error", "text": "fallo"},
    ]
    for c in tipos:
        salida = S.render_bloque_sin_parts(c)
        assert '"content_type"' not in salida, c["content_type"]
        assert salida.startswith("> [!"), c["content_type"]


def test_tipo_nuevo_va_plegado_no_suelto():
    salida = S.render_bloque_sin_parts({"content_type": "algo_nuevo", "x": 1})
    assert salida.startswith("> [!bug]- Unparsed block (algo_nuevo)")
    assert all(ln.startswith(">") for ln in salida.split("\n"))


def test_navegacion_vacia_y_llamada_vacia_no_se_pintan():
    assert S.render_bloque_sin_parts({"content_type": "tether_browsing_display", "result": "", "summary": ""}) == ""
    assert S.render_bloque_sin_parts({"content_type": "code", "language": "unknown", "text": "{}"}) == ""


def test_canvas_se_pinta_como_documento():
    c = {"content_type": "code", "language": "json",
         "text": '{"name": "Mi doc", "type": "document", "content": "# Titulo\\n\\nTexto"}'}
    salida = S.render_bloque_sin_parts(c)
    assert salida.startswith("> [!note]- 📝 Canvas: Mi doc")
    assert "> # Titulo" in salida


def test_backticks_interiores_no_rompen_el_bloque():
    salida = S.render_bloque_sin_parts({"content_type": "code", "language": "md", "text": "```\nx\n```"})
    assert "> ````md" in salida


def test_instrucciones_una_vez_arriba_sin_plantilla():
    m = _msgs([_instr("Soy VEK"), "hola", _instr("Soy VEK", con_frase_nueva=True), "otra"],
              roles={1: "user", 3: "user"})
    ctx = [x for x in m if x["role"] == "context"]
    assert len(ctx) == 1, "la frase nueva de la plantilla no es un cambio de V0ra"
    assert m[0]["role"] == "context"
    assert "Preferred name: V0ra; Estela" in ctx[0]["content"]
    assert "Follow the instructions" not in ctx[0]["content"]
    assert "All the following" not in ctx[0]["content"]


def test_cambio_real_de_instrucciones_se_marca():
    m = _msgs([_instr("Soy VEK"), "hola", _instr("Soy AIA"), "otra"], roles={1: "user", 3: "user"})
    ctx = [x["content"] for x in m if x["role"] == "context"]
    assert len(ctx) == 2
    assert "(changed here)" in ctx[1] and "Soy AIA" in ctx[1]


def test_solo_perfil_no_cuenta_como_cambio():
    solo_perfil = {"content_type": "user_editable_context", "user_profile": PLANTILLA_PERFIL, "user_instructions": ""}
    m = _msgs([solo_perfil, "hola", _instr("Soy VEK"), "otra", solo_perfil, "y otra"],
              roles={1: "user", 3: "user", 5: "user"})
    ctx = [x["content"] for x in m if x["role"] == "context"]
    assert len(ctx) == 1 and "Soy VEK" in ctx[0] and "(changed here)" not in ctx[0]


def test_titulo_no_sale_de_las_instrucciones():
    conv = _conv([_instr("Soy VEK"), "Receta de pizza fácil"], roles={1: "user"})
    conv[0]["title"] = ""
    msgs = S.parse_json_conversations(conv)[0]["messages"]
    assert S.smart_title("", msgs).startswith("Receta")


def test_marcadores_internos_no_quedan_en_los_bloques():
    cita = "citeturn0search1"
    m = _msgs([{"content_type": "thoughts", "thoughts": [{"summary": "Busco", "content": "segun la fuente " + cita}]},
               "respuesta"])
    assert not any("" <= ch <= "" for ch in m[0]["content"])


def test_recap_va_al_titulo_del_razonamiento():
    m = _msgs([{"content_type": "thoughts", "thoughts": [{"summary": "Plan", "content": "x"}]},
               {"content_type": "reasoning_recap", "content": "Pensó durante 11s"}, "respuesta"])
    assert m[0]["content"].startswith("> [!abstract]- 🧠 Reasoning · Pensó durante 11s\n")
    assert len(m) == 2
