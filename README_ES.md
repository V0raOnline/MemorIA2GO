# MemorIA2GO

<p align="center">
  <img src="assets/logo.png" alt="MemorIA2GO" width="180">
</p>

> Migra tu historial de conversaciones de ChatGPT a un vault estructurado y listo para MCP en Claude Desktop.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

---

## ¿Qué es MemorIA2GO?

MemorIA2GO es una herramienta específica que convierte tu exportación de ChatGPT en un vault limpio de archivos Markdown, organizado por proyectos y listo para usarse como contexto vivo en Claude Desktop a través de MCP (Model Context Protocol).

A diferencia de las herramientas de migración genéricas que solo transfieren memorias guardadas, MemorIA2GO trae tu **historial completo de conversaciones** — organizado, deduplicado y accesible de inmediato.

---

## Cómo funciona

MemorIA2GO ejecuta un pipeline de 3 pasos:

**Paso 1 — Importar y convertir**
Parsea tu exportación de ChatGPT (`.zip`, `.json` o `.html`) y genera un archivo `.md` por conversación con YAML frontmatter limpio: título, fecha, etiquetas y mapeo de proyecto.

**Paso 2 — Organizar por proyecto**
Reorganiza el vault en subcarpetas por proyecto usando el campo `Project_name` del frontmatter de cada nota. Soporta subcarpetas por año/mes dentro de cada proyecto.

**Paso 3 — Deduplicar**
Elimina las copias delta y variantes de hash generadas por el formato de exportación de ChatGPT. Conserva únicamente la versión canónica de cada conversación, reduciendo significativamente el tamaño del vault.

---

## Inicio rápido

### Requisitos

- Python 3.9+
- Claude Desktop
- Node.js (para el servidor MCP)

### Instalar dependencias

```bash
pip install rich pyyaml beautifulsoup4 lxml
```

### Ejecutar

```bash
python MemorIA2GO.py
```

El wizard preguntará:
- Ruta al archivo de exportación de ChatGPT o carpeta que lo contenga
- Carpeta de destino para el vault
- Gizmo map (mapeo ID de proyecto → nombre, opcional)
- Nombre del vault de proyectos (por defecto: `PRJ_VAULT`)
- Organización en subcarpetas por año/mes
- Generación de índice

Si existe un `memoria_config.yaml`, se carga automáticamente y ofrece usar los valores preconfigurados.

---

## Conectar a Claude Desktop via MCP

Una vez listo el vault, añádelo a la configuración MCP de Claude Desktop:

**Ubicación:** `%APPDATA%\Claude\claude_desktop_config.json` (Windows) o `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac)

**Instalar el servidor MCP filesystem:**
```bash
npm install -g @modelcontextprotocol/server-filesystem
```

**Configuración:**
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "mcp-server-filesystem",
      "args": [
        "C:\\ruta\\a\\tu\\vault\\PRJ_VAULT"
      ]
    }
  }
}
```

Reinicia Claude Desktop. Claude puede ahora buscar y referenciar tu historial completo de conversaciones bajo demanda.

---

## Configuración

Edita `memoria_config.yaml` para establecer rutas y opciones persistentes:

```yaml
paths:
  base_vault: 'ruta/al/destino'
  exports_dir: 'ruta/a/exports/chatgpt'
  gizmo_map: 'ruta/al/gizmo_map.json'

options:
  prj_vault_name: 'PRJ_VAULT'
  by_year: true
  by_month: true
  make_index: true
  dry_run: false
  keep_hashes: false
```

### gizmo_map.json

Mapea IDs de proyectos/GPTs de ChatGPT a nombres legibles. Formato:

```json
{
  "g-abc123...": "nombre-de-proyecto",
  "g-xyz456...": "otro-proyecto"
}
```

**Cómo construir tu gizmo_map.json:**

1. Abre ChatGPT en el navegador y navega a cada Proyecto o GPT personalizado
2. Copia el ID de la URL — aparece después de `/g/` y tiene este formato `g-p-6bd...4a2`:
   ```
   https://chatgpt.com/g/g-p-6bd............4a2-nombre-del-proyecto
   ```
3. Copia el nombre del proyecto de la interfaz de ChatGPT
4. Añade ambos a tu `gizmo_map.json`:
   ```json
   {
     "g-p-6bd............4a2": "nombre-del-proyecto"
   }
   ```

Repite para cada proyecto. Las conversaciones sin ID mapeado se agruparán bajo `none/`.

---

## Estructura de archivos

```
MemorIA2GO/
├── MemorIA2GO.py           # Orquestador principal
├── split_chatgpt_export.py # Paso 1: Export → Markdown
├── project_organizer.py    # Paso 2: Organizar por proyecto
├── vault_dedup.py          # Paso 3: Deduplicar
├── config_loader.py        # Cargador de config YAML
├── memoria_config.yaml     # Configuración
├── gizmo_map.json          # Mapeo ID → nombre de proyecto
└── requirements.txt        # Dependencias Python
```

---

## Estructura del vault resultante

```
PRJ_VAULT/
├── mi-proyecto/
│   ├── 2025/
│   │   └── 11/
│   │       ├── 2025-11-13_titulo-conversacion.md
│   │       └── 2025-11-22_otra-conversacion.md
│   └── 2026/
├── otro-proyecto/
└── none/                   # Conversaciones sin proyecto asignado
```

---

## Logs

Cada ejecución genera un log en:
```
logs/memoria2go_YYYYMMDD_HHMM.log
```

---

## Estado del proyecto

**v1.0** — Pipeline estable, probado en producción

- Pipeline completo de 3 pasos: importar → organizar → deduplicar
- Config YAML con wizard de fallback
- Parsing robusto: exports ZIP, JSON, HTML
- Compatible con Windows y Mac
- Interfaz de terminal con Rich

---

## Licencia

Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International

---

## Autora

**V0ra** — Investigación independiente de seguridad en IA

GitHub: [github.com/V0raOnline/MemorIA2GO](https://github.com/V0raOnline/MemorIA2GO)
