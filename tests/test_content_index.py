# -*- coding: utf-8 -*-
"""Tests de regresion de content_index.py (backlog: indice de contenido por
proveedor, decision V0ra 2026-07-22). Un archivo por proveedor, una rama
<details> colapsada por banco, cada conversacion tambien colapsada dentro.
Debe entender tanto ![](...) (imagenes) como [texto](...) (CLAUDE/ARTEFACTOS,
que nunca usa la forma de imagen) y bancos que mezclan ambas (GROK/ADJUNTOS).
"""
import json
from pathlib import Path

import content_index as ci


def _write_note(path: Path, *, title, date, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    front = f'---\ntitle: "{title}"\ndate: {date}\n---\n\n'
    path.write_text(front + body, encoding="utf-8")


def test_banco_de_imagenes_con_manifest(tmp_path):
    vault = tmp_path
    conv_dir = vault / "Conversaciones"
    _write_note(conv_dir / "a.md", title="Con imagen", date="2026-07-01",
                body="![](CHATGPT/GENERADAS/abc123.png)\n")

    bank_dir = vault / "CHATGPT" / "GENERADAS"
    bank_dir.mkdir(parents=True)
    (bank_dir / "_image_manifest.json").write_text(
        json.dumps({"abc123.png": {"origen": "generada", "width": 1024, "height": 1024}}),
        encoding="utf-8",
    )

    bank = ci.BankSpec(prefix="CHATGPT/GENERADAS", label="Generadas")
    entries = ci.collect_bank_entries(vault, "Conversaciones", bank)

    assert len(entries) == 1
    item = entries[0]["items"][0]
    assert item["es_imagen"] is True
    assert item["caption"] == "Generated · 1024×1024"


def test_banco_solo_enlaces_recupera_titulo_de_artefacto(tmp_path):
    vault = tmp_path
    conv_dir = vault / "Conversaciones"
    _write_note(conv_dir / "a.md", title="Con artefacto", date="2026-07-01",
                body="🧩 Artifact: **Mi Contador** → [contador-a1b2c3d4.py](CLAUDE/ARTEFACTOS/codigo/contador-a1b2c3d4.py)\n")

    bank = ci.BankSpec(prefix="CLAUDE/ARTEFACTOS", label="Artefactos")
    entries = ci.collect_bank_entries(vault, "Conversaciones", bank)

    assert len(entries) == 1
    item = entries[0]["items"][0]
    assert item["es_imagen"] is False
    assert item["titulo"] == "Mi Contador"
    assert item["fname"] == "contador-a1b2c3d4.py"


def test_banco_mixto_imagen_y_enlace_en_la_misma_nota(tmp_path):
    vault = tmp_path
    conv_dir = vault / "Conversaciones"
    _write_note(conv_dir / "a.md", title="Adjuntos mixtos", date="2026-07-01",
                body="![](GROK/ADJUNTOS/foto.jpg)\n\n📎 [Attached file](GROK/ADJUNTOS/informe.pdf)\n")

    bank = ci.BankSpec(prefix="GROK/ADJUNTOS", label="Adjuntos")
    entries = ci.collect_bank_entries(vault, "Conversaciones", bank)

    items = entries[0]["items"]
    assert len(items) == 2
    por_nombre = {it["fname"]: it for it in items}
    assert por_nombre["foto.jpg"]["es_imagen"] is True
    assert por_nombre["informe.pdf"]["es_imagen"] is False


def test_titulo_sin_patron_ni_texto_se_embellece_desde_el_nombre(tmp_path):
    vault = tmp_path
    conv_dir = vault / "Conversaciones"
    _write_note(conv_dir / "a.md", title="X", date="2026-07-01",
                body="[](GROK/ADJUNTOS/mi-documento-final.pdf)\n")

    bank = ci.BankSpec(prefix="GROK/ADJUNTOS", label="Adjuntos")
    entries = ci.collect_bank_entries(vault, "Conversaciones", bank)

    assert entries[0]["items"][0]["titulo"] == "mi documento final"


def test_generate_provider_index_combina_varios_bancos_colapsados(tmp_path):
    vault = tmp_path
    conv_dir = vault / "Conversaciones"
    _write_note(conv_dir / "a.md", title="Nota", date="2026-07-01",
                body="![](CHATGPT/GENERADAS/g1.png)\n\n![](CHATGPT/ADJUNTOS/s1.png)\n")

    bancos = [
        ci.BankSpec(prefix="CHATGPT/GENERADAS", label="Generadas"),
        ci.BankSpec(prefix="CHATGPT/ADJUNTOS", label="Adjuntos"),
    ]
    resultado = ci.generate_provider_index(vault, "Conversaciones", "ChatGPT", bancos)
    md = resultado["markdown"]

    assert "# ChatGPT" in md
    assert "Generadas (1)" in md
    assert "Adjuntos (1)" in md
    # colapsado por defecto: ningun <details> lleva el atributo open
    assert "<details open" not in md
    assert md.count("<details>") >= 4  # 2 ramas + 2 conversaciones (una por banco)
    assert resultado["stats"]["Generadas"]["items"] == 1
    assert resultado["stats"]["Adjuntos"]["items"] == 1
    # bug real 2026-07-22: el resumen llevaba un \n embebido que, sumado al
    # separador del join, dejaba DOS lineas en blanco antes de la primera
    # rama en vez de una -- se ve "raro" en Obsidian (hueco de mas).
    assert "\n\n\n" not in md


def test_banco_catalogo_lista_directo_desde_manifest_sin_notas(tmp_path):
    """media_posts de Grok (Imagine) son root-level -- no viven en ninguna
    conversacion, asi que no hay enlace que rastrear en ninguna nota. El
    banco se marca catalog=True y se lista directo desde el manifest."""
    vault = tmp_path
    bank_dir = vault / "GROK" / "GENERADAS_IMAGEN"
    bank_dir.mkdir(parents=True)
    (bank_dir / "abc.png").write_bytes(b"fake")
    (bank_dir / "def.png").write_bytes(b"fake")
    (bank_dir / "_image_manifest.json").write_text(json.dumps({
        "abc.png": {"origen": "generada", "prompt": "un gato", "create_time": "2026-06-10T08:00:00Z"},
        "def.png": {"origen": "generada", "prompt": "", "create_time": "2026-06-05T08:00:00Z"},
    }), encoding="utf-8")

    bank = ci.BankSpec(prefix="GROK/GENERADAS_IMAGEN", label="Generadas (imagen)", catalog=True)
    items = ci.collect_catalog_entries(bank, vault)

    assert len(items) == 2
    assert items[0]["fname"] == "abc.png"  # mas reciente primero
    assert items[0]["prompt"] == "un gato"

    md = ci.render_catalog_branch(bank, items)
    assert "Generadas (imagen) (2)" in md
    assert "<details open" not in md
    assert '"un gato"' in md


def test_banco_catalogo_prompt_con_comillas_propias_no_se_dobla(tmp_path):
    """Bug real 2026-07-22: algunos prompts de Grok Imagine ya vienen con
    comillas literales tecleadas por V0ra (p.ej. '"Arte en estilo...'), y
    render_catalog_branch envolvia el prompt en comillas sin comprobarlo,
    dejando '""Arte...' -- se veia "raro" en el indice real."""
    vault = tmp_path
    bank_dir = vault / "GROK" / "GENERADAS_IMAGEN"
    bank_dir.mkdir(parents=True)
    (bank_dir / "abc.png").write_bytes(b"fake")
    (bank_dir / "_image_manifest.json").write_text(json.dumps({
        "abc.png": {"origen": "generada", "prompt": '"Arte en estilo cyberpunk', "create_time": ""},
    }), encoding="utf-8")

    bank = ci.BankSpec(prefix="GROK/GENERADAS_IMAGEN", label="Generadas (imagen)", catalog=True)
    items = ci.collect_catalog_entries(bank, vault)
    assert items[0]["prompt"] == "Arte en estilo cyberpunk"

    md = ci.render_catalog_branch(bank, items)
    assert '> "Arte en estilo cyberpunk"' in md
    assert '""Arte' not in md


def test_render_pendientes_note_prompt_con_comillas_propias_no_se_dobla():
    pendientes = [{"id": "a", "prompt": '"un perro corriendo"', "link": "https://grok.com/x",
                   "media_type": "video", "create_time": "2025-06-01T00:00:00Z"}]
    md = ci.render_pendientes_note(pendientes, "Grok — pendientes de descarga")
    assert '""un perro' not in md
    assert '> "un perro corriendo"' in md


def test_bank_dir_fuera_del_vault_se_respeta(tmp_path):
    """Bug real 2026-07-22: en produccion los bancos (CHATGPT/GENERADAS...)
    cuelgan de base_vault, que NO es el mismo directorio que MERGED_VAULT
    (el 'vault' que se escanea en busca de notas). Si bank_dir por defecto
    cae a vault/prefix en vez de al bank_dir explicito, el manifest no se
    encuentra (captions mudas para bancos con enlaces en notas) o el
    catalogo sale vacio del todo (bancos catalog=True, sin notas que
    escanear). Los tests anteriores ponian el banco DENTRO del vault por
    casualidad y nunca lo habrian cazado -- aqui viven en sitios distintos
    a proposito, como en produccion (base_vault/CHATGPT/... vs MERGED_VAULT)."""
    base_vault = tmp_path / "base"
    vault = base_vault / "MERGED_VAULT"
    conv_dir = vault / "Conversaciones"
    _write_note(conv_dir / "a.md", title="Con imagen", date="2026-07-01",
                body="![](CHATGPT/GENERADAS/abc123.png)\n")

    bank_dir = base_vault / "CHATGPT" / "GENERADAS"  # hermano de MERGED_VAULT, no dentro
    bank_dir.mkdir(parents=True)
    (bank_dir / "_image_manifest.json").write_text(
        json.dumps({"abc123.png": {"origen": "generada", "width": 512, "height": 512}}),
        encoding="utf-8",
    )

    bank = ci.BankSpec(prefix="CHATGPT/GENERADAS", label="Generadas", bank_dir=bank_dir)
    entries = ci.collect_bank_entries(vault, "Conversaciones", bank)

    assert len(entries) == 1
    assert entries[0]["items"][0]["caption"] == "Generated · 512×512"


def test_render_pendientes_note_ordena_por_fecha_y_colapsa():
    pendientes = [
        {"id": "a", "prompt": "un perro", "link": "https://grok.com/x", "media_type": "video",
         "create_time": "2025-06-01T00:00:00Z"},
        {"id": "b", "prompt": "un gato", "link": "https://grok.com/y", "media_type": "image",
         "create_time": "2026-06-10T08:00:00Z"},
    ]
    md = ci.render_pendientes_note(pendientes, "Grok — pendientes de descarga")
    assert "<details open" not in md
    assert md.index("un gato") < md.index("un perro")  # mas reciente primero
    assert "https://grok.com/y" in md


def test_render_pendientes_note_vacio():
    md = ci.render_pendientes_note([], "Grok — pendientes de descarga")
    assert "Nothing pending" in md


def test_generate_provider_index_sin_contenido_no_revienta(tmp_path):
    vault = tmp_path
    (vault / "Conversaciones").mkdir()
    bancos = [ci.BankSpec(prefix="CLAUDE/ARTEFACTOS", label="Artefactos")]
    resultado = ci.generate_provider_index(vault, "Conversaciones", "Claude", bancos)
    assert "Artefactos (0)" in resultado["markdown"]
    assert resultado["stats"]["Artefactos"]["conversaciones"] == 0
