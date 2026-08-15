# -*- coding: utf-8 -*-
"""Los POST, que son los botones que se pulsan.

USO:  python installer/prueba_botones.py

Se disparan con el cuerpo vacio o a medias, que es lo que pasa cuando
alguien pulsa antes de configurar. Lo que se busca:

  500        -> mina
  cuelgue    -> mina peor (la interfaz se queda muerta sin decir nada)
  400 mudo   -> aceptable si trae mensaje; sospechoso si no

Los dos backups de musica se prueban SIN token a proposito: tienen que
responder 400 al instante y no tocar la red. Se mide el tiempo, que es la
prueba de que no salieron: si tardan, es que llamaron a alguien.
"""
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BANCO = Path(tempfile.mkdtemp(prefix="m3m0ria_post_"))
PUERTO = 8812

tar = subprocess.run(["git", "archive", "HEAD"], cwd=REPO, check=True, stdout=subprocess.PIPE).stdout
(BANCO / "a.tar").write_bytes(tar)
shutil.unpack_archive(str(BANCO / "a.tar"), str(BANCO), format="tar")
(BANCO / "a.tar").unlink()
for f in list(REPO.glob("*.py")) + list(REPO.glob("web/*.js")):
    d = BANCO / f.relative_to(REPO)
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(f, d)

vault = BANCO / "vault"; vault.mkdir()
exports = BANCO / "exports"; exports.mkdir()
(BANCO / "memoria_config.yaml").write_text(
    f"paths:\n  base_vault: '{vault}'\n  exports_dir: '{exports}'\noptions:\n  make_index: true\n",
    encoding="utf-8")

srv = subprocess.Popen([sys.executable, "launcher.py", "--port", str(PUERTO), "--no-browser"],
                       cwd=str(BANCO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace",
                       env={"PYTHONIOENCODING": "utf-8", **__import__("os").environ})
for _ in range(60):
    try:
        with socket.create_connection(("127.0.0.1", PUERTO), timeout=0.4):
            break
    except OSError:
        time.sleep(0.25)

CASOS = [
    # (ruta, cuerpo, segundos de paciencia, nota)
    ("/api/config", {}, 15, "guardar sin nada"),
    ("/api/config", {"paths": {"base_vault": str(vault)}}, 15, "guardar una ruta"),
    ("/api/topics", {}, 15, "temas: cuerpo vacio"),
    ("/api/topics", {"topics": {"prueba": ["palabra"]}}, 15, "temas: uno valido"),
    ("/api/topics/generate", {}, 90, "generar indice de temas"),
    ("/api/gizmos", {}, 15, "gizmos: cuerpo vacio"),
    ("/api/pendientes/descartar", {}, 15, "descartar sin id"),
    ("/api/pendientes/registrar", {}, 15, "registrar sin datos"),
    ("/api/suno/verify", {}, 30, "verificar backup de Suno sin configurar"),
    ("/api/suno/build", {}, 30, "construir vault de Suno sin backup"),
    ("/api/flowmusic/verify", {}, 30, "verificar Flow Music sin configurar"),
    ("/api/flowmusic/build", {}, 30, "construir Flow Music sin backup"),
    ("/api/substack/verify", {}, 30, "verificar Substack sin export"),
    ("/api/substack/build", {}, 30, "construir Tintero sin export"),
    ("/api/suno/backup", {}, 10, "SIN TOKEN: debe cortar sin salir a la red"),
    ("/api/flowmusic/backup", {}, 10, "SIN TOKEN: debe cortar sin salir a la red"),
    ("/api/reindex", {}, 120, "regenerar indices con el vault vacio"),
    # Cuerpos rotos: lo que manda un cliente con un bug, o un curl mal escrito
    ("/api/config", b"", 15, "CUERPO VACIO"),
    ("/api/topics", b"", 15, "CUERPO VACIO"),
    ("/api/topics", b"{no es json", 15, "JSON ROTO"),
    ("/api/gizmos", b"", 15, "CUERPO VACIO"),
    ("/api/suno/backup", b"", 10, "CUERPO VACIO"),
    ("/api/pendientes/descartar", b"[]", 15, "JSON de otro tipo"),
]

print(f"{'ruta':<32}{'codigo':<8}{'seg':<7}que pasa")
print("-" * 100)
minas = []
for ruta, cuerpo, paciencia, nota in CASOS:
    datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PUERTO}{ruta}", data=datos,
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=paciencia) as r:
            codigo, texto = r.status, r.read(3000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        codigo, texto = e.code, e.read(1500).decode("utf-8", "replace")
    except socket.timeout:
        codigo, texto = "CUELGUE", f"sin respuesta en {paciencia}s"
    except Exception as e:
        codigo, texto = 0, f"{type(e).__name__}: {e}"
    seg = time.time() - t0

    mensaje = ""
    try:
        j = json.loads(texto)
        mensaje = j.get("error") or ("ok" if j.get("ok") else json.dumps(j)[:60])
    except Exception:
        mensaje = texto.replace("\n", " ")[:70]

    mal = codigo == "CUELGUE" or codigo == 0 or (isinstance(codigo, int) and codigo >= 500)
    mudo = isinstance(codigo, int) and codigo >= 400 and not mensaje.strip()
    lenta = "backup" in ruta and seg > 3          # habria salido a la red
    if mal or mudo or lenta:
        minas.append((ruta, codigo, nota, mensaje[:120], round(seg, 1)))
    marca = "MINA" if (mal or mudo or lenta) else "  ok"
    print(f"{marca} {ruta:<28}{str(codigo):<8}{seg:<7.1f}{nota} -> {mensaje[:52]}")

srv.terminate()
try:
    srv.wait(timeout=10)
except subprocess.TimeoutExpired:
    srv.kill()

print(f"\n{'=' * 100}\nRESUMEN: {len(minas)} minas")
for m in minas:
    print(f"  {m}")
shutil.rmtree(BANCO, ignore_errors=True)
sys.exit(1 if minas else 0)
