# M3M0R·IA (MemorIA2GO)

<p align="center">
  <img src="assets/M3M0R-IA.png" alt="M3M0R·IA" width="180">
</p>

> Convierte tu historial de conversaciones con IAs — ChatGPT, Claude, Grok — en un vault de Obsidian estructurado y listo para MCP. Tu contexto, local y tuyo.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

---

## ¿Qué es M3M0R·IA?

M3M0R·IA convierte los exports nativos de tus proveedores de chat con IA en un vault limpio de notas Markdown, organizado por proyectos, listo para navegarse en Obsidian y para servir de contexto vivo a Claude Desktop vía MCP (Model Context Protocol).

A diferencia de las herramientas genéricas de migración que solo transfieren memorias guardadas, M3M0R·IA trae tu **historial completo de conversaciones** — deduplicado, fusionado, organizado por proyecto y fecha, con imágenes extraídas e índices de navegación generados.

**Proveedores soportados** (detección por estructura interna del JSON, nunca por nombre de archivo):

| Proveedor | Formato del export | Manejo de ramas | Adjuntos |
|-----------|-------------------|-----------------|----------|
| ChatGPT   | zip / json / html | recorrido del árbol vía `current_node` | texto inline, imágenes extraídas al IMAGE_BANK |
| Claude    | zip (puede llegar troceado en `batch-NNNN`) | reconstrucción por hoja más reciente (el export no trae current_node) | texto extraído citado inline; los binarios no viajan en el export |
| Grok      | zip (estructura `ttl/30d/...`) | `leaf_response_id` si viene poblado, hoja más reciente si no | referenciados por asset id (extracción de binarios en el roadmap) |

Todos los proveedores conviven en un único vault MERGED. Cada nota lleva `provider` y `source` en su frontmatter, así que puedes filtrar, colorear e indexar por origen.

---

## Cómo funciona

El pipeline corre en 4 pasos no destructivos:

**Paso 1 — Importar** (`split_chatgpt_export.py` + adaptadores en `providers/`)
Cada export válido y pendiente de tu carpeta de exports se detecta por estructura y se despacha a su adaptador. Una nota Markdown por conversación aterriza en `RAW_VAULT`, con frontmatter YAML (título, fecha, provider, source, mapeo de proyecto). Las ramas de regeneraciones descartadas se excluyen — solo el hilo que realmente conservaste.

**Paso 2 — Fusionar** (`vault_merge.py`)
Consolida variantes de la misma conversación entre exports en `MERGED_VAULT` sin perder mensajes: la variante más larga gana como campeón y cualquier mensaje que le falte se recupera de las demás.

**Paso 3 — Proyectos** (`project_organizer.py`)
Construye `PRJ_VAULT` como vista proyecto/año/mes de MERGED. Se refresca en cada ejecución (symlinks donde el sistema lo permite, copias reales en Windows).

**Paso 4 — Índices** (`tree_index.py`, `scaffolding_index.py`, `image_index.py`, `vault_stats.py`)
Índices de navegación (proyecto/año/mes), índice de uso de adjuntos, índice de imágenes, y la caché de estadísticas que alimenta el dashboard.

### ¿Cuándo ejecutar qué?

- **Importar pendientes (paso 1→4)** — el modo del día a día: dejaste exports nuevos en tu carpeta y quieres incorporarlos. Solo procesa lo que no se había importado.
- **Solo actualizar (paso 2→4)** — sin datos nuevos, pero cambió cómo se consolida u organiza: tras bautizar gizmos, tras una actualización de M3M0R·IA que toque la fusión, la vista de proyectos o los índices.
- **Reprocesar todos** — tras una versión de M3M0R·IA que añada o cambie campos del frontmatter (`provider`, `conv_id`, `model`...) o modifique los parsers: las notas existentes solo ganan los campos nuevos re-importándose desde los exports. Es seguro (los exports son la fuente de verdad y nada se destruye) pero tarda proporcionalmente a tu historial — café recomendado.
- **Generar índice de temas** (pestaña Cartografía) — cada vez que edites temas; no requiere reiniciar nada. El paso 4 lo regenera además automáticamente en cada pasada del pipeline.

---

## Requisitos

- Python **3.10+**
- Dependencias: `pip install -r requirements.txt`
  (beautifulsoup4, lxml, rich, pyyaml, flask)
- Obsidian (para navegar el resultado) y opcionalmente Claude Desktop con un servidor MCP de filesystem (para usarlo como contexto vivo)

Desarrollado y curtido en Windows; el pipeline en sí es multiplataforma.

---

## Arranque rápido (interfaz web)

M3M0R·IA incluye una interfaz web local — dashboard, configuración, verificación previa, ejecución del pipeline con log en vivo, y curación de proyectos huérfanos.

```bash
git clone <este repo>
cd MemorIA2GO
pip install -r requirements.txt

# 1. Crea tu configuración desde la plantilla y ajusta tus rutas
copy memoria_config.yaml.example memoria_config.yaml   # Windows
cp memoria_config.yaml.example memoria_config.yaml     # Linux / macOS

# 2. Lanza
python launcher.py     # en Linux, según tu distro: python3 launcher.py
```

El navegador se abre en `http://127.0.0.1:8765`. El servidor escucha solo en localhost — no tiene autenticación y puede ejecutar el pipeline, así que déjalo así.

Opciones:

```bash
python launcher.py --port 80 --no-browser   # para servidor local persistente
```

URL bonita opcional: añade `127.0.0.1  m3m0ria` a tu archivo hosts (Windows: `C:\Windows\System32\drivers\etc\hosts`; Linux/macOS: `/etc/hosts`, con `sudo`) y ejecuta en el puerto 80 → `http://m3m0ria/`. En Windows puedes registrar una Tarea Programada al iniciar sesión que ejecute `pythonw launcher.py --port 80 --no-browser` desde la carpeta del repo; en Linux, un servicio de usuario de systemd o una entrada de autostart con `python3 launcher.py --port 8765 --no-browser` cumple el mismo papel (el puerto 80 en Linux requiere privilegios: quédate en el 8765 o usa un proxy).

La primera carga del dashboard calcula las estadísticas una vez y las cachea junto a tu vault (`.m3m0ria_stats.json`); a partir de ahí, carga instantánea. El pipeline refresca la caché al final del paso 4, y el dashboard ofrece un enlace *recalcular* manual.

### CLI (sin web)

```bash
python MemorIA2GO.py                  # interactivo, pipeline completo
python MemorIA2GO.py --reprocess-all  # reprocesa todos los exports válidos desde cero
```

---

## Nunca he usado una terminal: guía paso a paso

¿Todo lo de arriba te suena a chino? Esta sección es para ti. Sin conocimientos previos, en Windows, paso a paso.

**1. Instala Python.**
Ve a [python.org/downloads](https://www.python.org/downloads/) y pulsa el botón amarillo de descarga. Al ejecutar el instalador, **marca la casilla "Add Python to PATH"** (abajo del todo, es fácil pasarla por alto — es la más importante de todo el proceso). Luego "Install Now" y espera.

**2. Descarga este proyecto.**
En esta misma página de GitHub, pulsa el botón verde **Code** → **Download ZIP**. Descomprime el ZIP donde quieras — por ejemplo en `C:\M3M0RIA`. (Botón derecho sobre el ZIP → "Extraer todo".)

**3. Abre una consola.**
Pulsa la tecla Windows, escribe `powershell` y pulsa Enter. Se abre una ventana azul o negra con texto: eso es la consola o terminal. Se usa escribiendo órdenes y pulsando Enter. No muerde.

**4. Entra en la carpeta del proyecto.**
Escribe esto (o cópialo y pégalo con botón derecho) y pulsa Enter — ajusta la ruta si lo descomprimiste en otro sitio:

```
cd "C:\M3M0RIA"
```

**5. Instala lo que el programa necesita.**
Copia esto, pégalo y Enter:

```
pip install -r requirements.txt
```

Verás pasar un montón de texto durante un rato. Es normal: está descargando las piezas que el programa usa. Cuando vuelva a aparecer el cursor, terminó.

**6. Crea tu configuración.**
Copia, pega, Enter:

```
copy memoria_config.yaml.example memoria_config.yaml
notepad memoria_config.yaml
```

Se abre el Bloc de notas con la configuración. Solo necesitas ajustar dos rutas: `base_vault` (la carpeta donde quieres que viva tu vault de notas — puede ser una carpeta nueva vacía) y `exports_dir` (la carpeta donde vas a dejar los ZIP que te descargas de ChatGPT/Claude/Grok). Guarda y cierra.

**7. Consigue tus exports.**
- **ChatGPT**: Ajustes → Controles de datos → Exportar datos. Te llega un email con un ZIP.
- **Claude**: Ajustes → Privacidad → Exportar datos. Te llega un email con un ZIP (a veces varios).
- **Grok**: Ajustes → Datos → Descargar tus datos.

Deja los ZIP tal cual (sin descomprimir) en la carpeta que pusiste en `exports_dir`.

**8. Arranca M3M0R·IA.**
En la consola:

```
python launcher.py
```

Se abre tu navegador con la interfaz. A partir de aquí, todo es con clics: pestaña **Configuración** para revisar rutas, **Verificación** para comprobar que tus ZIP se reconocen, y **Pipeline** → "Importar pendientes" para lanzar la conversión. El log te va contando lo que hace. Cuando termine, abre la carpeta de tu vault con Obsidian y a disfrutar.

**Si algo falla:**
- *"python no se reconoce como un comando..."* → la casilla del PATH del paso 1 no se marcó. Reinstala Python marcándola, cierra la consola y abre una nueva.
- *"pip no se reconoce..."* → lo mismo de arriba.
- La ventana del navegador no se abre → escribe a mano `http://127.0.0.1:8765` en tu navegador.

---

## Configuración

- `memoria_config.yaml` — tus rutas (vault base, carpeta de exports, gizmo map) y opciones (subcarpetas por año/mes, generación de índices). Se crea desde `memoria_config.yaml.example`; nunca se commitea.
- `gizmo_map.json` — mapea IDs de proyectos (gizmos) de ChatGPT a nombres humanos. Se cura desde la interfaz web (pestaña Cartografía); nunca se commitea.
- `topic_map.json` — tus temas para las conversaciones sin proyecto: `{"tema": ["palabras", "frases", "campo=valor"]}`. Se cura desde la interfaz; genera notas-índice con enlaces en `MERGED_VAULT/_Temas`. Nunca se commitea.

Los exports de Claude y Grok no vinculan conversaciones con proyectos: esas notas se organizan por temas (relación varios-a-varios), no por carpetas.

---

## Cómo ha evolucionado este proyecto

- La **v1** era un pipeline de 3 pasos, solo CLI, solo ChatGPT: importar, organizar por proyecto, indexar.
- La **v2** (actual) creció en cuatro direcciones, cada una empujada por un fallo real o una necesidad real:
  - **La fusión se convirtió en paso propio.** La deduplicación era destructiva; ahora las variantes se consolidan sin perder un solo mensaje, y la procedencia del campeón se preserva.
  - **Adaptadores multi-proveedor.** Los exports de Claude y Grok se diseccionaron contra datos reales antes de escribir código. La detección es estructural — el zip de Claude también contiene un `conversations.json`, y la raíz de Grok también tiene clave `conversations`, así que detectar por nombre de archivo produciría basura en silencio. Cada adaptador reconstruye el hilo vigente según el modelo de ramas de su proveedor.
  - **Una interfaz web (M3M0R·IA).** Dashboard con gráficas de evolución, estadísticas por proveedor y por proyecto, verificación previa que nombra el proveedor de cada export (y rechaza honestamente lo que aún no sabe parsear), ejecución del pipeline con log en vivo, y curación de proyectos huérfanos.
  - **Rendimiento por diseño.** Las estadísticas se calculan una vez por ejecución del pipeline y se cachean atómicamente; el dashboard lee la caché en milisegundos sea cual sea el tamaño del vault.
  - **Cartografía en vez de taxonomía forzada.** Las conversaciones sin proyecto no se meten con calzador en carpetas: una nube de vocabulario (sembrada con los nombres de proyecto de los tres proveedores) alimenta un sistema de Temas varios-a-varios — palabras, frases y reglas de metadatos `campo=valor` — que genera índices enlazados en Obsidian. Curado en un archivo por tema, derivado regenerable, notas intactas.
  - **Identidad por `conv_id`.** El ID nativo de cada conversación viaja al frontmatter y el merge agrupa por él: los renombrados de hilo entre exports (medidos: 21 de 593 conversaciones reales) se fusionan bajo el título más reciente conservando `titulo_original`, en vez de duplicarse como fantasmas.

Principios de diseño de principio a fin: diagnosticar antes de implementar, validar contra exports reales, no destruir datos jamás, y hacer que los fallos sean ruidosos y honestos en vez de silenciosos.

---

## Roadmap

- Selector manual conversación↔proyecto para casos residuales (namespace `manual:` en gizmo_map, diseñado y diferido)
- Extracción de assets de Grok al IMAGE_BANK (sus binarios sí viajan en el export)
- Tests de regresión con fixtures por proveedor
- Campo `model` en el frontmatter donde el export lo registre (Grok, ChatGPT)

---

## Licencia

CC BY-NC-SA 4.0 — ver badge arriba.
