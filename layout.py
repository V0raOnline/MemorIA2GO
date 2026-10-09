# -*- coding: utf-8 -*-
"""
layout.py — Unica fuente de los nombres de carpeta del vault.

Hasta aqui los nombres (RAW_VAULT, MERGED_VAULT, CHATGPT/GENERADAS...) estaban
escritos a mano en unos quince ficheros, y cambiar uno era una busqueda a ciegas.
Ahora viven en UNA tabla de datos: identificador logico -> ruta relativa a
base_vault. Y es una tabla, no un conjunto de funciones, a proposito: una tabla
se puede recorrer y comparar con otra, que es lo que necesita migrar un vault
existente de un layout a otro (restar dos tablas da la lista de renombrados y el
mapa de prefijos para relink_assets). Con funciones sueltas no se puede.

Dos reglas de uso:

  * Nadie escribe "MERGED_VAULT" ni "CHATGPT/GENERADAS" fuera de este modulo.
    tests/test_sin_nombres_a_mano.py lo vigila.
  * Las rutas que acaban DENTRO de las notas (los enlaces a assets) salen de
    `enlace()`, no de `ruta()`. Es la misma ruta pero relativa a base_vault y con
    barras `/`, que es como Obsidian la resuelve.

De donde sale el layout activo (`cargar`), por orden:
  1. variable de entorno M3M0RIA_LAYOUT (JSON): la pone el orquestador a los
     procesos hijos para que todos usen exactamente el mismo;
  2. el marcador `.m3m0ria_layout.json` en la raiz de base_vault: el layout con
     el que SE CONSTRUYO ese vault;
  3. el layout clasico, que es el de siempre.

El marcador es lo que permite saber, al migrar, cual es el layout "viejo" sin
adivinarlo mirando que carpetas existen.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

MARCADOR = ".m3m0ria_layout.json"
ENV_LAYOUT = "M3M0RIA_LAYOUT"
VERSION_MARCADOR = 1

# Identificador logico -> ruta relativa a base_vault (barras `/`).
# `{otra.clave}` se sustituye por el valor de esa otra clave: asi renombrar
# MERGED_VAULT arrastra a CLAUDE_WEB, CLAUDE_CODE y _Temas, que cuelgan de el.
#
# `conversaciones` es la UNICA clave relativa al vault (RAW/MERGED) y no a
# base_vault: es la subcarpeta donde viven las notas dentro de cada uno.
TABLA_CLASICA: Dict[str, str] = {
    # Los tres vaults del pipeline.
    "raw": "RAW_VAULT",
    "merged": "MERGED_VAULT",
    "prj": "PRJ_VAULT",
    "conversaciones": "Conversaciones",

    # Bancos de assets, uno por proveedor y tipo (hermanos de los vaults).
    "chatgpt.raiz": "CHATGPT",
    "chatgpt.generadas": "{chatgpt.raiz}/GENERADAS",
    "chatgpt.adjuntos": "{chatgpt.raiz}/ADJUNTOS",
    "chatgpt.web": "{chatgpt.raiz}/WEB",
    "chatgpt.pendientes": "{chatgpt.raiz}/_pendientes_descarga.json",

    "grok.raiz": "GROK",
    "grok.adjuntos": "{grok.raiz}/ADJUNTOS",
    "grok.generadas_imagen": "{grok.raiz}/GENERADAS_IMAGEN",
    "grok.generadas_video": "{grok.raiz}/GENERADAS_VIDEO",
    "grok.imagine": "{grok.raiz}/IMAGINE",
    "grok.pendientes": "{grok.raiz}/_pendientes_descarga.json",

    "claude.raiz": "CLAUDE",
    "claude.artefactos": "{claude.raiz}/ARTEFACTOS",
    "claude.memorias": "Claude_Mem",

    # Cuelgan de MERGED_VAULT.
    "claude.web_frames": "{merged}/CLAUDE_WEB/FRAMES",
    "sesiones.claude_code": "{merged}/CLAUDE_CODE/SESIONES",
    "sesiones.codex": "{merged}/CODEX/SESIONES",
    "temas": "{merged}/_Temas",
}

_REF = re.compile(r"\{([a-z_.]+)\}")


class LayoutError(ValueError):
    """La tabla de nombres no es valida (ruta absoluta, '..', duplicados...)."""


class Layout:
    def __init__(self, nombres: Optional[Dict[str, str]] = None, preset: str = "clasico"):
        base = dict(TABLA_CLASICA)
        if nombres:
            desconocidas = sorted(set(nombres) - set(base))
            if desconocidas:
                raise LayoutError(f"claves de layout desconocidas: {', '.join(desconocidas)}")
            base.update(nombres)
        self.preset = preset
        self._plantillas = base
        self._resueltas = {k: self._resolver(k, ()) for k in base}

    def _resolver(self, clave: str, pila: tuple) -> str:
        if clave in pila:
            raise LayoutError(f"referencia circular en el layout: {' -> '.join(pila + (clave,))}")

        def sub(m: "re.Match[str]") -> str:
            otra = m.group(1)
            if otra not in self._plantillas:
                raise LayoutError(f"'{clave}' referencia una clave que no existe: {{{otra}}}")
            return self._resolver(otra, pila + (clave,))

        return _REF.sub(sub, self._plantillas[clave])

    # ---- consulta -------------------------------------------------------
    def claves(self) -> List[str]:
        return list(self._resueltas)

    def rel(self, clave: str) -> str:
        """Ruta relativa a base_vault, con `/`. Es la que va dentro de los enlaces."""
        try:
            return self._resueltas[clave]
        except KeyError:
            raise KeyError(f"clave de layout inexistente: {clave!r}") from None

    def relativa(self, clave: str, desde: str) -> str:
        """`clave` relativa a la carpeta de `desde` (p.ej. el banco dentro de la
        raiz de su proveedor). Para las herramientas que reciben la carpeta del
        proveedor y no base_vault. Falla si `clave` no cuelga de `desde`."""
        total, base = self.rel(clave), self.rel(desde)
        if not total.lower().startswith(base.lower() + "/"):
            raise LayoutError(f"'{clave}' ({total}) no cuelga de '{desde}' ({base})")
        return total[len(base) + 1:]

    def ruta(self, base_vault, clave: str) -> Path:
        """Ruta absoluta en disco de `clave` bajo base_vault."""
        return Path(base_vault).joinpath(*self.rel(clave).split("/"))

    def enlace(self, clave: str, fichero: str = "") -> str:
        """Ruta tal como aparece en un enlace de nota: `CHATGPT/GENERADAS/x.png`."""
        return f"{self.rel(clave)}/{fichero}" if fichero else self.rel(clave)

    # ---- serializacion --------------------------------------------------
    def a_dict(self) -> Dict[str, str]:
        """Tabla ya resuelta (sin `{}`): lo que se guarda en el marcador."""
        return dict(self._resueltas)

    @classmethod
    def desde_dict(cls, nombres: Dict[str, str], preset: str = "clasico") -> "Layout":
        return cls(nombres, preset=preset)

    # ---- validacion -----------------------------------------------------
    def problemas(self) -> List[str]:
        """Lista legible de por que este layout no se puede usar. Vacia = valido."""
        malos: List[str] = []
        vistos: Dict[str, str] = {}
        for k, v in self._resueltas.items():
            if not v or v.strip() != v:
                malos.append(f"'{k}': nombre vacio o con espacios en los extremos")
                continue
            if os.path.isabs(v) or re.match(r"^[A-Za-z]:", v) or v.startswith(("/", "\\")):
                malos.append(f"'{k}': debe ser relativo a base_vault, no absoluto ({v})")
            if "\\" in v:
                malos.append(f"'{k}': usa '/' como separador, no '\\' ({v})")
            if any(p in ("", ".", "..") for p in v.split("/")):
                malos.append(f"'{k}': no puede contener '..', '.' ni tramos vacios ({v})")
            if re.search(r'[<>:"|?*]', v):
                malos.append(f"'{k}': caracteres no validos en Windows ({v})")
            # Windows no distingue mayusculas: dos claves que difieren solo en
            # eso serian la misma carpeta.
            if k != "conversaciones":
                previa = vistos.get(v.lower())
                if previa is not None:
                    malos.append(f"'{k}' y '{previa}' apuntan a la misma carpeta ({v})")
                vistos[v.lower()] = k
        return malos

    def validar(self) -> "Layout":
        malos = self.problemas()
        if malos:
            raise LayoutError("layout no valido:\n  - " + "\n  - ".join(malos))
        return self

    def __eq__(self, otro) -> bool:
        return isinstance(otro, Layout) and self._resueltas == otro._resueltas

    def __repr__(self) -> str:
        return f"Layout(preset={self.preset!r}, {len(self._resueltas)} claves)"


CLASICO = Layout()


# ---- marcador en el vault ------------------------------------------------
def leer_marcador(base_vault) -> Optional[Layout]:
    """El layout con el que se construyo ese vault, o None si no hay marcador
    (vaults anteriores a esta version: son, por definicion, el clasico)."""
    p = Path(base_vault) / MARCADOR
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
        return Layout.desde_dict(datos["nombres"], preset=datos.get("preset", "clasico"))
    except (OSError, ValueError, KeyError):
        return None


def escribir_marcador(base_vault, layout: Layout) -> Path:
    """Escritura atomica (.part + replace): un corte a mitad no deja un marcador
    corrupto que haga creer al siguiente arranque que el vault es de otro layout."""
    p = Path(base_vault) / MARCADOR
    parcial = p.with_name(p.name + ".part")
    cuerpo = {"version": VERSION_MARCADOR, "preset": layout.preset, "nombres": layout.a_dict()}
    parcial.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(parcial, p)
    return p


# ---- layout activo -------------------------------------------------------
def cargar(base_vault=None, prj_vault_name: Optional[str] = None,
           usar_entorno: bool = True) -> Layout:
    """Layout activo: entorno > marcador del vault > clasico.

    `usar_entorno=False` ignora la variable de entorno: lo necesita quien LA
    ESTABLECE (el launcher, en cada peticion). Si leyera su propio entorno de
    la peticion anterior, un layout cambiado en disco no se enteraria nunca.

    `prj_vault_name` es la opcion `options.prj_vault_name` de la config, que ya
    existia antes que el layout y se respeta: si viene, manda sobre la clave
    `prj`. Es la unica clave que hoy tiene una opcion propia."""
    layout: Optional[Layout] = None

    crudo = os.environ.get(ENV_LAYOUT) if usar_entorno else None
    if crudo:
        try:
            datos = json.loads(crudo)
            layout = Layout.desde_dict(datos["nombres"], preset=datos.get("preset", "clasico"))
        except (ValueError, KeyError):
            layout = None
    if layout is None and base_vault:
        layout = leer_marcador(base_vault)
    if layout is None:
        layout = CLASICO

    if prj_vault_name and prj_vault_name != layout.rel("prj"):
        nombres = layout.a_dict()
        nombres["prj"] = prj_vault_name
        layout = Layout.desde_dict(nombres, preset=layout.preset)
    return layout


def incoherencias(layout: Layout, pares) -> List[str]:
    """`pares`: (ruta_absoluta_en_disco, clave) de los bancos que un proceso va a
    escribir. Detecta el fallo que no da error: un banco que termina en una
    carpeta distinta de la que el layout escribe en los ENLACES de las notas.
    El proceso escribiria los ficheros en un sitio y apuntaria a otro, y las
    imagenes saldrian rotas en todas las notas sin que nada lo avisara."""
    malos: List[str] = []
    for ruta, clave in pares:
        if not ruta:
            continue
        esperado = layout.rel(clave).lower()
        real = Path(ruta).as_posix().rstrip("/").lower()
        if not (real == esperado or real.endswith("/" + esperado)):
            malos.append(f"{ruta} no termina en '{layout.rel(clave)}' (clave '{clave}'): "
                         "los enlaces de las notas apuntarian a otra carpeta que la escrita")
    return malos


def entorno(layout: Layout) -> Dict[str, str]:
    """Variable de entorno para los procesos hijos, de modo que todos usen el
    mismo layout que decidio el orquestador."""
    return {ENV_LAYOUT: json.dumps({"preset": layout.preset, "nombres": layout.a_dict()},
                                    ensure_ascii=False)}
