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


def test_sin_raw_da_error_claro(tmp_path):
    try:
        R.diagnosticar(tmp_path, log=lambda *_: None)
    except R.ErrorReparsea as e:
        assert "RAW" in str(e)
    else:
        raise AssertionError("tenia que fallar")
