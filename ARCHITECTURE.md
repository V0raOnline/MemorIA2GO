# Arquitectura

> **¿Qué pregunta responde este documento?**
> *¿Cómo funciona por dentro, y por qué así y no de otra manera?*

Para instalarlo y arrancarlo, ve al [README](README.md). Esto es para quien quiere entender el diseño.

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

## Los adaptadores, proveedor a proveedor

Cada proveedor exporta a su manera y cada uno esconde su propia trampa. Lo que sigue es lo que hay que saber para tocar un adaptador — vive aquí y no en el README porque responde "cómo funciona", no "qué es".

**Proveedores soportados** (detección por estructura interna del JSON, nunca por nombre de archivo):

| Proveedor | Formato del export | Gestión de ramas | Adjuntos |
|----------|--------------|-----------------|-------------|
| ChatGPT  | zip / json / html | recorrido del árbol por `current_node` | imágenes generadas por IA y subidas del usuario extraídas a bancos separados (`CHATGPT/GENERADAS`, `CHATGPT/ADJUNTOS`) |
| Claude   | zip (puede llegar en partes `batch-NNNN`) | reconstrucción por la hoja más reciente (el export no trae `current_node`) | texto extraído citado inline; los binarios subidos no vienen en el export; los **Artefactos generados** (documentos, código, HTML...) se extraen a `CLAUDE/ARTEFACTOS`, un fichero por artefacto, clasificados por tipo — solo la versión final, el historial de revisiones se descarta |
| Grok     | zip (estructura `ttl/30d/...`) | `leaf_response_id` cuando existe, si no la hoja más reciente | adjuntos extraídos a `GROK/ADJUNTOS`; las generaciones de Imagine (imagen y vídeo) se extraen a `GROK/GENERADAS_IMAGEN`/`GROK/GENERADAS_VIDEO` cuando el export trae el binario, si no se registran como lista de pendientes de descarga (prompt + enlace), nunca se descargan solas |

Todos los proveedores conviven en un único vault fusionado (MERGED). Cada nota lleva `provider` y `source` en su frontmatter, así que puedes filtrar, colorear e indexar por origen. Cada banco de assets tiene su propio índice navegable, mismo patrón que el índice de imágenes clásico.

Los tres tienen en común lo que de verdad importa: **las ramas descartadas se quedan fuera.** Cuando regeneras una respuesta, el export conserva el árbol entero; el adaptador camina hasta la hoja vigente y descarta el resto, así que el vault refleja la conversación que de verdad tuviste y no todos los intentos.

---

## Las herramientas hermanas

Ni la música ni Substack pasan por los cuatro pasos de arriba, y en cada caso por un motivo distinto. Merece la pena leer los dos juntos, porque la frontera se trazó dos veces con criterios que no se parecen.

### MUSIC·0LOGY — la música

MUSIC·0LOGY tiene **dos fuentes, Suno y Flow Music**, y las dos viven aparte de los cuatro pasos de arriba por el mismo motivo: **no tienen export**. La única forma de sacar tu biblioteca es pedírsela a su API, con la sesión iniciada, con un token que copias del navegador y que caduca en minutos. El pipeline de M3M0R·IA no sale a Internet por su cuenta — así que la música tiene su propia pestaña, sus propios pipelines y su propio paso manual, en vez de forzarla a ser un proveedor que no es.

La regla que lo gobierna merece enunciarse con precisión, porque la versión corta ("el pipeline nunca hace peticiones salientes") prohibiría esto y no debería: **la aplicación nunca sale a Internet por iniciativa propia — sale cuando le pones un token en la mano y pulsas.** Si algo de esto te suena a criptología, ve a [la guía del token](ME_HE_ATASCADO.md).

Lo que hacen las dos, con los mismos tres botones: descargan tu biblioteca (audio, portadas y metadatos), verifican que el backup está íntegro, y construyen **un vault de Obsidian por fuente** con una nota por pista, incluyendo el **linaje real** entre versiones resuelto como enlaces. Los árboles de decenas de variantes son normales, y los códigos Dewey los mantienen navegables. Las descargas van a un `.part` que solo se renombra cuando el tamaño cuadra con el `Content-Length`, así que un corte a mitad no deja un audio truncado haciéndose pasar por completo. Las dos asoman al Observatorio con su propia tarjeta.

Ahí se acaba el parecido. Son dos pipelines y no uno con un `if` porque las dos APIs no se parecen en lo que importa:

**Suno** tiene un feed plano de biblioteca: se pagina y ya está. Agrupa por **proyectos**, el linaje sale de `cover_clip_id` y del mashup, y el badge `Full Song` marca cuál es la versión terminada.

**Flow Music no tiene biblioteca.** Es un producto de chat, y las pistas cuelgan de las conversaciones: para enumerarlas hay que recorrer conversaciones. Lo que agrupa de verdad es la conversación en la que se generaron — `project_id` viene a `null` en todas las pistas, así que agrupar por proyecto habría dado un montón único. El linaje sale de `source_clip_ids`, y los badges se derivan de `op_type` (`audio__create_song`, `audio__render_edit`, `audio__split_stems`…), que dice más que el `task` de Suno; un `op_type` que no esté en el mapa se etiqueta *Otro* en vez de callarse. Descarga m4a **y** wav, pero al vault solo se copia el m4a: el wav es archivo y son ~5 GB, el vault está para escuchar y navegar, y la nota dice dónde quedó el wav.

Se retoman distinto, y eso importa cuando el token te caduca a mitad de una descarga larga: Suno reanuda por número de página, Flow Music guarda el `last_message_at` de cada conversación ya recorrida y solo vuelve a leer las que cambiaron. Es lo correcto para su modelo — si reordenas o añades pistas, seguir contando páginas deja de cuadrar.

Y una diferencia que se nota en el Observatorio: 15 de las 174 pistas reales de Flow Music no tienen duración, porque Flow nunca la calculó (`duration_status: "not_requested"`). No se cuentan como cero: se ignoran para la media, pero cuentan como pistas. Decir "0:00" de algo que existe es mentir, igual que pintar "0 pistas" sobre una biblioteca que todavía no has descargado.

### Tintero — lo que publicaste

Substack **sí tiene export**, a diferencia de la música: un zip que te descargas del panel. Así que aquí el obstáculo no fue la adquisición, fue el modelo — **un post no es una conversación**. Antes de que existiera Tintero, ese zip entraba por los cuatro pasos y salía convertido en un diálogo falso: los 109 posts se leían como *una* conversación de 108 mensajes alternando "usuario" y "asistente" con los párrafos de un solo artículo, y los otros 108 posts desaparecían sin hacer ruido. Ahora el pipeline lo reconoce y lo **rechaza en voz alta**, y Tintero lo recoge por su propia puerta. Misma carpeta de entrada, dos puertas distintas.

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

*Las decisiones de diseño con su porqué y sus alternativas descartadas están en [DEVLOG.md](DEVLOG.md).*
