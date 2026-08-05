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

## Las herramientas hermanas

## MUSIC·0LOGY — una herramienta hermana compartiendo casa

Suno vive aparte de los cuatro pasos de arriba, y a propósito. **No tiene export**: la única forma de sacar tu biblioteca es pedírsela a su API, con la sesión iniciada, con un token que copias del navegador y que caduca en minutos. El pipeline de M3M0R·IA no sale a Internet por su cuenta — así que Suno tiene su propia pestaña, su propio pipeline y su propio paso manual, en vez de forzarlo a ser un proveedor que no es.

Qué hace: descarga tu biblioteca (audio, portadas y metadatos), verifica que el backup está íntegro, y construye un vault de Obsidian aparte con una nota por pista — incluyendo el **linaje real** entre covers, remixes y mashups, resuelto como enlaces. Los árboles de 60+ variantes son normales; los códigos Dewey los mantienen navegables, y el badge `Full Song` marca cuál es la versión terminada.

También asoma al Observatorio: pistas, duración total, favoritas, canciones completas y proyectos.

La regla que lo gobierna merece enunciarse con precisión, porque la versión corta ("el pipeline nunca hace peticiones salientes") prohibiría esto y no debería: **la aplicación nunca sale a Internet por iniciativa propia — sale cuando le pones un token en la mano y pulsas.** Si algo de esto te suena a criptología, ve a [la guía del token](ME_HE_ATASCADO.md).

## Tintero — el archivo de lo que publicaste

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

*Las decisiones de diseño con su porqué y sus alternativas descartadas están en [DEVLOG.md](DEVLOG.md).*
