# -*- coding: utf-8 -*-
"""Tintero con VARIAS publicaciones de Substack.

Caso real (V0ra, 2026-10-20): en la carpeta de exports hay tres zips -- V0raOnline,
MasAlladelPrompt y BitacoraClandestina -- y Tintero solo cogia uno. `localizar_export`
devolvia el primer zip de Substack ordenado por fecha de modificacion, asi que el
mas reciente ganaba y los otros dos no existian. El CSV de estadisticas tenia el mismo
defecto: se elegia por orden de nombre, sin saber a que publicacion pertenecia.

La identidad de cada publicacion SI esta dentro de los ficheros: el zip trae
`email_list.<slug>.csv` y el CSV de estadisticas empieza por `<slug>_`. Se empareja
por ahi, sin adivinar.

Lo que no puede pasar -- y lo que vigilan estos tests:
  - que una publicacion se construya con el CSV de OTRA (el cruce daria 0 filas sin avisar);
  - que las notas de una publicacion acaben en la carpeta de otra;
  - que construir encima de un vault con el layout antiguo duplique una publicacion en silencio.
"""
import csv
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "substack"))

import build_substack_vault as bsv  # noqa: E402
import substack_stats  # noqa: E402

CABECERA_POSTS = ("post_id,post_date,is_published,email_sent_at,inbox_sent_at,type,audience,"
                  "title,subtitle,podcast_url\n")
CABECERA_STATS = ("title,post_date,section_name,tags,views,likes,comments,restacks,shares,opens,clicks\n")


def _zip(carpeta: Path, nombre_zip: str, slug, posts, mtime=None) -> Path:
    """`posts`: [(id, 'AAAA-MM-DD'|'', publicado, titulo)]. Si `slug` es None no hay email_list."""
    filas = "".join(
        f"{pid}.{pid.lower()}-slug,{fecha + 'T10:00:00.000Z' if fecha else ''},{'true' if pub else 'false'},"
        f",,newsletter,everyone,{titulo},,\n"
        for pid, fecha, pub, titulo in posts)
    ruta = carpeta / nombre_zip
    with zipfile.ZipFile(ruta, "w") as zf:
        zf.writestr("posts.csv", CABECERA_POSTS + filas)
        for pid, _f, _p, titulo in posts:
            zf.writestr(f"posts/{pid}.{pid.lower()}-slug.html", f"<p>Cuerpo de {titulo}.</p>")
        # PII de terceros: no se debe leer jamas.
        zf.writestr(f"posts/{posts[0][0]}.delivers.csv", "post_id,email\n1,suscriptor@ejemplo.test\n")
        if slug:
            zf.writestr(f"email_list.{slug}.csv", "email,active_subscription\nsuscriptor@ejemplo.test,true\n")
    if mtime is not None:
        os.utime(ruta, (mtime, mtime))
    return ruta


def _csv_stats(carpeta: Path, nombre: str, filas) -> Path:
    """`filas`: [(titulo, 'AAAA-MM-DD', seccion)]."""
    p = carpeta / nombre
    cuerpo = "".join(f'{t},{f}T10:00:00.000Z,{s},"etiqueta uno",10,1,0,0,0,5,0\n' for t, f, s in filas)
    p.write_text(CABECERA_STATS + cuerpo, encoding="utf-8")
    return p


@pytest.fixture
def tres(tmp_path):
    """Los tres exports de V0ra: nombres de zip como los suyos, y CSV de estadisticas para
    dos de ellos (MasAlladelPrompt no tiene)."""
    exp = tmp_path / "exports"
    exp.mkdir()
    _zip(exp, "BitacoraClandestina201026.zip", "bitacoraclandestina",
         [("B1", "2026-03-01", True, "Gravedad inversa"), ("B2", "", False, "")], mtime=1_000)
    _zip(exp, "MasAlladelPrompt.zip", "masalladelprompt",
         [("M1", "2026-04-02", True, "El arte de pensar despacio")], mtime=2_000)
    _zip(exp, "V0raOnline.zip", "v0raonline",
         [("V1", "2025-10-05", True, "Hackeo limbico"), ("V2", "2026-01-15", True, "La fabula")], mtime=3_000)
    _csv_stats(exp, "bitacoraclandestina_email_stats_2026-10-20.csv",
               [("Gravedad inversa", "2026-03-01", "Frontera")])
    _csv_stats(exp, "v0raonline_email_stats_2026-10-20.csv",
               [("Hackeo limbico", "2025-10-05", "Hackeo"), ("La fabula", "2026-01-15", "Fabulas")])
    return exp


def _log(*_a):
    pass


# ---- identidad: la publicacion sale del zip -----------------------------------

def test_el_slug_sale_del_email_list_del_zip(tres):
    assert bsv.slug_de_publicacion(zipfile.ZipFile(tres / "V0raOnline.zip").namelist(),
                                   tres / "V0raOnline.zip") == "v0raonline"


def test_sin_email_list_el_slug_cae_al_nombre_del_zip(tmp_path):
    z = _zip(tmp_path, "Mi Export (2026).zip", None, [("X1", "2026-01-01", True, "Uno")])
    assert bsv.slug_de_publicacion(zipfile.ZipFile(z).namelist(), z) == "miexport2026"


# ---- localizar: TODAS, no la primera ------------------------------------------

def test_encuentra_las_tres_publicaciones_y_no_solo_la_mas_reciente(tres):
    # El comportamiento de siempre, que es el bug: una sola, la mas reciente.
    assert bsv.localizar_export(tres).name == "V0raOnline.zip"
    pubs, repetidos = bsv.exports_por_publicacion(tres)
    assert sorted(pubs) == ["bitacoraclandestina", "masalladelprompt", "v0raonline"]
    assert repetidos == []


def test_dos_zips_de_la_misma_publicacion_gana_el_mas_reciente_y_se_avisa(tres):
    _zip(tres, "V0raOnline_viejo.zip", "v0raonline", [("V9", "2024-01-01", True, "Antiguo")], mtime=500)
    pubs, repetidos = bsv.exports_por_publicacion(tres)
    assert pubs["v0raonline"].name == "V0raOnline.zip"
    assert [p.name for p in repetidos] == ["V0raOnline_viejo.zip"]


def test_un_zip_que_no_es_de_substack_se_ignora(tres):
    with zipfile.ZipFile(tres / "otra_cosa.zip", "w") as zf:
        zf.writestr("conversations.json", "[]")
    pubs, _ = bsv.exports_por_publicacion(tres)
    assert len(pubs) == 3


# ---- el CSV de estadisticas es de UNA publicacion ----------------------------------

def test_cada_publicacion_coge_su_csv(tres):
    assert bsv.localizar_stats(tres, "v0raonline", unica=False).name == "v0raonline_email_stats_2026-10-20.csv"
    assert bsv.localizar_stats(tres, "bitacoraclandestina", unica=False).name == \
        "bitacoraclandestina_email_stats_2026-10-20.csv"


def test_una_publicacion_sin_csv_no_se_lleva_el_de_otra(tres):
    """Con el CSV equivocado el cruce por titulo y dia da 0 filas, en silencio."""
    assert bsv.localizar_stats(tres, "masalladelprompt", unica=False) is None


def test_el_csv_mas_reciente_de_la_publicacion_gana(tres):
    _csv_stats(tres, "v0raonline_email_stats_2026-11-01.csv", [("La fabula", "2026-01-15", "Nueva")])
    assert bsv.localizar_stats(tres, "v0raonline", unica=False).name == "v0raonline_email_stats_2026-11-01.csv"


def test_con_una_sola_publicacion_se_sigue_aceptando_un_csv_sin_el_slug_en_el_nombre(tmp_path):
    """Compatibilidad: quien ya lo usaba con su CSV renombrado no se queda sin estadisticas."""
    _zip(tmp_path, "export.zip", "mipub", [("P1", "2026-01-01", True, "Uno")])
    _csv_stats(tmp_path, "estadisticas.csv", [("Uno", "2026-01-01", "Seccion")])
    assert bsv.localizar_stats(tmp_path, "mipub", unica=True).name == "estadisticas.csv"
    assert bsv.localizar_stats(tmp_path, "mipub", unica=False) is None


def test_un_csv_que_no_es_de_estadisticas_se_ignora_por_la_cabecera(tres):
    (tres / "v0raonline_otra_cosa.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert bsv.localizar_stats(tres, "v0raonline", unica=False).name == "v0raonline_email_stats_2026-10-20.csv"


# ---- nombre de la carpeta de cada publicacion ------------------------------------------

def test_la_carpeta_respeta_las_mayusculas_del_nombre_del_zip(tres):
    pubs, _ = bsv.exports_por_publicacion(tres)
    vault = tres.parent / "vault"
    assert bsv.nombre_de_carpeta(vault, "bitacoraclandestina", pubs["bitacoraclandestina"]) == "BitacoraClandestina"
    assert bsv.nombre_de_carpeta(vault, "masalladelprompt", pubs["masalladelprompt"]) == "MasAlladelPrompt"
    assert bsv.nombre_de_carpeta(vault, "v0raonline", pubs["v0raonline"]) == "V0raOnline"


def test_una_carpeta_que_ya_existe_se_reutiliza_aunque_cambien_las_mayusculas(tmp_path):
    """Estabilidad: renombrar el zip no puede crear una carpeta nueva y duplicar la publicacion."""
    vault = tmp_path / "vault"
    (vault / "MiPublicacion").mkdir(parents=True)
    z = _zip(tmp_path, "OTRO_NOMBRE.zip", "mipublicacion", [("P1", "2026-01-01", True, "Uno")])
    assert bsv.nombre_de_carpeta(vault, "mipublicacion", z) == "MiPublicacion"


def test_si_el_zip_no_se_parece_al_slug_la_carpeta_es_el_slug(tmp_path):
    z = _zip(tmp_path, "descarga_final_v3.zip", "mipublicacion", [("P1", "2026-01-01", True, "Uno")])
    assert bsv.nombre_de_carpeta(tmp_path / "vault", "mipublicacion", z) == "mipublicacion"


# ---- construir las tres -------------------------------------------------------------------

def _tree(raiz: Path):
    return {p.relative_to(raiz).as_posix(): p.read_bytes() for p in raiz.rglob("*") if p.is_file()}


def test_construye_una_carpeta_por_publicacion(tres, tmp_path):
    vault = tmp_path / "vault"
    r = bsv.construir_publicaciones(tres, vault, log=_log)

    assert r["modo"] == "carpetas"
    assert sorted(p["carpeta"] for p in r["publicaciones"]) == ["BitacoraClandestina", "MasAlladelPrompt", "V0raOnline"]
    assert (vault / "V0raOnline" / "Posts" / "2025" / "10").is_dir()
    assert (vault / "MasAlladelPrompt" / "Posts" / "2026" / "04").is_dir()
    assert (vault / "BitacoraClandestina" / "Drafts").is_dir()           # su borrador
    # nada de layout antiguo en la raiz
    assert not (vault / "Posts").exists() and not (vault / "_index.md").exists()
    # cada publicacion con su propio indice
    for carpeta in ("V0raOnline", "MasAlladelPrompt", "BitacoraClandestina"):
        assert (vault / carpeta / "_index.md").is_file()


def test_cada_nota_esta_en_la_carpeta_de_su_publicacion_y_lo_dice(tres, tmp_path):
    vault = tmp_path / "vault"
    bsv.construir_publicaciones(tres, vault, log=_log)
    esperado = {"V0raOnline": ("v0raonline", {"Hackeo limbico", "La fabula"}),
                "MasAlladelPrompt": ("masalladelprompt", {"El arte de pensar despacio"}),
                "BitacoraClandestina": ("bitacoraclandestina", {"Gravedad inversa"})}
    for carpeta, (slug, titulos) in esperado.items():
        notas = list((vault / carpeta / "Posts").rglob("*.md"))
        vistos = set()
        for n in notas:
            texto = n.read_text(encoding="utf-8")
            assert f'publication: "{slug}"' in texto, (carpeta, n.name)
            vistos.update(t for t in titulos if f"Cuerpo de {t}." in texto)
            for ajeno in {t for c, (_s, ts) in esperado.items() if c != carpeta for t in ts}:
                assert f"Cuerpo de {ajeno}." not in texto, f"{ajeno} ha caido en {carpeta}"
        assert vistos == titulos, carpeta


def test_las_estadisticas_solo_enriquecen_a_su_publicacion(tres, tmp_path):
    vault = tmp_path / "vault"
    bsv.construir_publicaciones(tres, vault, log=_log)
    v0ra = (vault / "V0raOnline" / "Posts" / "2025" / "10").glob("*.md")
    assert 'section: "Hackeo"' in next(iter(v0ra)).read_text(encoding="utf-8")
    bit = next((vault / "BitacoraClandestina" / "Posts").rglob("*.md")).read_text(encoding="utf-8")
    assert 'section: "Frontera"' in bit
    # MasAlladelPrompt no tiene CSV: se construye igual, sin seccion ni metricas
    mas = next((vault / "MasAlladelPrompt" / "Posts").rglob("*.md")).read_text(encoding="utf-8")
    assert "section:" not in mas and "views:" not in mas
    assert not (vault / "MasAlladelPrompt" / "_sections.md").exists()


def test_el_indice_de_publicaciones_enlaza_a_ficheros_que_existen(tres, tmp_path):
    """Comprobar que el enlace FUNCIONA, no que su texto case."""
    vault = tmp_path / "vault"
    bsv.construir_publicaciones(tres, vault, log=_log)
    texto = (vault / "_publications.md").read_text(encoding="utf-8")
    import re
    enlaces = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", texto)
    assert len(enlaces) == 3, texto
    for e in enlaces:
        assert (vault / f"{e}.md").is_file(), f"enlace roto: [[{e}]]"
    for nombre in ("V0raOnline", "MasAlladelPrompt", "BitacoraClandestina"):
        assert nombre in texto


def test_reconstruir_no_cambia_nada(tres, tmp_path):
    vault = tmp_path / "vault"
    bsv.construir_publicaciones(tres, vault, log=_log)
    antes = _tree(vault)
    bsv.construir_publicaciones(tres, vault, log=_log)
    assert _tree(vault) == antes


def test_en_seco_no_escribe_nada(tres, tmp_path):
    vault = tmp_path / "vault"
    r = bsv.construir_publicaciones(tres, vault, dry_run=True, log=_log)
    assert not vault.exists()
    assert len(r["publicaciones"]) == 3          # pero cuenta lo que haria


def test_ningun_dato_de_suscriptor_llega_al_vault(tres, tmp_path):
    vault = tmp_path / "vault"
    bsv.construir_publicaciones(tres, vault, log=_log)
    for p in vault.rglob("*"):
        if p.is_file():
            assert "suscriptor@ejemplo.test" not in p.read_text(encoding="utf-8")


# ---- una sola publicacion: compatibilidad ------------------------------------------------------

def test_con_una_sola_publicacion_el_vault_sigue_plano(tmp_path):
    exp = tmp_path / "exports"
    exp.mkdir()
    _zip(exp, "unica.zip", "unica", [("U1", "2026-01-01", True, "Uno")])
    vault = tmp_path / "vault"
    r = bsv.construir_publicaciones(exp, vault, log=_log)
    assert r["modo"] == "plano"
    assert (vault / "Posts" / "2026" / "01").is_dir() and (vault / "_index.md").is_file()
    assert not (vault / "unica").exists() and not (vault / "_publications.md").exists()
    assert 'publication: "unica"' in next((vault / "Posts").rglob("*.md")).read_text(encoding="utf-8")


def test_un_vault_ya_organizado_por_publicaciones_sigue_asi_aunque_solo_quede_un_export(tres, tmp_path):
    """Si se retiran dos zips de la carpeta, construir con el que queda no puede crear
    un Posts/ en la raiz junto a las carpetas de publicacion."""
    vault = tmp_path / "vault"
    bsv.construir_publicaciones(tres, vault, log=_log)
    (tres / "BitacoraClandestina201026.zip").unlink()
    (tres / "MasAlladelPrompt.zip").unlink()
    r = bsv.construir_publicaciones(tres, vault, log=_log)
    assert r["modo"] == "carpetas"
    assert not (vault / "Posts").exists()


# ---- el layout antiguo: no se duplica en silencio ----------------------------------------------

def _vault_con_layout_antiguo(tmp_path) -> Path:
    vault = tmp_path / "vault"
    (vault / "Posts" / "2025" / "10").mkdir(parents=True)
    (vault / "Posts" / "2025" / "10" / "2025-10-05_antigua.md").write_text("nota antigua", encoding="utf-8")
    (vault / "Drafts").mkdir()
    (vault / "_index.md").write_text("indice antiguo", encoding="utf-8")
    return vault


def test_no_construye_encima_de_un_layout_de_un_solo_export(tres, tmp_path):
    vault = _vault_con_layout_antiguo(tmp_path)
    antes = _tree(vault)
    with pytest.raises(bsv.LayoutAntiguoError) as e:
        bsv.construir_publicaciones(tres, vault, log=_log)
    assert _tree(vault) == antes, "ha escrito algo pese a negarse"
    msg = str(e.value)
    assert "Posts" in msg and "--permitir-legado" in msg and "duplic" in msg.lower()


@pytest.mark.parametrize("marca", ["Borradores", "_secciones.md"])
def test_detecta_tambien_el_layout_antiguo_de_la_otra_edicion_y_los_indices(tres, tmp_path, marca):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / marca).mkdir() if marca == "Borradores" else (vault / marca).write_text("x", encoding="utf-8")
    assert bsv.layout_antiguo(vault) == [marca]
    with pytest.raises(bsv.LayoutAntiguoError):
        bsv.construir_publicaciones(tres, vault, log=_log)


def test_permitir_legado_construye_las_carpetas_nuevas_sin_tocar_lo_antiguo(tres, tmp_path):
    vault = _vault_con_layout_antiguo(tmp_path)
    antiguo = _tree(vault)
    bsv.construir_publicaciones(tres, vault, permitir_legado=True, log=_log)
    nuevo = _tree(vault)
    for ruta, cuerpo in antiguo.items():
        assert nuevo[ruta] == cuerpo, f"se ha tocado lo antiguo: {ruta}"
    assert (vault / "V0raOnline" / "_index.md").is_file()


def test_un_vault_vacio_o_inexistente_no_es_layout_antiguo(tmp_path):
    assert bsv.layout_antiguo(tmp_path / "no_existe") == []
    (tmp_path / "vacio").mkdir()
    assert bsv.layout_antiguo(tmp_path / "vacio") == []


# ---- linea de ordenes --------------------------------------------------------------------------

def _cli(*args):
    return subprocess.run([sys.executable, str(RAIZ / "substack" / "build_substack_vault.py"), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def test_cli_exports_dir_construye_todas(tres, tmp_path):
    vault = tmp_path / "vault"
    r = _cli("--exports-dir", tres, "--vault-dir", vault)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (vault / "V0raOnline" / "_index.md").is_file() and (vault / "_publications.md").is_file()


def test_cli_se_niega_con_codigo_1_ante_el_layout_antiguo(tres, tmp_path):
    vault = _vault_con_layout_antiguo(tmp_path)
    r = _cli("--exports-dir", tres, "--vault-dir", vault)
    assert r.returncode == 1 and "--permitir-legado" in (r.stdout + r.stderr)
    assert _cli("--exports-dir", tres, "--vault-dir", vault, "--permitir-legado").returncode == 0


def test_cli_export_suelto_sigue_construyendo_plano(tres, tmp_path):
    """El uso explicito de siempre: un zip, una carpeta."""
    vault = tmp_path / "vault"
    r = _cli("--export", tres / "MasAlladelPrompt.zip", "--vault-dir", vault)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (vault / "Posts" / "2026" / "04").is_dir() and not (vault / "_publications.md").exists()


# ---- las cifras del Observatorio y la verificacion ---------------------------------------------------

@pytest.fixture(autouse=True)
def _memo_limpio():
    substack_stats._memo.clear()
    yield
    substack_stats._memo.clear()


def test_la_tarjeta_suma_las_tres_y_las_lista(tres):
    d = substack_stats.compute_substack_stats(tres)
    assert d["posts"] == 5                                   # 2 + 1 + 2
    assert d["export"] == "3 publications", "la etiqueta de la tarjeta es visible: tiene que estar en ingles"
    assert [p["publicacion"] for p in d["publicaciones"]] == ["BitacoraClandestina", "MasAlladelPrompt", "V0raOnline"]
    por = {p["publicacion"]: p for p in d["publicaciones"]}
    assert por["V0raOnline"]["posts"] == 2 and por["MasAlladelPrompt"]["posts"] == 1
    assert d["publicados"] == sum(p["publicados"] for p in d["publicaciones"])
    assert d["borradores"] == 1                              # el borrador de Bitacora


def test_la_verificacion_lista_cada_publicacion_con_su_csv(tres):
    d = substack_stats.verificar_export(tres)
    assert d["encontrado"] is True and len(d["publicaciones"]) == 3
    por = {p["publicacion"]: p for p in d["publicaciones"]}
    assert por["V0raOnline"]["stats"]["nombre"] == "v0raonline_email_stats_2026-10-20.csv"
    assert por["V0raOnline"]["stats"]["cruzan"] == 2
    assert por["BitacoraClandestina"]["stats"]["cruzan"] == 1
    assert por["MasAlladelPrompt"]["stats"] is None          # sin CSV: no se inventa
    assert "comentarios" not in por["MasAlladelPrompt"]["ausencias"]


def test_la_verificacion_avisa_del_layout_antiguo_antes_de_construir(tres, tmp_path):
    vault = _vault_con_layout_antiguo(tmp_path)
    d = substack_stats.verificar_export(tres, vault=vault)
    assert any("Posts" in a["texto"] for a in d["avisos"]), d["avisos"]
    assert substack_stats.verificar_export(tres, vault=tmp_path / "limpio")["avisos"] == []


def test_la_verificacion_avisa_de_los_zips_repetidos(tres):
    _zip(tres, "V0raOnline_viejo.zip", "v0raonline", [("V9", "2024-01-01", True, "Antiguo")], mtime=500)
    d = substack_stats.verificar_export(tres)
    assert any("V0raOnline_viejo.zip" in a["texto"] for a in d["avisos"]), d["avisos"]


def test_sin_exports_no_hay_nada_que_inventar(tmp_path):
    assert substack_stats.compute_substack_stats(tmp_path) == {}
    assert substack_stats.verificar_export(tmp_path) == {"encontrado": False}


# ---- por los endpoints que usa la interfaz --------------------------------------------------------------

@pytest.fixture
def web(tres, tmp_path, monkeypatch):
    import launcher
    vault = tmp_path / "TINTERO_VAULT"
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(f"paths:\n  base_vault: '{(tmp_path / 'b').as_posix()}'\n  exports_dir: '{tres.as_posix()}'\n"
                   f"  substack_vault: '{vault.as_posix()}'\noptions:\n  by_month: true\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)
    launcher.app.config["TESTING"] = True
    return {"cliente": launcher.app.test_client(), "vault": vault}


def test_el_boton_de_construir_hace_las_tres_publicaciones(web):
    r = web["cliente"].post("/api/substack/build", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    for carpeta in ("V0raOnline", "MasAlladelPrompt", "BitacoraClandestina"):
        assert (web["vault"] / carpeta / "_index.md").is_file(), carpeta
    assert (web["vault"] / "_publications.md").is_file()


def test_el_boton_se_niega_ante_el_layout_antiguo_y_lo_dice_en_pantalla(web):
    (web["vault"] / "Posts" / "2025" / "10").mkdir(parents=True)
    (web["vault"] / "Posts" / "2025" / "10" / "antigua.md").write_text("antigua", encoding="utf-8")
    antes = _tree(web["vault"])

    r = web["cliente"].post("/api/substack/build", json={})

    assert r.status_code == 500
    error = r.get_json()["error"]
    assert "duplic" in error.lower() and "--permitir-legado" in error, error
    assert _tree(web["vault"]) == antes, "ha escrito algo pese a negarse"


def test_el_boton_puede_forzar_y_no_toca_lo_antiguo(web):
    (web["vault"] / "Posts").mkdir(parents=True)
    (web["vault"] / "Posts" / "antigua.md").write_text("antigua", encoding="utf-8")
    r = web["cliente"].post("/api/substack/build", json={"permitir_legado": True})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert (web["vault"] / "Posts" / "antigua.md").read_text(encoding="utf-8") == "antigua"
    assert (web["vault"] / "V0raOnline" / "_index.md").is_file()


def test_verificar_avisa_del_layout_antiguo_con_el_vault_configurado(web):
    (web["vault"] / "Posts").mkdir(parents=True)
    datos = web["cliente"].post("/api/substack/verify").get_json()
    assert len(datos["publicaciones"]) == 3
    assert any(a["tipo"] == "layout_antiguo" for a in datos["avisos"]), datos["avisos"]


# ---- el CSV de estadisticas tiene mas de un esquema (dato real: BitacoraClandestina) ----------------------

CABECERA_REDUCIDA = "title,post_date,audience,views,engagement_rate,signups,subscribes,estimated_value,open_rate\n"


def _csv_reducido(carpeta: Path, nombre: str, filas) -> Path:
    """El esquema que trae la publicacion de V0ra con menos historial: sin section_name,
    sin tags, sin likes ni comments. `filas`: [(titulo, 'AAAA-MM-DD', views)]."""
    p = carpeta / nombre
    cuerpo = "".join(f"{t},{f}T08:24:27.469Z,everyone,{v},1,0,0,0,0.2\n" for t, f, v in filas)
    p.write_text(CABECERA_REDUCIDA + cuerpo, encoding="utf-8")
    return p


def test_un_csv_de_estadisticas_con_el_esquema_reducido_se_reconoce(tmp_path):
    """Con `section_name` obligatorio se descartaba el CSV de Bitacora: 45 de 45 filas
    cruzaban con su zip y la herramienta decia 'sin CSV de estadisticas'."""
    exp = tmp_path / "exports"
    exp.mkdir()
    _zip(exp, "Bitacora.zip", "bitacora", [("B1", "2026-03-01", True, "Gravedad inversa")])
    csv_ = _csv_reducido(exp, "bitacora_email_stats_2026-10-20.csv", [("Gravedad inversa", "2026-03-01", 5)])
    assert bsv.es_csv_de_stats(csv_)
    assert bsv.localizar_stats(exp, "bitacora", unica=False) == csv_


@pytest.mark.parametrize("cabecera", [
    "a,b,c\n",                                   # no es de estadisticas
    "title,post_date\n",                         # tiene lo basico pero ninguna metrica: podria ser cualquier cosa
    "subtitle,post_date,views\n",                # 'subtitle' no es 'title'
])
def test_un_csv_que_no_es_de_estadisticas_se_sigue_rechazando(tmp_path, cabecera):
    p = tmp_path / "x.csv"
    p.write_text(cabecera + "1,2,3\n", encoding="utf-8")
    assert not bsv.es_csv_de_stats(p)


def test_con_el_esquema_reducido_la_nota_lleva_las_vistas_y_nada_inventado(tmp_path):
    exp = tmp_path / "exports"
    exp.mkdir()
    _zip(exp, "Bitacora.zip", "bitacora", [("B1", "2026-03-01", True, "Gravedad inversa")])
    _csv_reducido(exp, "bitacora_email_stats_2026-10-20.csv", [("Gravedad inversa", "2026-03-01", 5)])
    vault = tmp_path / "vault"
    r = bsv.construir_publicaciones(exp, vault, log=_log)
    assert r["publicaciones"][0]["resumen"]["cruzados"] == 1
    texto = next((vault / "Posts").rglob("*.md")).read_text(encoding="utf-8")
    assert "views: 5" in texto and "stats_snapshot: 2026-10-20" in texto
    assert "section:" not in texto and "likes:" not in texto and "comments:" not in texto


def test_sin_columna_de_comentarios_no_se_afirma_cuantos_hubo(tmp_path):
    """Si el CSV no tiene la columna `comments`, un '0 comentarios' seria afirmar algo que
    no se sabe. La clave no viaja."""
    exp = tmp_path / "exports"
    exp.mkdir()
    _zip(exp, "Bitacora.zip", "bitacora", [("B1", "2026-03-01", True, "Gravedad inversa")])
    _csv_reducido(exp, "bitacora_email_stats_2026-10-20.csv", [("Gravedad inversa", "2026-03-01", 5)])
    p = substack_stats.verificar_export(exp)["publicaciones"][0]
    assert p["stats"]["cruzan"] == 1
    assert "comentarios" not in p["ausencias"]


def test_con_la_columna_de_comentarios_si_se_cuentan(tres):
    por = {p["publicacion"]: p for p in substack_stats.verificar_export(tres)["publicaciones"]}
    assert por["V0raOnline"]["ausencias"]["comentarios"] == 0          # la columna existe y todo es 0
    assert "comentarios" in por["V0raOnline"]["ausencias"]
