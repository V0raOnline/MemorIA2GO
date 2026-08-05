#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_flowmusic.py — Reconocimiento de la API de Flow Music (flowmusic.app).

Paso previo a escribir un backup_flowmusic.py. NO descarga nada: solo
averigua tres cosas que ahora mismo no sabemos y que no se pueden
adivinar sin credenciales:

  1. QUE CABECERAS HACEN FALTA. Prueba /__api/users/me con distintas
     combinaciones y luego, por ablacion (quitando cabeceras de una en
     una), reduce el conjunto al minimo imprescindible. Es el equivalente
     a descubrir que Suno, ademas del Bearer de Clerk, exigia un header
     propietario 'browser-token' — eso costo una tarde de prueba y error.
  2. QUE FORMA TIENE LA API. Vuelca el esquema (claves -> tipos) de cada
     respuesta, que es lo que necesitamos para escribir el equivalente
     de extract_metadata().
  3. COMO PAGINA. Busca en las respuestas las pistas tipicas (next,
     cursor, offset, has_more, total...). El backend es FastAPI, asi que
     lo mas probable es limit/offset o cursor, NO el page/page_size de
     Suno — y eso cambia como se implementa el resume.

VIA RECOMENDADA: --curl-file
    NO copies las cabeceras a mano. Chrome trunca los valores largos en
    el panel Headers y los muestra con una elipsis (…); si copias lo que
    se ve, te llevas medio token con un caracter '…' literal en medio y
    requests revienta con UnicodeEncodeError (las cabeceras HTTP solo
    admiten latin-1). Pasa en la posicion ~505 con un JWT normal.

    En su lugar: DevTools -> Network -> filtro '__api' -> clic derecho
    sobre la request -> Copy -> "Copy as cURL (bash)". Pega eso en un
    .txt y daselo a este script con --curl-file. Se saca solas TODAS las
    cabeceras sin truncar: el Bearer, la Cookie entera y cualquier header
    propietario que ni sabiamos que existia.

DESCUBRIMIENTO POR TRAVESIA, NO POR FUERZA BRUTA: solo se piden las
rutas que ya hemos visto existir de verdad (/__api/, /__api/users/me,
/__api/projects) y luego se siguen los ids que devuelvan. No hay lista
de rutas adivinadas. Si algo no aparece siguiendo enlaces, se mira en el
Network de DevTools y se anade a SEEDS a mano.

USO:
    python probe_flowmusic.py --curl-file curl.txt --out ./flowmusic_probe

    # alternativas, si prefieres pasar las credenciales sueltas:
    $env:FLOWMUSIC_TOKEN="eyJ..."   # PowerShell
    python probe_flowmusic.py --out ./flowmusic_probe
    python probe_flowmusic.py --token-file token.txt --cookie-file cookie.txt

El token se lee de la variable de entorno o de un fichero, NUNCA de
argv: un token en argv aparece en la lista de procesos del sistema
(tasklist / ps) para cualquiera que mire, y da acceso a la cuenta entera
mientras dure. Mismo criterio que backup_suno.py.

Los valores sensibles se redactan en todo lo que se imprime y se guarda.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

# La consola de Windows (cp1252) revienta con UnicodeEncodeError al
# imprimir titulos con acentos o emoji — y la raiz de esta API responde
# literalmente {"\U0001f3b8": "Riffusion!"}.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://www.flowmusic.app"

# Solo rutas observadas en vivo, no adivinadas.
SEEDS = [
    "/__api/",            # 200 {"\U0001f3b8":"Riffusion!"} — el backend es Riffusion
    "/__api/users/me",    # 200 null sin sesion — canario perfecto para probar auth
    "/__api/projects",    # 401 {"detail":"Unauthorized"} sin sesion — la puerta buena
    # 'conversations' esta confirmada como coleccion (existe
    # /__api/projects/<id>/conversations) y /__api/projects demostro que las
    # colecciones tambien se listan colgando de la raiz. Combinar las dos
    # cosas no es inventar un nombre.
    "/__api/conversations",
]

# UA de navegador real. El UA de juguete de backup_suno.py
# ("Mozilla/5.0 (backup script personal)") es justo lo que un WAF marca,
# y flowmusic.app esta detras de Cloudflare.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

SLEEP = 1.0
TIMEOUT = 30

# Cabeceras que requests/urllib3 calculan solos: reenviarlas desde el
# cURL corrompe la peticion (content-length de un cuerpo que no mandamos,
# host de otra URL, etc.).
CABECERAS_A_IGNORAR = {
    "content-length", "host", "connection", "transfer-encoding",
    # El navegador anuncia br y zstd, que requests NO sabe descomprimir sin
    # brotli/zstandard instalados. Reenviarla hace que el cuerpo llegue
    # ilegible y que r.json() falle, lo que desde fuera parece un fallo de
    # autenticacion cuando en realidad el token esta perfecto. Dejamos que
    # requests anuncie solo lo que sabe decodificar.
    "accept-encoding",
    "te",
}

# Para decidir que valores hay que redactar al imprimir.
CABECERAS_SENSIBLES = ("authorization", "cookie", "token", "auth", "session",
                       "key", "secret", "csrf", "xsrf")

# Cabeceras de respuesta que dicen algo util: si hay rate limit, si
# Cloudflare esta interviniendo, si nos plantan una cookie nueva.
HEADERS_INTERESANTES = (
    "content-type", "set-cookie", "retry-after", "cf-ray", "cf-cache-status",
    "server", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
    "x-request-id", "www-authenticate", "access-control-allow-origin",
)

# Nombres que delatan como pagina una API.
PISTAS_PAGINACION = (
    "next", "next_page", "next_cursor", "cursor", "offset", "limit",
    "page", "page_size", "per_page", "has_more", "has_next", "total",
    "total_count", "count", "results", "items", "data", "edges",
)

ELIPSIS = "…"  # el '…' con el que Chrome trunca lo que muestra


# ---------------------------------------------------------------- cURL

# Chrome (bash) usa comillas simples; Chrome (cmd) y Firefox usan dobles.
# Se aceptan las dos formas, mas -b/--cookie para la cookie suelta.
PATRON_CABECERA = re.compile(
    r"""(?:-H|--header)\s+(?:'([^']*)'|"((?:[^"\\]|\\.)*)")"""
)
PATRON_COOKIE = re.compile(
    r"""(?:-b|--cookie)\s+(?:'([^']*)'|"((?:[^"\\]|\\.)*)")"""
)
PATRON_CUERPO = re.compile(
    r"""(?:--data-raw|--data-binary|--data-ascii|--data|-d)\s+"""
    r"""(?:'([^']*)'|"((?:[^"\\]|\\.)*)")"""
)
PATRON_METODO = re.compile(r"""(?:-X|--request)\s+['"]?([A-Z]+)['"]?""")

PATRON_URL = re.compile(r"""['"](https?://[^'"]+)['"]""")


def normalizar_curl(texto: str) -> str:
    """Chrome ofrece 'Copy as cURL' en dos sabores, y en Windows el que
    sale por defecto NO es el de bash: es el de cmd, que en vez de
    comillas simples usa un escapado propio con acentos circunflejos:

        curl.exe ^"https://...^" ^
          -H ^"accept: application/json^" ^

    Si no se deshace primero, ningun patron encaja y el fichero parece
    vacio aunque este perfectamente copiado."""
    if '^"' not in texto:
        return texto.replace("\\\n", " ")      # bash: continuacion con \

    texto = texto.replace("^\n", " ")           # cmd: continuacion con ^
    # En cmd el circunflejo escapa el caracter siguiente, sea cual sea:
    # no solo las comillas, tambien { } [ ] & | < >. Un cuerpo JSON sale
    # como ^{^"clip_ids^":^[... y si solo se quita el de las comillas
    # quedan llaves y corchetes con basura delante.
    texto = re.sub(r"\^(.)", r"\1", texto, flags=re.S)
    return texto


def desescapar(valor: str) -> str:
    """Deshace el \\" que queda dentro de los cuerpos JSON."""
    return valor.replace('\\"', '"').replace("\\\\", "\\")


def cargar_curl(ruta: Path):
    """Extrae URL, metodo, cuerpo y cabeceras de un 'Copy as cURL'.
    Devuelve (url, metodo, cuerpo, cabeceras).

    Esta es la via buena por tres motivos: los valores vienen completos
    (sin la elipsis con la que Chrome trunca lo que pinta en el panel
    Headers), la URL da el endpoint exacto sin deducirlo, y el
    --data-raw revela que el listado va por POST con los parametros en
    el cuerpo — cosa que desde fuera no se ve."""
    texto = normalizar_curl(ruta.read_text(encoding="utf-8"))

    cabeceras = {}
    for m in PATRON_CABECERA.finditer(texto):
        crudo = m.group(1) if m.group(1) is not None else m.group(2)
        if ":" not in crudo:
            continue
        k, v = crudo.split(":", 1)
        k, v = k.strip(), v.strip()
        # Pseudo-cabeceras HTTP/2 (:authority, :method...) no van por aqui.
        if not k or k.startswith(":"):
            continue
        if k.lower() in CABECERAS_A_IGNORAR:
            continue
        cabeceras[k] = v

    for m in PATRON_COOKIE.finditer(texto):
        crudo = m.group(1) if m.group(1) is not None else m.group(2)
        cabeceras.setdefault("Cookie", crudo.strip())

    # La primera URL entrecomillada es la del propio curl. Las que
    # aparecen dentro de un -H (referer, origin...) van despues.
    m = PATRON_URL.search(texto)
    url = m.group(1) if m else None

    m = PATRON_CUERPO.search(texto)
    cuerpo = None
    if m:
        cuerpo = desescapar(m.group(1) if m.group(1) is not None else m.group(2))

    m = PATRON_METODO.search(texto)
    if m:
        metodo = m.group(1)
    else:
        # curl sin -X manda POST en cuanto hay cuerpo; si no, GET.
        metodo = "POST" if cuerpo is not None else "GET"

    return url, metodo, cuerpo, cabeceras


# ----------------------------------------------------------- validacion

def validar_cabeceras(cabeceras: dict) -> list:
    """Caza credenciales truncadas ANTES de que urllib3 tire un
    UnicodeEncodeError ilegible desde las entranas de http.client."""
    problemas = []
    for k, v in cabeceras.items():
        if ELIPSIS in v:
            problemas.append(
                f"'{k}' contiene el caracter '…' en la posicion {v.find(ELIPSIS)}: "
                f"lo copiaste truncado del panel Headers de Chrome. "
                f"Usa 'Copy as cURL' y --curl-file.")
            continue
        try:
            v.encode("latin-1")
        except UnicodeEncodeError as e:
            malo = v[e.start:e.end]
            problemas.append(
                f"'{k}' tiene el caracter no-latin-1 {malo!r} en la posicion "
                f"{e.start}. Las cabeceras HTTP solo admiten latin-1, asi que "
                f"ese valor viene corrupto o mal copiado.")
            continue
        if k.lower() == "authorization" and "bearer" in v.lower():
            jwt = v.split(None, 1)[-1]
            if jwt.count(".") != 2:
                problemas.append(
                    f"el Bearer no tiene los 3 segmentos de un JWT "
                    f"({jwt.count('.') + 1} encontrados): esta incompleto.")
    return problemas


def es_sensible(nombre: str) -> bool:
    n = nombre.lower()
    return any(p in n for p in CABECERAS_SENSIBLES)


def redactar(texto: str, secretos: list) -> str:
    """Ningun secreto sale por pantalla ni acaba en disco."""
    for s in secretos:
        if s and len(s) > 8:
            texto = texto.replace(s, f"<REDACTADO:{len(s)}chars>")
    return texto


# -------------------------------------------------------------- esquema

def esquema(valor, profundidad=0, max_prof=4):
    """Resume un JSON como arbol de claves -> tipos. Esto es lo que de
    verdad necesitamos: no los datos, sino los NOMBRES DE CAMPO con los
    que se escribira extract_metadata()."""
    if profundidad > max_prof:
        return "..."
    if isinstance(valor, dict):
        return {k: esquema(v, profundidad + 1, max_prof) for k, v in valor.items()}
    if isinstance(valor, list):
        if not valor:
            return "[] (vacia)"
        return [esquema(valor[0], profundidad + 1, max_prof),
                f"(lista de {len(valor)} elementos, se muestra el primero)"]
    if valor is None:
        return "null"
    if isinstance(valor, str):
        # Marcar las URLs: nos dicen desde que CDN se sirve el audio y si
        # lleva firma con caducidad (query con Expires/Signature/token).
        if valor.startswith("http"):
            p = urlparse(valor)
            firmada = any(x in (p.query or "").lower()
                          for x in ("expires", "signature", "token", "x-amz", "x-goog"))
            return f"url<{p.netloc}>{' FIRMADA/CADUCA' if firmada else ''}"
        return f"str({len(valor)})"
    return type(valor).__name__


def rutas_api_desde_url(url: str) -> list:
    """De una URL de frontend tipo https://www.flowmusic.app/song/<uuid>
    deriva las rutas de API candidatas. Tampoco esto es adivinar de una
    lista de palabras: el propio navegador nos esta dando el nombre del
    recurso y un id valido. Solo hay que traducir la ruta de la SPA a la
    del backend, y probar singular y plural porque FastAPI suele exponer
    la coleccion en plural (/song/<id> -> /__api/songs/<id>)."""
    partes = [x for x in urlparse(url).path.split("/") if x]
    if len(partes) < 2:
        return []
    recurso, ident = partes[-2], partes[-1]
    plural = recurso if recurso.endswith("s") else recurso + "s"
    rutas = [f"/__api/{plural}/{ident}"]
    if plural != recurso:
        rutas.append(f"/__api/{recurso}/{ident}")
    return rutas


PATRON_CONTADOR = re.compile(r"^num_(\w+)$")


def derivar_subrecursos(valor, encontrados=None):
    """La API nombra sus propias sub-colecciones: un objeto proyecto con
    'num_conversations' esta diciendo que cuelga de el una coleccion
    llamada 'conversations'. Eso no es adivinar una ruta de una lista de
    palabras — es leer lo que la respuesta declara. Devuelve los nombres
    para poder pedir /__api/<recurso>/<id>/<nombre>."""
    encontrados = encontrados if encontrados is not None else set()
    if isinstance(valor, dict):
        for k, v in valor.items():
            m = PATRON_CONTADOR.match(k)
            if m and isinstance(v, int):
                encontrados.add(m.group(1))
            derivar_subrecursos(v, encontrados)
    elif isinstance(valor, list):
        for v in valor[:3]:
            derivar_subrecursos(v, encontrados)
    return encontrados


def recolectar(valor, ids=None, hosts=None, paginacion=None, ruta=""):
    """Recorre el JSON juntando (a) ids que se puedan seguir, (b) hosts
    de CDN, (c) claves que huelen a paginacion."""
    ids = ids if ids is not None else {}
    hosts = hosts if hosts is not None else set()
    paginacion = paginacion if paginacion is not None else {}

    if isinstance(valor, dict):
        for k, v in valor.items():
            sub = f"{ruta}.{k}" if ruta else k
            if k.lower() in PISTAS_PAGINACION and not isinstance(v, (dict, list)):
                paginacion[sub] = v
            if k == "id" or k.endswith("_id"):
                if isinstance(v, str) and v:
                    ids.setdefault(sub, v)
            recolectar(v, ids, hosts, paginacion, sub)
    elif isinstance(valor, list):
        for v in valor[:3]:
            recolectar(v, ids, hosts, paginacion, f"{ruta}[]")
    elif isinstance(valor, str) and valor.startswith("http"):
        hosts.add(urlparse(valor).netloc)

    return ids, hosts, paginacion


# ------------------------------------------------------------ peticiones

def autenticado(sesion, extra=None):
    """/__api/users/me es el canario ideal: sin sesion devuelve 200 con
    cuerpo 'null', asi que la diferencia entre autenticado y no se ve
    limpia, sin ambiguedad de codigos de estado."""
    try:
        r = sesion.get(BASE + "/__api/users/me", headers=extra or {}, timeout=TIMEOUT)
    except requests.RequestException as e:
        return False, None, str(e)
    try:
        cuerpo = r.json()
    except ValueError:
        # Distinguir "no autenticado" de "no he sabido leer la respuesta".
        # Confundirlos manda a depurar credenciales que estaban bien.
        pista = r.headers.get("content-encoding", "?")
        return False, r.status_code, f"<cuerpo ilegible, content-encoding={pista}>"
    return (r.status_code == 200 and cuerpo not in (None, {})), r.status_code, cuerpo


def sesion_con(cabeceras: dict) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    s.headers.update(cabeceras)
    return s


def matriz_de_auth(cabeceras_curl, token, cookie, secretos):
    print("\n=== 1. QUE CABECERAS HACEN FALTA ===")
    print("Probando /__api/users/me con distintas combinaciones:\n")

    combos = [("sin auth", {})]
    if token:
        combos.append(("solo Bearer", {"Authorization": f"Bearer {token}"}))
    if cookie:
        combos.append(("solo Cookie", {"Cookie": cookie}))
    if token and cookie:
        combos.append(("Bearer + Cookie",
                       {"Authorization": f"Bearer {token}", "Cookie": cookie}))
    if cabeceras_curl:
        combos.append((f"cURL completo ({len(cabeceras_curl)} cabeceras)",
                       dict(cabeceras_curl)))

    funciona = []
    for nombre, extra in combos:
        ok, status, cuerpo = autenticado(sesion_con({}), extra)
        marca = "SI" if ok else "no"
        resumen = json.dumps(cuerpo, ensure_ascii=False)[:100] if cuerpo else str(cuerpo)
        print(f"  [{marca:>2}] {nombre:<34} {status}  {redactar(resumen, secretos)}")
        if ok:
            funciona.append((nombre, extra))
        time.sleep(SLEEP)

    if not funciona:
        print("\n  [error] ninguna combinacion autentica. Opciones:")
        print("    - el token ha caducado (vuelve a copiarlo de DevTools)")
        print("    - lo copiaste truncado: usa 'Copy as cURL' y --curl-file")
        print("    - hay un header propietario mas, como el 'browser-token'")
        print("      de Suno, que solo aparece en el cURL completo")
        return None

    # El conjunto mas pequeno que funcione gana; si empatan, el primero.
    funciona.sort(key=lambda x: len(x[1]))
    print(f"\n  [ok] autentica con: {funciona[0][0]}")
    return funciona[0][1]


def minimizar_cabeceras(cabeceras, secretos):
    """Ablacion: quita cabeceras de una en una y mira si sigue
    autenticando. Lo que sobrevive es el conjunto minimo — exactamente lo
    que hay que mandar desde backup_flowmusic.py, ni una mas."""
    if len(cabeceras) <= 1:
        return dict(cabeceras)

    print(f"\n--- Ablacion: {len(cabeceras)} cabeceras, quitando de una en una ---")
    actuales = dict(cabeceras)
    for nombre in list(cabeceras.keys()):
        if len(actuales) <= 1:
            break
        prueba = {k: v for k, v in actuales.items() if k != nombre}
        ok, _, _ = autenticado(sesion_con({}), prueba)
        if ok:
            actuales = prueba
            print(f"  prescindible : {nombre}")
        else:
            print(f"  NECESARIA    : {nombre}")
        time.sleep(SLEEP)

    print(f"\n  [ok] conjunto minimo ({len(actuales)}): {list(actuales.keys())}")
    return actuales


def pedir(session, ruta, secretos, etiqueta=None, metodo="GET", cuerpo=None):
    url = ruta if ruta.startswith("http") else BASE + ruta
    etiqueta = etiqueta or ruta
    try:
        if metodo == "POST":
            r = session.post(url, data=cuerpo, timeout=TIMEOUT)
        else:
            r = session.get(url, timeout=TIMEOUT)
    except requests.RequestException as e:
        print(f"  [error] {etiqueta}: {e}")
        return None

    print(f"  {r.status_code}  {metodo} {etiqueta}")
    for h in HEADERS_INTERESANTES:
        if h in r.headers:
            print(f"        {h}: {redactar(r.headers[h], secretos)[:120]}")
    return r


def analizar(r, ruta, out_dir, secretos):
    """Vuelca la respuesta a disco y devuelve (json, ids, hosts, paginacion)."""
    if r is None:
        return None, {}, set(), {}

    cuerpo = r.text
    nombre = ruta.strip("/").replace("/", "_").replace("__api_", "") or "raiz"
    (out_dir / f"{nombre}.raw.json").write_text(
        redactar(cuerpo, secretos), encoding="utf-8")

    try:
        data = r.json()
    except ValueError:
        print(f"        [aviso] respuesta no-JSON ({len(cuerpo)} bytes) — "
              f"probablemente HTML de Cloudflare. Guardada en {nombre}.raw.json")
        return None, {}, set(), {}

    if data is None:
        print("        [aviso] cuerpo 'null' — NO estamos autenticados en esta ruta")
        return None, {}, set(), {}

    esq = esquema(data)
    (out_dir / f"{nombre}.schema.json").write_text(
        redactar(json.dumps(esq, indent=2, ensure_ascii=False), secretos),
        encoding="utf-8")

    ids, hosts, paginacion = recolectar(data)
    print(f"        esquema -> {nombre}.schema.json")
    if paginacion:
        print(f"        paginacion: {paginacion}")
    if hosts:
        print(f"        hosts de CDN: {', '.join(sorted(hosts))}")
    if ids:
        print(f"        ids seguibles: {list(ids.items())[:5]}")
    return data, ids, hosts, paginacion


# ----------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Reconocimiento de la API de Flow Music. No descarga nada.")
    ap.add_argument("--curl-file", help="Fichero con un 'Copy as cURL' pegado. "
                                        "VIA RECOMENDADA: no trunca los valores.")
    ap.add_argument("--token-file", help="Fichero con el Bearer (sin el prefijo 'Bearer ').")
    ap.add_argument("--cookie-file", help="Fichero con la cabecera Cookie completa.")
    ap.add_argument("--header", action="append", default=[], metavar="K:V",
                    help="Cabecera extra, repetible.")
    ap.add_argument("--out", default="./flowmusic_probe", help="Carpeta de salida.")
    ap.add_argument("--song-url", action="append", default=[], metavar="URL",
                    help="URL de una cancion del navegador "
                         "(https://www.flowmusic.app/song/<id>). Repetible. "
                         "De ahi se derivan las rutas de API a pedir.")
    ap.add_argument("--seguir", type=int, default=3,
                    help="Cuantos ids seguir para ver el detalle de un recurso.")
    ap.add_argument("--sin-ablacion", action="store_true",
                    help="Salta la fase de reduccion al conjunto minimo.")
    args = ap.parse_args()

    cabeceras_curl, url_curl = {}, None
    metodo_curl, cuerpo_curl = "GET", None
    if args.curl_file:
        url_curl, metodo_curl, cuerpo_curl, cabeceras_curl = cargar_curl(
            Path(args.curl_file))
        if not cabeceras_curl:
            print(f"[error] no se encontro ninguna cabecera en {args.curl_file}.")
            print("        Asegurate de pegar el 'Copy as cURL' entero, con sus -H.")
            sys.exit(1)
        if url_curl:
            print(f"[info] endpoint real capturado del cURL: {metodo_curl} {url_curl}")
        if cuerpo_curl:
            # El cuerpo es donde viaja la paginacion en un listado por POST.
            print(f"[info] cuerpo de la peticion ({len(cuerpo_curl)} chars):")
            print(f"       {redactar(cuerpo_curl, [])[:400]}")
        print(f"[info] {len(cabeceras_curl)} cabeceras leidas del cURL:")
        for k, v in cabeceras_curl.items():
            marca = "  (sensible, redactada)" if es_sensible(k) else ""
            print(f"       {k}: {len(v)} chars{marca}")

    token = os.environ.get("FLOWMUSIC_TOKEN")
    if not token and args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()

    cookie = os.environ.get("FLOWMUSIC_COOKIE")
    if not cookie and args.cookie_file:
        cookie = Path(args.cookie_file).read_text(encoding="utf-8").strip()

    for h in args.header:
        if ":" in h:
            k, v = h.split(":", 1)
            cabeceras_curl[k.strip()] = v.strip()

    if not token and not cookie and not cabeceras_curl:
        print("[error] necesitas --curl-file (recomendado), o FLOWMUSIC_TOKEN / "
              "--token-file, o --cookie-file")
        sys.exit(1)

    # Validar ANTES de tocar la red: un token truncado revienta dentro de
    # http.client con un traceback que no dice nada util.
    candidatas = dict(cabeceras_curl)
    if token:
        candidatas.setdefault("Authorization", f"Bearer {token}")
    if cookie:
        candidatas.setdefault("Cookie", cookie)

    problemas = validar_cabeceras(candidatas)
    if problemas:
        print("\n[error] credenciales mal copiadas:\n")
        for p in problemas:
            print(f"  - {p}")
        print("\n  Como copiarlas bien:")
        print("    DevTools -> Network -> filtro '__api' -> clic derecho en una")
        print("    request -> Copy -> 'Copy as cURL (bash)'. Pegalo en curl.txt")
        print("    y lanza:  python probe_flowmusic.py --curl-file curl.txt")
        sys.exit(1)

    secretos = [v for k, v in candidatas.items() if es_sensible(k) and len(v) > 8]
    secretos += [x for x in (token, cookie) if x]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    auth = matriz_de_auth(cabeceras_curl, token, cookie, secretos)
    if auth is None:
        sys.exit(1)

    if not args.sin_ablacion:
        auth = minimizar_cabeceras(auth, secretos)

    session = sesion_con(auth)

    print("\n=== 2. QUE FORMA TIENE LA API ===\n")
    todos_hosts, todos_ids, toda_paginacion = set(), {}, {}
    # El endpoint capturado del cURL va primero: es el unico que sabemos
    # con certeza que usa la app de verdad, sin deducirlo.
    rutas_a_pedir = ([(url_curl, metodo_curl, cuerpo_curl)] if url_curl else [])
    rutas_a_pedir += [(s, "GET", None) for s in SEEDS]
    for ruta, metodo, cuerpo in rutas_a_pedir:
        r = pedir(session, ruta, secretos, metodo=metodo, cuerpo=cuerpo)
        _, ids, hosts, pag = analizar(r, ruta, out_dir, secretos)
        todos_hosts |= hosts
        toda_paginacion.update({f"{ruta}:{k}": v for k, v in pag.items()})
        for k, v in ids.items():
            todos_ids.setdefault(f"{ruta}|{k}", v)
        time.sleep(SLEEP)

    # Una cancion concreta es la pieza clave: de su esquema salen los
    # nombres de campo del audio, el CDN y si la URL viene firmada.
    if args.song_url:
        print("\n=== 2b. CANCIONES QUE ME HAS PASADO ===\n")
        for u in args.song_url:
            candidatas_ruta = rutas_api_desde_url(u)
            if not candidatas_ruta:
                print(f"  [aviso] no se pudo derivar ninguna ruta de {u}")
                continue
            for ruta in candidatas_ruta:
                r = pedir(session, ruta, secretos)
                data, ids, hosts, pag = analizar(r, ruta, out_dir, secretos)
                todos_hosts |= hosts
                toda_paginacion.update({f"{ruta}:{k}": v for k, v in pag.items()})
                for k, v in (ids or {}).items():
                    todos_ids.setdefault(f"{ruta}|{k}", v)
                time.sleep(SLEEP)
                if data is not None:
                    break  # la primera forma que responde es la buena

    # Travesia en anchura: de /__api/projects salen ids, y de cada
    # respuesta salen los nombres de sus sub-colecciones (num_X -> X).
    # Encadenando las dos cosas se llega al audio sin adivinar rutas:
    # projects -> projects/{id}/conversations -> conversations/{id}/...
    print("\n=== 3. SIGUIENDO ENLACES ===\n")
    visitadas = set(SEEDS)
    # (ruta_base, id) pendientes de explorar
    cola = [("/__api/projects", ident)
            for origen, ident in todos_ids.items() if "projects" in origen]
    saltos = 0

    while cola and saltos < args.seguir:
        base, ident = cola.pop(0)
        rutas = [f"{base}/{ident}"]

        for ruta in rutas:
            if ruta in visitadas:
                continue
            visitadas.add(ruta)
            r = pedir(session, ruta, secretos)
            data, ids, hosts, pag = analizar(r, ruta, out_dir, secretos)
            todos_hosts |= hosts
            toda_paginacion.update({f"{ruta}:{k}": v for k, v in pag.items()})
            saltos += 1
            time.sleep(SLEEP)
            if data is None:
                continue

            # La respuesta declara sus hijos via num_X: pedirlos.
            for sub in sorted(derivar_subrecursos(data)):
                sub_ruta = f"{ruta}/{sub}"
                if sub_ruta in visitadas:
                    continue
                visitadas.add(sub_ruta)
                r2 = pedir(session, sub_ruta, secretos,
                           etiqueta=f"{sub_ruta}  (derivada de num_{sub})")
                data2, ids2, hosts2, pag2 = analizar(r2, sub_ruta, out_dir, secretos)
                todos_hosts |= hosts2
                toda_paginacion.update({f"{sub_ruta}:{k}": v for k, v in pag2.items()})
                saltos += 1
                time.sleep(SLEEP)
                # Los ids de la sub-coleccion alimentan el siguiente nivel.
                for k, v in (ids2 or {}).items():
                    if k.endswith("id") and v != ident:
                        cola.append((f"/__api/{sub}", v))

    # Los campos *_id nombran su coleccion (conversation_id -> conversations).
    # Solo se siguen los que apuntan a colecciones que YA hemos visto existir,
    # nunca a un nombre inventado: asi no degenera en fuerza bruta.
    colecciones = {"projects", "conversations", "clips"}
    print("\n=== 3b. RECURSOS REFERENCIADOS POR *_id ===\n")
    for origen, ident in list(todos_ids.items()):
        campo = origen.split(".")[-1].split("|")[-1]
        if not campo.endswith("_id"):
            continue
        nombre = campo[:-3]
        plural = nombre if nombre.endswith("s") else nombre + "s"
        if plural not in colecciones:
            continue
        ruta = f"/__api/{plural}/{ident}"
        if ruta in visitadas:
            continue
        visitadas.add(ruta)
        r = pedir(session, ruta, secretos, etiqueta=f"{ruta}  (desde {campo})")
        data, ids, hosts, pag = analizar(r, ruta, out_dir, secretos)
        todos_hosts |= hosts
        toda_paginacion.update({f"{ruta}:{k}": v for k, v in pag.items()})
        time.sleep(SLEEP)

    print("\n=== RESUMEN ===")
    print(f"Cabeceras necesarias : {list(auth.keys())}")
    print(f"Hosts de CDN vistos  : {', '.join(sorted(todos_hosts)) or '(ninguno todavia)'}")
    print(f"Pistas de paginacion : {toda_paginacion or '(ninguna todavia)'}")
    print(f"\nEsquemas y respuestas crudas en: {out_dir.resolve()}")
    print("\nSi el listado de pistas no ha aparecido: DevTools -> Network,")
    print("filtra por '__api', navega por tu biblioteca, y anade las rutas")
    print("que veas a la lista SEEDS de este script.")


if __name__ == "__main__":
    main()
