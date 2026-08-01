# -*- coding: utf-8 -*-
"""Tests de los endpoints de Tintero (pestaña de Substack).

El foco aquí no es una credencial (Tintero no maneja ninguna: Substack sí
tiene export y el zip entra por exports_dir como un fichero quieto más).
El foco son las tres cosas que sí pueden hacer daño en silencio:

  - Que un dato de un suscriptor acabe saliendo por la API.
  - Que la tarjeta del Observatorio se pinte a cero cuando en realidad no
    hay export, que sería mentir sobre una biblioteca que no existe.
  - Que se afirme un número que no se puede saber (los comentarios sin el
    CSV de estadísticas).
"""
import json
import zipfile

import pytest

import launcher


def _make_export(carpeta):
    zpath = carpeta / "export_substack.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("posts.csv",
                    "post_id,post_date,is_published,type,audience,title,subtitle,podcast_url\n"
                    "111.uno,2026-01-15T10:00:00.000Z,true,newsletter,everyone,Uno,,\n"
                    "222.dos,2025-12-06T10:00:00.000Z,false,newsletter,everyone,Dos,,\n"
                    "333.tres,,false,newsletter,everyone,,,\n"
                    "444.pod,2026-02-20T10:00:00.000Z,true,podcast,everyone,Pod,,\n")
        zf.writestr("posts/111.uno.html", '<p>Cuerpo uno.</p><img src="https://s3.test/a.png">')
        zf.writestr("posts/222.dos.html", "<p>Cuerpo dos.</p>")
        zf.writestr("posts/333.tres.html", "<p>Cuerpo tres.</p>")
        zf.writestr("posts/444.pod.html", "<p>Cuerpo pod.</p>")
        zf.writestr("posts/111.delivers.csv",
                    "post_id,timestamp,email\n111,2026-01-15T10:00:00.000Z,suscriptor@ejemplo.test\n")
        zf.writestr("posts/111.opens.csv",
                    "post_id,email,country,city\n111,suscriptor@ejemplo.test,ES,Madrid\n")
        zf.writestr("email_list.pub.csv",
                    "email,active_subscription\nsuscriptor@ejemplo.test,true\n")
    return zpath


def _make_stats(carpeta):
    p = carpeta / "v0raonline_email_stats_2026-07-31.csv"
    p.write_text(
        "title,post_date,section_name,tags,views,likes,comments,restacks,shares,opens,clicks\n"
        "Uno,2026-01-15T10:00:00.000Z,Bitacora,\"a, b\",55,6,3,1,0,43,0\n"
        "Dos,2025-12-06T10:00:00.000Z,Hackeo,c,36,2,0,2,0,0,0\n",
        encoding="utf-8")
    return p


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text(f"""
paths:
  base_vault: '{tmp_path / "vault"}'
  exports_dir: '{exports}'
  gizmo_map: ''
  substack_vault: '{tmp_path / "TINTERO_VAULT"}'
options:
  prj_vault_name: 'PRJ_VAULT'
""", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)
    launcher.app.config["TESTING"] = True
    # El memo de la tarjeta del Observatorio es de proceso: sin limpiarlo,
    # un test se lleva la respuesta del anterior.
    import substack_stats
    substack_stats._memo.clear()
    return {"exports": exports, "cliente": launcher.app.test_client(), "tmp": tmp_path}


def test_verify_sin_export_no_inventa_nada(entorno):
    r = entorno["cliente"].post("/api/substack/verify")
    assert r.status_code == 404
    assert "Substack export" in r.get_json()["error"]


def test_verify_cuenta_estados_y_ausencias(entorno):
    _make_export(entorno["exports"])
    _make_stats(entorno["exports"])
    datos = entorno["cliente"].post("/api/substack/verify").get_json()
    assert datos["export"]["posts"] == 4
    assert datos["export"]["publicados"] == 2
    assert datos["export"]["retirados"] == 1
    assert datos["export"]["borradores"] == 1
    assert datos["stats"]["cruzan"] == 2
    assert datos["stats"]["secciones"] == 2
    assert datos["csv_de_terceros"] == 3
    assert datos["ausencias"]["imagenes"] == 1
    assert datos["ausencias"]["podcasts_sin_audio"] == 1
    assert datos["ausencias"]["comentarios"] == 3


def test_sin_csv_no_se_afirma_cuantos_comentarios_hubo(entorno):
    """Sin el CSV no hay forma de saberlo. La clave NO debe viajar: un 0 ahí
    sería afirmar que no hubo conversación, que es distinto de no saberlo."""
    _make_export(entorno["exports"])
    datos = entorno["cliente"].post("/api/substack/verify").get_json()
    assert datos["stats"] is None
    assert "comentarios" not in datos["ausencias"]
    assert datos["ausencias"]["imagenes"] == 1


def test_ningun_dato_de_suscriptor_sale_por_la_api(entorno):
    """El zip lleva emails, país y ciudad de terceros. La respuesta entera
    se inspecciona en crudo: no basta con que el código 'no los lea'."""
    _make_export(entorno["exports"])
    _make_stats(entorno["exports"])
    crudo = entorno["cliente"].post("/api/substack/verify").get_data(as_text=True)
    assert "suscriptor@ejemplo.test" not in crudo
    assert "Madrid" not in crudo


def test_dashboard_no_pinta_la_tarjeta_si_no_hay_export(entorno):
    """No se pinta a cero: si no hay export, la clave no viaja. Misma regla
    que la tarjeta de música."""
    from config_loader import load_config
    cfg = load_config(str(launcher.CONFIG_PATH))
    assert "substack" not in launcher._con_substack({}, cfg)


def test_dashboard_pinta_las_cuatro_cifras_del_zip(entorno):
    """Las cuatro salen del ZIP, no del CSV: la tarjeta está completa aunque
    no se haya descargado el CSV de estadísticas."""
    _make_export(entorno["exports"])
    from config_loader import load_config
    cfg = load_config(str(launcher.CONFIG_PATH))
    datos = launcher._con_substack({}, cfg)["substack"]
    assert datos["posts"] == 4
    assert datos["publicados"] == 2
    assert datos["borradores"] == 1
    assert datos["palabras"] > 0


def test_build_exige_vault_configurado(entorno, monkeypatch):
    _make_export(entorno["exports"])
    cfg = entorno["tmp"] / "memoria_config.yaml"
    cfg.write_text(f"""
paths:
  base_vault: '{entorno["tmp"] / "vault"}'
  exports_dir: '{entorno["exports"]}'
  substack_vault: ''
options:
  prj_vault_name: 'PRJ_VAULT'
""", encoding="utf-8")
    r = entorno["cliente"].post("/api/substack/build", json={})
    assert r.status_code == 400
    assert "substack_vault" in r.get_json()["error"]


def test_build_construye_de_verdad(entorno):
    """Criterio de hecho: no basta con que el endpoint responda 200, la nota
    tiene que existir en disco y contener lo esperado."""
    _make_export(entorno["exports"])
    _make_stats(entorno["exports"])
    r = entorno["cliente"].post("/api/substack/build", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    nota = entorno["tmp"] / "TINTERO_VAULT" / "Posts" / "2026" / "01" / "2026-01-15_uno.md"
    assert nota.is_file()
    texto = nota.read_text(encoding="utf-8")
    assert 'status: "published"' in texto
    assert 'section: "Bitacora"' in texto
    assert "views: 55" in texto


def test_build_en_seco_no_escribe(entorno):
    _make_export(entorno["exports"])
    r = entorno["cliente"].post("/api/substack/build", json={"dry_run": True})
    assert r.status_code == 200
    assert not (entorno["tmp"] / "TINTERO_VAULT").exists()


def test_el_csv_de_stats_se_localiza_por_cabecera_no_por_nombre(entorno):
    """En exports_dir puede haber otros CSV. Coger el equivocado daría un
    cruce silencioso de 0 filas, que es peor que no encontrarlo."""
    (entorno["exports"] / "otra_cosa.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    assert launcher._stats_csv_en(entorno["exports"]) is None
    esperado = _make_stats(entorno["exports"])
    assert launcher._stats_csv_en(entorno["exports"]) == esperado


def test_una_clave_de_ruta_nueva_no_se_pierde_al_guardar(tmp_path, monkeypatch):
    """Fallo silencioso encontrado al montar la pestaña: patch_config_yaml
    solo reescribia lineas EXISTENTES, asi que guardar substack_vault desde
    la interfaz sobre una config anterior a Tintero no hacia nada y no
    avisaba. Vale para cualquier ruta futura, no solo para esta."""
    cfg = tmp_path / "memoria_config.yaml"
    cfg.write_text("""paths:
  # comentario que debe sobrevivir
  base_vault: 'X'
  exports_dir: 'Y'

options:
  prj_vault_name: 'PRJ_VAULT'
""", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_PATH", cfg)
    launcher.patch_config_yaml({"base_vault": "Z", "substack_vault": "T"})
    texto = cfg.read_text(encoding="utf-8")
    assert "substack_vault: 'T'" in texto
    assert "base_vault: 'Z'" in texto
    assert "# comentario que debe sobrevivir" in texto
    import yaml
    leido = yaml.safe_load(texto)
    assert leido["paths"]["substack_vault"] == "T"
    assert leido["options"]["prj_vault_name"] == "PRJ_VAULT"
