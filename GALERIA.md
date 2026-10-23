# Galería

> **¿Qué pregunta responde este documento?**
> *¿Qué hace la galería de imágenes, qué no hace, y de dónde saca lo que enseña de cada imagen?*

Para instalarlo y arrancarlo, ve al [README](README.md). Para el diseño general, a [ARCHITECTURE.md](ARCHITECTURE.md). Esto es solo la galería.

---

## En una frase

La galería junta en **una sola página HTML** todas las imágenes y vídeos de tus IAs (ChatGPT, Grok y Copilot), con una tira por conversación, búsqueda y filtros, y la abres en el navegador. No toca tu vault: lee lo que ya hay y escribe solo en su propia carpeta.

## ¿Es parte del pipeline?

**No.** Es un **complemento**: se genera cuando tú quieras, nunca durante una importación. Por eso **no se actualiza sola**: es una foto del vault en el momento de generarla. Si importas algo nuevo, vuelve a generarla. Rehacerla es rápido, porque las miniaturas que ya existen se reutilizan.

Tampoco decide nada por heurística. Todo lo que enseña de cada imagen **sale de un sitio concreto del vault** (abajo, «De dónde sale cada cosa»), y lo que no está en ningún sitio no se inventa: se queda en blanco.

---

## Qué hace y qué no hace

| Hace | No hace |
| ---- | ------- |
| Junta las imágenes y vídeos de los bancos de ChatGPT, Grok y Copilot | No mira Claude, ni Suno/Flow, ni Substack: allí no hay bancos de imágenes |
| Agrupa cada imagen con **su conversación**: título, fecha, proyecto, lo que pediste y el prompt | **No cambia nada del vault**: ni notas, ni bancos, ni manifiestos |
| Busca por palabras y filtra por origen, tipo, proveedor, generador, proyecto y mes | No busca dentro del texto completo de las conversaciones, solo en lo que enseña |
| Hace miniaturas pequeñas, una vez, y las reutiliza | No se actualiza sola: se regenera cuando tú lo pides |
| Usa los mismos temas de color que la app | No necesita la app abierta ni Internet: es un fichero que se abre en el navegador |
| Lleva a cada nota en Obsidian y al fichero original | No recupera imágenes que faltan: eso es [RECUPERAR_IMAGENES.md](RECUPERAR_IMAGENES.md) |

---

## Cómo se genera

**Desde la app**: Herramientas → Galerías → **Imágenes y vídeos** → «Generar y abrir». Enseña el registro en directo y, al terminar, la abre en tu navegador. «Abrir la última» abre la que ya tienes, sin regenerarla. El título plegado dice cuándo la generaste y cuánto lleva (lo lee de su `estado.json`, sin abrir la página).

**Desde una consola**, en la carpeta del programa:

```bash
python galeria.py
```

En el paquete de Windows, la carpeta es `app` (dentro de la que descomprimiste), y el Python es el suyo:

```bash
python\python.exe galeria.py
```

Sin opciones usa la carpeta base de tu configuración y escribe la galería en `<base>/.galeria/index.html`. Abre ese fichero con el navegador.

| Opción | Qué hace |
| ------ | -------- |
| `--base-vault <carpeta>` | otra carpeta base (si no, la de `memoria_config.yaml`) |
| `--salida <carpeta>` | escribir la galería en otro sitio (si no, `<base>/.galeria`) |
| `--sin-miniaturas` | no hacer miniaturas: la página carga los originales (mucho más pesada) |
| `--tema warm\|cool\|light` | el tema con el que abre (si no, el de tu configuración) |
| `--copilot-vault <carpeta>` | el vault de imágenes de Copilot (si no, `copilot_images_vault` de tu configuración) |

La app usa los valores por defecto: tu carpeta base, la salida en `.galeria` y el tema de tu configuración.

---

## De dónde sale cada cosa

| Lo que ves | De dónde sale |
| ---------- | ------------- |
| **Las imágenes y vídeos** | los bancos: `CHATGPT/GENERADAS`, `CHATGPT/ADJUNTOS`, `GROK/GENERADAS_IMAGEN`, `GROK/GENERADAS_VIDEO`, `GROK/IMAGINE`, `GROK/ADJUNTOS` y el vault de Copilot |
| **La conversación** (título, fecha, proyecto, proveedor) | la cabecera de la nota de `MERGED_VAULT/Conversaciones` que enlaza la imagen |
| **Lo que pediste** | tu último mensaje antes de la imagen, en esa nota (hasta 300 caracteres, sin los enlaces) |
| **El prompt** | en ChatGPT, el que el asistente mandó a la herramienta de imagen, si la nota lo guarda; en DALL·E y Grok, el que guarda su banco; en Copilot, el de la nota de cada imagen |
| **El título y la hora** de las generadas de la biblioteca de ChatGPT | el bloque que deja la importación (o `recuperar_imagenes.py --biblioteca`): `*Título* · fecha hora` |
| **Generada o subida** | el banco donde está (`GENERADAS` frente a `ADJUNTOS`) |
| **El generador** (generación nativa, DALL·E, biblioteca, Grok chat, Imagine, Copilot) | el manifiesto del banco (`_image_manifest.json`); en Grok, el banco mismo |
| **El modelo** (gpt-4o, gpt-5…) | el manifiesto: es el modelo **del chat** en ese turno, no el de la herramienta de imagen |
| **«Edición de otra imagen»** | el manifiesto, cuando la imagen se hizo a partir de otra |

---

## Cómo se agrupa

- **Una tira por conversación.** Todas las imágenes que enlaza una misma nota, juntas, la subida y la generada incluidas.
- **Copilot no tiene conversaciones**: tiene una nota por imagen. Se agrupan por **prompt y día**, porque Copilot hace varias variantes de cada petición.
- **Lo que ninguna nota enlaza** (Grok Imagine, imágenes sueltas) va en **una tira por día y proveedor**, con el título «Grok · sin conversación».
- Las tiras van de la **más reciente a la más antigua**, en secciones por mes.

---

## La letra pequeña: lo que sorprende

Cada fila es un comportamiento de `galeria.py` o de su página, fijado por un test (`tests/test_galeria_documentada.py`).

| Situación | Qué pasa | Qué hacer |
| --------- | -------- | --------- |
| **Solo se mira MERGED** | una imagen enlazada solo desde `RAW_VAULT` o `PRJ_VAULT` sale «sin conversación» | Pasa el pipeline (paso 2): MERGED es la vista fusionada |
| **Una imagen en dos conversaciones** | sale **una vez**, en la primera nota **por orden de carpeta y nombre**, no por fecha | Nada: no se repite a propósito |
| **El prompt de ChatGPT** | solo existe en las imágenes de exports antiguos (hasta marzo de 2026). Los exports nuevos ya no lo traen y **no se recupera** | Nada que hacer: OpenAI lo quitó del export |
| **El prompt no se hereda** | si después de una imagen escribes otra petición, la imagen siguiente **no** se lleva el prompt de la anterior | Nada: así no hay prompts falsos |
| **Sin generador** | las imágenes importadas antes de esta versión no lo tienen: salen sin generador y no entran en ese filtro | Pasa `recuperar_imagenes.py --metadatos` con tus exports ([RECUPERAR_IMAGENES.md](RECUPERAR_IMAGENES.md)) |
| **Fecha de lo que no tiene conversación** | la del manifiesto; si no hay, la **fecha de modificación del fichero**, que puede ser el día en que se copió | Nada: es la mejor que hay |
| **Formatos** | solo `.png .jpg .jpeg .webp .gif` y vídeos `.mp4 .webm .mov`. Un `.heic` o un `.svg` no aparecen; tampoco nada que empiece por `_` | Conviértelos si quieres verlos |
| **Buscar** | busca **trozos de texto** (`gat` encuentra «gato»), sin mayúsculas ni acentos, y exige **todas** las palabras que escribas | Menos palabras, más resultados |
| **Dónde busca** | en el título de la conversación, el proyecto, el título de la imagen, el prompt, lo que pediste, el proveedor, el generador y el modelo. **No** en el resto de la conversación ni en el nombre del fichero | Para buscar en las conversaciones, usa Obsidian |
| **«Abrir en Obsidian»** | abre la nota en el vault que se llama **como tu carpeta base**. Si en Obsidian solo tienes abierto `MERGED_VAULT` como vault, el enlace no la encuentra | Abre en Obsidian la carpeta base como vault |
| **Copilot fuera de la carpeta base** | entra en la galería, pero **sin** «Abrir en Obsidian»: es otro vault | Nada: el fichero original sí se abre |
| **Miniaturas propias** | si existe `CHATGPT/GENERADAS_Thmbnails/thmbnail_<nombre>.png`, la miniatura sale de ahí (más rápido). Pero si **retocas** una miniatura propia, la galería **no** la rehace mientras el original no cambie | Borra `.galeria/miniaturas` y regenera |
| **Vídeos** | no tienen miniatura: la tira carga el primer fotograma del original | Nada |
| **Un fichero roto** | no para nada: sale «sin miniatura» y se avisa en la consola | Mira el aviso: el fichero está dañado |
| **Sin Pillow** | no hace miniaturas y se para avisando | `pip install pillow`, o genera con `--sin-miniaturas` (el paquete de Windows ya lo lleva) |
| **Mover el vault** | los enlaces son **relativos**: la galería sigue funcionando si mueves la carpeta base entera. Si la salida está en otra unidad, son absolutos y se rompen al moverla | Deja la galería dentro de la base (lo normal) |

---

## Qué escribe y qué no

Solo escribe dentro de su carpeta (`<base>/.galeria`, o la de `--salida`):

| Fichero | Qué es |
| ------- | ------ |
| `index.html` | la página, con todos los datos dentro |
| `miniaturas/` | una miniatura JPEG por imagen (480 px de lado), con la misma estructura de carpetas que los bancos |
| `miniaturas/.version` | la versión de las miniaturas: si cambia cómo se hacen, se rehacen todas |
| `imageIA.png` | el cerebrito de image.ia, para la cabecera y la pestaña del navegador |
| `estado.json` | cuándo se generó y cuánto lleva: es lo que lee la app para decirte el estado de la galería sin abrir la página |

Fuera de esa carpeta **no toca nada**. El punto delante de `.galeria` hace que Obsidian no la indexe: miles de miniaturas en el árbol del vault serían solo ruido.

Es **derivada y regenerable**: puedes borrar la carpeta entera y volver a generarla. Lo único que cuesta rehacer son las miniaturas.

---

## Un ejemplo real

Sobre el vault con el que se construyó (cuatro años de ChatGPT, Grok y Copilot):

- **5.986** imágenes y vídeos en **1.221** tiras.
- **5.782** miniaturas: la carpeta ocupa unos **174 MB** (los originales, varios GB).
- La primera vez tarda unos minutos, por las miniaturas. Las siguientes, segundos.
- La página se abre rápido porque cada tira **se pinta al desplegarla**: con miles de imágenes, pintarlas todas de golpe la congelaría.

---

## Dónde vive cada cosa

| Qué | Dónde |
| --- | ----- |
| **La galería** | `<base>/.galeria/index.html` |
| El generador | `galeria.py` |
| La plantilla de la página | `galeria_plantilla.html` (los colores los copia de `web/style.css` al generar) |
| El tema que recuerda | el que elijas en la página se guarda **en ese navegador** |

---

## Cómo comprobar que ves lo que hay

- **La consola** termina con el recuento: cuántas imágenes y vídeos, en cuántos grupos, por proveedor, y cuántas miniaturas son nuevas, reutilizadas o fallidas.
- **El contador de arriba** de la página dice cuántas ves de cuántas hay. Si no cuadra, mira el botón **Filtros**: lleva un número con los filtros activos.
- **Una imagen sin conversación** que esperabas con conversación: busca su nombre de fichero en `MERGED_VAULT/Conversaciones`. Si no aparece, ninguna nota fusionada la enlaza.

---

## Límites conocidos

- **Es una foto**: no se actualiza sola.
- **Solo ChatGPT, Grok y Copilot.**
- **Solo mira `MERGED_VAULT/Conversaciones`** para el contexto.
- **El prompt de las imágenes recientes de ChatGPT no existe**: el export ya no lo trae.
- **La búsqueda es de texto**, no de significado: no encuentra «perro» buscando «can».
