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

### MUSIC·0LOGY — una herramienta hermana compartiendo casa

Suno vive aparte de los cuatro pasos de arriba, y a propósito. **No tiene export**: la única forma de sacar tu biblioteca es pedírsela a su API, con la sesión iniciada, con un token que copias del navegador y que caduca en minutos. El pipeline de M3M0R·IA no sale a Internet por su cuenta — así que Suno tiene su propia pestaña, su propio pipeline y su propio paso manual, en vez de forzarlo a ser un proveedor que no es.

Qué hace: descarga tu biblioteca (audio, portadas y metadatos), verifica que el backup está íntegro, y construye un vault de Obsidian aparte con una nota por pista — incluyendo el **linaje real** entre covers, remixes y mashups, resuelto como enlaces. Los árboles de 60+ variantes son normales; los códigos Dewey los mantienen navegables, y el badge `Full Song` marca cuál es la versión terminada.

También asoma al Observatorio: pistas, duración total, favoritas, canciones completas y proyectos.

La regla que lo gobierna merece enunciarse con precisión, porque la versión corta ("el pipeline nunca hace peticiones salientes") prohibiría esto y no debería: **la aplicación nunca sale a Internet por iniciativa propia — sale cuando le pones un token en la mano y pulsas.** Si algo de esto te suena a criptología, ve a [la guía del token](#el-token-de-suno-o-la-llave-de-tu-propia-casa).

### Tintero — el archivo de lo que publicaste

Substack **sí tiene export**, a diferencia de Suno: un zip que te descargas del panel. Así que aquí el obstáculo no fue la adquisición, fue el modelo — **un post no es una conversación**. Antes de que existiera Tintero, ese zip entraba por los cuatro pasos y salía convertido en un diálogo falso: los 109 posts se leían como *una* conversación de 108 mensajes alternando "usuario" y "asistente" con los párrafos de un solo artículo, y los otros 108 posts desaparecían sin hacer ruido. Ahora el pipeline lo reconoce y lo **rechaza en voz alta**, y Tintero lo recoge por su propia puerta. Misma carpeta de entrada, dos puertas distintas.

Qué hace: convierte cada post en una nota de Obsidian con el cuerpo en Markdown, y distingue **publicados, retirados y borradores** — porque un borrador con fecha y métricas no es un borrador, es algo que publicaste y luego bajaste. Si le pasas el CSV de estadísticas que se descarga aparte, recupera además dos cosas que el export **no** trae: la **sección** y las **etiquetas** de cada post, que son las que hacen que el grafo se ordene solo.

Tiene su propia pestaña, con dos pasos: **verificar** —qué trae el export, cuánto cruza el CSV, cuántos CSV de suscriptores se ignoran y, sobre todo, **qué no viene**— y **construir**. También asoma al Observatorio con posts, palabras, publicados y borradores: las cuatro cifras salen del zip, así que la tarjeta está completa aunque no hayas descargado el CSV, y si no hay export no se pinta en vez de mentir con ceros.

Y desde la terminal, si lo prefieres:

```bash
python substack/build_substack_vault.py --exports-dir "TU_CARPETA_DE_EXPORTS" --vault-dir "TU_VAULT_DE_TINTERO" --stats "ruta/al/email_stats_AAAA-MM-DD.csv"
```

Las métricas van **fechadas** dentro de la nota, no sueltas: un `views: 55` sin fecha miente con aplomo seis meses después. Cada CSV nuevo sobrescribe la foto; el histórico vive en los propios ficheros, que ya llevan la fecha en el nombre.

El vault se construye con dos índices propios: `_indice.md`, con las cifras y el archivo en cronología inversa por año y mes, más bloques aparte para los retirados y los borradores; y `_secciones.md`, con tu taxonomía. Ese segundo **solo existe si le has dado el CSV** — sin él no se fabrica una categoría "sin clasificar", porque pintaría como dato lo que en realidad es una fuente que no descargaste.

Un detalle que se nota al mirar el vault: las etiquetas se normalizan al escribirlas (`bitácora glitch` → `bitácora-glitch`). Obsidian no admite espacios dentro de una etiqueta y, sin ese cambio, quedan en el fichero pero muertas — ni panel de etiquetas ni grafo. Los acentos se conservan.

Dos ausencias que conviene saber de antemano, porque son del export y no de la herramienta: **los comentarios no viajan** (ninguno) y **las imágenes tampoco** — solo sus URLs remotas, que la nota conserva.

Y una advertencia que la herramienta te da sola: el zip de Substack arrastra **datos personales de tus suscriptores** — emails, y en las aperturas también país, ciudad y dispositivo. Tintero los cuenta para decírtelo en voz alta y **no los lee nunca**. No son tu memoria: son datos de otras personas que están a tu cargo.

---

## Cómo funciona

El pipeline corre en 4 pasos no destructivos:

**Paso 1 — Importar** (`split_chatgpt_export.py` + adaptadores en `providers/`)
Cada export válido y pendiente en tu carpeta de exports se detecta por estructura y se despacha a su adaptador. Una nota Markdown por conversación aterriza en `RAW_VAULT`, con frontmatter YAML (título, fecha, proveedor, origen, mapeo de proyecto). Las ramas de regeneración descartadas quedan excluidas — solo el hilo que de verdad conservaste.

**Paso 2 — Fusionar** (`vault_merge.py`)
Consolida variantes de la misma conversación entre exports en `MERGED_VAULT` sin perder mensajes: la variante más larga gana como campeona, y cualquier mensaje que le falte se recupera de las demás.

**Paso 3 — Proyectos** (`project_organizer.py`)
Construye `PRJ_VAULT` como una vista de proyecto/año/mes de MERGED. Se refresca en cada corrida (symlinks donde el sistema operativo lo permite, copias reales en Windows).

**Paso 4 — Índices** (`tree_index.py`, `scaffolding_index.py`, `image_index.py`, `vault_stats.py`)
Índices de navegación (proyecto/año/mes), índice de uso de adjuntos, índice de imágenes, y la caché de estadísticas que alimenta el dashboard.

### Cuándo lanzar qué

- **Importar pendientes (paso 1→4)** — el modo del día a día: soltaste exports nuevos en tu carpeta y quieres que entren. Solo procesa lo que aún no se había importado.
- **Solo actualizar (paso 2→4)** — no hay datos nuevos, pero cambió cómo se consolida u organiza: tras nombrar gizmos, o tras una actualización de M3M0R·IA que toque la fusión, la vista de proyectos o los índices.
- **Reprocesar todo** — tras una versión de M3M0R·IA que añade o cambia campos del frontmatter (`provider`, `conv_id`, `model`...) o modifica los parsers: las notas existentes solo ganan campos nuevos si se re-importan desde los exports. Seguro (los exports son la fuente de verdad, nada se destruye) pero tarda proporcionalmente a tu historial — café recomendado.
- **Generar índice de temas** (pestaña Cartografía) — cada vez que edites temas; no hace falta reiniciar. El paso 4 también lo regenera automáticamente en cada corrida del pipeline.

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

## Nunca he usado una terminal: guía paso a paso

¿Todo lo de arriba sonó a chino? Esta sección es para ti. Sin conocimientos previos, en Windows, paso a paso.

**1. Instala Python.**
Ve a [python.org/downloads](https://www.python.org/downloads/) y pulsa el botón amarillo de descarga. Al ejecutar el instalador, **marca la casilla "Add Python to PATH"** (abajo del todo, fácil de pasar por alto — es el paso más importante de todos). Luego "Install Now" y espera.

**2. Descarga este proyecto.**
En esta página de GitHub, pulsa el botón verde **Code** → **Download ZIP**. Extrae el ZIP donde quieras — por ejemplo `C:\M3M0RIA`. (Clic derecho en el ZIP → "Extraer todo".)

**3. Abre una consola.**
Pulsa la tecla Windows, escribe `powershell` y pulsa Enter. Se abre una ventana azul o negra con texto: eso es la consola o terminal. Se usa escribiendo comandos y pulsando Enter. No muerde.

**4. Entra en la carpeta del proyecto.**
Escribe esto (o cópialo y pégalo con clic derecho) y pulsa Enter — ajusta la ruta si lo extrajiste en otro sitio:

```
cd "C:\M3M0RIA"
```

**5. Instala lo que el programa necesita.**
Copia esto, pega, Enter:

```
pip install -r requirements.txt
```

Va a desfilar un muro de texto durante un rato. Es normal: está descargando las piezas que usa el programa. Cuando vuelva el cursor, ha terminado.

**6. Crea tu configuración.**
Copia, pega, Enter:

```
copy memoria_config.yaml.example memoria_config.yaml
notepad memoria_config.yaml
```

Se abre el Bloc de notas con la configuración. Solo necesitas ajustar dos rutas: `base_vault` (la carpeta donde vivirá tu vault de notas — sirve una carpeta vacía nueva) y `exports_dir` (la carpeta donde soltarás los ZIP que te descargues de ChatGPT/Claude/Grok). Guarda y cierra.

**7. Consigue tus exports.**
- **ChatGPT**: Configuración → Controles de datos → Exportar datos. Te llega un email con un ZIP.
- **Claude**: Configuración → Privacidad → Exportar datos. Te llega un email con un ZIP (a veces varios).
- **Grok**: Configuración → Datos → Descarga tus datos.

Suelta los ZIP tal cual (no los descomprimas) en la carpeta que pusiste como `exports_dir`.

**8. Lanza M3M0R·IA.**
En la consola:

```
python launcher.py
```

Tu navegador se abre con la interfaz. A partir de aquí, todo son clics: pestaña **Configuración** para revisar rutas, **Verificación** para comprobar que tus ZIP se reconocen, y **Construcción** → "Importar pendientes" para lanzar la conversión. El log en vivo te cuenta qué está haciendo. Cuando termine, abre la carpeta de tu vault con Obsidian y disfruta.

**Si algo falla:**
- *"python no se reconoce como un comando..."* → no marcaste la casilla de PATH del paso 1. Reinstala Python marcándola, cierra la consola y abre una nueva.
- *"pip no se reconoce..."* → lo mismo que arriba.
- No se abre la ventana del navegador → escribe a mano `http://127.0.0.1:8765` en tu navegador.

---

## El token de Suno, o la llave de tu propia casa

¿Token, F12, cabeceras? Esta sección es para ti. No hace falta saber programar: es copiar un texto largo de una pantalla a otra. Lo raro es dónde está escondido.

### Por qué este paso es manual

Los demás proveedores te dan un botón de "exportar mis datos" y un ZIP. **Suno no.** Tu biblioteca solo se puede pedir a su API, y la API quiere una prueba de que eres tú.

Esa prueba es el **token**: un pase temporal que tu navegador ya tiene desde que iniciaste sesión. Vive unos minutos y caduca solo. No hay nada que guardar, ni credenciales que meter en un archivo de configuración — por eso el paso no se automatiza, y por eso lo haces tú cada vez.

Conviene decirlo claro: **mientras dura, ese token vale por ti**. Quien lo tenga puede pedirle a Suno lo mismo que tú. No lo pegues en ningún sitio que no sea esta aplicación, no lo mandes por chat y no lo publiques en una captura de pantalla. Caduca rápido, que es la buena noticia.

M3M0R·IA lo trata en consecuencia: viaja en el cuerpo de la petición y no por la barra de direcciones, se le pasa al proceso por su entorno y no por la línea de comandos, se censura del log antes de que llegue a tu pantalla, y no se guarda en ningún sitio. Se va contigo al cerrar la pestaña.

### Sacarlo, paso a paso

**1. Abre tu biblioteca en Suno.**
Ve a [suno.com](https://suno.com) con tu sesión iniciada, a la pantalla donde ves tus canciones.

**2. Abre las herramientas de desarrollo.**
Pulsa `F12`. Si tu teclado tiene tecla `Fn`, quizá sea `Fn`+`F12`. Se abre un panel, al lado o debajo, lleno de pestañas: es la consola que trae de fábrica cualquier navegador. Mirar no rompe nada.

**3. Ve a la pestaña «Network».**
En algunos navegadores se llama «Red». Estará vacía: solo registra lo que pasa *mientras* está abierta. Así que **refresca la página** (`F5`) sin cerrar el panel. Verás llenarse una lista — cada línea es una petición que tu navegador le hace a Suno.

**4. Busca con la lupa.**
En esa misma pestaña hay un icono de **lupa**. Ábrelo y escribe `bearer`. Esta búsqueda mira *dentro* de las peticiones, no solo en sus nombres, que es exactamente lo que hace falta: el token va dentro. Te señalará las líneas que lo llevan.

**5. Ponte en la vista «Headers».**
Haz clic en uno de los resultados. Se abre un panel de detalle con sus propias pestañas: **Headers** (o «Cabeceras»), Payload, Response... **Tienes que estar en Headers.** En las otras vistas el token no aparece, y es donde más gente se atasca.

**6. Copia el token.**
Busca la línea `Authorization: Bearer eyJ...` y copia **solo lo que va después de la palabra «Bearer»**: una tira larguísima de letras y números que empieza por `eyJ`. Sin la palabra «Bearer», sin comillas y sin espacios al principio.

**7. Pégalo en la pestaña MUSIC·0LOGY** y pulsa «Descargar biblioteca».

### Si algo no cuadra

- **No encuentro ninguna línea con `Authorization`.** Refresca la página con el panel abierto. Si la lista sigue vacía, comprueba que estás en Network y no en Console.
- **Lo pegué y dice que no vale.** Puede que hayas copiado la palabra «Bearer» delante, o un espacio. También puede que hayas cogido una petición a `clerk.suno.com`: esas llevan token pero no sirven. Las buenas van a `studio-api`.
- **La descarga se cortó a la mitad.** Casi siempre es que el token caducó. Saca uno nuevo repitiendo estos pasos y vuelve a lanzarla: **retoma donde se quedó**, no empieza de cero.
- **Se me ha olvidado todo esto.** Está también dentro de la aplicación: en la pestaña MUSIC·0LOGY, el desplegable «¿Esto te suena a criptología? Ábreme».

---

## Configuración

- `memoria_config.yaml` — tus rutas (vault base, carpeta de exports, mapa de gizmos) y opciones (carpetas por año/mes, generación de índice). Se crea desde `memoria_config.yaml.example`; nunca se commitea.
- `gizmo_map.json` — mapea IDs de proyecto (gizmo) de ChatGPT a nombres humanos. Se cura desde la interfaz web (pestaña Cartografía); nunca se commitea.
- `topic_map.json` — tus temas para conversaciones sin asignar: `{"tema": ["palabras", "frases", "campo=valor"]}`. Se cura desde la interfaz; genera notas de índice enlazadas en `MERGED_VAULT/_Temas`. Nunca se commitea.
- `substack_vault` (en `memoria_config.yaml`) — dónde se construye el vault de Tintero. Es la **única** ruta que necesita: el export de Substack y su CSV de estadísticas viven en tu carpeta de exports de siempre, porque el pipeline de conversaciones los rechaza y Tintero los recoge de ahí. Una carpeta, dos puertas.
- `suno_backup` y `suno_vault` (en `memoria_config.yaml`) — las dos rutas de MUSIC·0LOGY: dónde vive el backup crudo de Suno, y dónde se construye su vault de Obsidian. Las dos opcionales: sin `suno_backup` la tarjeta del Observatorio simplemente no aparece — no se pinta a cero, porque decir "0 pistas" sobre una biblioteca que no has descargado es mentir, no informar.

Los exports de Claude y Grok no enlazan conversaciones a proyectos: esas notas se organizan por temas (varios-a-varios), no por carpetas.

---

## Cómo evolucionó este proyecto

- **v1** era un pipeline solo por CLI, solo ChatGPT, de 3 pasos: importar, organizar por proyecto, indexar.
- **v2** (actual) creció en cuatro direcciones, cada una impulsada por un fallo real o una necesidad real:
  - **La fusión se convirtió en su propio paso.** La deduplicación solía ser destructiva; ahora las variantes se consolidan sin perder un solo mensaje, y se conserva la procedencia de la campeona.
  - **Adaptadores multi-proveedor.** Los exports de Claude y Grok se diseccionaron contra datos reales antes de escribir una sola línea de código. La detección es estructural — un zip de Claude también contiene un `conversations.json`, y la raíz de Grok también tiene una clave `conversations`, así que detectar por nombre de archivo produciría basura en silencio. Cada adaptador reconstruye el hilo activo de conversación según el modelo de ramas propio de su proveedor.
  - **Una interfaz web (M3M0R·IA).** Dashboard con gráficos de evolución, estadísticas por proveedor y por proyecto, verificación previa que identifica el proveedor de cada export (y rechaza honestamente lo que aún no sabe parsear), lanzador del pipeline con log en vivo, y curación de proyectos huérfanos.
  - **Rendimiento por diseño.** Las estadísticas se calculan una vez por corrida del pipeline y se cachean atómicamente; el dashboard lee la caché en milisegundos sin importar el tamaño del vault.
  - **Cartografía en vez de taxonomía forzada.** Las conversaciones sin asignar no se embuten en carpetas: una nube de vocabulario (sembrada con nombres de proyecto de los tres proveedores) alimenta un sistema de Temas varios-a-varios — palabras, frases y reglas de metadatos `campo=valor` — que genera índices enlazados en Obsidian. La curación vive en una entrada por tema, el índice derivado es regenerable, las notas quedan intactas.
  - **Identidad vía `conv_id`.** El ID nativo de cada conversación viaja al frontmatter y la fusión agrupa por él: los renombrados de hilo entre exports (medido: 21 de 593 conversaciones reales) se fusionan bajo el título más reciente conservando `titulo_original`, en vez de duplicarse como fantasmas.
- **v2.5** hizo el proyecto testeable en vez de solo probado a mano:
  - **Un suite de regresión de verdad.** Fixtures sintéticos para los tres proveedores (sin datos personales) cubren adaptadores, detección previa, fusión de renombrados de hilo, y el sistema de temas — cada bug real cazado durante el desarrollo tiene ahora un test que lo habría cazado antes. Se lanza con `pip install -r requirements-dev.txt && python -m pytest tests/`.
  - **Detección de deriva de formato.** Cada adaptador ahora declara los campos que realmente lee. Un chequeo profundo opcional muestrea las conversaciones reales de un export y avisa de campos nunca vistos — el mismo tipo de cambio que una vez hizo desaparecer en silencio un lote entero de proyectos de ChatGPT. Desactivado por defecto (tiene que leer el export completo, que no es gratis en uno grande); un clic en Verificación lo activa.
  - **Un autocompletado de rutas que no trunca.** Las sugerencias nativas de ruta del navegador cortaban las rutas largas de Windows sin forma de ver el resto. Reemplazado por un desplegable pequeño que envuelve en vez de recortar.
  - **Verificaciones previas colapsables.** El chequeo de la carpeta de exports solía volcar el estado de cada fichero en pantalla de golpe. Ahora es una sola línea — semáforo más resumen de una frase — que se despliega a la lista por fichero solo cuando quieres mirar, y cada fichero se despliega otra vez a su detalle completo.
- **v2.6 reconstruyó cómo se guardan las imágenes y el contenido generado**, tras un chequeo rutinario que destapó un bug real de clasificación:
  - **El bug**: la generación nativa de imágenes *más nueva* de ChatGPT (el flujo "genera una imagen" in-context, a diferencia de la llamada clásica a la herramienta DALL·E) no rellena el campo que el pipeline comprobaba para el prompt. Resultado: **5117 imágenes generadas por IA en un historial real de 47 exports se estaban archivando como subidas del usuario.** Confirmado y arreglado comprobando el ID de generación en vez del texto del prompt.
  - **Taxonomía nueva.** Los assets ya no se vuelcan en un único `IMAGE_BANK` compartido. Cada proveedor tiene bancos divididos por *qué es realmente el contenido*: `CHATGPT/GENERADAS` vs `CHATGPT/ADJUNTOS`, `GROK/GENERADAS_IMAGEN` / `GROK/GENERADAS_VIDEO` / `GROK/ADJUNTOS`, `CLAUDE/ARTEFACTOS/<tipo>` (markdown, html, código por lenguaje, etc.). Cada banco tiene su propio índice navegable.
  - **Los adjuntos de Grok y las generaciones de Imagine ahora se extraen de verdad** (antes solo una referencia de texto — ver la tabla de proveedores más arriba). Las generaciones de Imagine sin binario en el export (la mayoría en la práctica: solo ~18% de las generaciones de un export real viajan en el zip) se registran con su prompt y enlace original para descargar a mano más tarde, a propósito — esta herramienta nunca contacta con la red en tu nombre.
  - **Los Artefactos de Claude ahora se extraen**, resueltos a su estado *final*: un artefacto revisado una docena de veces en una sola conversación antes era invisible; ahora es un fichero limpio, no un montón de revisiones casi-duplicadas.
  - **Una herramienta reutilizable de re-enlazado** (`relink_assets.py`) reescribe los enlaces de assets por todo el vault cuando un banco se mueve o se renombra — es la segunda vez que pasa esto, y no será la última, así que ahora es una herramienta de verdad en vez de un script de usar y tirar.
  - **Un bug latente en seis scripts distintos**, encontrado al lanzar esta misma migración: un atajo de compatibilidad heredado de una reorganización anterior podía apuntar a la nada (p.ej. tras vaciar la vieja carpeta compartida de imágenes), y el código de escaneo de ficheros usado en todas partes no tenía forma elegante de manejarlo — simplemente dejaba de escanear en mitad del vault, sin explicación. Arreglado una vez, centralizadamente, y ahora cubierto por un test que reproduce el escenario exacto del atajo roto en vez de confiar en que no vuelva a pasar.
- **v2.7 reemplazó los viejos índices de imágenes por banco con un índice de contenido por proveedor**:
  - **Un archivo por proveedor** (`_index_chatgpt.md`, `_index_claude.md`, `_index_grok.md`) en vez de uno por banco. Cada banco dentro es su propia rama colapsada, y cada conversación dentro de esa rama también colapsa — `<details>` nativo de Obsidian, sin plugins.
  - **La lista de pendientes de descarga de Grok vive en su propia nota** (`_grok_pendientes.md`), ordenada por más reciente primero, separada del índice principal para no ensuciar lo que ya está descargado.
  - **El índice de Claude muestra solo un enlace y un resumen corto** — nunca el contenido completo del artefacto inline, ya que eso ya vive en el propio fichero del artefacto y en la nota de conversación.
  - **Un bug cazado en su propia verificación**: las carpetas de banco viven junto a `MERGED_VAULT`/`PRJ_VAULT` bajo el vault base, no dentro de ellos — un valor por defecto que asumía lo contrario producía en silencio captions vacíos y, para bancos sin notas que rastrear (las generaciones de Imagine de Grok), un catálogo vacío pese a haber ficheros reales en disco. Arreglado con una ruta de vault base explícita, con un test que separa a propósito ambas rutas para que el hueco no vuelva a abrirse sin que se note.
  - **Los tres archivos de índice viejos por banco se retiran automáticamente** en cada corrida, ya que el nuevo índice por proveedor los sustituye por completo.
- **v2.8 retiró `IMAGE_BANK` para siempre y le dio a la interfaz web una identidad de verdad**:
  - **La tarjeta de assets del dashboard estaba midiendo en silencio una carpeta vacía.** `IMAGE_BANK` se había migrado por completo en v2.6, pero el código de estadísticas nunca dejó de apuntar ahí — la tarjeta simplemente leía 0/0 B para siempre. Reconstruida para contar los bancos reales (incluyendo artefactos de Claude y vídeo de Grok, no solo imágenes), con un total más un desglose por proveedor y tipo.
  - **`IMAGE_BANK` en sí ha desaparecido**, no solo ha quedado sin uso: el mecanismo de junction que lo enlazaba antes a cada vault (`ensure_image_bank_junction`) se ha retirado del pipeline, y los tres junctions sobrantes más la carpeta vacía se limpiaron del vault real tras confirmar que cero notas reales dependían aún de ellos. La vieja herramienta standalone `image_index.py` para la que existía también ha desaparecido, superada por `content_index.py`.
  - **La interfaz ganó un nombre, no solo una UI.** "Pipeline" y "Dashboard" eran genéricos — el resto de la app habla de reconstruir memoria a partir de ficheros de export, y esos dos no lo hacían. Renombrados a **Observatorio**, **Configuración**, **Verificación**, **Construcción**, **Cartografía**, cada una con su propia cabecera: una frase de "qué haces aquí", un eslogan de marca consistente debajo, y una pequeña mascota ilustrada por sección.
  - **Una pestaña nueva, Reconexión, cierra un hueco real.** Regenerar índices por sí solo nunca iba a hacer aparecer un fichero de Grok descargado a mano — el catálogo lee del *manifest* del asset, no de la carpeta, así que un fichero soltado a mano sin entrada de manifest se quedaba invisible. Reconexión lista los pendientes de descarga de Grok, acepta el fichero por subida (nunca una ruta escrita a mano — el servidor elige el banco y calcula el mismo nombre basado en hash que calcularía el extractor automático), y un botón separado "Regenerar índices" relanza solo el paso de indexado (`--reindex-only`) sin un reproceso completo.

- **v2.10 trajo una herramienta hermana a la casa: MUSIC·0LOGY.** Suno vivía en un repositorio aparte, porque parecía que no encajaba — M3M0R·IA asume conversaciones, y una pista es un evento de generación con linaje padre→hijo. Ese razonamiento era medio correcto: juzgaba el paso 1. El obstáculo decisivo resultó ser otro. M3M0R·IA come ficheros quietos en una carpeta; Suno no tiene export ninguno, solo una API autenticada. Así que se integró **en la interfaz, no en el pipeline**: su pestaña, su pipeline, su paso manual. La regla de producto sobrevive, enunciada con más precisión — la aplicación no sale a Internet por iniciativa propia, sale cuando le pones un token en la mano y pulsas. La biblioteca asoma también al Observatorio, y hay guía paso a paso para quien nunca ha abierto DevTools.

Principios de diseño en todo momento: diagnosticar antes de implementar, validar contra exports reales, nunca destruir datos, y que los fallos sean ruidosos y honestos en vez de silenciosos.

---

## Roadmap

- Selector manual conversación↔proyecto para casos residuales (namespace `manual:` en gizmo_map, diseñado y diferido hasta que el montón de conversaciones sin asignar se reduzca más)
- Extracción de assets para los adjuntos `.dat` del export fragmentado de ChatGPT 2026+ (un formato binario distinto al ya soportado)
- Distinguir "nunca tuvo proyecto" de "tiene un proyecto que nadie ha nombrado todavía" en `Project_name` — hoy ambos colapsan a `none`
- Un tipo de tool-call `image_group` de ChatGPT que el parser aún no reconoce y se cuela en crudo en el texto de la nota — hace falta una muestra real de export para fijar la ruta de código exacta antes de arreglarlo

---

## Licencia

CC BY-NC-SA 4.0 — ver el badge de arriba.
