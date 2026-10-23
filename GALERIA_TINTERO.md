# Galería de Tintero

> **¿Qué pregunta responde este documento?**
> *¿Qué hace la galería de tus posts de Substack, qué no hace, y de dónde saca la portada de cada uno?*

Para instalarlo y arrancarlo, ve al [README](README.md). Para la galería de imágenes, a [GALERIA.md](GALERIA.md). Esto es solo la galería de Tintero.

---

## En una frase

La galería de Tintero junta en **una sola página HTML** todos los posts que Tintero construyó de tus publicaciones de Substack: una tarjeta por post con su portada, su título, su subtítulo y sus primeras palabras, con búsqueda y filtros, y la abres en el navegador. No toca tu vault: lee las notas y escribe solo en su propia carpeta.

## ¿Es parte de Tintero?

**Es su complemento**, como la [galería de imágenes](GALERIA.md) lo es del vault de conversaciones. Se genera cuando tú quieras, nunca al construir el vault, y por eso **no se actualiza sola**: si reconstruyes Tintero con un export nuevo, vuelve a generarla. Rehacerla es rápido, porque las portadas ya bajadas se reutilizan.

---

## Qué hace y qué no hace

| Hace | No hace |
| ---- | ------- |
| Una tarjeta por post de todas tus publicaciones, por meses | No mira otros vaults: solo el de Tintero |
| Pone a cada post **su portada de Substack**, o la primera imagen de su texto | **No cambia ninguna nota** |
| Busca por palabras y filtra por estado, tipo, publicación, sección, etiqueta y mes | No busca en el texto completo: solo en lo que enseña la tarjeta |
| Baja cada portada **una vez**, pequeña, y la reutiliza | No baja las imágenes del texto de los posts: solo la que hace de portada |
| Oculta los borradores por defecto | No borra ni esconde nada de tu vault: los borradores se ven con su filtro |
| Usa los mismos temas de color que la app | No necesita la app abierta |

---

## Cómo se genera

**Desde la app**: Herramientas → Galerías → **Posts de Substack** → «Generar y abrir». La casilla «Sin salir a Internet» es la opción `--sin-red`. Enseña el registro en directo y, al terminar, la abre en tu navegador; «Abrir la última» abre la que ya tienes. El título plegado dice cuándo la generaste y cuántos posts lleva.

**Desde una consola**, en la carpeta del programa (en el paquete de Windows, la carpeta `app`, con `python\python.exe` en vez de `python`):

```bash
python galeria_tintero.py
```

Sin opciones usa el vault de Tintero de tu configuración (`substack_vault`) y escribe la galería en `<vault de Tintero>/.galeria/index.html`. Abre ese fichero con el navegador.

| Opción | Qué hace |
| ------ | -------- |
| `--vault <carpeta>` | otro vault de Tintero (si no, `substack_vault` de `memoria_config.yaml`) |
| `--salida <carpeta>` | escribir la galería en otro sitio (si no, `<vault>/.galeria`) |
| `--sin-red` | no salir a Internet: solo las portadas que ya se bajaron |
| `--tema warm\|cool\|light` | el tema con el que abre (si no, el de tu configuración) |

---

## La portada: de dónde sale

**El export de Substack no trae la portada**: `posts.csv` no tiene esa columna, y las imágenes del texto son enlaces a los servidores de Substack, no ficheros. Por eso, por orden:

1. **La portada de Substack**, la que ves en tu publicación. Se le pide a la API pública del archivo de cada publicación (`https://<publicación>.substack.com/api/v1/archive`), **sin credencial**: es la misma información que ve cualquiera que visite tu Substack. Solo existe para lo **publicado**.
2. **Si no hay, la primera imagen del texto** del post.
3. **Si tampoco, la inicial del título**, en grande. No es un fichero: la pinta la página.

La galería **sale a Internet al generarla**, para preguntar por las portadas y bajar las que falten. Nada más: ni manda nada tuyo, ni guarda credenciales, porque no las usa. Con `--sin-red` no sale.

---

## La tarjeta

| Lo que ves | De dónde sale |
| ---------- | ------------- |
| **La publicación** (insignia) | la carpeta de la publicación en el vault de Tintero |
| **«retirado», «borrador», «🎙 podcast»** | `status` y `type` de la nota |
| **La fecha y la sección** | `date` y `section` de la nota |
| **El título y el subtítulo** | `title` y `subtitle` de la nota |
| **Las primeras palabras** | las 50 primeras del texto del post, sin el título, el subtítulo, los avisos de Tintero, las imágenes ni sus pies |
| **Vistas, me gusta, comentarios** | las estadísticas de la nota, si Tintero tuvo el CSV de estadísticas |
| **Obsidian ↗** | la nota, en su vault de Obsidian |
| **Substack ↗** | el post en tu publicación (solo los publicados) |

---

## La letra pequeña: lo que sorprende

Cada fila es un comportamiento de `galeria_tintero.py` o de su página, fijado por un test (`tests/test_galeria_tintero.py`).

| Situación | Qué pasa | Qué hacer |
| --------- | -------- | --------- |
| **Borradores** | no se ven por defecto: el resumen dice cuántos hay ocultos. Se ven con «Borradores» o con «Todo» | Nada: los borradores no tienen fecha y muchos ni título |
| **Un borrador sin título** | sale con el nombre que le dio Tintero, que suele ser un trozo del identificador («084») | Ponle título en Substack y reconstruye |
| **Retirados** | su portada no está en la API (ya no son públicos): sale la primera imagen de su texto, o la inicial | Nada |
| **Un post repetido** (por ejemplo, en `Borradores` y en `Drafts`, de haber construido con las dos ediciones) | sale **una vez**: la nota modificada más recientemente | Nada |
| **Sin estadísticas** | si Tintero no tuvo el CSV de estadísticas de esa publicación, la tarjeta no enseña números. **No pinta 0**: no saberlo no es lo mismo que cero | Pon el CSV de estadísticas en tu carpeta de exports y reconstruye Tintero |
| **Una portada que no se puede bajar** | se intenta la siguiente opción (la primera imagen, luego la inicial) y se avisa en la consola. Se vuelve a intentar en la siguiente generación | Nada: algunas imágenes de terceros no dejan bajarse |
| **Substack cambia la portada** | se baja la nueva: cada portada se recuerda junto con su dirección | Nada |
| **La API no responde** | se sigue sin ella, con la primera imagen del texto, y se avisa | Vuelve a generarla más tarde |
| **`--sin-red`** | no sale a Internet: usa las portadas ya bajadas; un post sin ninguna, con la inicial | Nada |
| **Buscar** | busca **trozos de texto**, sin mayúsculas ni acentos, y exige **todas** las palabras | Menos palabras, más resultados |
| **Dónde busca** | en el título, el subtítulo, las primeras palabras, la sección, la publicación y las etiquetas. **No** en el resto del post | Para buscar en los posts, usa Obsidian |
| **«Obsidian ↗»** | abre la nota en la carpeta más cercana que Obsidian tenga como vault (la que tiene `.obsidian`). Si no hay ninguna, la abre por su ruta | Nada |
| **«Texto» en el filtro de tipo** | es todo lo que no es podcast | Nada |
| **Portadas recortadas** | se recortan **desde arriba** para llenar la tarjeta: en una portada vertical se ve la parte de arriba | Nada |

---

## Qué escribe y qué no

Solo escribe dentro de su carpeta (`<vault de Tintero>/.galeria`, o la de `--salida`):

| Fichero | Qué es |
| ------- | ------ |
| `index.html` | la página, con todos los datos dentro |
| `portadas/<publicación>/<id del post>.jpg` | una portada por post, JPEG de 640 px de lado |
| `portadas/_origen.json` | de qué dirección salió cada portada, para saber si Substack la cambió |
| `tintero.png` | la mascota de Tintero, para la cabecera y la pestaña |
| `estado.json` | cuándo se generó y cuántos posts lleva: es lo que lee la app para decirte el estado de la galería |

Fuera de esa carpeta **no toca nada**. El punto delante de `.galeria` hace que Obsidian no la indexe. Es **derivada y regenerable**: si la borras, la siguiente generación vuelve a bajar las portadas.

---

## Un ejemplo real

Sobre el vault con el que se construyó, con tres publicaciones:

- **190 posts**: 135 de V0raOnline, 48 de BitacoraClandestina y 7 de MasAlladelPrompt; 14 son borradores.
- **Portadas**: 145 de Substack, 18 de la primera imagen y 27 con la inicial. Dos imágenes de terceros no se dejaron bajar.
- La carpeta de portadas ocupa unos **11 MB**. La primera vez tarda un par de minutos; las siguientes, segundos, sin bajar nada.

---

## Dónde vive cada cosa

| Qué | Dónde |
| --- | ----- |
| **La galería** | `<vault de Tintero>/.galeria/index.html` |
| El generador | `galeria_tintero.py` |
| La plantilla de la página | `galeria_tintero_plantilla.html` (los colores los copia de `web/style.css` al generar) |

---

## Límites conocidos

- **Es una foto**: no se actualiza sola.
- **Solo sabe lo que sabe Tintero.** Lo que el export de Substack no trae (el audio de los podcasts, los comentarios) tampoco está aquí.
- **La portada de lo retirado y de los borradores no existe** en Substack de forma pública.
- **La búsqueda es de texto**, no de significado.
