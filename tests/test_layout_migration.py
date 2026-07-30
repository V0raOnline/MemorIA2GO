# -*- coding: utf-8 -*-
"""Tests de layout_migration.py — conversion de un vault espanol al layout
ingles (i18n fase 3b).

Por que importa que esto este bien probado: es la unica pieza del proyecto
que RENOMBRA cosas en el vault del usuario. El resto del pipeline solo
anade. Un fallo aqui no es un indice feo, es un vault movido a medias.

El fixture construye un vault espanol completo, con las dos formas de
enlace y con la subcarpeta de tipo de los artefactos, que es donde vive la
complicacion real.
"""
from pathlib import Path

import layout_migration as lm


def _vault_espanol(base: Path) -> Path:
    """Vault con el layout de la edicion espanola, con contenido en los
    sitios donde el renombrado puede romper algo."""
    (base / "RAW_VAULT" / "Conversaciones" / "2026" / "07").mkdir(parents=True)
    (base / "MERGED_VAULT" / "Conversaciones" / "2026" / "07").mkdir(parents=True)
    (base / "MERGED_VAULT" / "_Temas").mkdir(parents=True)
    (base / "PRJ_VAULT" / "proyecto" / "2026" / "07").mkdir(parents=True)

    for banco in ("CHATGPT/GENERADAS", "CHATGPT/ADJUNTOS", "GROK/ADJUNTOS",
                  "GROK/GENERADAS_IMAGEN", "GROK/GENERADAS_VIDEO"):
        (base / banco).mkdir(parents=True)
    (base / "CLAUDE" / "ARTEFACTOS" / "codigo").mkdir(parents=True)
    (base / "CLAUDE" / "ARTEFACTOS" / "markdown").mkdir(parents=True)

    (base / "CHATGPT" / "GENERADAS" / "img.png").write_bytes(b"x")
    (base / "CLAUDE" / "ARTEFACTOS" / "codigo" / "s.py").write_text("x", encoding="utf-8")
    (base / "CLAUDE" / "ARTEFACTOS" / "markdown" / "doc.md").write_text("x", encoding="utf-8")

    nota = (
        "---\ntitle: \"X\"\ndate: 2026-07-01\n---\n\n"
        "![](CHATGPT/GENERADAS/img.png)\n\n"
        "[s.py](CLAUDE/ARTEFACTOS/codigo/s.py)\n\n"
        "[doc.md](CLAUDE/ARTEFACTOS/markdown/doc.md)\n\n"
        "[[no-tocar/CHATGPT/GENERADAS/img.png]]\n"
    )
    for v, sub in (("RAW_VAULT", "Conversaciones/2026/07"),
                   ("MERGED_VAULT", "Conversaciones/2026/07"),
                   ("PRJ_VAULT", "proyecto/2026/07")):
        (base / v / sub / "a.md").write_text(nota, encoding="utf-8")

    (base / "MERGED_VAULT" / "_Temas" / "_sin-tema.md").write_text(
        "---\ntipo: tema\n---\n\n# Sin tema\n", encoding="utf-8")
    (base / "MERGED_VAULT" / "_grok_pendientes.md").write_text("# Pendientes\n", encoding="utf-8")

    # Ficheros de estado: NO se tocan (decision V0ra). Viven en carpetas que
    # tampoco se renombran, asi que deben seguir enteros al terminar.
    (base / "GROK" / "_pendientes_descarga.json").write_text('[{"id": "a"}]', encoding="utf-8")
    (base / "RAW_VAULT" / "_exports_procesados.json").write_text('{"x": 1}', encoding="utf-8")
    return base


def test_detectar_vault_espanol_pide_migracion(tmp_path):
    _vault_espanol(tmp_path)

    plan = lm.detectar(tmp_path)

    assert plan["necesaria"] is True
    de = {c["de"] for c in plan["carpetas"]}
    assert "MERGED_VAULT/Conversaciones" in de
    assert "CLAUDE/ARTEFACTOS" in de
    assert plan["bloqueadas"] == []


def test_detectar_vault_ingles_no_pide_nada(tmp_path):
    """La card de la UI se pinta con esto: en un vault ya ingles no debe
    aparecer. Un usuario nuevo no tiene por que ver un boton que no le sirve."""
    (tmp_path / "MERGED_VAULT" / "Conversations").mkdir(parents=True)
    (tmp_path / "CHATGPT" / "GENERATED").mkdir(parents=True)

    plan = lm.detectar(tmp_path)

    assert plan["necesaria"] is False
    assert plan["carpetas"] == []


def test_migrar_renombra_carpetas_y_conserva_el_contenido(tmp_path):
    _vault_espanol(tmp_path)

    lm.migrar(tmp_path)

    assert (tmp_path / "MERGED_VAULT" / "Conversations").is_dir()
    assert not (tmp_path / "MERGED_VAULT" / "Conversaciones").exists()
    assert (tmp_path / "CLAUDE" / "ARTIFACTS" / "code" / "s.py").is_file()
    assert (tmp_path / "CHATGPT" / "GENERATED" / "img.png").is_file()
    assert (tmp_path / "GROK" / "GENERATED_IMAGE").is_dir()


def test_migrar_reengancha_las_dos_formas_de_enlace(tmp_path):
    _vault_espanol(tmp_path)

    hechos = lm.migrar(tmp_path)

    nota = (tmp_path / "MERGED_VAULT" / "Conversations" / "2026" / "07" / "a.md").read_text(encoding="utf-8")
    assert "![](CHATGPT/GENERATED/img.png)" in nota
    assert "[s.py](CLAUDE/ARTIFACTS/code/s.py)" in nota
    assert "[doc.md](CLAUDE/ARTIFACTS/markdown/doc.md)" in nota
    assert "ADJUNTOS" not in nota and "ARTEFACTOS" not in nota
    # 3 enlaces x 3 vaults
    assert hechos["enlaces_reescritos"] == 9


def test_migrar_deja_todos_los_enlaces_apuntando_a_ficheros_que_existen(tmp_path):
    """La comprobacion que de verdad cierra el asunto: despues de mover
    carpetas Y reescribir enlaces, cada enlace resuelve en disco. Es la
    misma clase de test que caza el bug del indice de Claude."""
    import re
    _vault_espanol(tmp_path)

    lm.migrar(tmp_path)

    rx = re.compile(r"!?\[[^\]]*\]\(((?:CHATGPT|GROK|CLAUDE)/[^)]+)\)")
    comprobados = 0
    for v in ("RAW_VAULT", "MERGED_VAULT", "PRJ_VAULT"):
        for f in (tmp_path / v).rglob("*.md"):
            for m in rx.finditer(f.read_text(encoding="utf-8")):
                comprobados += 1
                assert (tmp_path / m.group(1)).exists(), f"enlace roto: {m.group(1)}"
    assert comprobados == 9


def test_migrar_renombra_la_nota_sin_tema_dentro_de_su_carpeta_ya_renombrada(tmp_path):
    """_sin-tema.md vive DENTRO de _Temas: cuando le toca, su carpeta padre
    ya se llama _Topics y el fichero no esta donde el plan lo vio. Si esto
    se resuelve mal, la nota se queda con el nombre viejo para siempre."""
    _vault_espanol(tmp_path)

    lm.migrar(tmp_path)

    assert (tmp_path / "MERGED_VAULT" / "_Topics" / "_no-topic.md").is_file()
    assert not (tmp_path / "MERGED_VAULT" / "_Topics" / "_sin-tema.md").exists()
    assert (tmp_path / "MERGED_VAULT" / "_grok_pending.md").is_file()


def test_migrar_no_toca_los_ficheros_de_estado(tmp_path):
    """Decision de V0ra: la capa B se queda. Sale gratis porque vive en
    carpetas que no se renombran -- este test lo fija para que nadie la
    arrastre sin querer en un cambio futuro. Si se pierde
    _pendientes_descarga.json se pierde el triaje manual del usuario, que es
    lo unico aqui que no se puede regenerar desde los exports."""
    _vault_espanol(tmp_path)

    lm.migrar(tmp_path)

    triaje = tmp_path / "GROK" / "_pendientes_descarga.json"
    registro = tmp_path / "RAW_VAULT" / "_exports_procesados.json"
    assert triaje.read_text(encoding="utf-8") == '[{"id": "a"}]'
    assert registro.read_text(encoding="utf-8") == '{"x": 1}'


def test_migrar_no_toca_wikilinks(tmp_path):
    _vault_espanol(tmp_path)

    lm.migrar(tmp_path)

    nota = (tmp_path / "MERGED_VAULT" / "Conversations" / "2026" / "07" / "a.md").read_text(encoding="utf-8")
    assert "[[no-tocar/CHATGPT/GENERADAS/img.png]]" in nota


def test_dry_run_no_escribe_nada(tmp_path):
    _vault_espanol(tmp_path)

    hechos = lm.migrar(tmp_path, dry_run=True)

    assert len(hechos["carpetas"]) > 0
    assert (tmp_path / "MERGED_VAULT" / "Conversaciones").is_dir()
    assert not (tmp_path / "MERGED_VAULT" / "Conversations").exists()
    nota = (tmp_path / "MERGED_VAULT" / "Conversaciones" / "2026" / "07" / "a.md").read_text(encoding="utf-8")
    assert "CHATGPT/GENERADAS/img.png" in nota


def test_destino_ocupado_se_salta_y_se_reporta(tmp_path):
    """No destructivo por encima de todo: si ya existe una carpeta con el
    nombre nuevo (un intento anterior a medias, o algo del usuario), NO se
    fusionan ni se pisan. Se salta y se dice."""
    _vault_espanol(tmp_path)
    (tmp_path / "MERGED_VAULT" / "Conversations").mkdir()
    (tmp_path / "MERGED_VAULT" / "Conversations" / "mia.md").write_text("no me borres", encoding="utf-8")

    plan = lm.detectar(tmp_path)
    hechos = lm.migrar(tmp_path)

    assert any(b["de"] == "MERGED_VAULT/Conversaciones" for b in plan["bloqueadas"])
    assert any(b["de"] == "MERGED_VAULT/Conversaciones" for b in hechos["bloqueadas"])
    assert (tmp_path / "MERGED_VAULT" / "Conversaciones").is_dir()  # intacta
    assert (tmp_path / "MERGED_VAULT" / "Conversations" / "mia.md").read_text(encoding="utf-8") == "no me borres"


def test_migrar_es_idempotente(tmp_path):
    """Pulsar dos veces el boton no debe romper nada ni reportar trabajo
    fantasma."""
    _vault_espanol(tmp_path)

    lm.migrar(tmp_path)
    segunda = lm.migrar(tmp_path)

    assert segunda["carpetas"] == []
    assert segunda["ficheros"] == []
    assert segunda["enlaces_reescritos"] == 0
    assert lm.detectar(tmp_path)["necesaria"] is False
