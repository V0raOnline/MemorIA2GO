# Organizar el vault

> **¿Qué pregunta responde este documento?**
> *¿Cómo se organizan las carpetas de mi vault, qué puedo cambiar, y por qué a veces M3M0R·IA se niega a seguir?*

Para instalarlo y arrancarlo, ve al [README](README.md). Para el diseño general, a [ARCHITECTURE.md](ARCHITECTURE.md). Esto es solo cómo se reparten las carpetas.

Lo que dice este documento lo vigila un test: `tests/test_organizar_vault_documentado.py`. Si el código cambia y el documento no, el test falla.

---

## En una frase

Puedes elegir cómo se organiza el vault fusionado (todo junto, todo junto con un vault de proyectos, o una carpeta por proveedor) y dónde vive la fuente cruda (`RAW_VAULT`). M3M0R·IA **se niega a seguir** antes que dejarte un vault partido en dos sin avisar.

## Las tres organizaciones

Se eligen en **Configuración → Organización del vault fusionado** (en `memoria_config.yaml`, `options.layout_preset`).

| Organización | En la configuración | Conversaciones fusionadas | Vault de proyectos |
|---|---|---|---|
| **Todo junto + proyectos** (por defecto) | `proyectos` | todas en `MERGED_VAULT/Conversaciones` | sí, `PRJ_VAULT`, una carpeta por proyecto |
| **Todo junto** | `unico` | todas en `MERGED_VAULT/Conversaciones` | no |
| **Una carpeta por proveedor** | `proveedor` | `MERGED_VAULT/ChatGPT/Conversaciones`, `MERGED_VAULT/Claude/Conversaciones`… | no |

«Todo junto + proyectos» es lo que M3M0R·IA hacía siempre. Un vault construido antes de que existiera esta opción es de este tipo.

Con **una carpeta por proveedor**:
- Cada nota va a la carpeta de su campo `provider`. Las sesiones de Claude Code van con Claude y las de Codex con ChatGPT, porque es de OpenAI. Un proveedor que M3M0R·IA no conoce recibe una carpeta con su nombre en vez de perderse.
- Solo se crean las carpetas de los proveedores que tienen notas. Si solo importas Claude, no aparece un `ChatGPT/` vacío.
- **Los temas siguen siendo comunes** (`MERGED_VAULT/_Temas`), porque un tema cruza proveedores.

**Sin vault de proyectos**, los proyectos del export nuevo de Claude no se pierden: van a `MERGED_VAULT/CLAUDE_WEB/PROYECTOS`, junto a sus artefactos (con una carpeta por proveedor, `MERGED_VAULT/Claude/CLAUDE_WEB/PROYECTOS`).

**La fuente cruda (`RAW_VAULT`) no se parte nunca.** Es de donde sale todo lo demás, y la fusión la recorre entera cada vez.

## Cuándo se puede cambiar y cuándo no

Un vault **sin conversaciones fusionadas** puede cambiar de organización libremente. Uno que ya las tiene:

| Cambio | ¿Se puede? | Por qué |
|---|---|---|
| Entre «todo junto» y «todo junto + proyectos» | sí | el vault de proyectos es una vista que se regenera |
| …si ya hay proyectos de Claude escritos | **no** | esos ficheros son la única copia: escribir los nuevos en otro sitio los partiría |
| De «todo junto» a «una carpeta por proveedor», o al revés | **no** | las notas nuevas irían a otra carpeta y cada conversación saldría dos veces |

Cuando no se puede, la opción sale **desactivada en Configuración, con el motivo**, y si la pones a mano en `memoria_config.yaml` el pipeline **se para antes de escribir nada**. Mover un vault con notas de una organización a otra necesita una migración que **todavía no existe**.

## Dónde vive la fuente cruda (`RAW_VAULT`)

Por defecto, dentro de tu carpeta base, como siempre. Pero es materia prima del pipeline, no algo pensado para abrir en Obsidian, así que puedes llevarla a otra carpeta o a otro disco (en la configuración, `paths.raw_vault`).

**Si ya tienes un vault, no cambies la ruta a mano:** muévela con

```
python mover_raw.py --hacia <carpeta>
```

- **Copia y verifica** cada fichero: tamaño, contenido (SHA-1) y fecha de modificación, que la fusión usa para desempatar.
- **No borra el original.** Cuando lo hayas comprobado, lo borras tú.
- Con `--dry-run` solo cuenta y comprueba.
- Si se corta, se puede repetir: lo que ya está copiado e igual no se vuelve a copiar.
- Se niega con un destino que ya tiene ficheros ajenos, que está dentro del RAW o que contiene el vault.

Al terminar, te dice que pongas la carpeta nueva en Configuración.

**El pipeline se niega a seguir** si la configuración dice que el RAW está en un sitio y el vault sabe que está en otro, o si la fuente externa no está (un disco desconectado). Seguir escribiría las notas nuevas en un RAW vacío y la fusión no vería las anteriores, sin ningún error.

## Cómo lo sabe: el marcador

La primera vez que el pipeline trabaja sobre un vault, deja en su raíz un fichero pequeño, `.m3m0ria_layout.json`, con la organización y las carpetas con las que se construyó. Así M3M0R·IA sabe cómo es tu vault sin adivinarlo mirando qué carpetas hay. El punto delante hace que Obsidian no lo enseñe. No lo borres ni lo edites a mano.

## Qué sigue a la organización

Todo lo que recorre conversaciones lee las carpetas del marcador: la fusión, los índices, las estadísticas del Observatorio, Cartografía, las sesiones locales, **la galería de imágenes y la recuperación de imágenes** (que también encuentra las notas de un RAW externo, y las devuelve a su sitio al deshacer).

## Lo que no hace

- **No migra un vault con notas de una organización a otra.** Está en el roadmap.
- **No hace opcional el RAW.** La fusión no es incremental: reagrupa todas las variantes de cada conversación desde el RAW cada vez, y el RAW guarda el registro de lo importado.
- **No mueve nada por su cuenta.** Ni el RAW ni las carpetas: lo que cambia de sitio lo cambias tú, con la herramienta o a mano.
