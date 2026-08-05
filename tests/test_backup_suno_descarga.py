# -*- coding: utf-8 -*-
"""Tests de la descarga de backup_suno.py.

Motivo: el bug que diagnostico agnt_music0logy escribiendo el backup de
Flow Music (CONTEXT.md 3l). La version anterior hacia `write_bytes` directo
sobre el destino final, asi que un corte a mitad de escritura dejaba un
fichero TRUNCADO QUE EXISTE. La siguiente pasada solo miraba `.exists()`,
lo daba por bueno, y ese mp3 cortado no se reparaba nunca: el backup se
cree completo y no lo esta.

Es de la familia de fallos que mas veces ha mordido en este proyecto -- no
lanza excepcion, no deja rastro y la suite sigue verde. Por eso estos tests
comprueban el estado del DISCO, no el valor de retorno.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "suno"))

import backup_suno


class _Resp:
    """Respuesta minima al estilo requests: contenido + cabeceras."""

    def __init__(self, content: bytes, content_length=None):
        self.content = content
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}


def _fake_get(resp):
    return lambda session, url, params=None, debug=False: resp


def test_descarga_completa_deja_el_fichero_final(tmp_path, monkeypatch):
    destino = tmp_path / "cancion.mp3"
    monkeypatch.setattr(backup_suno, "get_with_retries", _fake_get(_Resp(b"12345", 5)))

    assert backup_suno._descargar_a_fichero(None, "http://x", destino) is True
    assert destino.read_bytes() == b"12345"
    assert not list(tmp_path.glob("*.part")), "quedo un .part sin limpiar"


def test_descarga_truncada_no_deja_fichero_final(tmp_path, monkeypatch):
    """EL CASO QUE MOTIVA TODO: el servidor dice 5000 bytes y llegan 3.
    Antes esto escribia 3 bytes en cancion.mp3 y la siguiente pasada lo daba
    por descargado. Ahora no debe quedar NADA, para que se reintente."""
    destino = tmp_path / "cancion.mp3"
    monkeypatch.setattr(backup_suno, "get_with_retries", _fake_get(_Resp(b"123", 5000)))

    assert backup_suno._descargar_a_fichero(None, "http://x", destino) is False
    assert not destino.exists(), "quedo un fichero truncado que parecera completo"
    assert not list(tmp_path.glob("*.part")), "quedo un .part huerfano"


def test_una_segunda_pasada_reintenta_lo_truncado(tmp_path, monkeypatch):
    """El efecto real que importa: tras un corte, la siguiente corrida SI
    vuelve a bajarlo. Es lo que el bug rompia."""
    destino = tmp_path / "cancion.mp3"
    monkeypatch.setattr(backup_suno, "get_with_retries", _fake_get(_Resp(b"123", 5000)))
    backup_suno._descargar_a_fichero(None, "http://x", destino)

    monkeypatch.setattr(backup_suno, "get_with_retries", _fake_get(_Resp(b"12345", 5)))
    assert backup_suno._descargar_a_fichero(None, "http://x", destino) is True
    assert destino.read_bytes() == b"12345"


def test_sin_content_length_se_acepta_lo_que_llega(tmp_path, monkeypatch):
    """Si el servidor no manda la cabecera no hay nada que comprobar.
    Inventarse una comprobacion seria peor: rechazaria descargas buenas."""
    destino = tmp_path / "cancion.mp3"
    monkeypatch.setattr(backup_suno, "get_with_retries", _fake_get(_Resp(b"12345")))

    assert backup_suno._descargar_a_fichero(None, "http://x", destino) is True
    assert destino.read_bytes() == b"12345"


def test_content_length_con_basura_no_revienta(tmp_path, monkeypatch):
    destino = tmp_path / "cancion.mp3"
    monkeypatch.setattr(backup_suno, "get_with_retries", _fake_get(_Resp(b"12345", "no-soy-un-numero")))

    assert backup_suno._descargar_a_fichero(None, "http://x", destino) is True
    assert destino.exists()


def test_fichero_ya_existente_no_se_vuelve_a_bajar(tmp_path, monkeypatch):
    """La idempotencia de siempre se conserva: lo ya descargado no se toca."""
    destino = tmp_path / "cancion.mp3"
    destino.write_bytes(b"ya estaba")

    def _no_deberia_llamarse(*a, **kw):
        raise AssertionError("se intento descargar algo que ya estaba en disco")

    monkeypatch.setattr(backup_suno, "get_with_retries", _no_deberia_llamarse)

    assert backup_suno._descargar_a_fichero(None, "http://x", destino) is False
    assert destino.read_bytes() == b"ya estaba"


def test_fallo_de_red_no_deja_rastro(tmp_path, monkeypatch):
    destino = tmp_path / "cancion.mp3"
    monkeypatch.setattr(backup_suno, "get_with_retries",
                        lambda session, url, params=None, debug=False: None)

    assert backup_suno._descargar_a_fichero(None, "http://x", destino) is False
    assert not destino.exists()
    assert not list(tmp_path.glob("*.part"))
