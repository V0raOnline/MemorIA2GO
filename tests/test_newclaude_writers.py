# -*- coding: utf-8 -*-
"""Tests de los writers del nuevo export de Claude (Fases C-E, D2-D4).

Fija los tres contratos que resuelven las tres decisiones del plan:
  - D3: projects van a PRJ_VAULT/<name>/ con 00_proyecto.md + _docs/;
  - D4: memory_files van a Claude_Mem/ respetando el path literal;
  - D2: conversations_memory y project_memories tambien van a Claude_Mem/,
    en su propio fichero.

Todos los writers son idempotentes por contenido y toleran capas parciales
(un layout sin memories, un proyecto sin docs, etc). Verificado contra el
export real de V0ra al final.
"""
import json
from pathlib import Path

import pytest

from providers import newclaude_adapter as nc


# ─────────────────────────────────────────
# Fixtures reutilizables
# ─────────────────────────────────────────

def _crear_layout(tmp_path: Path, *, con_projects=None, con_memories=None,
                  con_frames=None, con_conversations=None) -> Path:
    """Monta un layout completo de NewClaude sobre tmp_path con las
    categorias que le pasen. Devuelve la carpeta raiz."""
    layout = tmp_path / "NewClaude"
    layout.mkdir()

    # conversations siempre presente para pasar detect_layout (aunque
    # los tests no las usen aqui).
    conv_dir = layout / "conversations-000"
    conv_dir.mkdir()
    (conv_dir / "conversations.json").write_text(
        json.dumps(con_conversations if con_conversations is not None else []),
        encoding="utf-8",
    )

    if con_projects is not None:
        pdir = layout / "projects-000" / "projects"
        pdir.mkdir(parents=True)
        for pr in con_projects:
            (pdir / f"{pr['uuid']}.json").write_text(
                json.dumps(pr, ensure_ascii=False), encoding="utf-8"
            )

    if con_memories is not None:
        mdir = layout / "memories-000" / "memories"
        mdir.mkdir(parents=True)
        (mdir / f"{con_memories.get('account_uuid', 'x')}.json").write_text(
            json.dumps(con_memories, ensure_ascii=False), encoding="utf-8"
        )

    if con_frames is not None:
        fdir = layout / "frames-000" / "artifacts"
        fdir.mkdir(parents=True)
        for fr in con_frames:
            adir = fdir / fr["id"]
            adir.mkdir()
            (adir / "artifact.json").write_text(
                json.dumps({k: v for k, v in fr.items() if k != "_versions_html" and k != "_comments"},
                           ensure_ascii=False),
                encoding="utf-8"
            )
            if fr.get("_versions_html"):
                vdir = adir / "versions"
                vdir.mkdir()
                for vid, html in fr["_versions_html"].items():
                    (vdir / f"{vid}.html").write_text(html, encoding="utf-8")
            if fr.get("_comments") is not None:
                (adir / "artifact_comments.json").write_text(
                    json.dumps(fr["_comments"], ensure_ascii=False), encoding="utf-8"
                )

    return layout


def _proyecto_minimo(**overrides):
    base = {
        "uuid": "019a-proj-uuid",
        "name": "Un proyecto",
        "description": "Descripcion del proyecto",
        "is_private": True,
        "is_starter_project": False,
        "prompt_template": "",
        "created_at": "2026-01-15T10:00:00+00:00",
        "updated_at": "2026-06-20T15:00:00+00:00",
        "creator": {"uuid": "usr-1", "full_name": "V0ra"},
        "docs": [],
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────
# write_projects
# ─────────────────────────────────────────

def test_write_projects_crea_carpeta_con_nota_indice_y_docs(tmp_path):
    """Un proyecto con 2 docs -> carpeta con 00_proyecto.md + _docs/*."""
    layout = _crear_layout(tmp_path, con_projects=[
        _proyecto_minimo(name="MemorIA2GO", docs=[
            {"uuid": "d1", "filename": "guia.md", "content": "# Guia\ntexto",
             "created_at": "2026-02-01T00:00:00+00:00"},
            {"uuid": "d2", "filename": "notas.md", "content": "notas planas",
             "created_at": "2026-02-02T00:00:00+00:00"},
        ]),
    ])
    prj = tmp_path / "PRJ_VAULT"
    stats = nc.write_projects(layout, prj)
    assert stats["proyectos"] == 1
    assert stats["docs"] == 2
    carp = prj / "MemorIA2GO"
    nota = (carp / "00_proyecto.md").read_text(encoding="utf-8")
    assert 'name: "MemorIA2GO"' in nota
    assert 'uuid: "019a-proj-uuid"' in nota
    assert "Descripcion del proyecto" in nota
    # Los docs son ficheros literales en _docs/
    assert (carp / "_docs" / "guia.md").read_text(encoding="utf-8") == "# Guia\ntexto"
    assert (carp / "_docs" / "notas.md").read_text(encoding="utf-8") == "notas planas"


def test_write_projects_incluye_prompt_template_como_bloque_codigo(tmp_path):
    """El prompt_template es el system prompt del proyecto. Va como
    bloque de codigo para que sea legible tal cual, sin interpretar
    markdown que pudiera contener."""
    layout = _crear_layout(tmp_path, con_projects=[
        _proyecto_minimo(name="X", prompt_template="Eres un asistente que...")
    ])
    prj = tmp_path / "PRJ_VAULT"
    nc.write_projects(layout, prj)
    nota = (prj / "X" / "00_proyecto.md").read_text(encoding="utf-8")
    assert "Instrucciones del proyecto" in nota
    assert "Eres un asistente que..." in nota
    assert "```" in nota


def test_write_projects_es_idempotente(tmp_path):
    """Reingesta con contenido identico: cero escrituras nuevas."""
    layout = _crear_layout(tmp_path, con_projects=[_proyecto_minimo()])
    prj = tmp_path / "PRJ_VAULT"
    s1 = nc.write_projects(layout, prj)
    s2 = nc.write_projects(layout, prj)
    assert s1["escritas"] > 0
    assert s2["escritas"] == 0
    assert s2["saltadas"] == s1["escritas"]


def test_write_projects_sanea_nombres_prohibidos_en_windows(tmp_path):
    """Windows no acepta \\ / : * ? " < > | en nombres. Se sustituyen
    por '_' pero acentos, mayusculas y espacios se conservan."""
    layout = _crear_layout(tmp_path, con_projects=[
        _proyecto_minimo(uuid="pu1", name='Un/proyecto"raro?', docs=[]),
        _proyecto_minimo(uuid="pu2", name="Tiro Parabólico", docs=[]),
    ])
    prj = tmp_path / "PRJ_VAULT"
    nc.write_projects(layout, prj)
    # El primero cae con los prohibidos sustituidos
    assert (prj / "Un_proyecto_raro_" / "00_proyecto.md").exists()
    # El segundo respeta acento y mayusculas
    assert (prj / "Tiro Parabólico" / "00_proyecto.md").exists()


def test_write_projects_enlaza_a_claude_mem_por_uuid(tmp_path):
    """La nota-indice tiene que enlazar a Claude_Mem/projects/<uuid>/
    para que V0ra vea la memoria de Claude sobre ESE proyecto sin
    tener que buscarla."""
    layout = _crear_layout(tmp_path, con_projects=[_proyecto_minimo(uuid="019a")])
    prj = tmp_path / "PRJ_VAULT"
    nc.write_projects(layout, prj)
    nota = (prj / "Un proyecto" / "00_proyecto.md").read_text(encoding="utf-8")
    assert "Claude_Mem/projects/019a/" in nota


# ─────────────────────────────────────────
# write_frames
# ─────────────────────────────────────────

def test_write_frames_crea_nota_y_copia_versiones(tmp_path):
    layout = _crear_layout(tmp_path, con_frames=[{
        "id": "art-1", "kind": "artifact", "visibility": "private",
        "owner_account": "usr-1", "active_version": "v-b",
        "updated_at": "2026-08-01T10:00:00+00:00",
        "versions": [
            {"id": "v-a", "title": "Primera", "description": "",
             "created_at": "2026-07-01T00:00:00+00:00"},
            {"id": "v-b", "title": "Segunda", "description": "mejora del acento",
             "created_at": "2026-08-01T10:00:00+00:00"},
        ],
        "_versions_html": {"v-a": "<html>1</html>", "v-b": "<html>2 mejor</html>"},
    }])
    banco = tmp_path / "FRAMES"
    stats = nc.write_frames(layout, banco)
    assert stats["frames"] == 1
    assert stats["versiones"] == 2
    nota = (banco / "art-1" / "00_frame.md").read_text(encoding="utf-8")
    assert 'id: "art-1"' in nota
    assert "activa" in nota  # la marca de version activa aparece
    assert "Segunda" in nota
    # Las versiones se copian tal cual, sin modificar
    assert (banco / "art-1" / "versions" / "v-a.html").read_text(encoding="utf-8") == "<html>1</html>"
    assert (banco / "art-1" / "versions" / "v-b.html").read_text(encoding="utf-8") == "<html>2 mejor</html>"


def test_write_frames_incluye_hilos_de_comentarios_si_los_hay(tmp_path):
    layout = _crear_layout(tmp_path, con_frames=[{
        "id": "art-2", "kind": "artifact", "visibility": "private",
        "owner_account": "usr-1", "active_version": "v-x",
        "updated_at": "2026-08-01T10:00:00+00:00",
        "versions": [{"id": "v-x", "title": "t", "description": "",
                       "created_at": "2026-08-01T10:00:00+00:00"}],
        "_versions_html": {"v-x": "<html/>"},
        "_comments": {"threads": [
            {"created_at": "2026-08-02T09:00:00+00:00",
             "resolved": True, "carried": False,
             "comments": [
                 {"author_index": 1, "author_role": "",
                  "author_is_artifact_owner": False,
                  "text": "El verde no me convence",
                  "created_at": "2026-08-02T09:00:00+00:00",
                  "to_claude_at": "2026-08-02T09:00:00+00:00"},
                 {"author_index": 1, "author_role": "assistant",
                  "author_is_artifact_owner": False,
                  "text": "Cambiado a cian oscuro",
                  "created_at": "2026-08-02T09:05:00+00:00",
                  "to_claude_at": "2026-08-02T09:05:00+00:00"},
             ]}
        ]},
    }])
    banco = tmp_path / "FRAMES"
    stats = nc.write_frames(layout, banco)
    assert stats["comentarios"] == 2
    nota = (banco / "art-2" / "00_frame.md").read_text(encoding="utf-8")
    assert "El verde no me convence" in nota
    assert "Cambiado a cian oscuro" in nota
    assert "resuelto" in nota


def test_write_frames_es_idempotente(tmp_path):
    layout = _crear_layout(tmp_path, con_frames=[{
        "id": "art-3", "kind": "artifact", "visibility": "private",
        "owner_account": "usr-1", "active_version": "v-x",
        "updated_at": "2026-08-01T10:00:00+00:00",
        "versions": [{"id": "v-x", "title": "t", "description": "",
                       "created_at": "2026-08-01T10:00:00+00:00"}],
        "_versions_html": {"v-x": "<html/>"},
    }])
    banco = tmp_path / "FRAMES"
    s1 = nc.write_frames(layout, banco)
    s2 = nc.write_frames(layout, banco)
    assert s2["escritas"] == 0
    assert s2["saltadas"] == s1["escritas"]


# ─────────────────────────────────────────
# write_memories
# ─────────────────────────────────────────

def test_write_memories_replica_path_literal(tmp_path):
    """D4: los 71 memory_files conservan su jerarquia (/areas /people
    /projects /topics /profile.md). Aplanar destruiria la organizacion
    que Claude ha inventado, que es informacion en si misma."""
    layout = _crear_layout(tmp_path, con_memories={
        "account_uuid": "usr-1",
        "conversations_memory": "",
        "project_memories": {},
        "memory_files": [
            {"path": "/profile.md", "content": "perfil general",
             "updated_at": "2026-01-01T00:00:00+00:00"},
            {"path": "/areas/foo.md", "content": "area foo",
             "updated_at": "2026-01-01T00:00:00+00:00"},
            {"path": "/projects/uuid-x/index.md", "content": "index del proyecto",
             "updated_at": "2026-01-01T00:00:00+00:00"},
        ],
    })
    mem = tmp_path / "Claude_Mem"
    stats = nc.write_memories(layout, mem)
    assert stats["memory_files"] == 3
    assert (mem / "profile.md").read_text(encoding="utf-8") == "perfil general"
    assert (mem / "areas" / "foo.md").read_text(encoding="utf-8") == "area foo"
    assert (mem / "projects" / "uuid-x" / "index.md").read_text(encoding="utf-8") == "index del proyecto"


def test_write_memories_dossier_personal_va_a_conversations_md(tmp_path):
    """conversations_memory es el dossier personal largo (~6.7 KB en el
    export real). Se aisla en su propio fichero para poder verlo/
    editarlo sin diluirlo en profile.md."""
    layout = _crear_layout(tmp_path, con_memories={
        "account_uuid": "usr-1",
        "conversations_memory": "**Work context**\n\nV0ra works...",
        "project_memories": {},
        "memory_files": [],
    })
    mem = tmp_path / "Claude_Mem"
    stats = nc.write_memories(layout, mem)
    assert stats["secciones"] >= 1
    text = (mem / "conversations.md").read_text(encoding="utf-8")
    assert "Work context" in text
    assert "V0ra works" in text
    assert 'account_uuid: "usr-1"' in text  # frontmatter con la identidad


def test_write_memories_project_memories_va_a_summary_agregado(tmp_path):
    """project_memories es dict {uuid: resumen textual}. Se junta en un
    unico project_summaries.md para escanear la vista de conjunto sin
    saltar entre 20 ficheros."""
    layout = _crear_layout(tmp_path, con_memories={
        "account_uuid": "usr-1",
        "conversations_memory": "",
        "project_memories": {
            "uuid-alpha": "Contexto del proyecto alfa",
            "uuid-beta": "Contexto del proyecto beta",
        },
        "memory_files": [],
    })
    mem = tmp_path / "Claude_Mem"
    stats = nc.write_memories(layout, mem)
    text = (mem / "project_summaries.md").read_text(encoding="utf-8")
    assert "uuid-alpha" in text and "Contexto del proyecto alfa" in text
    assert "uuid-beta" in text and "Contexto del proyecto beta" in text


def test_write_memories_defiende_de_path_traversal(tmp_path):
    """Un path malicioso con '..' no puede escribir fuera de
    claude_mem_dir. El export real no lo hace, pero el guard es
    barato y evita convertirse en un vector de escritura arbitraria."""
    layout = _crear_layout(tmp_path, con_memories={
        "account_uuid": "usr-1",
        "conversations_memory": "",
        "project_memories": {},
        "memory_files": [
            {"path": "/../../fuera.md", "content": "no debería crearse",
             "updated_at": "2026-01-01T00:00:00+00:00"},
        ],
    })
    mem = tmp_path / "Claude_Mem"
    nc.write_memories(layout, mem)
    # Fuera del Claude_Mem no aparece nada
    assert not (tmp_path.parent / "fuera.md").exists()
    assert not (tmp_path / "fuera.md").exists()


def test_write_memories_es_idempotente(tmp_path):
    layout = _crear_layout(tmp_path, con_memories={
        "account_uuid": "usr-1",
        "conversations_memory": "dossier",
        "project_memories": {"u1": "resumen"},
        "memory_files": [
            {"path": "/areas/a.md", "content": "x",
             "updated_at": "2026-01-01T00:00:00+00:00"},
        ],
    })
    mem = tmp_path / "Claude_Mem"
    s1 = nc.write_memories(layout, mem)
    s2 = nc.write_memories(layout, mem)
    assert s1["escritas"] > 0
    assert s2["escritas"] == 0


def test_parse_memories_devuelve_none_sin_layout_de_memories(tmp_path):
    layout = _crear_layout(tmp_path)  # sin memories
    assert nc.parse_memories(layout) is None


# ─────────────────────────────────────────
# Orquestador
# ─────────────────────────────────────────

def test_ingest_extras_lanza_los_tres_writers(tmp_path):
    """El orquestador tiene que llamar a los tres y devolver stats
    agregadas. Se comprueba que las tres carpetas de destino existen
    despues de la ejecucion."""
    layout = _crear_layout(
        tmp_path,
        con_projects=[_proyecto_minimo(uuid="pu", name="P")],
        con_memories={"account_uuid": "u", "conversations_memory": "d",
                      "project_memories": {}, "memory_files": []},
        con_frames=[{"id": "af", "kind": "artifact", "visibility": "private",
                     "owner_account": "u", "active_version": "v",
                     "updated_at": "2026-01-01T00:00:00+00:00",
                     "versions": [{"id": "v", "title": "t", "description": "",
                                   "created_at": "2026-01-01T00:00:00+00:00"}],
                     "_versions_html": {"v": "<html/>"}}],
    )
    base = tmp_path / "vault"
    stats = nc.ingest_extras(layout, base)
    assert stats["projects"]["proyectos"] == 1
    assert stats["memories"]["secciones"] >= 1
    assert stats["frames"]["frames"] == 1
    assert (base / "PRJ_VAULT" / "P" / "00_proyecto.md").exists()
    assert (base / "Claude_Mem" / "conversations.md").exists()
    assert (base / "MERGED_VAULT" / "CLAUDE_WEB" / "FRAMES" / "af" / "00_frame.md").exists()


def test_ingest_extras_admite_layout_parcial(tmp_path):
    """Si el layout solo trae conversations, los otros writers no
    encuentran nada y devuelven stats en cero -- sin explotar."""
    layout = _crear_layout(tmp_path)  # solo conversations
    base = tmp_path / "vault"
    stats = nc.ingest_extras(layout, base)
    assert stats["projects"]["proyectos"] == 0
    assert stats["frames"]["frames"] == 0
    assert stats["memories"]["secciones"] == 0


# ─────────────────────────────────────────
# Prueba contra el export REAL de V0ra
# ─────────────────────────────────────────

_BCK = Path(__file__).resolve().parent.parent / "bck" / "NewClaude"


@pytest.mark.skipif(not _BCK.is_dir(), reason="bck/NewClaude/ no disponible")
def test_ingest_extras_contra_export_real(tmp_path):
    """La prueba de la disciplina del skill: contra el export real de
    V0ra, no contra sinteticos. Se ingesta a un vault de prueba en
    tmp_path para no contaminar el suyo. Se verifican los conteos
    minimos que el export debe producir (24 proyectos, 10 frames,
    71 memory_files)."""
    base = tmp_path / "vault"
    stats = nc.ingest_extras(_BCK, base)
    assert stats["projects"]["proyectos"] == 24
    assert stats["frames"]["frames"] == 10
    assert stats["frames"]["versiones"] == 118  # medido antes contra el zip
    assert stats["memories"]["memory_files"] == 71
    # conversations_memory (dossier), project_memories (agregado)
    assert stats["memories"]["secciones"] == 2
    # 18 UUIDs distintos bajo /projects/ en el export real (medido:
    # distribucion desigual, 2-4 ficheros por UUID; algunos proyectos
    # aparecen en projects/*.json pero sin memoria en memory_files).
    algun_proj = list((base / "Claude_Mem" / "projects").iterdir())
    assert len(algun_proj) == 18
    assert (base / "Claude_Mem" / "conversations.md").exists()
    assert (base / "Claude_Mem" / "profile.md").exists()  # esta en la raiz de memory_files
