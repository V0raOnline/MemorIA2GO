#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pendientes.py — Identidad de un pendiente de descarga, separada de su llave.

POR QUE EXISTE (2026-08-30)
───────────────────────────
Un pendiente necesita dos cosas que hasta hoy eran el mismo dato: saber CUAL
es, para no duplicarlo en cada reproceso, y poder ABRIRLO, para descargarlo.

Mientras fueran el mismo dato, la lista de pendientes era una lista de llaves:
algunos proveedores publican el contenido generado en URLs que no piden
autenticacion, asi que quien tuviera el fichero tenia el contenido. Y como la
credencial era la clave primaria, triar no reducia la exposicion -- rescatar o
descartar dejaba la llave dentro para siempre. La lista solo podia crecer.

Aqui se separan. La identidad pasa a ser `ref`, un hash de la credencial: de
una sola direccion, asi que sirve para comparar y no sirve para abrir nada. Se
recalcula del export en cada pase, de modo que la idempotencia se mantiene
igual de bien -- se comparan hashes en vez de credenciales.

LA REGLA
────────
- SIN TRIAR conserva su credencial. Tiene que ser pulsable: es su razon de
  existir, y quitarsela romperia la descarga manual.
- TRIADA (rescatada o descartada) la pierde. Queda `ref` con los metadatos
  descriptivos, que es todo lo que el pipeline necesita para reconocerla y
  para pintar lo que le toque en la nota.

OJO CON GROK: la credencial no es solo `link`. El `id` del post basta para
construir la ruta al fichero, comprobado sobre 209 casos reales. Guardar el
hash del enlace y conservar el `id` no protegeria nada -- y daria sensacion de
arreglado, que es peor. Por eso se van los dos.

Este modulo no importa nada del proyecto a proposito: lo usan
`split_chatgpt_export`, `launcher`, `chatgpt_markers` y `rescue_pending`, y
cualquier dependencia haria un ciclo.
"""

import hashlib
from typing import Dict, List, Optional

# Que campos abren algo, por proveedor. El PRIMERO es la credencial de
# referencia: la que se hashea para obtener `ref`. Tiene que ser un campo que
# el export traiga siempre, o el hash de un export y el de un fichero guardado
# no coincidirian.
CAMPOS_CREDENCIAL: Dict[str, tuple] = {
    "grok": ("id", "link"),
    "chatgpt": ("url",),
}


def ref_pendiente(credencial: Optional[str]) -> str:
    """Identidad derivada de la credencial. 16 hex de sha256: de sobra para no
    colisionar en listas de miles, y no reversible."""
    return hashlib.sha256((credencial or "").strip().encode("utf-8")).hexdigest()[:16]


def ref_de_entrada(entrada: dict, proveedor: str) -> Optional[str]:
    """El `ref` de una entrada, calculandolo si aun no lo tiene (ficheros
    escritos antes de este cambio). None si no hay ni ref ni credencial."""
    if entrada.get("ref"):
        return entrada["ref"]
    campo = CAMPOS_CREDENCIAL[proveedor][0]
    valor = entrada.get(campo)
    return ref_pendiente(valor) if valor else None


def olvidar_credencial(entrada: dict, proveedor: str) -> dict:
    """Quita de una entrada todo lo que abre algo, dejandole su `ref`.
    Idempotente: sobre una entrada ya limpia no hace nada."""
    r = ref_de_entrada(entrada, proveedor)
    if r:
        entrada["ref"] = r
    for campo in CAMPOS_CREDENCIAL[proveedor]:
        entrada.pop(campo, None)
    return entrada


def esta_sin_triar(entrada: dict) -> bool:
    """Sin `estado` = sin triar, para no romper ficheros ya existentes."""
    return (entrada.get("estado") or "sin_triar") == "sin_triar"


def sanear(pendientes: List[dict], proveedor: str) -> int:
    """Asegura `ref` en todas y limpia la credencial de las ya triadas.
    Devuelve cuantas se limpiaron.

    Es la migracion, y se ejecuta sola: cualquier escritura del fichero pasa
    por aqui, asi que un vault viejo queda limpio en el primer reproceso sin
    que nadie tenga que acordarse de lanzar nada.
    """
    limpiadas = 0
    for p in pendientes:
        if not isinstance(p, dict):
            continue
        r = ref_de_entrada(p, proveedor)
        if r and not p.get("ref"):
            p["ref"] = r
        if not esta_sin_triar(p):
            if any(c in p for c in CAMPOS_CREDENCIAL[proveedor]):
                olvidar_credencial(p, proveedor)
                limpiadas += 1
    return limpiadas


def cuenta_credenciales(pendientes: List[dict], proveedor: str) -> int:
    """Cuantas entradas guardan todavia algo que abre. Para poder decir en voz
    alta cuanto queda expuesto, antes y despues."""
    campos = CAMPOS_CREDENCIAL[proveedor]
    return sum(1 for p in pendientes
               if isinstance(p, dict) and any(p.get(c) for c in campos))
