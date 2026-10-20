# Cartografía

> **¿Qué pregunta responde este documento?**
> *¿Qué hace la pestaña Cartografía, qué no hace, y cómo decide qué conversación va en qué tema?*

Para instalarlo y arrancarlo, ve al [README](README.md). Para el diseño general, a [ARCHITECTURE.md](ARCHITECTURE.md). Esto es solo Cartografía.

---

## En una frase

Cartografía te ayuda a ordenar las conversaciones que **no pertenecen a ningún proyecto**, sin moverlas ni etiquetarlas: tú escribes reglas por tema, M3M0R·IA genera una nota índice por tema con enlaces a sus conversaciones, y el grafo de Obsidian dibuja el resto.

## ¿Lo decide por heurística?

**No.** No hay IA, ni embeddings, ni «parecido de significado», ni puntuación de relevancia. Es **coincidencia de texto determinista con reglas que escribes tú**: la misma nota y las mismas reglas dan siempre el mismo resultado, y siempre puedes saber por qué una nota entró en un tema.

Una nota entra en un tema si:

- contiene, **literalmente**, alguna de sus palabras o frases, o
- su frontmatter tiene el valor que pide una regla `campo=valor`.

Lo único con aire de heurística está en la **nube** (las palabras que se te *sugieren*): filtra por frecuencia y descarta palabras de relleno. Pero la nube solo sugiere. Quien decide qué entra en un tema son tus reglas, y nada más.

---

## Qué hace y qué no hace

| Hace | No hace |
| ---- | ------- |
| Mira las conversaciones **huérfanas** (sin proyecto) | No mira las que ya tienen proyecto, ni otros vaults (música, imágenes, Substack…) |
| Te enseña de qué hablan, con una nube de palabras | No entiende significados: «perro» no encuentra «can», ni «organoide» encuentra «organoides» |
| Agrupa por **tus** reglas, en temas | No clasifica sola: sin reglas tuyas no hay temas |
| Genera una nota índice por tema, con enlaces | **No cambia ninguna conversación**: no la mueve, ni la renombra, ni le añade etiquetas ni `Project_name` |
| Te dice qué ha quedado sin cubrir y cuánto cubren tus temas | No crea proyectos ni toca `PRJ_VAULT`: un tema no es un proyecto, y una nota puede estar en varios |
| Te deja poner nombre a los proyectos de ChatGPT que el export trae sin nombre | No ordena por relevancia: una palabra mencionada de pasada cuenta igual que si fuera el asunto |
| Funciona sin Internet | No borra material tuyo (ver «Qué borra y qué no») |

---

## Qué notas mira

Solo las **huérfanas** de `MERGED_VAULT/Conversaciones`: las que tienen `Project_name: none`, vacío o sin esa línea. Se excluyen los ficheros de índice.

- Una conversación **deja de ser huérfana** cuando se le asigna un proyecto, por ejemplo al nombrar un gizmo (ver más abajo). Entonces desaparece de la nube y de los temas.
- Las conversaciones de sesiones de Claude Code y Codex entran por su **nota madre**; las notas hijas (razonamientos, herramientas) quedan fuera a propósito, porque su vocabulario (`git`, rutas, comandos) ensuciaría la nube.
- Las huérfanas quedan en la carpeta `none` de `PRJ_VAULT`. Cartografía no las mueve de ahí.

---

## 1. La nube

Es un **catalejo, solo lectura**: no clasifica ni modifica nada.

Cómo se calcula:

1. De cada huérfana se toman las palabras del cuerpo y del título (cada palabra cuenta **una vez por nota**, así una conversación enorme no secuestra la nube).
2. Se cuenta en cuántas notas aparece cada palabra. Ese número es el tamaño.
3. **Ranking genérico**: se descartan las palabras de relleno (artículos, «pero», «the»…, en español e inglés), las que aparecen en menos de 3 notas y las que aparecen en más de la cuarta parte de las huérfanas (esas son «fondo conversacional»: lo que discrimina vive en la franja media). Se muestran hasta 100.
4. **Vocabulario de proyectos**: las palabras que coinciden con nombres de proyecto que ya existen se muestran **siempre**, aunque sean raras, y salen en **magenta**. Esos nombres se siembran de tres sitios: las carpetas de primer nivel de `PRJ_VAULT`, los valores de `gizmo_map.json` y los proyectos declarados dentro de los exports de Claude y Grok.
5. Al pulsar una palabra ves las notas que la contienen (hasta 200, con el total). **Usa exactamente las mismas reglas que un tema de una sola palabra**: lo que ahí ves es lo que esa regla pescaría.

---

## 2. Los temas: cómo se decide qué nota entra

Un tema es un **nombre** y una **lista de reglas**. Hay tres tipos:

| Regla | Cómo se escribe | Qué exige | Ejemplo |
| ----- | --------------- | --------- | ------- |
| **Palabra** | una sola palabra, sin espacios | que aparezca como **palabra entera exacta**, en el cuerpo o en el título | `receta` |
| **Frase** | con espacios | que ese texto aparezca **tal cual** en el cuerpo o en el título, como trozo de texto (sin límite de palabra) | `rutina de ejercicios` |
| **Campo=valor** | `campo=valor` | que ese campo del frontmatter valga **exactamente** eso | `provider=claude`, `source=claude_export` |

Cómo se combinan:

- **Una sola regla basta.** Las reglas de un tema se combinan con «o».
- **Una nota puede estar en varios temas**, y eso es lo deseado.
- No hay pesos ni umbrales: una mención y cien valen lo mismo.
- Dentro de cada tema, las notas salen de la **más reciente a la más antigua**.
- Antes de comparar, **todo se pasa a minúsculas y se le quitan los acentos**, en las reglas y en las notas: `FÍSICA`, `física` y `fisica` son lo mismo.
- Un tema cuyas reglas son **todas** `campo=valor` se llama **estructural** («de dónde viene»). Uno con alguna palabra o frase es **de contenido** («de qué habla»).

### Qué texto se mira

- **Sí**: el cuerpo (todos los mensajes, tuyos y de la IA) y el **título**.
- **No**: las etiquetas, el nombre del fichero ni el resto del frontmatter. El frontmatter solo entra por una regla `campo=valor`.

### La letra pequeña: lo que sorprende

Cada fila es una regla del motor, fijada por un test (`tests/test_cartografia_documentada.py`).

| Situación | Qué pasa | Qué hacer |
| --------- | -------- | --------- |
| **Singular y plural** | `organoide` y `organoides` son palabras distintas | Pon las dos en el tema |
| **Guion o guion bajo** | no separan palabras: `happypuking-lab` es **una** palabra y la regla `happypuking` no la pesca | Escribe la regla completa, `happypuking-lab` |
| **Menos de 3 letras** | no existen como palabras: `ia`, `ml`, `o3` no pescan nada | Usa una palabra más larga o una frase (`de la ia`) |
| **Números sueltos** | `2025` no pesca; mezclados con letras sí (`gpt4`) | Añade una palabra con letras |
| **Frases** | son un trozo de texto: `casa de` pesca «casa **de**corada» | Hazlas lo bastante específicas |
| **Palabras de relleno** | **no** se filtran en los temas (solo en la nube): una regla `pero` pesca casi todo | No uses relleno como regla |
| **Trozos de palabra** | una palabra es entera: `receta` no pesca «recetario» | Pon `recetario` aparte |

Si un tema te devuelve **0**, casi siempre es una de estas filas.

---

## 3. El índice: cómo se genera

**Cuándo**: al pulsar «Generar índice», y también **automáticamente en el paso 4 de cada ejecución del pipeline**, si existe tu `topic_map.json`. No hace falta reiniciar nada al editar temas.

**Cómo**: se escanean las huérfanas **una sola vez**, y por cada tema se escribe una nota en `MERGED_VAULT/_Temas/`. El nombre del fichero es el del tema pasado a minúsculas, sin acentos y con guiones.

Es **derivado y regenerable**: puedes borrarlo y regenerarlo, y las conversaciones no se tocan.

Lo que se escribe:

| Fichero | Qué es |
| ------- | ------ |
| `_Temas/<tema>.md` | una nota por tema: su nombre, sus reglas y la lista de conversaciones con enlace `[[…]]`, fecha, proveedor y título |
| `_Temas/_sin-tema.md` | los **puntos ciegos** (abajo) |
| `_Temas/.temas_stats.json` | un resumen para el Observatorio, oculto para Obsidian por el punto inicial |

### Qué borra y qué no

Al regenerar, solo se retiran las notas de `_Temas/` que **llevan la marca `generado_por: m3m0ria`** y cuyo tema **ya no está en tu mapa**. Una nota tuya que viva en esa carpeta, sin la marca, no se toca. Las conversaciones nunca se tocan.

---

## 4. Puntos ciegos y cobertura

`_sin-tema.md` te dice qué te falta, en dos capas:

| Capa | Qué significa | Para qué sirve |
| ---- | ------------- | -------------- |
| **Sin ningún tema** | ni una regla de contenido ni una estructural las pesca | Si has creado un tema estructural por proveedor, debería rondar cero: lo que aparezca suele ser una **anomalía** de frontmatter |
| **Solo pescadas por redes estructurales** | se sabe de dónde vienen, pero ningún tema de contenido las toca | Es **tu trabajo pendiente real**: las que aún no sabes de qué hablan |

La **cobertura de contenido** que ves en el Observatorio es el porcentaje de huérfanas que cae en **al menos un tema de contenido** (por palabra o frase). Una conversación pescada solo por `provider=claude` **no cuenta**: sabes de dónde viene, no de qué trata. Mide cobertura, **no calidad**: un tema mal escrito que pesca muchas notas también sube la cifra.

---

## Un ejemplo completo (salida real)

Cinco huérfanas y una que ya tiene proyecto, y estos temas:

```json
{
  "Cocina": ["receta"],
  "Entrenamiento": ["rutina de ejercicios"],
  "Fuente Claude": ["provider=claude"],
  "Organoides": ["organoides"],
  "Inteligencia artificial": ["ia"]
}
```

| Nota | Qué dice | Resultado |
| ---- | -------- | --------- |
| `pan-casero` | «Quiero una **receta** de pan» | en **Cocina** |
| `plan-deportivo` | «Una **rutina de ejercicios** para el gimnasio» | en **Entrenamiento** |
| `charla-claude` | «Hablemos de filosofía» (proveedor Claude) | en **Fuente Claude**, y como solo cae ahí, en la capa *solo estructural* |
| `cultivo` | «Mi **organoide** crece bien» | **sin ningún tema**: la regla dice `organoides`, la nota dice `organoide` |
| `sobre-ia` | «La **IA** y yo» | **sin ningún tema**: `ia` tiene menos de 3 letras y no pesca nada |
| `cena-de-gala` | «Otra receta…» | **ni se mira**: ya tiene proyecto (`Arkinesis`) |

Lo que se genera, tal cual:

```markdown
---
title: "Tema: Cocina"
tipo: tema
generado_por: m3m0ria
generado: 2026-10-20T20:31:36
palabras: "receta"
---

# Tema: Cocina

1 conversaciones huerfanas relacionadas (palabras: receta).

- [[pan-casero]] — 2026-06-03 · chatgpt · Pan casero
```

Y `Organoides` e `Inteligencia artificial` se crean igualmente, con «0 conversaciones»: es la señal de que esas reglas no pescan nada. La cobertura de contenido sale **40 %** (2 de 5: solo `pan-casero` y `plan-deportivo` caen en un tema de contenido).

---

## El otro mecanismo: Proyectos huérfanos (ChatGPT)

No tiene que ver con los temas. Resuelve un problema distinto: el export de ChatGPT identifica los proyectos con un **ID interno (gizmo) sin nombre**.

1. **Se detectan al importar.** Una conversación con un gizmo que no está en `gizmo_map.json` se apunta en `RAW_VAULT/_gizmos_pendientes.json`, con cuántas conversaciones tiene y títulos y fechas de muestra.
2. **Tú les das nombre.** La pestaña muestra cada ID con sus títulos de muestra, para que lo reconozcas. Escribes el nombre y pulsas «Guardar y actualizar vault».
3. **Se corrige sin reimportar.** El nombre se guarda en `gizmo_map.json`; `patch_gizmo_map.py` reescribe **solo** las líneas `Project_name` y `source_project` de las notas del RAW (el cuerpo no se toca); y la interfaz relanza los pasos 2 a 4, sin repetir la importación.
4. **Efecto.** Esas conversaciones dejan de ser huérfanas, se ordenan bajo su proyecto en `PRJ_VAULT`, y el nombre pasa a sembrar la nube (magenta).

Las filas que dejes en blanco siguen esperando. Solo afecta a ChatGPT: Claude y Grok traen los nombres de sus proyectos en el export.

---

## Dónde vive cada cosa

| Qué | Dónde |
| --- | ----- |
| **Tus temas** | `topic_map.json`, junto al programa. No se commitea. Al guardar desde la interfaz se hace antes una copia `.bak`. **Es curación tuya y ningún reproceso la reconstruye: guarda una copia.** |
| Nombres de gizmos | `gizmo_map.json` (la ruta está en tu configuración) |
| Gizmos pendientes | `RAW_VAULT/_gizmos_pendientes.json` |
| Índices de temas | `MERGED_VAULT/_Temas/` |
| El motor | `orphan_cloud.py` (nube, temas, índice) y `patch_gizmo_map.py` (gizmos) |

Si tu `topic_map.json` tiene un error (basta una coma de más), el motor **se queda sin ningún tema, avisa por consola y no toca los índices que ya existían**. Ojo con dónde ves ese aviso: aparece en el **log en vivo de la Construcción** (el paso 4 lo ejecuta), pero el botón «Generar índice» solo te dirá «0 tema(s)», sin explicar por qué. Si te dice 0 y no esperabas 0, abre `topic_map.json` y busca el error de JSON. Y no pulses «Guardar temas» con la lista vacía: sobrescribiría el fichero (te quedaría la copia `.bak`).

---

## Cómo comprobar que un tema hace lo que crees

- **Mira lo que te dice «Generar índice».** Termina con «sin coincidencias: …» y la lista de los temas que no pescaron nada. Cada uno de esos nombres es una regla que no funciona: revisa la tabla de la letra pequeña.
- **Abre `_Temas/<tema>.md`.** El número de arriba y la lista dicen qué pescó.
- **Prueba la palabra en la nube**: pulsarla enseña las notas que contiene, con las mismas reglas que un tema de una palabra.
- **Desde la consola**: `python orphan_cloud.py "<tu base_vault>" --term palabra` lista las notas que contienen esa palabra.

---

## Límites conocidos

- **Solo texto, sin sinónimos ni raíces.** No entiende significado, ni singular/plural, ni conjugaciones.
- **Está anclada a `MERGED_VAULT/Conversaciones`.** No mira otros vaults.
- **Las palabras de relleno de la nube son de español e inglés.** En otro idioma verás más ruido.
- **La cobertura no mide calidad.**
- **Las frases se buscan como texto**, no como palabras enteras.
