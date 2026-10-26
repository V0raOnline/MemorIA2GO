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

El RAW puede vivir FUERA de base_vault (`externas`): es la fuente del pipeline,
no algo pensado para recorrerse, y no tiene por que aparecer al abrir el vault en
Obsidian. Es la unica clave que admite una ruta absoluta propia.

De donde sale el layout activo (`cargar`), por orden:
  1. variable de entorno M3M0RIA_LAYOUT (JSON): la pone el orquestador a los
     procesos hijos para que todos usen exactamente el mismo;
  2. el marcador `.m3m0ria_layout.json` en la raiz de base_vault: el layout con
     el que SE CONSTRUYO ese vault;
  3. el layout clasico, que es el de siempre (mas el RAW externo que pida la
     config, si el vault aun no tiene marcador).

El marcador es lo que permite saber, al migrar, cual es el layout "viejo" sin
adivinarlo mirando que carpetas existen. Y `conflictos` lo usa para negarse a
seguir si la config pide un RAW distinto del que el vault ya tiene: seguir
escribiria las notas nuevas en un sitio y el merge no veria las anteriores,
sin ningun error.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

MARCADOR = ".m3m0ria_layout.json"
ENV_LAYOUT = "M3M0RIA_LAYOUT"
VERSION_MARCADOR = 3   # v3: anade `particion` y `proyectos`; v2: `externas`. Los anteriores se leen igual.

# Claves que pueden vivir FUERA de base_vault, en una ruta absoluta propia.
EXTERNABLES = ("raw",)

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
    # Miniaturas que algunos vaults ya traen junto a GENERADAS: la galeria parte de ellas si estan.
    "chatgpt.generadas_miniaturas": "{chatgpt.raiz}/GENERADAS_Thmbnails",

    "grok.raiz": "GROK",
    "grok.adjuntos": "{grok.raiz}/ADJUNTOS",
    "grok.generadas_imagen": "{grok.raiz}/GENERADAS_IMAGEN",
    "grok.generadas_video": "{grok.raiz}/GENERADAS_VIDEO",
    "grok.imagine": "{grok.raiz}/IMAGINE",
    "grok.pendientes": "{grok.raiz}/_pendientes_descarga.json",

    "claude.raiz": "CLAUDE",
    "claude.artefactos": "{claude.raiz}/ARTEFACTOS",
    "claude.memorias": "Claude_Mem",

    # El vault de imagenes de Copilot que construye image.ia, si la config no lo pone en otro sitio
    # (`paths.copilot_images_vault`).
    "copilot.raiz": "COPILOT",
    "copilot.generadas_imagen": "{copilot.raiz}/GENERADAS_IMAGEN",

    # Cuelgan de MERGED_VAULT.
    "claude.web_raiz": "{merged}/CLAUDE_WEB",
    "claude.web_frames": "{claude.web_raiz}/FRAMES",
    # Donde se escriben los proyectos del export de Claude (su definicion y sus docs).
    # Con vault de proyectos, dentro de el, como siempre; sin el, junto a FRAMES.
    "claude.proyectos": "{prj}",
    "sesiones.claude_code": "{merged}/CLAUDE_CODE/SESIONES",
    "sesiones.codex": "{merged}/CODEX/SESIONES",
    "temas": "{merged}/_Temas",
}

# ---- presets --------------------------------------------------------------
# Dos interruptores independientes sobre el mismo vault principal; un preset es
# solo una combinacion con nombre:
#
#   particion  "unico":     todas las conversaciones fusionadas en MERGED/Conversaciones
#              "proveedor": una carpeta por proveedor dentro de MERGED
#                           (MERGED/ChatGPT/Conversaciones, MERGED/Claude/...)
#   proyectos  True:        ademas, PRJ_VAULT con una carpeta por proyecto
#
# La particion solo afecta a MERGED. El RAW es la fuente y no se parte nunca, y
# `_Temas` es transversal a proposito: un tema cruza proveedores.
PARTICIONES = ("unico", "proveedor")
PRESETS: Dict[str, tuple] = {            # nombre -> (particion, proyectos)
    "unico": ("unico", False),
    "proveedor": ("proveedor", False),
    "proyectos": ("unico", True),
}
# Lo que la aplicacion hacia antes de que existieran los presets: MERGED mezclado
# y PRJ_VAULT siempre. Un vault sin marcador, o con uno de antes, es este.
PRESET_DEFECTO = "proyectos"
_ALIAS_PRESET = {"clasico": PRESET_DEFECTO}

# Lo que cambia de la tabla al partir MERGED por proveedor: lo que cuelga de un
# proveedor concreto pasa a vivir dentro de su carpeta.
NOMBRES_PROVEEDOR: Dict[str, str] = {
    "claude.web_raiz": "{merged}/Claude/CLAUDE_WEB",
    "sesiones.claude_code": "{merged}/Claude/CLAUDE_CODE/SESIONES",
    "sesiones.codex": "{merged}/ChatGPT/CODEX/SESIONES",
}

# Y al apagar el vault de proyectos: los proyectos de Claude no se pueden perder ni
# escribir en un vault que no existe, asi que pasan a MERGED, al lado de FRAMES.
NOMBRES_SIN_PROYECTOS: Dict[str, str] = {
    "claude.proyectos": "{claude.web_raiz}/PROYECTOS",
}


def _cierre_de_interruptor() -> frozenset:
    """Las claves que fijan los interruptores y todas las que cuelgan de ellas
    (`claude.web_frames` cuelga de `claude.web_raiz`). Importa porque el marcador
    guarda la tabla YA RESUELTA: al cambiar un interruptor hay que soltar tambien
    las derivadas, o se quedan con la ruta del preset anterior."""
    claves = set(NOMBRES_PROVEEDOR) | set(NOMBRES_SIN_PROYECTOS)
    cambio = True
    while cambio:
        cambio = False
        for k, plantilla in TABLA_CLASICA.items():
            if k not in claves and any(r in claves for r in _REF.findall(plantilla)):
                claves.add(k)
                cambio = True
    return frozenset(claves)

# Valor del campo `provider` de una nota -> carpeta del proveedor. Las sesiones de
# Claude Code cuelgan de Claude y las de Codex de ChatGPT (es de OpenAI). Un
# proveedor que no este aqui no se pierde: se le hace una carpeta con su nombre.
PROVEEDOR_CARPETA = {
    "chatgpt": "ChatGPT", "claude": "Claude", "claude-code": "Claude",
    "grok": "Grok", "copilot": "Copilot", "codex": "ChatGPT",
}

_REF = re.compile(r"\{([a-z_.]+)\}")

# Las claves que fijan los interruptores y sus derivadas (no las elige quien edita la tabla).
CLAVES_DE_INTERRUPTOR = _cierre_de_interruptor()

# Nombres que Windows reserva para dispositivos, con o sin extension ("NUL.txt"
# tambien lo es). Crear una carpeta asi falla, o peor, no hace lo que parece.
_RESERVADOS_WINDOWS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)})


class LayoutError(ValueError):
    """La tabla de nombres no es valida (ruta absoluta, '..', duplicados...)."""


def norm(ruta) -> str:
    """Forma comparable de una ruta: absoluta, normalizada y, en Windows, sin
    distinguir mayusculas. No toca el disco (la ruta puede no existir aun)."""
    return os.path.normcase(os.path.normpath(os.path.abspath(str(ruta))))


def dentro(hijo: str, padre: str) -> bool:
    """`hijo` y `padre` ya normalizados con norm."""
    return hijo == padre or hijo.startswith(padre.rstrip(os.sep) + os.sep)


def normalizar_preset(preset: Optional[str]) -> str:
    """Nombre de preset valido (acepta el alias antiguo 'clasico'). Vacio = el de siempre."""
    p = (preset or "").strip().lower() or PRESET_DEFECTO
    p = _ALIAS_PRESET.get(p, p)
    if p not in PRESETS:
        raise LayoutError(f"preset desconocido: '{preset}' (los hay: {', '.join(PRESETS)})")
    return p


def carpeta_proveedor(proveedor: Optional[str]) -> str:
    """Carpeta de un proveedor dentro de un MERGED partido. Una nota sin `provider`
    es de ChatGPT, por definicion: el campo nacio con los adaptadores."""
    clave = (proveedor or "").strip().strip('"').lower() or "chatgpt"
    if clave in PROVEEDOR_CARPETA:
        return PROVEEDOR_CARPETA[clave]
    limpio = re.sub(r"[^\w .-]", "", clave).strip(" .").title() or "Otros"
    return f"_{limpio}" if limpio.split(".")[0].upper() in _RESERVADOS_WINDOWS else limpio


class Layout:
    def __init__(self, nombres: Optional[Dict[str, str]] = None, preset: str = PRESET_DEFECTO,
                 externas: Optional[Dict[str, str]] = None,
                 particion: Optional[str] = None, proyectos: Optional[bool] = None):
        preset = _ALIAS_PRESET.get(preset, preset)
        # Un preset con nombre fija los dos interruptores; una etiqueta cualquiera
        # ("mio", "de-prueba") no fija nada y se queda en lo de siempre.
        part_preset, proy_preset = PRESETS.get(preset, PRESETS[PRESET_DEFECTO])
        self.particion = particion if particion is not None else part_preset
        self.proyectos = bool(proy_preset if proyectos is None else proyectos)
        if self.particion not in PARTICIONES:
            raise LayoutError(f"particion desconocida: '{self.particion}' (las hay: {', '.join(PARTICIONES)})")
        base = dict(TABLA_CLASICA)
        if self.particion == "proveedor":
            base.update(NOMBRES_PROVEEDOR)
        if not self.proyectos:
            base.update(NOMBRES_SIN_PROYECTOS)
        if nombres:
            desconocidas = sorted(set(nombres) - set(base))
            if desconocidas:
                raise LayoutError(f"claves de layout desconocidas: {', '.join(desconocidas)}")
            base.update(nombres)
        self.preset = preset
        self._plantillas = base
        self._resueltas = {k: self._resolver(k, ()) for k in base}

        self.externas: Dict[str, str] = {}
        for k, v in (externas or {}).items():
            if k not in EXTERNABLES:
                raise LayoutError(f"'{k}' no puede vivir fuera de base_vault "
                                  f"(solo: {', '.join(EXTERNABLES)})")
            if v:
                self.externas[k] = str(v)

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
        """Ruta relativa a base_vault, con `/`. Es la que va dentro de los enlaces.
        Para una clave externa es el nombre que tendria DENTRO de base_vault: sigue
        sirviendo de etiqueta (estadisticas, mensajes) aunque la carpeta viva fuera."""
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

    def es_externa(self, clave: str) -> bool:
        return clave in self.externas

    def ruta(self, base_vault, clave: str) -> Path:
        """Ruta absoluta en disco de `clave`: la externa si la tiene, si no bajo base_vault."""
        if clave in self.externas:
            return Path(self.externas[clave])
        return Path(base_vault).joinpath(*self.rel(clave).split("/"))

    def enlace(self, clave: str, fichero: str = "") -> str:
        """Ruta tal como aparece en un enlace de nota: `CHATGPT/GENERADAS/x.png`."""
        return f"{self.rel(clave)}/{fichero}" if fichero else self.rel(clave)

    # ---- conversaciones del vault fusionado -------------------------------
    def conv_rel(self, proveedor: Optional[str] = None) -> str:
        """Carpeta de conversaciones DEL VAULT FUSIONADO, relativa a su raiz, para
        las notas de ese proveedor. Con un MERGED unico es siempre la misma; partido,
        es la carpeta de su proveedor. (El RAW no se parte: usa `rel("conversaciones")`.)"""
        base = self.rel("conversaciones")
        if self.particion == "proveedor":
            return f"{carpeta_proveedor(proveedor)}/{base}"
        return base

    def conv_dirs(self, raiz_vault) -> List[str]:
        """Carpetas de conversaciones del vault fusionado (relativas a `raiz_vault`,
        con `/`) que hay que recorrer para ver TODAS sus notas. Una sola con MERGED
        unico, exista o no (quien recorre ya comprueba si existe); partido, una por
        cada carpeta de proveedor que tenga conversaciones en disco, incluidos los
        proveedores que este modulo no conoce."""
        base = self.rel("conversaciones")
        if self.particion != "proveedor":
            return [base]
        raiz = Path(raiz_vault)
        try:
            hijos = sorted(p for p in raiz.iterdir() if p.is_dir() and (p / base).is_dir())
        except OSError:
            return []
        return [f"{p.name}/{base}" for p in hijos]

    # ---- serializacion --------------------------------------------------
    def a_dict(self) -> Dict[str, str]:
        """Tabla ya resuelta (sin `{}`): los nombres relativos."""
        return dict(self._resueltas)

    def a_estado(self) -> dict:
        """Todo lo que define este layout, para el marcador y el entorno."""
        return {"preset": self.preset, "particion": self.particion, "proyectos": self.proyectos,
                "nombres": self.a_dict(), "externas": dict(self.externas)}

    def con(self, nombres: Optional[Dict[str, str]] = None, externas: Optional[Dict[str, str]] = None,
            preset: Optional[str] = None) -> "Layout":
        """Copia con otra tabla, otras ubicaciones externas o otro nombre, conservando
        los interruptores. `externas={}` quita las que hubiera."""
        return Layout(self.a_dict() if nombres is None else nombres,
                      preset=self.preset if preset is None else preset,
                      externas=self.externas if externas is None else externas,
                      particion=self.particion, proyectos=self.proyectos)

    @classmethod
    def desde_dict(cls, nombres: Dict[str, str], preset: str = PRESET_DEFECTO) -> "Layout":
        return cls(nombres, preset=preset)

    @classmethod
    def desde_estado(cls, datos: dict) -> "Layout":
        # Un marcador de antes de los presets (v1, v2) no trae los interruptores: es
        # el layout de siempre, MERGED unico y PRJ_VAULT.
        return cls(datos["nombres"], preset=datos.get("preset", PRESET_DEFECTO),
                   externas=datos.get("externas"),
                   particion=datos.get("particion"), proyectos=datos.get("proyectos"))

    # ---- validacion -----------------------------------------------------
    def problemas(self, base_vault=None) -> List[str]:
        """Lista legible de por que este layout no se puede usar. Vacia = valido.
        Con `base_vault` comprueba ademas las ubicaciones externas contra el vault."""
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
            if re.search(r'[<>:"|?*\x00-\x1f]', v):
                malos.append(f"'{k}': caracteres no validos en Windows ({v})")
            # Lo que Windows hace en silencio: quitar el punto o el espacio del final
            # ("RAW." pasa a ser "RAW") y rechazar los nombres de dispositivo. En
            # Linux funcionarian, y un vault asi no se podria abrir luego en Windows.
            for p in v.split("/"):
                if p in ("", ".", ".."):
                    continue
                if p.endswith((".", " ")):
                    malos.append(f"'{k}': '{p}' acaba en punto o espacio; Windows lo recortaria ({v})")
                if p.split(".")[0].upper() in _RESERVADOS_WINDOWS:
                    malos.append(f"'{k}': '{p}' es un nombre reservado de Windows ({v})")
            # Windows no distingue mayusculas: dos claves que difieren solo en
            # eso serian la misma carpeta.
            # `claude.proyectos` es a proposito la misma carpeta que `prj` cuando hay vault de proyectos.
            if k not in ("conversaciones", "claude.proyectos"):
                previa = vistos.get(v.lower())
                if previa is not None:
                    malos.append(f"'{k}' y '{previa}' apuntan a la misma carpeta ({v})")
                vistos[v.lower()] = k

        for k, v in self.externas.items():
            p = Path(v)
            if not p.is_absolute():
                malos.append(f"'{k}' externo debe ser una ruta absoluta, no relativa ({v})")
                continue
            if ".." in p.parts:
                malos.append(f"'{k}' externo no puede contener '..' ({v})")
                continue
            if base_vault is None:
                continue
            base, ext = norm(base_vault), norm(v)
            if ext == base:
                malos.append(f"'{k}' externo no puede ser la propia carpeta base ({v})")
            elif dentro(base, ext):
                malos.append(f"'{k}' externo contiene la carpeta base: el pipeline recorreria "
                             f"todo el vault como si fuera la fuente ({v})")
            else:
                for otra, rel in self._resueltas.items():
                    if otra in ("conversaciones", "raw"):
                        continue
                    if dentro(ext, norm(Path(base_vault) / rel)):
                        malos.append(f"'{k}' externo cae dentro de '{rel}' ({v}): "
                                     "mezclaria la fuente con un vault o un banco")
                        break
        return malos

    def validar(self, base_vault=None) -> "Layout":
        malos = self.problemas(base_vault)
        if malos:
            raise LayoutError("layout no valido:\n  - " + "\n  - ".join(malos))
        return self

    def __eq__(self, otro) -> bool:
        return (isinstance(otro, Layout) and self._resueltas == otro._resueltas
                and self.particion == otro.particion and self.proyectos == otro.proyectos
                and {k: norm(v) for k, v in self.externas.items()}
                == {k: norm(v) for k, v in otro.externas.items()})

    def __repr__(self) -> str:
        ext = f", externas={sorted(self.externas)}" if self.externas else ""
        return (f"Layout(preset={self.preset!r}, particion={self.particion!r}, "
                f"proyectos={self.proyectos}, {len(self._resueltas)} claves{ext})")


CLASICO = Layout()


# ---- marcador en el vault ------------------------------------------------
def leer_marcador(base_vault) -> Optional[Layout]:
    """El layout con el que se construyo ese vault, o None si no hay marcador
    (vaults anteriores a esta version: son, por definicion, el clasico)."""
    p = Path(base_vault) / MARCADOR
    try:
        return Layout.desde_estado(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def escribir_marcador(base_vault, layout: Layout) -> Path:
    """Escritura atomica (.part + replace): un corte a mitad no deja un marcador
    corrupto que haga creer al siguiente arranque que el vault es de otro layout."""
    p = Path(base_vault) / MARCADOR
    parcial = p.with_name(p.name + ".part")
    cuerpo = {"version": VERSION_MARCADOR, **layout.a_estado()}
    parcial.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(parcial, p)
    return p


# ---- layout activo -------------------------------------------------------
def _con_prj(layout: Layout, prj_vault_name: Optional[str]) -> Layout:
    if prj_vault_name and prj_vault_name != layout.rel("prj"):
        nombres = layout.a_dict()
        nombres["prj"] = prj_vault_name
        return layout.con(nombres=nombres)
    return layout


def cargar(base_vault=None, prj_vault_name: Optional[str] = None,
           usar_entorno: bool = True, raw_vault: Optional[str] = None,
           preset: Optional[str] = None) -> Layout:
    """Layout activo: entorno > marcador del vault > clasico.

    `usar_entorno=False` ignora la variable de entorno: lo necesita quien LA
    ESTABLECE (el launcher, en cada peticion). Si leyera su propio entorno de
    la peticion anterior, un layout cambiado en disco no se enteraria nunca.

    `prj_vault_name` es la opcion `options.prj_vault_name` de la config, que ya
    existia antes que el layout y se respeta: si viene, manda sobre la clave
    `prj`.

    `raw_vault` (config `paths.raw_vault`) y `preset` (`options.layout_preset`)
    solo cuentan cuando el vault todavia no tiene marcador: en cuanto lo tiene, el
    layout aplicado es el del marcador, y si la config discrepa lo dice
    `conflictos` -- no se obedece en silencio."""
    layout: Optional[Layout] = None

    crudo = os.environ.get(ENV_LAYOUT) if usar_entorno else None
    if crudo:
        try:
            layout = Layout.desde_estado(json.loads(crudo))
        except (ValueError, KeyError, TypeError):
            layout = None
    if layout is None and base_vault:
        layout = leer_marcador(base_vault)
    if layout is None:
        nombre = normalizar_preset(preset) if preset else PRESET_DEFECTO
        layout = (Layout(externas={"raw": str(raw_vault)} if raw_vault else None, preset=nombre)
                  if (raw_vault or nombre != PRESET_DEFECTO) else CLASICO)
    return _con_prj(layout, prj_vault_name)


def pedido(base_vault=None, prj_vault_name: Optional[str] = None,
           raw_vault: Optional[str] = None, preset: Optional[str] = None) -> Layout:
    """El layout que la CONFIG pide: la tabla del marcador (o la clasica) mas el RAW
    externo de `paths.raw_vault`, que aqui manda -- vacio significa "dentro de
    base_vault" --, y el preset de `options.layout_preset`, que si viene fija los
    interruptores (sin el, valen los del marcador). Es lo que compara `conflictos`
    con lo que el vault ya tiene."""
    previo = leer_marcador(base_vault) if base_vault else None
    externas = {"raw": str(raw_vault)} if raw_vault else {}
    if preset:
        nombre = normalizar_preset(preset)
        particion, proyectos = PRESETS[nombre]
        nombres = previo.a_dict() if previo else None
        if nombres and (previo.particion, previo.proyectos) != (particion, proyectos):
            # Lo que cuelga de un interruptor lo deciden los interruptores nuevos,
            # no los que tenia el marcador.
            for k in CLAVES_DE_INTERRUPTOR:
                nombres.pop(k, None)
        lay = Layout(nombres, preset=nombre, externas=externas, particion=particion, proyectos=proyectos)
    else:
        lay = (previo or CLASICO).con(externas=externas)
    return _con_prj(lay, prj_vault_name)


def _conflicto_particion(base: Path, actual: Layout, pedido_: Layout) -> List[str]:
    """Cambiar como se parte MERGED sobre un vault que ya tiene notas fusionadas
    escribiria las nuevas en otra carpeta y dejaria las viejas donde estaban: cada
    conversacion aparecería dos veces, o los indices solo verian una parte. Sin
    notas todavia no hay nada que partir en dos, y se deja cambiar."""
    if actual.particion == pedido_.particion:
        return []
    merged = actual.ruta(base, "merged")
    hay_notas = any(
        True
        for d in actual.conv_dirs(merged)
        if (merged / d).is_dir()
        for _ in (merged / d).rglob("*.md"))
    if not hay_notas:
        return []
    nombres = {"unico": "unico (todo mezclado en una carpeta)", "proveedor": "por proveedor"}
    return [
        f"el vault ya tiene conversaciones fusionadas organizadas {nombres[actual.particion]}, y la "
        f"configuracion pide {nombres[pedido_.particion]}. Seguir escribiria las nuevas en otra carpeta "
        "y dejaria las anteriores donde estan: cada conversacion saldria dos veces. Cambiar la "
        "organizacion de un vault con notas necesita migrarlo, y eso aun no esta disponible; "
        f"mientras, deja `layout_preset` como estaba ('{actual.preset}')."]


def _conflicto_proyectos(base: Path, actual: Layout, pedido_: Layout) -> List[str]:
    """Encender o apagar el vault de proyectos cambia donde se escriben los proyectos
    del export de Claude. A diferencia de PRJ_VAULT, que es una vista que se
    regenera, esos ficheros son la unica copia: dejarlos en el sitio viejo y escribir
    los nuevos en otro los partiria sin ningun error."""
    if actual.proyectos == pedido_.proyectos:
        return []
    viejo = actual.ruta(base, "claude.proyectos")
    # PRJ_VAULT mezcla dos cosas: las vistas de conversaciones por proyecto (se
    # regeneran) y los proyectos de Claude (`<nombre>/00_proyecto.md`, la unica copia).
    # Solo importan los segundos.
    if not viejo.is_dir() or not any(viejo.glob("*/00_proyecto.md")):
        return []
    return [f"los proyectos de Claude ya estan en {viejo} y cambiar el vault de proyectos los escribiria "
            f"en {pedido_.ruta(base, 'claude.proyectos')}, dejando los anteriores donde estan. Cambiar "
            "esto en un vault con proyectos necesita migrarlo, y eso aun no esta disponible; "
            f"mientras, deja `layout_preset` como estaba ('{actual.preset}')."]


def conflictos(base_vault, pedido_: Layout) -> List[str]:
    """Por que NO se debe seguir con `pedido_` sobre este vault. Vacia = via libre.

    El fallo que evita no da error: con la fuente RAW en otro sitio del que ya
    tiene el vault, el pipeline escribiria las notas nuevas en un RAW vacio, el
    merge solo veria esas, y las anteriores quedarian sin la fusion. Todo en verde."""
    base = Path(base_vault)
    marcador = leer_marcador(base)
    malos: List[str] = []
    if marcador is None:
        # Sin marcador: un vault anterior a esta version es el clasico, pero solo
        # "tiene" un RAW si la carpeta existe. Uno nuevo adopta lo que pida la config.
        actual, de_donde = CLASICO, "el vault ya tiene su RAW en"
        tiene_raw = CLASICO.ruta(base, "raw").is_dir()
    else:
        actual, de_donde = marcador, "el marcador del vault dice que su RAW esta en"
        tiene_raw = True

    malos.extend(_conflicto_particion(base, actual, pedido_))
    malos.extend(_conflicto_proyectos(base, actual, pedido_))
    if not tiene_raw:
        return malos

    raw_actual, raw_pedido = actual.ruta(base, "raw"), pedido_.ruta(base, "raw")
    if norm(raw_actual) != norm(raw_pedido):
        malos.append(
            f"la configuracion pone el RAW en {raw_pedido}, pero {de_donde} {raw_actual}. "
            "Seguir escribiria las notas nuevas en un RAW distinto y el merge no vería las "
            "anteriores. Mueve el RAW con `python mover_raw.py --hacia <carpeta>` (copia y "
            "verifica, no borra el original), o deja `raw_vault` en la configuración como estaba.")
        return malos

    if pedido_.es_externa("raw") and marcador is not None and not raw_pedido.is_dir():
        malos.append(
            f"la fuente RAW no existe en {raw_pedido}. Si esta en un disco o una carpeta de red "
            "que no esta conectada, conectala: crear un RAW nuevo aqui partiria la fuente en dos.")
    return malos


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
    return {ENV_LAYOUT: json.dumps(layout.a_estado(), ensure_ascii=False)}
