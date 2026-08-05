# Me he atascado

> **¿Qué pregunta responde este documento?**
> *¿Y si no sé nada de esto?*

M3M0R·IA da por sabidas dos cosas que no tiene por qué saber todo el mundo: usar una terminal y abrir las herramientas de desarrollo del navegador. Este documento no enseña a usar M3M0R·IA — enseña lo que hay **antes**.

No hace falta leerlo entero. Ve a lo tuyo:

- [No he usado una terminal en mi vida](#no-he-usado-una-terminal-en-mi-vida) — instalar Python y arrancar la aplicación.
- [Me piden un token de Suno y no sé qué es eso](#me-piden-un-token-de-suno-y-no-sé-qué-es-eso) — sacarlo del navegador, paso a paso.

---

## No he usado una terminal en mi vida

Sin conocimientos previos, en Windows, paso a paso. No hay nada aquí que puedas romper.

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

## Me piden un token de Suno y no sé qué es eso

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

*¿Sigues atascada? Lo que no esté aquí probablemente esté en [ARCHITECTURE.md](ARCHITECTURE.md) (cómo funciona por dentro) o en [DEVLOG.md](DEVLOG.md) (qué aprendimos construyéndolo).*
