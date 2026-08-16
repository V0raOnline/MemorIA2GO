# -*- coding: utf-8 -*-
"""Escribir dos veces la misma nota no puede crear un fichero más.

BUG REAL, medido en el vault de V0ra el 2026-08-16 tras un
`--reprocess-all`: `RAW_VAULT` paso de 6.053 notas a 12.164. Las copias por
conversacion eran 2, 4, 6, 8... siempre pares. **7.134 ficheros y 936 MB,
todos byte a byte identicos** a la nota que ya existia.

La causa estaba en una linea que parecia defensiva:

    write_path = f"{base}-h{h}{ext}"     # nombre = SHA-1 del contenido
    i = 2
    while os.path.exists(write_path):    # y aqui se destruye
        write_path = f"{base}-h{h}-{i}{ext}"

El nombre YA era la identidad, igual que en los bancos de assets -- que por
eso nunca han duplicado nada: se llaman por hash y si ya estan no se
reescriben. Si ese fichero existe, dentro esta exactamente esto. Pero el
bucle trataba "existe" como conflicto en vez de como "ya esta hecho".

No era un fallo del reproceso: salta en CUALQUIER escritura donde el
contenido coincida con algo ya guardado. De esas 7.134 copias, mil eran
anteriores al reproceso; el reproceso solo lo hizo visible porque coincide
con todas a la vez.

La propiedad que se protege: **escribir dos veces lo mismo tiene que ser
igual que escribirlo una vez.** Ningun test lo comprobaba porque todos
escribian una sola vez.

OJO AL MONTAR EL ESCENARIO -- la primera version de estos tests estaba en
verde y no probaba nada, y lo dijo la mutacion, no la suite. Reescribir la
MISMA nota no llega nunca al bloque del hash: la corta antes la guarda
`skip_identical` de mas arriba, que compara contra el nombre base. Para
pisar el camino del bug hacen falta DOS variantes distintas de la misma
conversacion -- que es lo normal cuando exportas cada pocas semanas -- y
volver a escribir la segunda.
"""
from pathlib import Path

import pytest

import split_chatgpt_export as sce

POLITICA = {"keep_versions": True, "version_scheme": "hash", "skip_identical": True}
MENSAJES = [{"role": "user", "content": "Hola"}, {"role": "assistant", "content": "Qué tal"}]


def _escribir(salida: Path, mensajes=None, titulo="Una conversación") -> str:
    ruta, _ = sce.write_md(str(salida), titulo, "2025-06-15",
                           mensajes if mensajes is not None else MENSAJES,
                           tags=[], existing_policy=POLITICA)
    return ruta


def _ficheros(salida: Path) -> list:
    return sorted(p.relative_to(salida).as_posix() for p in salida.rglob("*.md"))


OTRA = [{"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Qué tal, y aquí bastante más texto"}]


def test_reescribir_una_variante_ya_guardada_no_crea_nada(tmp_path):
    """EL BUG, con el escenario que de verdad lo dispara: dos exports con la
    misma conversación en distinto momento, y luego un reproceso."""
    salida = tmp_path / "RAW"
    _escribir(salida)                       # export de junio
    _escribir(salida, mensajes=OTRA)        # export de julio, ya tiene más texto
    antes = _ficheros(salida)
    assert len(antes) == 2, f"el escenario no quedó montado: {antes}"

    _escribir(salida, mensajes=OTRA)        # reproceso: vuelve a ver la de julio

    assert _ficheros(salida) == antes,         f"sobra(n): {sorted(set(_ficheros(salida)) - set(antes))}"


def test_escribir_lo_mismo_dos_veces_no_crea_nada_nuevo(tmp_path):
    """El camino corto, el que corta `skip_identical`. Vale como red, pero
    NO prueba el arreglo: por sí solo pasaba también con el bug dentro."""
    salida = tmp_path / "RAW"

    _escribir(salida)
    primera = _ficheros(salida)
    _escribir(salida)
    segunda = _ficheros(salida)

    assert primera, "la primera escritura no dejó nada -- fixture mal montado"
    assert segunda == primera, f"sobra(n): {sorted(set(segunda) - set(primera))}"


def test_ni_a_la_tercera_ni_a_la_septima(tmp_path):
    """Doblaba en CADA pasada -- en el vault real había hasta ocho copias de
    la misma conversación. Una sola repetición no basta como red."""
    salida = tmp_path / "RAW"
    _escribir(salida)
    _escribir(salida, mensajes=OTRA)
    esperado = _ficheros(salida)

    for vuelta in range(2, 8):
        _escribir(salida, mensajes=OTRA)
        assert _ficheros(salida) == esperado, \
            f"creció en la pasada {vuelta}: {len(_ficheros(salida))} ficheros"


def test_devuelve_la_ruta_de_la_nota_que_ya_estaba(tmp_path):
    """Quien llama usa esa ruta para el manifiesto y los índices. Si al
    saltar devolviera otra cosa, los índices apuntarían a un fichero que no
    existe -- que es el fallo de la familia contraria."""
    salida = tmp_path / "RAW"

    _escribir(salida)
    primera = _escribir(salida, mensajes=OTRA)
    segunda = _escribir(salida, mensajes=OTRA)

    assert segunda == primera
    assert Path(segunda).exists()
    assert "-h" in Path(primera).name, "el escenario tiene que llegar al nombre por hash"


def test_una_variante_con_contenido_DISTINTO_se_conserva_aparte(tmp_path):
    """La otra mitad del contrato, y la razón de que el versionado exista:
    si el contenido cambió de verdad, la variante nueva NO puede pisar a la
    vieja. De eso vive el paso de fusión, que recupera mensajes que a una le
    faltan y a la otra no."""
    salida = tmp_path / "RAW"
    _escribir(salida)
    antes = _ficheros(salida)

    _escribir(salida, mensajes=[{"role": "user", "content": "Hola"},
                                {"role": "assistant", "content": "Qué tal, y algo más"}])

    assert len(_ficheros(salida)) == len(antes) + 1, \
        "una variante distinta tiene que guardarse aparte, y se perdió"


def test_el_ayudante_compara_contenido_y_no_nombres(tmp_path):
    """La comprobación se hace leyendo el fichero, no deduciéndolo del
    nombre. Es la lección de la semana: que el nombre cuadre no es que el
    contenido cuadre."""
    f = tmp_path / "nota.md"
    f.write_text("hola\n", encoding="utf-8")

    assert sce.contenido_identico(str(f), "hola")
    assert sce.contenido_identico(str(f), "  hola  \n")
    assert not sce.contenido_identico(str(f), "adiós")
    assert not sce.contenido_identico(str(tmp_path / "no_existe.md"), "hola")
