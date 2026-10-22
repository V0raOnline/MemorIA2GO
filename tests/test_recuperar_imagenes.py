# -*- coding: utf-8 -*-
"""recuperar_imagenes.py: devolver a las notas las imagenes que quedaron como
"imagen no disponible en el export" (export de ChatGPT de octubre, ficheros .dat).

Lo que importa de verdad, medido sobre una copia del vault real:
  * reimportar NO sirve: el merge ve el aviso y el enlace como mensajes distintos y
    deja los dos (187 -> 217 turnos de usuario en el hilo de ejemplo);
  * la reparacion tiene que dejar la nota IDENTICA a la que escribiria una importacion
    nueva del mismo export, para que el siguiente export no duplique nada;
  * conserva la fecha de modificacion de cada nota (el merge desempata por ella) y se
    puede deshacer sin perder un byte.
"""
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import recuperar_imagenes as rec
import split_chatgpt_export as sce

RAIZ = Path(__file__).resolve().parent.parent
PNG = b"\x89PNG\r\n\x1a\n" + b"png-de-prueba-uno"
PNG2 = b"\x89PNG\r\n\x1a\n" + b"png-de-prueba-dos"
JPG = b"\xff\xd8\xff\xe0" + b"jpg-de-prueba"
FECHA_VIEJA = 1_700_000_000          # una fecha de modificacion que ningun test produce por casualidad


# ---- un export de ChatGPT con el formato nuevo ----------------------------------------
def _nodo(i, padre, hijo, rol, partes, meta=None):
    return {"id": f"n{i}", "parent": padre, "children": [hijo] if hijo else [], "message": {
        "id": f"m{i}", "author": {"role": rol}, "create_time": 1790000000.0 + i,
        "content": {"content_type": "multimodal_text", "parts": partes}, "metadata": meta or {}}}


def _imagen(puntero, generada=False):
    md = {"dalle": {"gen_id": "g1", "prompt": "un gato"}} if generada else {}
    return {"content_type": "image_asset_pointer", "asset_pointer": puntero, "metadata": md}


def _conv(imagenes, titulo="Con imagenes", cid="conv-rec-0001", extra_turno=None):
    """Una conversacion: pregunta, imagenes, respuesta (y opcionalmente un turno mas)."""
    nodos = {}
    cadena = [("user", ["Mira estas imagenes"]), ("user", [_imagen(p, g) for p, g in imagenes]),
              ("assistant", ["Las veo, gracias."])]
    if extra_turno:
        cadena += [("user", [extra_turno]), ("assistant", ["Entendido."])]
    for i, (rol, partes) in enumerate(cadena):
        nodos[f"n{i}"] = _nodo(i, f"n{i - 1}" if i else None, f"n{i + 1}" if i < len(cadena) - 1 else None, rol,
                               partes)
    return {"title": titulo, "conversation_id": cid, "create_time": 1790000000.0, "update_time": 1790000100.0,
            "current_node": f"n{len(cadena) - 1}", "mapping": nodos}


def _zip(ruta: Path, convs, ficheros: dict, biblioteca=None) -> Path:
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("conversations-000.json", json.dumps(convs))
        for n, d in ficheros.items():
            z.writestr(n, d)
        if biblioteca is not None:
            z.writestr("library_files.json", json.dumps(biblioteca))
    return ruta


def _importar(zip_: Path, raw_conv: Path, base: Path):
    r = subprocess.run(
        [sys.executable, str(RAIZ / "split_chatgpt_export.py"), str(zip_), str(raw_conv), "--by-year", "--by-month",
         "--keep-versions", "--generadas-dir", str(base / "CHATGPT" / "GENERATED"),
         "--adjuntos-dir", str(base / "CHATGPT" / "ATTACHMENTS")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RAIZ)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]


def _fusionar(raw: Path, merged: Path):
    r = subprocess.run([sys.executable, str(RAIZ / "vault_merge.py"), str(raw), str(merged), "--merge",
                        "--by-year", "--by-month"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=RAIZ)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]


def _por_proyectos(merged: Path, prj: Path):
    r = subprocess.run([sys.executable, str(RAIZ / "project_organizer.py"), str(merged), str(prj), "--by-date"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RAIZ)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]


def _notas(carpeta: Path):
    return sorted(p for p in carpeta.rglob("*.md") if not p.name.startswith("_"))


@pytest.fixture
def vault_con_avisos(tmp_path):
    """Un vault construido por el pipeline REAL a partir de un export al que le falta el
    binario de las imagenes (lo que paso con el bug), mas el export completo."""
    base = tmp_path / "vault"
    convs = [_conv([("sediment://file_aaa", False), ("file-service://file-bbb", True)])]
    completo = _zip(tmp_path / "completo.zip", convs,
                    {"file_aaa.dat": PNG, "file-bbb.dat": JPG})
    sin_binarios = _zip(tmp_path / "sin_binarios.zip", convs, {})
    _importar(sin_binarios, base / "RAW_VAULT" / "Conversations", base)
    _fusionar(base / "RAW_VAULT", base / "MERGED_VAULT")
    _por_proyectos(base / "MERGED_VAULT", base / "PRJ_VAULT")
    for d in (base / "RAW_VAULT" / "Conversations", base / "MERGED_VAULT" / "Conversations", base / "PRJ_VAULT"):
        for n in _notas(d):
            os.utime(n, (FECHA_VIEJA, FECHA_VIEJA))
    return base, completo, convs, tmp_path


def _recuperar(base, export, tmp_path, **kw):
    return rec.recuperar(export, base, carpeta_logs=tmp_path / "logs", log=lambda *_: None, **kw)


def _foto(base: Path):
    return {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob("*") if p.is_file()}


# ---- la simulacion ---------------------------------------------------------------------
def test_los_avisos_estan_en_raw_merged_y_prj_antes_de_reparar(vault_con_avisos):
    base, *_ = vault_con_avisos
    for d in ("RAW_VAULT/Conversations", "MERGED_VAULT/Conversations", "PRJ_VAULT"):
        textos = [n.read_text(encoding="utf-8") for n in _notas(base / d)]
        assert textos and all("imagen no disponible en el export" in t for t in textos), d


def test_la_simulacion_no_escribe_nada(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    antes = _foto(base)
    r = _recuperar(base, completo, tmp)
    assert _foto(base) == antes, "la simulacion ha tocado el vault"
    assert not (tmp / "logs").exists(), "la simulacion ha creado una copia de seguridad"
    assert not (base / "CHATGPT" / "GENERATED").exists() or not list((base / "CHATGPT" / "GENERATED").iterdir())
    assert r["aplicado"] is False and r["imagenes_con_aviso"] == 2 and r["recuperables"] == 2
    assert r["sin_recuperar"] == 0 and r["notas_a_cambiar"] == 3 and r["notas_cambiadas"] == 0


def test_los_contadores_cuentan_avisos_no_solo_imagenes(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    r = _recuperar(base, completo, tmp)
    assert r["marcas"] == 6 and r["marcas_recuperables"] == 6       # 2 imagenes x 3 copias de la nota


# ---- aplicar ------------------------------------------------------------------------------
def test_aplicar_sustituye_el_aviso_por_el_enlace_en_las_tres_copias(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    r = _recuperar(base, completo, tmp, aplicar=True)
    assert r["notas_cambiadas"] == 3
    for d in ("RAW_VAULT/Conversations", "MERGED_VAULT/Conversations", "PRJ_VAULT"):
        for n in _notas(base / d):
            t = n.read_text(encoding="utf-8")
            assert "imagen no disponible" not in t, n
            assert t.count("![](CHATGPT/") == 2, n


def test_cada_enlace_apunta_a_un_fichero_que_existe_y_con_su_extension_real(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    _recuperar(base, completo, tmp, aplicar=True)
    import re
    enlaces = re.findall(r"!\[\]\((CHATGPT/[^)]+)\)", _notas(base / "MERGED_VAULT" / "Conversations")[0]
                         .read_text(encoding="utf-8"))
    assert sorted(Path(e).suffix for e in enlaces) == [".jpg", ".png"]
    for e in enlaces:
        assert (base / e).is_file(), e
    assert {(base / e).read_bytes() for e in enlaces} == {PNG, JPG}


def test_cada_imagen_va_al_banco_que_le_toca(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    _recuperar(base, completo, tmp, aplicar=True)
    assert [p.suffix for p in (base / "CHATGPT" / "ATTACHMENTS").glob("*.png")] == [".png"]      # subida
    assert [p.suffix for p in (base / "CHATGPT" / "GENERATED").glob("*.jpg")] == [".jpg"]     # generada


def test_el_manifiesto_lleva_el_origen_y_la_conversacion(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    _recuperar(base, completo, tmp, aplicar=True)
    gen = json.loads((base / "CHATGPT" / "GENERATED" / "_image_manifest.json").read_text(encoding="utf-8"))
    sub = json.loads((base / "CHATGPT" / "ATTACHMENTS" / "_image_manifest.json").read_text(encoding="utf-8"))
    assert [m["origen"] for m in gen.values()] == ["generada"]
    assert [m["origen"] for m in sub.values()] == ["subida"]
    assert all(m["primera_conversacion"] == "Con imagenes" for m in (*gen.values(), *sub.values()))


def test_conserva_la_fecha_de_modificacion_de_cada_nota(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    _recuperar(base, completo, tmp, aplicar=True)
    for d in ("RAW_VAULT/Conversations", "MERGED_VAULT/Conversations", "PRJ_VAULT"):
        for n in _notas(base / d):
            assert int(n.stat().st_mtime) == FECHA_VIEJA, f"{n}: el merge desempata los renombrados por esta fecha"


def test_no_deja_ficheros_temporales(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    _recuperar(base, completo, tmp, aplicar=True)
    assert not list(base.rglob("*.recuperar.part"))


def test_es_idempotente(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    _recuperar(base, completo, tmp, aplicar=True)
    antes = _foto(base)
    r = _recuperar(base, completo, tmp, aplicar=True)
    assert r["imagenes_con_aviso"] == 0 and r["notas_cambiadas"] == 0 and r["copia"] is None
    assert _foto(base) == antes


def test_lo_que_el_export_no_trae_se_queda_como_aviso_y_se_cuenta(tmp_path):
    base = tmp_path / "vault"
    convs = [_conv([("sediment://file_aaa", False), ("sediment://file_que_no_viene", False)])]
    _importar(_zip(tmp_path / "a.zip", convs, {}), base / "RAW_VAULT" / "Conversations", base)
    export = _zip(tmp_path / "b.zip", convs, {"file_aaa.dat": PNG})
    r = _recuperar(base, export, tmp_path, aplicar=True)
    nota = _notas(base / "RAW_VAULT" / "Conversations")[0].read_text(encoding="utf-8")
    assert r["recuperables"] == 1 and r["sin_recuperar"] == 1
    assert r["sin_recuperar_punteros"] == ["sediment://file_que_no_viene"]
    assert nota.count("![](CHATGPT/") == 1
    assert "imagen no disponible en el export: sediment://file_que_no_viene" in nota


# ---- la propiedad que importa: igual que una importacion nueva --------------------------------
def test_la_nota_reparada_es_identica_a_la_que_escribe_una_importacion_nueva(vault_con_avisos, tmp_path):
    base, completo, _, tmp = vault_con_avisos
    _recuperar(base, completo, tmp, aplicar=True)
    fresco = tmp_path / "fresco"
    _importar(completo, fresco / "RAW_VAULT" / "Conversations", fresco)
    reparada = _notas(base / "RAW_VAULT" / "Conversations")[0].read_text(encoding="utf-8")
    nueva = _notas(fresco / "RAW_VAULT" / "Conversations")[0].read_text(encoding="utf-8")
    assert reparada == nueva
    assert sorted(p.name for p in (base / "CHATGPT").rglob("*") if p.is_file() and not p.name.startswith("_")) == \
        sorted(p.name for p in (fresco / "CHATGPT").rglob("*") if p.is_file() and not p.name.startswith("_"))


def _turnos_de_usuario(carpeta: Path) -> int:
    return sum(n.read_text(encoding="utf-8").count("### User") for n in _notas(carpeta))


def _siguiente_export(base, tmp_path, convs, ficheros):
    """El export de la semana siguiente: la misma conversacion con un turno mas."""
    convs2 = [_conv([("sediment://file_aaa", False), ("file-service://file-bbb", True)], extra_turno="Una cosa mas")]
    z = _zip(tmp_path / "siguiente.zip", convs2, ficheros)
    _importar(z, base / "RAW_VAULT" / "Conversations", base)
    _fusionar(base / "RAW_VAULT", base / "MERGED_VAULT_NUEVO")
    return _turnos_de_usuario(base / "MERGED_VAULT_NUEVO")


def test_control_sin_reparar_el_siguiente_export_duplica_turnos(vault_con_avisos):
    """Lo que habia que evitar. Si esto dejara de pasar, la herramienta ya no haria falta."""
    base, completo, convs, tmp = vault_con_avisos
    sin_cambios = _turnos_de_usuario(base / "MERGED_VAULT" / "Conversations")
    total = _siguiente_export(base, tmp, convs, {"file_aaa.dat": PNG, "file-bbb.dat": JPG})
    assert total > sin_cambios + 1, f"esperaba duplicados y salieron {total} turnos sobre {sin_cambios}"


def test_reparado_el_siguiente_export_solo_anade_su_turno_nuevo(vault_con_avisos):
    base, completo, convs, tmp = vault_con_avisos
    _recuperar(base, completo, tmp, aplicar=True)
    antes = _turnos_de_usuario(base / "MERGED_VAULT" / "Conversations")
    total = _siguiente_export(base, tmp, convs, {"file_aaa.dat": PNG, "file-bbb.dat": JPG})
    assert total == antes + 1, f"{total} turnos de usuario; debian ser {antes + 1} (los de antes mas el nuevo)"


# ---- deshacer ------------------------------------------------------------------------------------
def test_deshacer_devuelve_cada_nota_byte_a_byte_y_con_su_fecha(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    antes = {p: p.read_bytes() for d in ("RAW_VAULT/Conversations", "MERGED_VAULT/Conversations", "PRJ_VAULT")
             for p in _notas(base / d)}
    r = _recuperar(base, completo, tmp, aplicar=True)
    assert any(p.read_bytes() != b for p, b in antes.items())
    assert rec.deshacer(Path(r["copia"]), log=lambda *_: None) == 3
    for p, b in antes.items():
        assert p.read_bytes() == b
        assert int(p.stat().st_mtime) == FECHA_VIEJA


def test_deshacer_se_niega_con_una_carpeta_que_no_es_una_copia(tmp_path):
    with pytest.raises(rec.ErrorRecuperar, match="diario.json"):
        rec.deshacer(tmp_path)


def test_las_imagenes_copiadas_se_quedan_aunque_se_deshaga(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    r = _recuperar(base, completo, tmp, aplicar=True)
    rec.deshacer(Path(r["copia"]), log=lambda *_: None)
    assert list((base / "CHATGPT" / "ATTACHMENTS").glob("*.png"))


# ---- avisos de conversaciones que este export ya no trae ----------------------------------------------
def _nota_con_avisos(base: Path, nombre: str, punteros):
    p = base / "RAW_VAULT" / "Conversations" / "2026" / "01" / nombre
    p.parent.mkdir(parents=True, exist_ok=True)
    cuerpo = "".join(f"*[imagen no disponible en el export: {q}]*\n" for q in punteros)
    p.write_text(f'---\ntitle: "Vieja"\ndate: 2026-01-05\n---\n\n### User\n\n{cuerpo}', encoding="utf-8")
    return p


def test_un_aviso_de_una_conversacion_que_el_export_no_trae_usa_la_biblioteca_para_el_banco(tmp_path):
    """Las notas vienen de exports anteriores; este solo trae el binario y la biblioteca."""
    base = tmp_path / "vault"
    nota = _nota_con_avisos(base, "2026-01-05_vieja.md",
                            ["sediment://file_gen", "sediment://file_subida", "sediment://file_sin_biblioteca"])
    biblioteca = [_entrada_biblioteca("file_gen", "Generada.png"),
                  _entrada_biblioteca("file_subida", "Captura de pantalla.png", generada=False)]
    z = _zip(tmp_path / "x.zip", [_conv([("sediment://otra_cosa", False)])],
             {"file_gen.dat": PNG, "file_subida.dat": PNG2, "file_sin_biblioteca.dat": JPG}, biblioteca)
    r = _recuperar(base, z, tmp_path, aplicar=True)
    assert r["recuperables"] == 3 and r["notas_cambiadas"] == 1
    texto = nota.read_text(encoding="utf-8")
    assert texto.count("![](CHATGPT/GENERATED/") == 1, "la generada va a GENERATED"
    assert texto.count("![](CHATGPT/ATTACHMENTS/") == 2, "la subida y la que no esta en la biblioteca van a ATTACHMENTS"
    gen = json.loads((base / "CHATGPT" / "GENERATED" / "_image_manifest.json").read_text(encoding="utf-8"))
    sub = json.loads((base / "CHATGPT" / "ATTACHMENTS" / "_image_manifest.json").read_text(encoding="utf-8"))
    assert [m["origen"] for m in gen.values()] == ["generada"]
    assert sorted(m.get("adjunto_nombre", "") for m in sub.values()) == ["", "Captura de pantalla.png"]
    assert all(m["primera_conversacion"] == "Vieja" for m in (*gen.values(), *sub.values()))


def test_sin_biblioteca_un_aviso_antiguo_se_trata_como_subida(tmp_path):
    base = tmp_path / "vault"
    nota = _nota_con_avisos(base, "2026-01-05_vieja.md", ["sediment://file_x"])
    z = _zip(tmp_path / "x.zip", [_conv([("sediment://otra_cosa", False)])], {"file_x.dat": PNG})
    _recuperar(base, z, tmp_path, aplicar=True)
    assert "![](CHATGPT/ATTACHMENTS/" in nota.read_text(encoding="utf-8")


# ---- la biblioteca -----------------------------------------------------------------------------------
def _entrada_biblioteca(fid, nombre, generada=True, mime="image/png"):
    return {"file_id": fid, "file_name": nombre, "mime_type": mime, "created_at": "2026-10-17T21:12:23.484227+00:00",
            "image_gen_generation_id": "s_123" if generada else None}


@pytest.fixture
def export_con_biblioteca(tmp_path):
    convs = [_conv([("sediment://file_enlazada", True)])]
    biblioteca = [
        _entrada_biblioteca("file_enlazada", "Ya enlazada.png"),
        _entrada_biblioteca("file_huerfana", "Polluelo de gorrion.png"),
        _entrada_biblioteca("file_sin_binario", "No viene.png"),
        _entrada_biblioteca("file_subida", "Subida mia.png", generada=False),
        _entrada_biblioteca("file_texto", "notas.md", mime="text/markdown"),
    ]
    ficheros = {"file_enlazada.dat": PNG, "file_huerfana.dat": PNG2, "file_subida.dat": JPG}
    return _zip(tmp_path / "bib.zip", convs, ficheros, biblioteca)


@pytest.fixture
def vault_minimo(tmp_path):
    base = tmp_path / "vault"
    (base / "MERGED_VAULT" / "Conversations").mkdir(parents=True)
    return base


def test_biblioteca_copia_solo_las_generadas_que_ninguna_conversacion_enlaza(vault_minimo, export_con_biblioteca,
                                                                              tmp_path):
    r = _recuperar(vault_minimo, export_con_biblioteca, tmp_path, aplicar=True, biblioteca=True)
    assert {k: r["biblioteca"][k] for k in ("generadas", "sin_fichero", "ya_enlazadas", "copiadas")} ==         {"generadas": 3, "sin_fichero": 1, "ya_enlazadas": 1, "copiadas": 1}
    ficheros = [p for p in (vault_minimo / "CHATGPT" / "GENERATED").iterdir() if not p.name.startswith("_")]
    assert len(ficheros) == 1 and ficheros[0].read_bytes() == PNG2
    meta = json.loads((vault_minimo / "CHATGPT" / "GENERATED" / "_image_manifest.json").read_text(encoding="utf-8"))
    (m,) = meta.values()
    assert m["origen"] == "generada" and m["titulo_biblioteca"] == "Polluelo de gorrion"
    assert m["creada"] == "2026-10-17T21:12:23"


def test_biblioteca_en_simulacion_no_escribe(vault_minimo, export_con_biblioteca, tmp_path):
    antes = _foto(vault_minimo)
    r = _recuperar(vault_minimo, export_con_biblioteca, tmp_path, aplicar=False, biblioteca=True)
    assert r["biblioteca"]["copiadas"] == 1
    assert _foto(vault_minimo) == antes


def test_sin_biblioteca_no_se_toca_la_carpeta_de_generadas(vault_minimo, export_con_biblioteca, tmp_path):
    r = _recuperar(vault_minimo, export_con_biblioteca, tmp_path, aplicar=True, biblioteca=False)
    assert r["biblioteca"] is None
    assert not [p for p in (vault_minimo / "CHATGPT" / "GENERATED").iterdir() if not p.name.startswith("_")]


def test_biblioteca_dos_veces_no_duplica(vault_minimo, export_con_biblioteca, tmp_path):
    _recuperar(vault_minimo, export_con_biblioteca, tmp_path, aplicar=True, biblioteca=True)
    antes = _foto(vault_minimo)
    _recuperar(vault_minimo, export_con_biblioteca, tmp_path, aplicar=True, biblioteca=True)
    assert _foto(vault_minimo) == antes


def test_un_export_sin_biblioteca_lo_dice_y_sigue(vault_minimo, tmp_path):
    z = _zip(tmp_path / "x.zip", [_conv([("sediment://file_a", False)])], {"file_a.dat": PNG})
    r = _recuperar(vault_minimo, z, tmp_path, aplicar=False, biblioteca=True)
    assert r["biblioteca"]["generadas"] == 0


# ---- errores -----------------------------------------------------------------------------------------
def test_se_niega_si_el_export_no_es_un_zip(vault_minimo, tmp_path):
    f = tmp_path / "x.json"
    f.write_text("[]", encoding="utf-8")
    with pytest.raises(rec.ErrorRecuperar, match=".zip"):
        _recuperar(vault_minimo, f, tmp_path)


def test_se_niega_si_la_base_no_tiene_vaults(tmp_path):
    z = _zip(tmp_path / "x.zip", [_conv([("sediment://file_a", False)])], {"file_a.dat": PNG})
    (tmp_path / "vacia").mkdir()
    with pytest.raises(rec.ErrorRecuperar, match="can't find"):
        _recuperar(tmp_path / "vacia", z, tmp_path)


def test_se_niega_si_no_puede_indexar_ninguna_imagen_del_zip(vault_minimo, tmp_path):
    """Que el formato cambie otra vez no debe acabar en 'recuperadas 0' sin explicacion."""
    z = _zip(tmp_path / "x.zip", [_conv([("sediment://file_a", False)])], {"imagen-rara": PNG})
    with pytest.raises(rec.ErrorRecuperar, match="export format"):
        _recuperar(vault_minimo, z, tmp_path)


# ---- la linea de comandos --------------------------------------------------------------------------------
def _cli(*args):
    return subprocess.run([sys.executable, str(RAIZ / "recuperar_imagenes.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RAIZ)


def test_cli_simulacion_y_aplicar(vault_con_avisos):
    base, completo, _, tmp = vault_con_avisos
    r = _cli("--export", str(completo), "--base-vault", str(base))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRY RUN" in r.stdout and "repeat with --aplicar" in r.stdout
    assert "imagen no disponible" in _notas(base / "RAW_VAULT" / "Conversations")[0].read_text(encoding="utf-8")
    r = _cli("--export", str(completo), "--base-vault", str(base), "--aplicar")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DONE" in r.stdout and "--deshacer" in r.stdout
    assert "imagen no disponible" not in _notas(base / "RAW_VAULT" / "Conversations")[0].read_text(encoding="utf-8")
    copia = next(Path(l.split('"')[1]) for l in r.stdout.splitlines() if "--deshacer" in l)
    try:
        r = _cli("--deshacer", str(copia))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "imagen no disponible" in _notas(base / "RAW_VAULT" / "Conversations")[0].read_text(encoding="utf-8")
    finally:
        import shutil
        shutil.rmtree(copia, ignore_errors=True)       # la copia del CLI cae en logs/ del repo


def test_cli_error_claro_con_un_export_que_no_existe(vault_minimo, tmp_path):
    r = _cli("--export", str(tmp_path / "no_existe.zip"), "--base-vault", str(vault_minimo))
    assert r.returncode == 2 and "[error]" in r.stdout
