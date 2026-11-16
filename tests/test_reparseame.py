"""REParsea·me, pieza 1: el diagnostico cuenta bien y no escribe nada."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reparseame as R  # noqa: E402

LIMPIA = ('---\ntitle: "Limpia"\ndate: 2026-01-01\nsource: chatgpt_export\nprovider: "chatgpt"\n'
          'conv_id: "c1"\nmodel: "gpt-5"\n---\n\n### User\n\nhola\n')


def _vault(tmp_path, notas):
    raw = R.carpeta_raw(tmp_path)
    raw.mkdir(parents=True)
    for nombre, contenido in notas.items():
        (raw / nombre).write_bytes(contenido.encode("utf-8") if isinstance(contenido, str) else contenido)
    return raw


def test_nota_limpia_sin_derivas():
    assert R.derivas_de(LIMPIA.encode("utf-8")) == []


def test_cada_deriva_se_detecta():
    sucia = (LIMPIA.replace('conv_id: "c1"\n', "").replace('model: "gpt-5"\n', "")
             + '\n### User\n\n{"content_type": "user_editable_context", "user_profile": "x"}\n'
             + "\n*[imagen no disponible en el export: file-abc]*\n"
             + "\nsegun citeturn0search1\n").encode("utf-8") + b"\x00IMG:x\x00"
    assert set(R.derivas_de(sucia)) == {"json_crudo", "bytes_nulos", "citas_crudas",
                                        "imagen_no_disponible", "sin_model", "sin_conv_id"}


def test_cita_dentro_del_json_no_cuenta_dos_veces():
    nota = LIMPIA + '\n{"content_type": "thoughts", "thoughts": [{"content": "x cite"}]}\n'
    assert R.derivas_de(nota.encode("utf-8")) == ["json_crudo"]


def test_otros_proveedores_no_se_tocan():
    # Una conversacion de Claude donde V0ra pego JSON de ChatGPT: es contenido, no deriva.
    claude = LIMPIA.replace('provider: "chatgpt"', 'provider: "claude"').replace("chatgpt_export", "claude_export")
    claude += '\n{"content_type": "tether_quote", "text": "pegado a mano"}\n'
    assert R.derivas_de(claude.encode("utf-8")) == []


def test_notas_antiguas_sin_provider_usan_source():
    vieja = LIMPIA.replace('provider: "chatgpt"\n', "") + '\n{"content_type": "code", "text": "x"}\n'
    assert "json_crudo" in R.derivas_de(vieja.encode("utf-8"))


def test_diagnosticar_cuenta_y_no_escribe(tmp_path):
    sucia = LIMPIA + '\n{"content_type": "code", "text": "x"}\n'
    raw = _vault(tmp_path, {"a.md": LIMPIA, "b.md": sucia,
                            "c.md": LIMPIA.replace('model: "gpt-5"\n', "")})
    antes = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in raw.iterdir()}
    inf = R.diagnosticar(tmp_path, log=lambda *_: None)
    assert inf["notas"] == 3
    assert inf["por_deriva"]["json_crudo"] == 1 and inf["por_deriva"]["sin_model"] == 1
    assert inf["con_la_nota"] == 1 and inf["con_el_export"] == 1
    despues = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in raw.iterdir()}
    assert antes == despues


# ---------- pieza 2 ----------

import json  # noqa: E402

import split_chatgpt_export as S  # noqa: E402

POLITICA = {"keep_versions": True, "version_scheme": "hash"}  # la del pipeline: sin skip_identical

INSTR = {"content_type": "user_editable_context",
         "user_profile": "User profile:\n```Preferred name: V0ra\n```",
         "user_instructions": "```Follow the instructions below naturally!\n\nSoy VEK\n```"}
BLOQUES = [
    ("user", INSTR),
    ("user", "hola"),
    ("assistant", {"content_type": "thoughts", "thoughts": [{"summary": "Plan", "content": "pensar"}]}),
    # Orden de claves de los exports de 2025: el detector no puede depender de el.
    ("assistant", {"content": "Pensó durante 3s", "content_type": "reasoning_recap"}),
    ("tool", {"content_type": "tether_browsing_display", "result": "", "summary": ""}),
    ("assistant", {"content_type": "code", "language": "python", "text": "print(1)"}),
    ("tool", {"content_type": "execution_output", "text": "1"}),
    ("assistant", "Aquí tienes:\n\n```\n### User\ncitado en un bloque\n```\n\nfin  "),
]


def _conv_de(bloques):
    mapping, padre = {}, None
    for i, (rol, c) in enumerate(bloques):
        contenido = c if isinstance(c, dict) else {"content_type": "text", "parts": [c]}
        mapping[f"n{i}"] = {"parent": padre, "message": {"author": {"role": rol}, "content": contenido,
                                                          "create_time": 1000 + i, "metadata": {}}}
        padre = f"n{i}"
    return [{"title": "Prueba", "create_time": 1000, "mapping": mapping, "current_node": padre,
             "conversation_id": "c1"}]


def _nota(tmp_path, carpeta, mensajes):
    ruta, _ = S.write_md(str(tmp_path / carpeta), "Prueba", "2025-11-04", mensajes, [],
                         existing_policy=POLITICA, extra_front={"conv_id": "c1", "model": "gpt-5"})
    return open(ruta, encoding="utf-8").read()


def _nota_antigua(tmp_path):
    """Como la escribia el parser antes de 9fc3496: el bloque volcado con json.dumps."""
    viejos = []
    for rol, c in BLOQUES:
        if isinstance(c, dict):
            viejos.append({"role": rol, "content": json.dumps(c, ensure_ascii=False)})
        else:
            viejos.append({"role": rol, "content": c})
    return _nota(tmp_path, "antes", viejos)


def test_reparada_igual_byte_a_byte_que_la_importacion_de_hoy(tmp_path):
    hoy = _nota(tmp_path, "hoy", S.parse_json_conversations(_conv_de(BLOQUES))[0]["messages"])
    antigua = _nota_antigua(tmp_path)
    assert "json_crudo" in R.derivas_de(antigua.encode("utf-8"))
    assert R.reparar_texto(antigua) == hoy


def test_partir_y_componer_no_pierden_un_byte(tmp_path):
    antigua = _nota_antigua(tmp_path)
    assert R.componer(*R.partir(antigua)) == antigua
    vacia = '---\ntitle: "x"\n---\n'
    assert R.partir(vacia) == ('---\ntitle: "x"', [])
    assert R.componer(*R.partir(vacia)) == vacia


def test_nota_sin_json_no_se_reescribe(tmp_path):
    assert R.reparar_texto(LIMPIA) is None


def _raw_de_prueba(tmp_path):
    raw = R.carpeta_raw(tmp_path)
    (raw / "2025" / "11").mkdir(parents=True)
    d = raw / "2025" / "11"
    antigua = _nota_antigua(tmp_path)
    (d / "2025-11-04_prueba.md").write_text(antigua, encoding="utf-8", newline="")
    (d / f"2025-11-04_prueba-h{R.hashlib.sha1(antigua.encode()).hexdigest()[:8]}.md").write_text(
        antigua, encoding="utf-8", newline="")                       # gemela identica
    (d / "2025-11-04_otra-hdeadbeef.md").write_text(LIMPIA, encoding="utf-8", newline="")  # huella que no cuadra
    (d / "2025-11-04_limpia.md").write_text(LIMPIA, encoding="utf-8", newline="")          # no se toca
    for i, p in enumerate(sorted(d.iterdir())):
        os.utime(p, ns=(10**18 + i, 10**18 + i))
    return d


def _foto(d):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in d.iterdir()}


def test_aplicar_y_deshacer(tmp_path):
    d = _raw_de_prueba(tmp_path)
    antes = _foto(d)
    plan = R.planificar(tmp_path, log=lambda *_: None)
    assert (plan["reescribir"], plan["renombrar"], plan["papelera"]) == (1, 1, 1)
    copia = R.aplicar(plan, tmp_path / "logs", log=lambda *_: None)
    despues = _foto(d)
    assert "2025-11-04_limpia.md" in despues and despues["2025-11-04_limpia.md"] == antes["2025-11-04_limpia.md"]
    assert "2025-11-04_otra-hdeadbeef.md" not in despues
    assert f"2025-11-04_otra-h{R.hashlib.sha1(LIMPIA.encode()).hexdigest()[:8]}.md" in despues
    reparada = despues["2025-11-04_prueba.md"]
    assert b'{"content_type"' not in reparada[0]
    assert reparada[1] == antes["2025-11-04_prueba.md"][1], "conserva la fecha de modificacion"
    assert len([n for n in despues if n.startswith("2025-11-04_prueba")]) == 1, "la gemela va a la copia"
    R.deshacer(copia, log=lambda *_: None)
    assert _foto(d) == antes


def test_tras_aplicar_reimportar_no_crea_ficheros(tmp_path):
    d = _raw_de_prueba(tmp_path)
    R.aplicar(R.planificar(tmp_path, log=lambda *_: None), tmp_path / "logs", log=lambda *_: None)
    antes = set(p.name for p in d.iterdir())
    msgs = S.parse_json_conversations(_conv_de(BLOQUES))[0]["messages"]
    S.write_md(str(R.carpeta_raw(tmp_path)), "Prueba", "2025-11-04", msgs, [], by_year=True, by_month=True,
               existing_policy=POLITICA, extra_front={"conv_id": "c1", "model": "gpt-5"})
    assert set(p.name for p in d.iterdir()) == antes


def test_deshacer_no_pisa_cambios_posteriores(tmp_path):
    d = _raw_de_prueba(tmp_path)
    copia = R.aplicar(R.planificar(tmp_path, log=lambda *_: None), tmp_path / "logs", log=lambda *_: None)
    (d / "2025-11-04_prueba.md").write_text("editada despues", encoding="utf-8")
    try:
        R.deshacer(copia, log=lambda *_: None)
    except R.ErrorReparsea:
        pass
    else:
        raise AssertionError("tenia que negarse")
    assert (d / "2025-11-04_prueba.md").read_text(encoding="utf-8") == "editada despues"


def test_write_md_no_crea_gemela_de_la_primera_version(tmp_path):
    msgs = [{"role": "user", "content": "hola"}]
    S.write_md(str(tmp_path), "Gemela", "2026-01-01", msgs, [], existing_policy=POLITICA)
    S.write_md(str(tmp_path), "Gemela", "2026-01-01", msgs, [], existing_policy=POLITICA)
    assert len(list(tmp_path.glob("*.md"))) == 1
    S.write_md(str(tmp_path), "Gemela", "2026-01-01", [{"role": "user", "content": "otra"}], [],
               existing_policy=POLITICA)
    assert len(list(tmp_path.glob("*.md"))) == 2, "una version distinta si se escribe"


def test_sin_raw_da_error_claro(tmp_path):
    try:
        R.diagnosticar(tmp_path, log=lambda *_: None)
    except R.ErrorReparsea as e:
        assert "RAW" in str(e)
    else:
        raise AssertionError("tenia que fallar")
