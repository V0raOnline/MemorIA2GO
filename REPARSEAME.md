# REParsea·me

> **¿Qué pregunta responde este documento?**
> *Mi vault se escribió con versiones antiguas de la importación: ¿cómo lo pongo al día sin perder nada y sin duplicar conversaciones?*

Para instalar y arrancar, el [README](README.md). Para el diseño general, [ARCHITECTURE.md](ARCHITECTURE.md). La recuperación de imágenes, que es otra herramienta, está en [RECUPERAR_IMAGENES.md](RECUPERAR_IMAGENES.md).

---

## En una frase

REParsea·me reescribe las notas de tu vault crudo como las escribiría **la importación de hoy**, cada una fiel a **su propio export**, les pone el nombre que les daría la importación y deja al día el vault fusionado y el de proyectos. **Primero simula, guarda una copia exacta de todo lo que toca y se puede deshacer.**

## Por qué existe

Cada mejora de la importación vale para lo que importas **después**. Las notas que ya tenías se quedan como salieron. Medido en el vault con el que se construyó (7.358 notas en RAW) antes de la primera pasada:

| Qué fallaba | Notas |
| --- | --- |
| Bloques en JSON crudo (`{"content_type": …}`): razonamiento, llamadas a herramientas, archivos citados, instrucciones personalizadas, documentos de Canvas | 3.696 |
| «Imagen no disponible» (imágenes que la importación antigua no sabía leer, o que el export no traía) | 1.645 |
| Notas de ChatGPT sin `model` en el frontmatter | 261 |
| Sin `conv_id` en el frontmatter | 44 |
| Bytes nulos (marcadores de imagen sin resolver) | 19 |

Y va a volver a pasar: cada vez que la importación mejore, habrá algo nuevo para las notas antiguas.

## Por qué no basta con reimportar

Por las **huellas**. Cada nota de RAW lleva en el nombre la huella de su contenido (`…-h4e66319e.md`). Si la importación de hoy escribe la misma conversación de otra manera, la huella cambia, el nombre también, y RAW gana **otra versión al lado de la vieja**. Después la fusión:

- elige como campeona la versión con **más palabras**, que suele ser la vieja, porque el JSON crudo abulta;
- añade los mensajes de la otra como «exclusivos», porque no los reconoce como iguales.

Resultado: miles de notas fusionadas con **las dos formas mezcladas**. Por eso REParsea·me conviene pasarlo **antes** de importar exports nuevos.

---

## Cómo se usa

### Desde la app

Herramientas → Taller → **REParsea·me**. El título plegado dice la última pasada y cuántas notas siguen con JSON crudo (lo demás solo lo sabe una simulación).

1. **Cierra Obsidian** y haz una copia del vault. Es recomendable, no obligatorio, porque REParsea·me guarda la suya.
2. **Simular**: enseña el registro en directo y un resumen en tarjetas. No escribe nada en tu vault.
3. Si los números te cuadran, **Aplicar**. Solo aparece después de simular y pide confirmación. Tarda unos minutos.
4. **Deshacer la última** dice qué pasada desharía, y deja RAW, el fusionado y el de proyectos **idénticos** a como estaban: nombres, bytes y fechas. Las imágenes copiadas a los bancos se quedan; se llaman por su huella y no duplican nada.

### Desde una consola

```bash
python reparseame.py                        # diagnóstico y plan: no escribe nada
python reparseame.py --aplicar              # de verdad
python reparseame.py --deshacer "logs\reparseame_AAAAMMDD-HHMMSS"
```

`--base-vault`, `--exports` y `--logs` cambian lo que dice `memoria_config.yaml`; `--csv` guarda una fila por nota afectada.

---

## Qué hace

1. **Fusiona RAW tal cual**, aparte, para compararlo con tu vault fusionado. Una nota fusionada con líneas que la fusión no produce se **editó a mano**: se marca y no se toca.
2. **Las imágenes de cualquiera de tus exports.** Cada aviso de «imagen no disponible» lleva dentro el puntero de su imagen.
   - REParsea·me la busca en todos tus exports, la copia a su banco con el nombre que le daría la importación y apunta puntero → enlace en `<CHATGPT>/_punteros_imagenes.json`.
   - **RAW no se toca**: si ese export no traía la imagen, el aviso es la verdad de ese export.
   - La fusión lee esa correspondencia y enseña la imagen en el fusionado si *algún* export la tuvo. El aviso y el enlace de la **misma** imagen pasan a ser un solo mensaje; dos imágenes distintas siguen siendo distintas.
   - La importación alimenta la misma correspondencia, así que los exports futuros a los que les falten imágenes se arreglan solos en el fusionado.
3. **Reescribe RAW:**
   - El JSON crudo se convierte **con las mismas funciones de la importación**: el razonamiento, las herramientas y los resultados van plegados; Canvas se lee como documento; las instrucciones personalizadas van una vez, arriba. Si la importación mejora, REParsea·me mejora con ella.
   - Lo que la nota sola no sabe sale de **su propio export**: el `model`, el `conv_id` y las imágenes que su export sí traía y la importación antigua no leía. El manifiesto de la importación (`logs/conversaciones_manifest.jsonl`) dice qué exports trajeron cada conversación. Se regenera desde ellos y la nota solo se sustituye si aparece su **versión exacta**: los mismos mensajes, sin contar imágenes ni frontmatter. Si varios exports dan la misma versión, gana la más parecida a la nota, porque es la huella del export que la escribió.
   - Cada nota con huella se **renombra por su contenido nuevo**, para que la próxima importación la reconozca y la salte.
   - Las **versiones idénticas** de una misma conversación se apartan a la copia. La que se queda hereda la fecha más reciente, porque la fusión titula una conversación renombrada por su versión más reciente.
4. **Vault fusionado:** fusiona el RAW reparado aparte y sincroniza **solo las notas que son de la fusión**, las de las carpetas de año. Las notas de sesiones (Claude Code, Codex) y lo demás que viva ahí no se tocan. Las huérfanas van a la copia: son notas que la fusión ya no produce porque su conversación tiene ahora otro nombre.
5. **Vault de proyectos:** se refresca como en una importación normal, y las copias rancias de conversaciones que cambiaron de proyecto van a la copia.
6. **Índices**, como en una importación normal.

## Qué hace y qué no hace

| Hace | No hace |
| --- | --- |
| Reescribe RAW como lo escribiría la importación de hoy, cada nota desde su propio export | Inventar lo que ningún export trae: esas imágenes se quedan como aviso |
| Enseña en el fusionado las imágenes que tenga cualquiera de tus exports | Poner en una nota de RAW una imagen que su propio export no traía |
| Renombra por huella para que la próxima importación no duplique | Tocar notas fusionadas editadas a mano (las marca) |
| Guarda una copia exacta de todo y deshace al byte | Borrar nada: lo que se aparta va a la copia |
| **Por defecto solo simula** | Escribir una sola nota sin `--aplicar` / «Aplicar» |

**Las notas no se editan a mano.** Son el archivo de tus conversaciones y dicen lo que se dijo, erratas incluidas. Por eso la fusión normal hace bien en pisar los cambios a mano en el fusionado, y por eso REParsea·me solo los marca: la siguiente importación los devuelve a su forma original.

## Medido en el vault real

Primero en una copia entera y después en el vault mismo (2026-11-16), con las mismas cifras:

- **RAW:** 1.745 notas reescritas, 209 renombradas y 3.695 versiones idénticas apartadas. Las 7.358 notas se quedaron en 3.663 sin perder un mensaje. Después, desde su propio export, se regeneraron 10; otras 985 ya eran fieles (lo que les falta, su export tampoco lo trae).
- **Imágenes:** 1.721 de las 2.431 imágenes avisadas están en algún export, y las notas fusionadas con avisos bajaron de 602 a 194. Las otras 710 imágenes no están en ningún export.
- **Fusionado y proyectos:** en las tres pasadas se pusieron al día 1.166, 452 y 15 notas fusionadas. Se apartaron 7 huérfanas del fusionado y 24 copias rancias de proyectos, y quedó sin tocar una nota editada a mano.
- **El día después:** importar dos exports más y volver a fusionar no crea ningún duplicado.

## Cómo se comprueba

- **De punta a punta:** una nota escrita a la antigua sale **byte a byte** igual que la que escribe la importación de hoy desde el mismo export.
- **Sin duplicados:** después de REParsea·me, reimportar el mismo export **no crea ni un fichero** en RAW.
- **Deshacer:** aplicar y deshacer lo deja todo idéntico (contenido, nombres y fechas). Deshacer se niega si una nota ha cambiado desde entonces.
- **La fusión:**
  - el aviso y el enlace de la misma imagen son un solo mensaje;
  - sin el fichero en el banco, el aviso se queda;
  - dos imágenes distintas no se funden.
- **El Taller:** el estado, simular, aplicar, deshacer y «ya hay una ejecución en curso».

## Pendiente

- El diagnóstico todavía cuenta como pendientes notas que son fieles a su export, porque su export tampoco trae lo que les falta. Tendría que distinguir «fiel» de «roto».
- Cubrir los dos casos que todavía hace [RECUPERAR_IMAGENES.md](RECUPERAR_IMAGENES.md), para poder retirarla: colgar las imágenes de la biblioteca en notas antiguas y los metadatos de generación.
