# -*- coding: utf-8 -*-
"""Tests de ida y vuelta escritor<->lector del indice de adjuntos.

Motivo: scaffolding_index.py NO parsea el export, parsea el TEXTO QUE
NOSOTROS ESCRIBIMOS en las notas. Eso lo convierte en un par acoplado con
split_chatgpt_export.py y providers/claude_adapter.py: si alguien cambia la
linea que se escribe y no el patron que la lee (o al reves), los adjuntos
desaparecen del indice SIN error, sin excepcion y sin test rojo.

En esta rama el par nunca se ha desemparejado. En release/en si, durante la
traduccion (fase 3a): el patron legado quedo suelto de su escritor y la
suite siguio verde, porque nadie comprobaba el recorrido completo. El test
se escribio alli y aqui no, asi que release/es se quedo con el codigo
expuesto y sin la red -- que es peor sitio donde estar, porque esta es la
edicion que corre a diario.

Estos tests parten de la salida REAL de los renderizadores, no de literales
copiados a mano. Copiar el literal a mano es exactamente lo que hace que un
par desemparejado siga pareciendo correcto: el test y el codigo se equivocan
juntos. Si el formato cambia en un solo lado, aqui se ve.
"""
from pathlib import Path

import scaffolding_index as si
import split_chatgpt_export as sce
from providers import claude_adapter


def _nota(path: Path, cuerpo: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: \"X\"\ndate: 2026-07-01\n---\n\n{cuerpo}\n",
                    encoding="utf-8")


def test_adjunto_de_chatgpt_llega_al_indice(tmp_path):
    """metadata.attachments -> render_attachments -> ATTACHMENT_RE."""
    msg = {"metadata": {"attachments": [
        {"name": "contrato.pdf", "mimeType": "application/pdf", "fileSizeTokens": 1200},
    ]}}
    linea = sce.render_attachments(msg)
    assert linea, "el renderizador no produjo nada -- fixture mal construido"

    _nota(tmp_path / "Conversaciones" / "a.md", linea)
    encontrados = si.scan_vault(tmp_path)

    assert "contrato.pdf" in encontrados


def test_adjunto_de_claude_llega_al_indice(tmp_path):
    """El adaptador de Claude escribe la MISMA linea que ChatGPT: si diverge,
    la mitad de los adjuntos del vault se caen del indice."""
    m = {"attachments": [
        {"file_name": "anexo.docx", "file_type": "docx", "file_size": 4096},
    ]}
    lineas = claude_adapter._render_attachments(m)
    _nota(tmp_path / "Conversaciones" / "b.md", "\n".join(lineas))

    encontrados = si.scan_vault(tmp_path)

    assert "anexo.docx" in encontrados


def test_tether_quote_llega_al_indice(tmp_path):
    """El patron 'legado' NO esta muerto: render_tether_quote lo sigue
    escribiendo hoy. Es el que se desemparejo en la otra rama sin que ningun
    test se pusiera rojo."""
    rendered = sce.render_tether_quote({
        "content_type": "tether_quote",
        "domain": "informe-anual.pdf",
        "text": "Contenido citado del fichero.",
    })
    assert rendered, "render_tether_quote devolvio None -- fixture mal construido"

    _nota(tmp_path / "Conversaciones" / "c.md", rendered)
    encontrados = si.scan_vault(tmp_path)

    assert "informe-anual.pdf" in encontrados


def test_tether_quote_sin_texto_tambien_llega(tmp_path):
    """La rama 'sin contenido' es un literal distinto del caso con texto --
    tiene su propio riesgo de quedarse desemparejada."""
    rendered = sce.render_tether_quote({
        "content_type": "tether_quote",
        "domain": "vacio.txt",
        "text": "",
    })
    _nota(tmp_path / "Conversaciones" / "d.md", rendered)

    assert "vacio.txt" in si.scan_vault(tmp_path)


def test_una_nota_con_ambos_formatos_cuenta_los_dos(tmp_path):
    msg = {"metadata": {"attachments": [{"name": "uno.pdf", "mimeType": "application/pdf"}]}}
    tether = sce.render_tether_quote({
        "content_type": "tether_quote", "domain": "dos.txt", "text": "algo",
    })
    _nota(tmp_path / "Conversaciones" / "e.md",
          sce.render_attachments(msg) + "\n\n" + tether)

    encontrados = si.scan_vault(tmp_path)

    assert {"uno.pdf", "dos.txt"} <= set(encontrados)


def test_el_indice_generado_lista_los_ficheros(tmp_path):
    """Comprobacion de extremo a extremo: del render al markdown final."""
    msg = {"metadata": {"attachments": [{"name": "memoria.pdf", "mimeType": "application/pdf"}]}}
    _nota(tmp_path / "Conversaciones" / "f.md", sce.render_attachments(msg))

    md = si.build_index_text(si.scan_vault(tmp_path))

    assert "memoria.pdf" in md
    assert "_Archivos distintos:_ **1**" in md
