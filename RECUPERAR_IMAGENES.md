# Recuperar imágenes

> **¿Qué pregunta responde este documento?**
> *¿Qué hace `recuperar_imagenes.py`, qué no hace, y por qué hace falta si ya importaste tus exports?*

Para instalarlo y arrancarlo, ve al [README](README.md). Para el diseño general, a [ARCHITECTURE.md](ARCHITECTURE.md). Esto es solo la recuperación de imágenes de ChatGPT.

---

## En una frase

`recuperar_imagenes.py` devuelve a tus notas las imágenes de ChatGPT que se quedaron como `*[imagen no disponible en el export: …]*`, cuelga de su conversación las imágenes generadas que el export nuevo trae sueltas, y apunta con qué se generó cada una. **Sin reimportar nada**: cambia cada nota en su sitio, con copia de seguridad y vuelta atrás.

## Por qué existe

En 2026 OpenAI cambió el export de ChatGPT, sin avisar:

- **Las imágenes ahora se llaman `file_XXXX.dat`.** Hasta la v3.1.0, M3M0R·IA no las reconocía: no indexaba ni una y cada imagen salía como «imagen no disponible en el export», **sin un solo error**. Desde la v3.2.0 la importación las lee, pero las notas que ya tenías siguen con el aviso.
- **Las imágenes generadas ya no van dentro de las conversaciones.** Solo vienen sueltas en `library_files.json` (la «biblioteca»), cada una con el identificador de la conversación de la que salió. Sin colgarlas de ella, no aparecen en ninguna nota.
- **El prompt de generación ya no viaja.** Los exports antiguos lo guardaban; los nuevos no. Eso no se puede recuperar.

## ¿Por qué no basta con reimportar?

Porque **duplicaría tus conversaciones**. La fusión (`MERGED_VAULT`) compara los mensajes por su texto: una nota con el aviso y la misma nota con el enlace son, para ella, mensajes **distintos**, y se quedaría con los dos. Medido en una copia del vault real: una conversación pasó de 187 a 217 turnos tuyos y conservó sus 44 avisos además de los 44 enlaces.

Por eso esta herramienta **sustituye el aviso por el enlace dentro de cada nota**, con **exactamente el mismo texto** que escribiría la importación nueva. Así, cuando llegue tu siguiente export, la fusión ve el mismo mensaje y no duplica nada.

---

## Qué hace y qué no hace

| Hace | No hace |
| ---- | ------- |
| Cambia el aviso por el enlace a la imagen, en `RAW_VAULT`, `MERGED_VAULT` y `PRJ_VAULT` | No reimporta ni vuelve a fusionar nada |
| Copia cada imagen a su banco, con el mismo nombre (su huella) que le daría la importación | No inventa imágenes: lo que tu export no trae se queda como aviso |
| Con `--biblioteca`, cuelga las generadas de la biblioteca de **su** conversación | No sabe en qué punto exacto de la conversación iban: van **al final** |
| Con `--metadatos`, apunta con qué se generó cada imagen (para filtrar en la [galería](GALERIA.md)) | No recupera el prompt de las imágenes recientes: el export ya no lo trae |
| Guarda una copia exacta de cada nota antes de tocarla, y deshace con `--deshacer` | **No borra nada.** Las imágenes copiadas a los bancos se quedan aunque deshagas |
| Conserva la fecha de modificación de cada nota | No cambia el número de turnos de ninguna conversación |
| **Por defecto solo cuenta** (simulación) | Sin `--aplicar` no escribe ni una nota ni una imagen |

---

## Cómo se usa

### Desde la app

Herramientas → Taller → **Recuperar imágenes de ChatGPT**. El título plegado dice cuántos avisos quedan en tus notas (la primera vez tarda casi un minuto en contarlos: lee todas las notas; después lo recuerda hasta que aplicas o deshaces algo).

1. Elige el export en el desplegable: salen los de ChatGPT de tu carpeta de exports, el más reciente primero.
2. «Simular»: enseña el registro en directo y no escribe nada.
3. Si te cuadran los números, «Aplicar» (solo aparece después de simular). Pide confirmación: cierra Obsidian antes.
4. «Deshacer la última» dice cuál desharía (su fecha y si fue de avisos, de la biblioteca o de metadatos). Pulsarla otra vez deshace la anterior, en el orden correcto. La copia deshecha no se borra: se marca con un `deshecho.json` para no volver a usarla.

La casilla «Colgar también las generadas de la biblioteca» es la opción `--biblioteca`. Lo de `--metadatos` sigue siendo solo de consola: se hace una vez.

### Desde una consola

En la carpeta del programa (en el paquete de Windows, la carpeta `app`, con `python\python.exe` en vez de `python`). Primero, **siempre**, la simulación:

```bash
python recuperar_imagenes.py --export "D:\Exports\chatgpt-2026-10-18.zip"
```

Te dice cuántos avisos hay, cuántos recupera ese export, cuántos no, y cuántas notas cambiaría. Si te cuadra, lo mismo con `--aplicar`:

```bash
python recuperar_imagenes.py --export "D:\Exports\chatgpt-2026-10-18.zip" --aplicar
```

| Opción | Qué hace |
| ------ | -------- |
| `--export <zip>` | el export de ChatGPT que trae las imágenes. Obligatorio salvo con `--deshacer` |
| `--base-vault <carpeta>` | otra carpeta base (si no, la de `memoria_config.yaml`) |
| `--aplicar` | hacer los cambios de verdad. Sin esto, solo cuenta |
| `--biblioteca` | además, copiar las generadas de la biblioteca a `GENERADAS` y colgarlas de su conversación |
| `--metadatos` | en vez de reparar notas: completar en el manifiesto de `GENERADAS` con qué se generó cada imagen |
| `--deshacer <carpeta>` | restaurar desde la copia de una pasada con `--aplicar` |
| `--logs <carpeta>` | dónde guardar las copias de seguridad (si no, `logs/` junto al programa) |

**Con varios exports**, pásalos uno detrás de otro: cada uno recupera lo que trae, y lo ya recuperado no se vuelve a tocar. El orden da igual.

---

## Los tres trabajos

### 1. Los avisos (sin opciones)

1. Busca los avisos `*[imagen no disponible en el export: <puntero>]*` en las notas `.md` de `RAW_VAULT/Conversaciones`, `MERGED_VAULT/Conversaciones` y `PRJ_VAULT`.
2. Para cada imagen que el export **sí** trae, la copia a su banco: `CHATGPT/GENERADAS` si es generada, `CHATGPT/ADJUNTOS` si la subiste tú, con el mismo nombre, el mismo criterio y el mismo manifiesto que la importación.
3. Cambia el aviso por `![](CHATGPT/<banco>/<huella>.<ext>)`.

### 2. La biblioteca (`--biblioteca`)

Las generadas que el export trae en `library_files.json` y **ninguna conversación enlaza**:

1. Se copian a `CHATGPT/GENERADAS`, con su título y su fecha en el manifiesto.
2. Se cuelgan de su conversación: al **final de cada nota** de ese hilo (en RAW, MERGED y PRJ) se añade un bloque como este, el mismo formato que dejaban los exports antiguos:

```markdown
### Tool

*Polluelo de gorrión en grafito* · 2026-10-17 23:12

![](CHATGPT/GENERADAS/5f7fa7a14d883163.png)
```

La nota de cada hilo se encuentra por el `conv_id` de su cabecera. La **importación hace lo mismo** con los exports nuevos, con el mismo texto.

### 3. Con qué se generó (`--metadatos`)

Para las generadas importadas **antes** de la v3.2.0, que no lo tienen apuntado. Añade a su entrada del manifiesto de `GENERADAS`, sacado exacto del export:

| Campo | Qué es |
| ----- | ------ |
| `generador` | `chatgpt-imagen` (la generación nativa), `chatgpt-dalle` o `chatgpt-biblioteca` (llegada sin conversación, por la biblioteca) |
| `modelo` | el modelo **del chat** en ese turno (gpt-4o, gpt-5…), no el de la herramienta de imagen |
| `edicion` | `true` si se hizo a partir de otra imagen |

Casa cada imagen por su **huella** (el nombre del fichero), así que da igual en qué nota esté. No toca las entradas que ya lo tienen, ni nada más del manifiesto.

---

## La letra pequeña: lo que sorprende

Cada fila es un comportamiento de `recuperar_imagenes.py`, fijado por un test (`tests/test_recuperar_documentado.py`; lo que hace la app, en `tests/test_launcher_taller.py`).

| Situación | Qué pasa | Qué hacer |
| --------- | -------- | --------- |
| **Sin `--aplicar`** | no escribe nada: ni notas, ni imágenes, ni copia de seguridad | Mira los números y repite con `--aplicar` |
| **Un export no lo trae todo** | los avisos de imágenes que ese export no trae **se quedan como están** | Pásalo con cada export que tengas. Los que ningún export trae, no tienen arreglo |
| **Repetir** | no hace daño: una nota ya reparada no tiene aviso, y un bloque de la biblioteca que ya está no se añade otra vez | Nada |
| **El banco de una imagen de un export antiguo** | si su conversación no está en este export, decide la biblioteca: generada si allí consta como generada; si no está en ella, va a `ADJUNTOS` | Nada: es la mejor información que hay |
| **La misma imagen en varias notas** | se copia **una vez** al banco (mismo contenido, mismo nombre) y se enlaza en todas | Nada |
| **Las fechas de las notas** | la de modificación se conserva: la fusión la usa para desempatar | Nada |
| **Dónde va una imagen de la biblioteca** | al **final** de la nota, no entre sus turnos: el export no dice tras qué mensaje se generó | Mira la hora del bloque: es la de ChatGPT |
| **La hora del bloque** | en **tu hora local**, la que ves en ChatGPT | Nada |
| **El título del bloque** | el que ChatGPT le puso, sin la extensión y sin asteriscos. Si no tiene, «Imagen generada» | Nada |
| **Una generada cuya conversación no está en tu vault** | se copia a `GENERADAS`, pero no se cuelga de ninguna nota: en la galería sale «sin conversación» | Importa ese export y repite `--biblioteca` |
| **Generadas sin fichero en el zip** | se saltan: la biblioteca las apunta, pero el fichero no viaja | Nada que hacer |
| **Deshacer las dos cosas** | si pasaste avisos y `--biblioteca` a la vez hay **dos** copias: deshaz **primero la de la biblioteca** y luego la otra. Al revés, las notas se quedan con los enlaces | En la app, «Deshacer la última» ya va en ese orden. En la consola, te lo dice al terminar |
| **Deshacer no borra imágenes** | las notas vuelven a como estaban; las imágenes copiadas a los bancos se quedan | Nada: no estorban, y no hay borrados sin pedirlos |
| **Los enlaces simbólicos** | se saltan: no se sigue ningún enlace simbólico | Nada |
| **`--metadatos` no toca lo que ya está** | una entrada que ya tiene `generador` se queda como está, aunque el export diga otra cosa | Nada |

---

## Qué escribe y dónde

| Qué | Dónde |
| --- | ----- |
| Las notas reparadas | en su sitio: `RAW_VAULT/Conversaciones`, `MERGED_VAULT/Conversaciones`, `PRJ_VAULT` |
| Las imágenes | `CHATGPT/GENERADAS` y `CHATGPT/ADJUNTOS`, con su `_image_manifest.json` |
| **La copia de seguridad** | `logs/recuperar_imagenes_<fecha>/` (avisos), `…_biblioteca/` y `…_metadatos/`, dentro de la carpeta del programa (o la de `--logs`). Cada una con un `diario.json` que dice qué export, qué base y qué ficheros, y un `deshecho.json` si ya la deshiciste desde la app |

Cada nota se escribe de forma atómica (a un fichero temporal y luego se sustituye): un corte a mitad no deja una nota a medias. Las copias de seguridad **no se borran solas**: cuando ya no las quieras, bórralas tú.

---

## Un ejemplo real

Sobre el vault con el que se construyó, con 16 exports de ChatGPT de distintas fechas:

- **Avisos**: de 20.091 a 3.159. Recuperadas **4.272** imágenes distintas; **710** no están en ningún export y se quedan como aviso.
- **Biblioteca**: 387 generadas copiadas a `GENERADAS` y 1.375 bloques en 375 notas (la misma conversación vive en RAW, MERGED y PRJ).
- **Metadatos**: las 1.169 generadas, con su generador (778 nativas, 387 de la biblioteca, 4 de DALL·E; 53 son ediciones).
- 9.503 notas revisadas: **ninguna** cambió su número de turnos ni su fecha de modificación.

---

## Cómo comprobar que ha ido bien

- **La simulación y la pasada real deben dar los mismos números.**
- **Abre una conversación que tenía avisos** en Obsidian: donde estaba el aviso, ahora está la imagen.
- **Busca en el vault** `imagen no disponible en el export`: lo que quede es lo que tus exports no traen.
- **Genera la [galería](GALERIA.md)**: las imágenes recuperadas aparecen en su conversación, y el filtro de generador ya distingue nativa, DALL·E y biblioteca.

---

## Límites conocidos

- **Solo ChatGPT.**
- **Lo que no está en ningún export no se recupera.** Los exports antiguos que borraste se llevaron sus imágenes.
- **El prompt de las imágenes recientes no existe** en el export.
- **La posición** de las imágenes de la biblioteca dentro de la conversación es aproximada: al final, con su hora.
- **El texto del aviso es siempre en español**, también en la edición inglesa: es el que escribe la importación, y es el que se busca.
