# M3M0R·IA (MemorIA2GO)

<p align="center">
  <img src="assets/M3M0R-IA.png" alt="M3M0R·IA" width="180">
</p>

> Convierte tu historial de conversaciones con IAs — ChatGPT, Claude, Grok — en un vault de Obsidian estructurado y listo para MCP. Tu contexto, local y tuyo.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

---

## Ediciones por idioma

M3M0R·IA se mantiene como dos líneas de producto en paralelo mientras se completa la localización al inglés:

- **`release/es` (esta rama) — edición española.** La aplicación original, completamente funcional: interfaz web, mensajes en tiempo de ejecución y contenido generado en el vault, todo en español. Recibe correcciones de errores mientras dura el esfuerzo de localización.
- **`release/en` — edición inglesa.** La interfaz web ya está traducida por completo (hito `i18n-web`); los mensajes en tiempo de ejecución y el contenido generado en el vault siguen en español hasta que aterricen las fases de localización 2 (`i18n-runtime`) y 3 (`i18n-content`).
- **`main`** está congelada en el último estado común (v2.8.0) como referencia inmutable hasta que ambas ediciones alcancen paridad de funcionalidades.

---

## ¿Qué es M3M0R·IA?

M3M0R·IA convierte los exports nativos de tus proveedores de chat con IA en un vault limpio de notas Markdown, organizado por proyectos, listo para navegarse en Obsidian y para servir de contexto vivo a Claude Desktop vía MCP (Model Context Protocol).

A diferencia de las herramientas genéricas de migración que solo transfieren memorias guardadas, M3M0R·IA trae tu **historial completo de conversaciones** — deduplicado, fusionado, organizado por proyecto y fecha, con imágenes extraídas e índices de navegación generados.

**Proveedores soportados** (detección por estructura interna del JSON, nunca por nombre de archivo):

| Proveedor | Formato del export | Gestión de ramas | Adjuntos |
|----------|--------------|-----------------|-------------|
| ChatGPT  | zip / json / html | recorrido del árbol por `current_node` | imágenes generadas por IA y subidas del usuario extraídas a bancos separados (`CHATGPT/GENERADAS`, `CHATGPT/ADJUNTOS`) |
| Claude   | zip (puede llegar en partes `batch-NNNN`) | reconstrucción por la hoja más reciente (el export no trae `current_node`) | texto extraído citado inline; los binarios subidos no vienen en el export; los **Artefactos generados** (documentos, código, HTML...) se extraen a `CLAUDE/ARTEFACTOS`, un fichero por artefacto, clasificados por tipo — solo la versión final, el historial de revisiones se descarta |
| Grok     | zip (estructura `ttl/30d/...`) | `leaf_response_id` cuando existe, si no la hoja más reciente | adjuntos extraídos a `GROK/ADJUNTOS`; las generaciones de Imagine (imagen y vídeo) se extraen a `GROK/GENERADAS_IMAGEN`/`GROK/GENERADAS_VIDEO` cuando el export trae el binario, si no se registran como lista de pendientes de descarga (prompt + enlace), nunca se descargan solas |

Todos los proveedores conviven en un único vault fusionado (MERGED). Cada nota lleva `provider` y `source` en su frontmatter, así que puedes filtrar, colorear e indexar por origen. Cada banco de assets tiene su propio índice navegable, mismo patrón que el índice de imágenes clásico.

*El detalle de cómo funciona por dentro —los cuatro pasos, los adaptadores, las herramientas hermanas— está en **[ARCHITECTURE.md](ARCHITECTURE.md)**.*

---

## Requisitos

- Python **3.10+**
- Dependencias: `pip install -r requirements.txt`
  (beautifulsoup4, lxml, rich, pyyaml, flask)
- Obsidian (para navegar el resultado) y opcionalmente Claude Desktop con un servidor MCP de filesystem (para usarlo como contexto vivo)
- Opcional, para correr el suite de tests: `pip install -r requirements-dev.txt && python -m pytest tests/`

Desarrollado y probado a fondo en Windows; el pipeline en sí es multiplataforma.

---

## Arranque rápido (interfaz web)

M3M0R·IA viene con una interfaz web local — dashboard, configuración, verificación previa, lanzador del pipeline con log en vivo, y curación de proyectos huérfanos.

```bash
git clone <este repo>
cd MemorIA2GO
pip install -r requirements.txt

# 1. Crea tu configuración desde la plantilla y ajusta tus rutas
copy memoria_config.yaml.example memoria_config.yaml   # Windows
cp memoria_config.yaml.example memoria_config.yaml     # Linux / macOS

# 2. Arranca
python launcher.py     # en Linux, según tu distro: python3 launcher.py
```

Tu navegador se abre en `http://127.0.0.1:8765`. El servidor solo escucha en localhost — no tiene autenticación y puede lanzar el pipeline, así que déjalo así.

Opciones:

```bash
python launcher.py --port 80 --no-browser   # para un servidor local persistente
```

URL bonita opcional: añade `127.0.0.1  m3m0ria` a tu fichero hosts (Windows: `C:\Windows\System32\drivers\etc\hosts`; Linux/macOS: `/etc/hosts`, con `sudo`) y arranca en el puerto 80 → `http://m3m0ria/`. En Windows puedes registrar una tarea programada de inicio de sesión que lance `pythonw launcher.py --port 80 --no-browser` desde la carpeta del repo; en Linux, un servicio de usuario de systemd o una entrada de autoarranque lanzando `python3 launcher.py --port 8765 --no-browser` hace el mismo trabajo (el puerto 80 en Linux necesita privilegios: quédate en el 8765 o pon un proxy delante).

La primera carga del dashboard calcula las estadísticas una vez y las cachea junto a tu vault (`.m3m0ria_stats.json`); después de eso, las cargas son instantáneas. El pipeline refresca la caché al final del paso 4, y el dashboard ofrece un enlace manual de *recalcular*.

### CLI (sin web)

```bash
python MemorIA2GO.py                  # interactivo, pipeline completo
python MemorIA2GO.py --reprocess-all  # re-parsea todos los exports válidos desde cero
```

---

> ### ¿Te has atascado?
>
> Si nunca has usado una terminal, o te piden un token de Suno y no sabes qué es eso, no sigas peleándote con esto: **[ME_HE_ATASCADO.md](ME_HE_ATASCADO.md)** lo cuenta desde cero, sin dar nada por sabido.

## Configuración

- `memoria_config.yaml` — tus rutas (vault base, carpeta de exports, mapa de gizmos) y opciones (carpetas por año/mes, generación de índice). Se crea desde `memoria_config.yaml.example`; nunca se commitea.
- `gizmo_map.json` — mapea IDs de proyecto (gizmo) de ChatGPT a nombres humanos. Se cura desde la interfaz web (pestaña Cartografía); nunca se commitea.
- `topic_map.json` — tus temas para conversaciones sin asignar: `{"tema": ["palabras", "frases", "campo=valor"]}`. Se cura desde la interfaz; genera notas de índice enlazadas en `MERGED_VAULT/_Temas`. Nunca se commitea.
- `substack_vault` (en `memoria_config.yaml`) — dónde se construye el vault de Tintero. Es la **única** ruta que necesita: el export de Substack y su CSV de estadísticas viven en tu carpeta de exports de siempre, porque el pipeline de conversaciones los rechaza y Tintero los recoge de ahí. Una carpeta, dos puertas.
- `suno_backup` y `suno_vault` (en `memoria_config.yaml`) — las dos rutas de MUSIC·0LOGY: dónde vive el backup crudo de Suno, y dónde se construye su vault de Obsidian. Las dos opcionales: sin `suno_backup` la tarjeta del Observatorio simplemente no aparece — no se pinta a cero, porque decir "0 pistas" sobre una biblioteca que no has descargado es mentir, no informar.

Los exports de Claude y Grok no enlazan conversaciones a proyectos: esas notas se organizan por temas (varios-a-varios), no por carpetas.

---

## La documentación, por preguntas

Cada documento responde **una** pregunta. Si buscas algo que no está aquí, probablemente esté en otro:

| | Responde |
|---|---|
| **README** (estás aquí) | ¿Qué es y cómo lo arranco? |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | ¿Cómo funciona por dentro y por qué así? |
| **[ME_HE_ATASCADO.md](ME_HE_ATASCADO.md)** | ¿Y si no sé nada de esto? |
| **[DEVLOG.md](DEVLOG.md)** | ¿Qué aprendimos construyéndolo? |

---

## Roadmap

- Selector manual conversación↔proyecto para casos residuales (namespace `manual:` en gizmo_map, diseñado y diferido hasta que el montón de conversaciones sin asignar se reduzca más)
- Extracción de assets para los adjuntos `.dat` del export fragmentado de ChatGPT 2026+ (un formato binario distinto al ya soportado)
- Distinguir "nunca tuvo proyecto" de "tiene un proyecto que nadie ha nombrado todavía" en `Project_name` — hoy ambos colapsan a `none`
- Un tipo de tool-call `image_group` de ChatGPT que el parser aún no reconoce y se cuela en crudo en el texto de la nota — hace falta una muestra real de export para fijar la ruta de código exacta antes de arreglarlo

---

## Licencia

CC BY-NC-SA 4.0 — ver el badge de arriba.
