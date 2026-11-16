# REParsea·me

> **¿Qué pregunta responde este documento?**
> *Mi vault se escribió con versiones antiguas del parser: ¿cómo lo pongo al día sin perder nada y sin duplicar conversaciones?*

> **Estado (2026-11-16): fases 1, 2 y 3 hechas, en `reparseame.py`.** Diagnóstico, reescritura de RAW y puesta al día de MERGED y PRJ, todo probado sobre una copia entera del vault real. Pendientes: la fase 4 (derivas que necesitan el export) y la 5 (pantalla del Taller).
>
> Prueba en una copia del vault real (RAW con 7.358 notas, MERGED y PRJ):
> - **RAW:** 1.745 notas reescritas, 209 renombradas por su huella y 3.695 versiones idénticas apartadas. Quedan 3.663 notas.
> - **MERGED:** 1.166 notas al día y 7 huérfanas apartadas. La única nota editada a mano queda sin tocar. Lo que no es de la fusión (Sesiones, `CLAUDE_CODE`, `CODEX`) no se toca.
> - **PRJ:** refrescado, con 23 copias huérfanas apartadas.
> - Pasarlo otra vez no hace nada. `--deshacer` deja RAW, MERGED y PRJ **idénticos** al original (nombres, bytes y fechas).
> - **El día después:** importar después el export de 2025-12-20 con el mapa de proyectos real y volver a fusionar no cambia ni una nota de RAW; en MERGED cambia una sola, la editada a mano (ver abajo). Sin reparar, la misma importación crea 312 notas en RAW.
>
> **Las notas no se editan a mano** (decisión de V0ra, 2026-11-16): son el archivo de las conversaciones y dicen lo que se dijo, erratas incluidas. Por eso la fusión normal hace bien en pisar cualquier cambio a mano en MERGED. REParsea·me solo marca esas notas como aviso («no coincide con el archivo») y las deja para que la siguiente importación las devuelva a su forma original.
>
> **Aplicado al vault real** el 2026-11-16, con backup previo y Obsidian cerrado. Dio las mismas cifras que en la copia.

Para la recuperación de imágenes, que es otra herramienta, ve a [RECUPERAR_IMAGENES.md](RECUPERAR_IMAGENES.md). Para el diseño general, a [ARCHITECTURE.md](ARCHITECTURE.md).

---

## En una frase

REParsea·me reescribe las notas de `RAW_VAULT` como las escribiría **el parser de hoy**, les pone el nombre que les daría hoy, y después reconstruye `MERGED_VAULT` y `PRJ_VAULT` desde cero. **Con simulación primero, copia de seguridad y vuelta atrás.**

## Por qué existe

Cada mejora del parser vale para lo que se importa **después**. Las notas que ya estaban escritas se quedan como salieron. Medido el 2026-11-16 en el vault real, con 7.358 notas en RAW:

| Deriva | Notas | Desde |
| --- | --- | --- |
| Bloques en JSON crudo (`{"content_type": …}`): razonamiento, herramientas, archivos citados, instrucciones personalizadas, Canvas | 3.316 | Hasta `9fc3496` |
| «Imagen no disponible» | 1.648 | Exports de 2026 (`file_XXXX.dat`) |
| ChatGPT sin `model` en el frontmatter | 261 | Antes de que se guardara |
| Sin `conv_id` | 44 | Las más antiguas |
| Bytes nulos (marcadores `\x00IMG` sin resolver) | 19 | Versiones antiguas |
| Marcadores de cita en crudo | 8 | Antes de `1827009` |
| Sin la lista de adjuntos del proyecto | ¿? | Antiguas |

Y va a volver a pasar: cada vez que el parser mejore habrá una deriva nueva.

## Por qué no basta con reimportar

Por las **huellas**. Cada nota de RAW lleva en el nombre la huella de su contenido (`…-h4e66319e.md`). Si el parser de hoy escribe la misma conversación de otra manera, la huella cambia, el nombre también, y RAW gana **otra versión al lado de la vieja**. Después la fusión:

- elige como campeona la versión con **más palabras**, que suele ser la vieja, porque el JSON crudo abulta;
- añade los mensajes de la otra como «exclusivos», porque no los reconoce como iguales.

Resultado: miles de notas de MERGED con **las dos formas mezcladas**. Pasaría con el próximo export de ChatGPT aunque nadie tocara nada, así que conviene pasar REParsea·me **antes** de importar exports nuevos.

---

## Cómo lo hace

### Paso 0. Aviso

Antes de empezar: copia de seguridad del vault (recomendada, no obligatoria) y **Obsidian cerrado**.

### Paso 1. Diagnóstico (no escribe nada)

Recorre RAW y, por cada nota, dice qué derivas tiene. Cada deriva sabe si se puede arreglar **con la nota sola** o si hace falta **el export**:

| Se arregla con la nota sola | Necesita el export |
| --- | --- |
| JSON crudo (la línea lleva el bloque completo), instrucciones arriba, bytes nulos, citas en crudo | Imagen no disponible, `model`, `conv_id`, adjuntos del proyecto |

El informe sale con cifras, como la tabla de arriba.

### Paso 2. Arreglar RAW

- **Con la nota sola:** convierte cada bloque **con las mismas funciones del parser** (`render_bloque_sin_parts`, `_resolver_marcadores`…). No se vuelve a escribir la lógica: si el parser mejora, REParsea·me mejora con él.
- **Con el export:** si el export de origen está en la carpeta de exports, regenera la nota entera desde él. Si no está, se queda con lo que se pueda arreglar con la nota sola, y el informe lo dice.
- **Renombra cada nota con la huella de su contenido nuevo.** Es la clave: así la próxima importación encuentra ese nombre, ve el mismo contenido y la salta, sin duplicar.
- Si dos versiones de una conversación quedan **idénticas** (solo se diferenciaban por las derivas), se queda una y la otra va a la papelera.
- Copia exacta de cada nota antes de tocarla, como `recuperar_imagenes.py`, y `--deshacer`.

### Paso 3. Reconstruir los derivados

`vault_merge.py` y `project_organizer.py` desde cero, **en carpetas nuevas**, y cambio al final. Hace falta porque la fusión sobrescribe por nombre pero **nunca borra**: las notas que cambian de nombre (hay 4 cuyo título salió del JSON, `content-type-user-editable-context…`) dejarían una huérfana. Los vaults viejos quedan guardados hasta que V0ra diga.

### Paso 4. Sello de versión

Cada nota escrita, por la importación o por REParsea·me, lleva `parser: <fecha>` en el frontmatter. La próxima vez, el diagnóstico es «estas son anteriores a tal fecha» en vez de heurísticas.

---

## Qué hace y qué no hace

| Hace | No hace |
| --- | --- |
| Pone RAW como lo escribiría el parser de hoy | No inventa lo que el export no trae |
| Renombra por huella para que la próxima importación no duplique | No toca notas editadas a mano sin preguntar (ver decisiones) |
| Reconstruye MERGED y PRJ en limpio | No borra nada sin papelera |
| **Por defecto solo simula** | Sin `--aplicar` no escribe ni una nota |

## Cómo se comprueba que funciona

- Test de punta a punta: RAW sintético con cada deriva → REParsea·me → la nota es **byte a byte** igual a la que escribe la importación del mismo export.
- Test anti-duplicado: después de REParsea·me, reimportar el mismo export **no crea ni un fichero** en RAW.
- Test de vuelta atrás: aplicar + deshacer deja RAW idéntico al de antes (contenido, nombres y fechas).
- Prueba en una **copia** del vault real antes de tocar el de V0ra.

## Decisiones

Tomadas con V0ra el 2026-11-16:

1. **Versiones: se arreglan todas.** RAW sigue siendo el archivo fiel de cada export, solo que legible, y la fusión sigue teniendo todas las versiones para elegir.
2. **Notas editadas a mano: se marcan y no se tocan.** Si, quitando las derivas conocidas, una nota sigue sin coincidir con lo que sale de su export, el informe la lista como «no toco: difiere del export» para que V0ra la mire. Las notas no deberían editarse nunca, porque son el archivo; el aviso existe para encontrar las que sí se editaron.
3. **Recuperar imágenes queda integrado.** Coser cada nota con su imagen es trabajo del parser: hoy, al importar, resuelve los `file_XXXX.dat`, cuelga las generadas de la biblioteca en su conversación y guarda con qué se generó cada una. Al regenerar desde el export con el parser de hoy, las imágenes vuelven solas. «Imagen no disponible» pasa a ser una deriva más, de las que necesitan el export. `recuperar_imagenes.py` se retira cuando REParsea·me cubra sus tres casos (avisos, `--biblioteca` y `--metadatos`) con tests. Hasta entonces se queda como está.

Abiertas:

4. **Quién hace de papelera:** ¿la misma carpeta de copias de `recuperar_imagenes.py`, o una propia? Si se integra, lo natural es heredar la suya.
5. Comprobar si algo más apunta a los nombres de RAW. Revisado el 16-nov: la galería lee MERGED, así que se regenera. Faltan los pendientes y `_exports_procesados.json`.
6. Las imágenes copiadas a los bancos al regenerar llevan la misma huella que les daría la importación, así que no se duplican. Hay que comprobarlo con un test.

## Pendiente

- Port a EN (**REParse·me**) en el worktree `en`.
