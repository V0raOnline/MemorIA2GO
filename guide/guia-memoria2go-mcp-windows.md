# Recupera tu historial de ChatGPT en Claude Desktop
### Guía paso a paso para Windows · Sin conocimientos técnicos

---

## ¿Qué vas a conseguir?

Al terminar esta guía, Claude Desktop podrá leer y usar **todo tu historial de conversaciones de ChatGPT** como contexto. No una migración parcial de memorias — acceso real a todos tus chats, organizados por proyectos, con fechas y etiquetas, bajo demanda.

---

## Lo que necesitas antes de empezar

- Windows 10 o Windows 11
- Tu export de ChatGPT (si no lo tienes, ve al Paso 0)
- Python 3.9 o superior instalado
- Conexión a internet
- ~20 minutos

---

## Paso 0 — Exporta tus conversaciones de ChatGPT

1. Entra en [chat.openai.com](https://chat.openai.com)
2. Haz clic en tu avatar (abajo a la izquierda) → **Configuración**
3. Ve a **Privacidad de datos** → **Exportar datos**
4. Confirma el email que te llegará
5. Descarga el archivo `.zip` cuando llegue (puede tardar unos minutos)
6. Guárdalo en una carpeta, por ejemplo: `C:\Users\TuUsuario\chatgpt-export`

> No necesitas descomprimirlo — MemorIA2GO lo procesa directamente.

---

## Paso 1 — Descarga MemorIA2GO

MemorIA2GO convierte tu export de ChatGPT en archivos `.md` limpios, organizados por proyectos, listos para conectar con Claude Desktop via MCP.

1. Ve a [github.com/V0raOnline/MemorIA2GO](https://github.com/V0raOnline/MemorIA2GO)
2. Haz clic en **Code** → **Download ZIP**
3. Descomprímelo en una carpeta, por ejemplo: `C:\Users\TuUsuario\MemorIA2GO`

### Instala las dependencias

Abre **PowerShell** y ejecuta:

```powershell
cd C:\Users\TuUsuario\MemorIA2GO
pip install rich pyyaml beautifulsoup4 lxml
```

---

## Paso 2 — Instala Node.js

Node.js es el motor que necesita el servidor MCP para funcionar.

1. Ve a [nodejs.org](https://nodejs.org)
2. Descarga el botón verde **LTS** (versión estable)
3. Ejecuta el instalador `.msi` → Siguiente, Siguiente, Instalar
4. Cuando termine, abre **PowerShell** y verifica:

```powershell
node --version
```

Deberías ver algo como `v22.x.x`. Si lo ves, Node está listo.

---

## Paso 3 — Instala Claude Desktop

1. Ve a [claude.ai/download](https://claude.ai/download)
2. Descarga la versión para Windows
3. Instala normalmente
4. Ábrelo e inicia sesión con tu cuenta de Anthropic

---

## Paso 4 — Instala el servidor MCP de filesystem

Este servidor es el puente entre Claude Desktop y tu vault de `.md`.

Abre **PowerShell** y ejecuta:

```powershell
npm install -g @modelcontextprotocol/server-filesystem
```

Espera a que termine. Verás muchas líneas de texto — es normal.

---

## Paso 5 — Ejecuta MemorIA2GO

Abre **PowerShell** y ejecuta:

```powershell
cd C:\Users\TuUsuario\MemorIA2GO
python MemorIA2GO.py
```

El wizard te hará estas preguntas:

| Pregunta | Qué responder |
|---|---|
| Ruta al archivo de exportación | La carpeta donde guardaste el `.zip` de ChatGPT |
| Carpeta de destino para el vault | Donde quieres que se cree el vault, ej: `C:\Users\TuUsuario\mi-vault` |
| Ruta al gizmo_map.json | Déjalo vacío si no tienes uno (ver nota abajo) |
| Nombre del vault de proyectos | `PRJ_VAULT` (o el nombre que quieras) |
| ¿Organizar por año/mes? | S (recomendado) |
| ¿Generar índice? | S (recomendado) |

MemorIA2GO ejecutará 3 pasos automáticamente:
1. **Convierte** el export a archivos `.md` con frontmatter
2. **Organiza** las conversaciones por proyecto en subcarpetas
3. **Deduplica** eliminando copias redundantes del export

Al terminar tendrás una carpeta `PRJ_VAULT` con todas tus conversaciones limpias y organizadas.

> **Sobre el gizmo_map.json:** Si tus chats están agrupados por proyectos en ChatGPT, puedes crear este archivo para que las carpetas del vault tengan nombres legibles. Ve a cada proyecto en `chatgpt.com`, copia el ID de la URL (`g-p-6bd...4a2`) y el nombre del proyecto, y añádelos al archivo. Sin el mapa, las conversaciones sin proyecto se agrupan en `none/`.

---

## Paso 6 — Configura Claude Desktop para leer tu vault

Ahora tienes que decirle a Claude Desktop dónde están tus archivos.

### Abre el archivo de configuración

En PowerShell, ejecuta:

```powershell
notepad "$env:APPDATA\Claude\claude_desktop_config.json"
```

Si Notepad pregunta si quieres crear el archivo, di que **sí**.

### Pega esta configuración

Reemplaza **todo** el contenido del archivo por esto, cambiando la ruta por la tuya real:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "mcp-server-filesystem",
      "args": [
        "C:\\Users\\TuUsuario\\mi-vault\\PRJ_VAULT"
      ]
    }
  }
}
```

> **Importante con las rutas:**
> - Usa doble barra invertida `\\` entre carpetas
> - La ruta apunta a la carpeta `PRJ_VAULT` dentro de tu vault
> - Ejemplo real: `"G:\\Mis Documentos\\mi-vault\\PRJ_VAULT"`

Si tienes los archivos en **varias carpetas** (por ejemplo, el vault de ChatGPT y un vault de Obsidian), añade las rutas separadas por comas:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "mcp-server-filesystem",
      "args": [
        "C:\\Users\\TuUsuario\\mi-vault\\PRJ_VAULT",
        "C:\\Users\\TuUsuario\\obsidian-vault"
      ]
    }
  }
}
```

Guarda el archivo (`Ctrl + S`) y cierra Notepad.

---

## Paso 7 — Reinicia Claude Desktop

Cierra Claude Desktop completamente:

1. Haz clic derecho en el icono de Claude en la **barra de tareas** (abajo a la derecha, cerca del reloj)
2. Selecciona **Cerrar** o **Quit**
3. Vuelve a abrir Claude Desktop desde el menú inicio

---

## Paso 8 — Verifica que funciona

Abre un chat nuevo en Claude Desktop y escribe:

```
¿Qué archivos tienes disponibles en mi vault?
```

Si Claude responde listando carpetas y archivos `.md`, todo está funcionando.

---

## Cómo usarlo en la práctica

Claude no lee todos tus archivos automáticamente — accede a ellos cuando se lo pides. Algunos ejemplos:

- *"Busca en mis notas conversaciones sobre productividad"*
- *"¿Qué decidí sobre X según mis chats anteriores?"*
- *"Lee el archivo llamado 2024-03-15-proyecto-trabajo.md"*
- *"¿Hay alguna nota donde hable de mi método de trabajo?"*
- *"¿Qué conversaciones tengo en el proyecto club-201?"*

Esto es más potente que la memoria automática: tú controlas qué contexto activas y cuándo.

---

## Solución de problemas frecuentes

| Problema | Causa probable | Solución |
|---|---|---|
| `node no se reconoce` | Node no instalado o sesión no reiniciada | Cierra y reabre PowerShell tras instalar Node |
| `MCP filesystem: Server disconnected` | Problema con el servidor global | Asegúrate de haber hecho el `npm install -g` del Paso 4 |
| Claude no ve los archivos | Ruta incorrecta en el config | Verifica que la ruta apunta a `PRJ_VAULT`, no al vault raíz |
| El archivo config no existe | Primera vez | Notepad lo crea al guardar — normal |
| `pip no se reconoce` | Python no instalado o no en el PATH | Descarga Python desde python.org e instala marcando "Add to PATH" |

---

## Qué diferencia esto de la migración oficial de Anthropic

La herramienta de migración de Anthropic importa únicamente las **memorias explícitas** que ChatGPT guardó sobre ti — un resumen plano y limitado. Si no tenías memoria activada, no migra nada.

MemorIA2GO da acceso a **todo el historial real**: cada conversación completa, organizada por proyecto, con su fecha y contexto. No es una migración — es infraestructura.

---

*Guía elaborada a partir de una instalación real en Windows 11 · MemorIA2GO + MCP filesystem server*
