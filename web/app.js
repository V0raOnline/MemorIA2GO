// ─────────────────────────────────────────
// Navegación entre pestañas
// ─────────────────────────────────────────
const tabButtons = document.querySelectorAll(".tab-btn");
const panels = document.querySelectorAll(".panel");

function showTab(name) {
  tabButtons.forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  panels.forEach(p => p.classList.toggle("active", p.id === `panel-${name}`));
  if (name === "dashboard") loadDashboard();
  if (name === "gizmos") loadGizmos();
  if (name === "verificar") loadVerificarBadge();
  if (name === "reconexion") loadReconexion();
}

tabButtons.forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ─────────────────────────────────────────
// Config
// ─────────────────────────────────────────
async function loadConfig() {
  const res = await fetch("/api/config");
  const cfg = await res.json();
  const paths = cfg.paths || {};
  const opts = cfg.options || {};

  document.getElementById("cfg-base_vault").value = paths.base_vault || "";
  document.getElementById("cfg-exports_dir").value = paths.exports_dir || "";
  document.getElementById("cfg-gizmo_map").value = paths.gizmo_map || "";
  document.getElementById("cfg-suno_backup").value = paths.suno_backup || "";
  document.getElementById("cfg-suno_vault").value = paths.suno_vault || "";
  document.getElementById("cfg-flowmusic_backup").value = paths.flowmusic_backup || "";
  document.getElementById("cfg-flowmusic_vault").value = paths.flowmusic_vault || "";
  document.getElementById("cfg-substack_vault").value = paths.substack_vault || "";
  document.getElementById("cfg-prj_vault_name").value = opts.prj_vault_name || "PRJ_VAULT";
  document.getElementById("cfg-by_year").checked = opts.by_year !== false;
  document.getElementById("cfg-by_month").checked = opts.by_month !== false;
  document.getElementById("cfg-make_index").checked = opts.make_index !== false;
  updateConfigBadge(Boolean((paths.base_vault || "").trim() && (paths.exports_dir || "").trim()));
}

async function saveConfig() {
  const payload = {
    paths: {
      base_vault: document.getElementById("cfg-base_vault").value.trim(),
      exports_dir: document.getElementById("cfg-exports_dir").value.trim(),
      gizmo_map: document.getElementById("cfg-gizmo_map").value.trim(),
      suno_backup: document.getElementById("cfg-suno_backup").value.trim(),
      suno_vault: document.getElementById("cfg-suno_vault").value.trim(),
      flowmusic_backup: document.getElementById("cfg-flowmusic_backup").value.trim(),
      flowmusic_vault: document.getElementById("cfg-flowmusic_vault").value.trim(),
      substack_vault: document.getElementById("cfg-substack_vault").value.trim(),
    },
    options: {
      prj_vault_name: document.getElementById("cfg-prj_vault_name").value.trim() || "PRJ_VAULT",
      by_year: document.getElementById("cfg-by_year").checked,
      by_month: document.getElementById("cfg-by_month").checked,
      make_index: document.getElementById("cfg-make_index").checked,
    },
  };
  const msg = document.getElementById("config-msg");
  msg.textContent = "Guardando...";
  msg.className = "msg";
  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    msg.textContent = "Guardado.";
    msg.className = "msg ok";
    updateConfigBadge(Boolean(payload.paths.base_vault && payload.paths.exports_dir));
  } catch (e) {
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  }
}

document.getElementById("btn-save-config").addEventListener("click", saveConfig);

// Estado de un candidato: "ok" (valido, sin aviso) | "warn" (valido pero con
// deriva de formato detectada, deep=True) | "err" (invalido). valido sigue
// siendo la unica senal dura -- "warn" nunca bloquea nada, es solo aviso.
function candidatoEstado(cand) {
  if (!cand.valido) return "err";
  if (cand.aviso) return "warn";
  return "ok";
}

const ESTADO_BADGE_LABEL = { ok: "OK", warn: "revisar", err: "inválido" };

function candidatoRow(cand) {
  const estado = candidatoEstado(cand);
  const subtitulo = [cand.tipo || (cand.valido ? "" : "sin reconocer"), cand.aviso ? "deriva de formato" : ""]
    .filter(Boolean).join(" · ");
  return `<details class="check-fold check-fold-${estado}">
    <summary>
      <span class="check-fold-name">${escapeHtml(cand.nombre)}</span>
      <span class="badge ${estado}">${ESTADO_BADGE_LABEL[estado]}</span>
      ${subtitulo ? `<span class="check-fold-sub">${escapeHtml(subtitulo)}</span>` : ""}
    </summary>
    <div class="check-fold-body">${escapeHtml(cand.mensaje)}</div>
  </details>`;
}

// exports_dir es el unico check con un segundo nivel: caja nivel-1
// colapsada por defecto (semaforo + resumen de una linea en la cabecera),
// que al desplegarse muestra la lista de zips -- cada uno con su propio
// plegable (candidatoRow). base_vault/gizmo_map no tienen ese segundo
// nivel y se quedan en la caja plana de siempre (ver checkRow). Diseno
// confirmado con V0ra 2026-07-21 antes de implementar.
function exportsDirFold(c) {
  const estado = c.estado || "err";
  const resumen = (c.candidatos && c.candidatos.length)
    ? `${c.validos} válido(s) · ${c.ya_procesados} ya importado(s) · ${c.pendientes} pendiente(s)`
    : c.mensaje;
  const body = (c.candidatos && c.candidatos.length)
    ? c.candidatos.map(candidatoRow).join("")
    : `<div class="sub">${escapeHtml(c.mensaje)}</div>`;
  return `<details class="check-fold check-fold-${estado}" style="margin-bottom:8px; padding:12px 14px;">
    <summary>
      <span class="check-fold-campo">${c.campo}</span>
      <span class="badge ${estado}">${ESTADO_BADGE_LABEL[estado]}</span>
      <span class="check-fold-sub" style="margin-left:auto;">${escapeHtml(resumen)}</span>
    </summary>
    <div style="margin-top:10px; padding-top:10px; border-top:1px solid var(--border);">${body}</div>
  </details>`;
}

function checkRow(c) {
  if (c.campo === "exports_dir") return exportsDirFold(c);

  const badge = c.ok ? `<span class="badge ok">OK</span>` : `<span class="badge warn">revisar</span>`;
  const detalle = (c.detalle && c.detalle.contenido_encontrado) || c.contenido_encontrado;
  return `<div class="stat-box" style="margin-bottom:8px;">
    <div class="label">${c.campo} ${badge}</div>
    <div style="font-size:13px; margin-top:4px;">${c.mensaje}</div>
    ${detalle ? `<div class="sub">Contenido encontrado: ${detalle.join(", ")}</div>` : ""}
  </div>`;
}

async function runVerificar() {
  const el = document.getElementById("verificar-results");
  el.innerHTML = `<div class="empty-note">Verificando...</div>`;
  try {
    // deep=1: ademas de la validacion estructural barata, muestrea el
    // contenido de cada export para avisar de claves nuevas (deriva de
    // formato). Solo se pide aqui, en la accion explicita del boton -- el
    // poll automatico del badge (loadVerificarBadge) se queda con el chequeo
    // barato para no parsear JSON grande en cada cambio de pestaña.
    const res = await fetch("/api/verificar?deep=1");
    const report = await res.json();
    if (report.error) {
      el.innerHTML = `<div class="msg error">${report.error}</div>`;
      return;
    }
    el.innerHTML = report.checks.map(checkRow).join("") +
      `<div class="msg ${report.ok ? "ok" : "error"}" style="margin-top:10px;">${
        report.ok ? "Todo en orden, puedes pasar a Construcción." : "Hay problemas que conviene resolver antes de ejecutar."
      }</div>`;
    updateVerificarBadge(report.ok);
  } catch (e) {
    el.innerHTML = `<div class="msg error">Error: ${e.message}</div>`;
  }
}

function updateVerificarBadge(ok) {
  const badge = document.getElementById("verificar-badge");
  badge.innerHTML = ok === null ? "" : (ok ? `<span class="badge ok">OK</span>` : `<span class="badge warn">!</span>`);
}

function updateConfigBadge(ok) {
  const badge = document.getElementById("config-badge");
  badge.innerHTML = ok === null ? "" : (ok ? `<span class="badge ok">OK</span>` : `<span class="badge warn">!</span>`);
}

function updatePipelineBadge(ok) {
  const badge = document.getElementById("pipeline-badge");
  badge.innerHTML = ok === null ? "" : (ok ? `<span class="badge ok">OK</span>` : `<span class="badge warn">!</span>`);
}

async function loadVerificarBadge() {
  try {
    const res = await fetch("/api/verificar");
    const report = await res.json();
    if (!report.error) updateVerificarBadge(report.ok);
  } catch (e) { /* silencioso */ }
}

document.getElementById("btn-verificar").addEventListener("click", runVerificar);

// ─────────────────────────────────────────
// Dashboard
// ─────────────────────────────────────────
function humanBytes(n) {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0, v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

function statBox(label, value, sub) {
  return `<div class="stat-box">
    <div class="label">${label}</div>
    <div class="value">${value}</div>
    ${sub ? `<div class="sub">${sub}</div>` : ""}
  </div>`;
}

async function loadDashboard(refresh = false) {
  const summaryEl = document.getElementById("dashboard-summary");
  const vaultsEl = document.getElementById("dashboard-vaults");
  const imagesEl = document.getElementById("dashboard-images");

  summaryEl.innerHTML = `<div class="empty-note">Cargando...</div>`;
  vaultsEl.innerHTML = "";
  imagesEl.innerHTML = "";
  loadSessionsStat();  // independiente de /api/stats: su propio endpoint barato

  try {
    const res = await fetch("/api/stats" + (refresh ? "?refresh=1" : ""));
    const stats = await res.json();
    if (stats.error) {
      summaryEl.innerHTML = `<div class="empty-note">${stats.error} — configura la carpeta base en la pestaña Configuración.</div>`;
      document.getElementById("evolution-chart").innerHTML = `<div class="empty-note">Sin datos.</div>`;
      document.getElementById("topics-top").innerHTML = `<div class="empty-note">Sin datos.</div>`;
      return;
    }

    const ui = stats.ultima_importacion;
    const gizmosPend = stats.gizmos_pendientes || 0;

    summaryEl.innerHTML = [
      statBox("Última importación", ui ? `hace ${ui.dias_transcurridos} día(s)` : "sin registro",
              ui ? ui.timestamp.slice(0, 16).replace("T", " ") : ""),
      statBox("Gizmos sin nombrar", gizmosPend,
              gizmosPend > 0 ? `<span class="badge warn">revisar</span>` : `<span class="badge ok">al día</span>`),
    ].join("");

    vaultsEl.innerHTML = Object.entries(stats.vaults).map(([name, v]) => {
      if (!v.existe) return statBox(name, "no existe todavía");
      const rango = v.fecha_mas_antigua ? `${v.fecha_mas_antigua} → ${v.fecha_mas_moderna}` : "sin fechas";
      return statBox(name, `${v.notas} notas`, `${rango}<br>${v.tamano_legible}`);
    }).join("");

    renderAssets(stats);
    renderMusicology(stats);
    renderSubstack(stats);

    renderEvolution(stats);
    renderTopTemas(stats);
    renderProviders(stats);
    renderFreshness(stats);

  } catch (e) {
    summaryEl.innerHTML = `<div class="empty-note">Error cargando estadísticas: ${e.message}</div>`;
  }
}

// ─────────────────────────────────────────
// Evolución y top proyectos (dashboard)
// ─────────────────────────────────────────
const MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
let evoMode = "acum";      // "acum" | "mensual"
let evoSerie = [];          // [["AAAA-MM", n], ...] con huecos rellenados a 0
let evoSinFecha = 0;

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

function fmtNum(v) {
  if (v >= 1000) {
    let k = (v / 1000).toFixed(1);
    if (k.endsWith(".0")) k = k.slice(0, -2);
    return k + "k";
  }
  return String(Math.round(v));
}

function niceCeil(v) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / p;
  const m = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
  return m * p;
}

function etiquetaMes(key) {
  const partes = key.split("-");
  return MESES_CORTOS[Number(partes[1]) - 1] + " " + partes[0].slice(2);
}

function prepareEvolution(stats) {
  // Fuente de verdad temporal: MERGED_VAULT (consolidado, sin ramas duplicadas)
  const mv = (stats.vaults && stats.vaults.MERGED_VAULT) || {};
  const porMes = mv.notas_por_mes || {};
  evoSinFecha = porMes["sin fecha"] || 0;
  const meses = Object.keys(porMes).filter(m => m !== "sin fecha").sort();
  evoSerie = [];
  if (meses.length === 0) return;
  let inicio = meses[0].split("-").map(Number);
  const fin = meses[meses.length - 1].split("-").map(Number);
  let y = inicio[0], m = inicio[1];
  while (y < fin[0] || (y === fin[0] && m <= fin[1])) {
    const key = y + "-" + String(m).padStart(2, "0");
    evoSerie.push([key, porMes[key] || 0]);
    m += 1;
    if (m > 12) { m = 1; y += 1; }
  }
}

function drawEvolution() {
  const el = document.getElementById("evolution-chart");
  const note = document.getElementById("evolution-note");
  if (evoSerie.length === 0) {
    el.innerHTML = `<div class="empty-note">No hay notas con fecha en MERGED_VAULT todavía.</div>`;
    note.textContent = "";
    return;
  }

  let vals;
  if (evoMode === "acum") {
    let acc = 0;
    vals = evoSerie.map(par => (acc += par[1]));
  } else {
    vals = evoSerie.map(par => par[1]);
  }

  const W = 640, H = 220, padL = 46, padR = 16, padT = 14, padB = 30;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const maxV = niceCeil(Math.max(...vals, 1));
  const n = vals.length;
  const x = i => padL + (n === 1 ? innerW / 2 : (i * innerW) / (n - 1));
  const y = v => padT + innerH - (v / maxV) * innerH;

  const grid = [0, maxV / 2, maxV].map(v =>
    `<line x1="${padL}" y1="${y(v).toFixed(1)}" x2="${W - padR}" y2="${y(v).toFixed(1)}" class="ch-grid"/>` +
    `<text x="${padL - 8}" y="${(y(v) + 3.5).toFixed(1)}" class="ch-label" text-anchor="end">${fmtNum(v)}</text>`
  ).join("");

  const pts = vals.map((v, i) => x(i).toFixed(1) + "," + y(v).toFixed(1));
  const area = "M " + x(0).toFixed(1) + "," + y(0).toFixed(1) + " L " + pts.join(" L ") +
               " L " + x(n - 1).toFixed(1) + "," + y(0).toFixed(1) + " Z";

  const step = Math.max(1, Math.ceil(n / 6));
  const xLabels = evoSerie.map((par, i) => {
    if (i % step !== 0 && i !== n - 1) return "";
    return `<text x="${x(i).toFixed(1)}" y="${H - 8}" class="ch-label" text-anchor="middle">${etiquetaMes(par[0])}</text>`;
  }).join("");

  const dots = evoSerie.map((par, i) => {
    const detalle = evoMode === "acum" ? `${vals[i]} acumuladas (${par[1]} ese mes)` : `${vals[i]} nota(s)`;
    return `<circle cx="${x(i).toFixed(1)}" cy="${y(vals[i]).toFixed(1)}" r="3" class="ch-dot"><title>${par[0]}: ${detalle}</title></circle>`;
  }).join("");

  el.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">` +
    grid +
    `<path d="${area}" class="ch-area"/>` +
    `<polyline points="${pts.join(" ")}" class="ch-line"/>` +
    dots + xLabels +
    `</svg>`;

  note.textContent = evoSinFecha > 0 ? `${evoSinFecha} nota(s) sin fecha no aparecen en la gráfica.` : "";
}

function renderEvolution(stats) {
  prepareEvolution(stats);
  drawEvolution();
}

function setEvoMode(mode) {
  evoMode = mode;
  document.getElementById("evo-btn-acum").classList.toggle("active", mode === "acum");
  document.getElementById("evo-btn-mensual").classList.toggle("active", mode === "mensual");
  drawEvolution();
}

document.getElementById("evo-btn-acum").addEventListener("click", () => setEvoMode("acum"));
document.getElementById("evo-btn-mensual").addEventListener("click", () => setEvoMode("mensual"));

function renderFreshness(stats) {
  const el = document.getElementById("stats-freshness");
  if (!stats.calculado) { el.innerHTML = ""; return; }
  el.innerHTML = `Estadísticas calculadas: ${stats.calculado.replace("T", " ")} · <a href="#" id="stats-refresh">recalcular</a>`;
  document.getElementById("stats-refresh").addEventListener("click", (e) => {
    e.preventDefault();
    loadDashboard(true);
  });
}

function renderProviders(stats) {
  const el = document.getElementById("dashboard-providers");
  const mv = (stats.vaults && stats.vaults.MERGED_VAULT) || {};
  const pp = mv.notas_por_proveedor || {};
  const NOMBRES = { chatgpt: "ChatGPT", claude: "Claude", grok: "Grok" };
  const entries = Object.entries(pp);
  if (entries.length === 0) {
    el.innerHTML = `<div class="empty-note">Sin datos de proveedor todavía.</div>`;
    return;
  }
  const cajas = [statBox("Proveedores", entries.length)];
  for (const par of entries) {
    cajas.push(statBox(NOMBRES[par[0]] || par[0], par[1], "notas"));
  }
  el.innerHTML = cajas.join("");
}

function renderAssets(stats) {
  const el = document.getElementById("dashboard-images");
  const a = stats.assets;
  if (!a || !a.total_items) {
    el.innerHTML = `<div class="empty-note">Sin assets todavía.</div>`;
    return;
  }
  const NOMBRES = { chatgpt: "ChatGPT", claude: "Claude", grok: "Grok" };
  const cajas = [
    statBox("Assets", a.total_items),
    statBox("Tamaño", a.tamano_legible),
  ];
  for (const [proveedor, v] of Object.entries(a.por_proveedor)) {
    const detalle = v.detalle.filter(d => d.items).map(d => `${d.items} ${d.etiqueta}`).join(" · ");
    cajas.push(statBox(NOMBRES[proveedor] || proveedor, v.items, detalle || "sin contenido"));
  }
  el.innerHTML = cajas.join("");
}

// MUSIC·0LOGY. La tarjeta solo existe si hay backup: sin ruta configurada
// el backend no manda la clave y la caja no se pinta. Deliberadamente NO se
// pinta a cero -- decir "0 pistas" sobre una biblioteca que no has
// descargado es mentir, no informar.
// Trunca los minutos, no los redondea, para dar el MISMO numero que
// _legible() en flowmusic_stats.py y _horas() en suno_stats.py. Con
// redondeo, 30477 s salia como "8 h 28 min" en el acumulado y "8 h 27
// min" en el desglose de la misma tarjeta.
function horasLegibles(segundos) {
  const h = Math.floor(segundos / 3600);
  const m = Math.floor((segundos % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

// Una tarjeta para las dos bibliotecas: acumulado arriba, desglose por
// fuente debajo. Mismo patron que renderProviders().
//
// La tarjeta se pinta si hay AL MENOS una fuente. Las que no tienen backup
// configurado no viajan en el payload y no aparecen -- no se pintan a cero,
// que seria mentir sobre una biblioteca que no se ha descargado.
function renderMusicology(stats) {
  const card = document.getElementById("card-musica");
  const fuentes = [
    { clave: "suno", nombre: "Suno", s: stats.suno },
    { clave: "flowmusic", nombre: "Flow Music", s: stats.flowmusic },
  ].filter((f) => f.s);

  if (fuentes.length === 0) {
    card.style.display = "none";
    renderFoldSub("fold-suno-sub", null);
    renderFoldSub("fold-flowmusic-sub", null);
    return;
  }
  card.style.display = "";

  const total = fuentes.reduce((a, f) => a + (f.s.total || 0), 0);
  const favoritas = fuentes.reduce((a, f) => a + (f.s.favoritas || 0), 0);
  const segundos = fuentes.reduce((a, f) => a + (f.s.duracion_segundos || 0), 0);

  document.getElementById("dashboard-musica").innerHTML = [
    statBox("Pistas", total, horasLegibles(segundos)),
    statBox("Favoritas", favoritas),
    statBox("Bibliotecas", fuentes.length),
  ].join("");

  document.getElementById("dashboard-musica-fuentes").innerHTML = fuentes
    .map((f) => statBox(f.nombre, f.s.total, f.s.duracion_legible))
    .join("");

  // La cabecera plegada de cada fuente: sirve para saber que hay dentro
  // sin abrirla.
  renderFoldSub("fold-suno-sub", stats.suno);
  renderFoldSub("fold-flowmusic-sub", stats.flowmusic);
}

function renderFoldSub(id, s) {
  const el = document.getElementById(id);
  if (!el) return;
  // Sin datos puede significar dos cosas distintas -- que no hay ruta
  // configurada, o que la ruta apunta a una carpeta sin _index.json -- y
  // desde aqui no se distinguen. Se dice lo que se sabe y no la causa.
  el.textContent = s ? `${s.total} pistas · ${s.duracion_legible}` : "sin backup todavía";
}

// Tintero: las cuatro cifras salen del ZIP, nunca del CSV de estadisticas,
// para que la tarjeta este completa aunque el CSV no se haya descargado. Si
// no hay export en la carpeta, la clave no viaja y la tarjeta no se pinta --
// no se pinta a cero, misma regla que la de musica.
function renderSubstack(stats) {
  const card = document.getElementById("card-substack");
  const s = stats.substack;
  if (!s) {
    card.style.display = "none";
    return;
  }
  card.style.display = "";
  const retirados = s.retirados ? `${s.retirados} retirados` : "";
  document.getElementById("dashboard-substack").innerHTML = [
    statBox("Posts", s.posts, s.export),
    statBox("Palabras", s.palabras.toLocaleString("es-ES")),
    statBox("Publicados", s.publicados, retirados),
    statBox("Borradores", s.borradores),
  ].join("");
}

function sbRow(clase, icono, titulo, sub) {
  return `<div class="sb-row ${clase}">
    <svg class="sb-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${icono}</svg>
    <div class="sb-txt">
      <div class="sb-titulo">${titulo}</div>
      <div class="sb-sub">${sub}</div>
    </div>
  </div>`;
}

const SB_ICONO_ZIP = '<path d="M4 4a2 2 0 0 1 2-2h8l6 6v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" /><path d="M14 2v6h6" />';
const SB_ICONO_CHART = '<path d="M3 3v18h18" /><circle cx="9" cy="12" r="1.5" /><circle cx="14" cy="8" r="1.5" /><circle cx="19" cy="14" r="1.5" />';
const SB_ICONO_ESCUDO = '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="M9 12h6" />';

function pintarVerificacion(d) {
  const e = d.export;
  const filas = [
    sbRow("ok", SB_ICONO_ZIP, e.nombre,
      `${e.posts} posts · ${e.publicados} publicados · ${e.retirados} retirados · ${e.borradores} borradores`),
  ];
  if (d.stats) {
    filas.push(sbRow("ok", SB_ICONO_CHART, d.stats.nombre,
      `cruza ${d.stats.cruzan}/${d.stats.filas} · aporta ${d.stats.secciones} secciones y etiquetas en ${d.stats.con_tags}`));
  } else {
    filas.push(sbRow("aviso", SB_ICONO_CHART, "Sin CSV de estadísticas",
      "las notas irán sin sección, etiquetas ni métricas — descárgalo del panel de Substack y déjalo junto al export"));
  }
  filas.push(sbRow("aviso", SB_ICONO_ESCUDO, `${d.csv_de_terceros} CSV con datos de suscriptores`,
    "no son tu memoria: no se leen nunca"));

  // Lo que NO viene. Solo se puede decir aqui: una vez construido el vault,
  // lo que falta no se ve por ninguna parte.
  const a = d.ausencias || {};
  const chips = [];
  if (a.comentarios !== undefined) {
    chips.push(`${a.comentarios} comentarios en ${a.posts_con_comentarios} posts`);
  }
  if (a.podcasts_sin_audio) chips.push(`audio de ${a.podcasts_sin_audio} podcast`);
  if (a.imagenes) chips.push(`${a.imagenes} imágenes, solo su URL`);

  let html = filas.join("");
  if (chips.length) {
    html += `<div class="sb-ausencias-label">Lo que el export no trae</div>
      <div class="sb-chips">${chips.map((c) => `<span class="sb-chip">${c}</span>`).join("")}</div>`;
  }
  return html;
}

async function substackVerify() {
  const btn = document.getElementById("btn-substack-verify");
  const msg = document.getElementById("substack-verify-msg");
  const out = document.getElementById("substack-verify-out");
  btn.disabled = true;
  msg.textContent = "Mirando dentro del export...";
  msg.className = "msg";
  out.style.display = "none";
  try {
    const res = await fetch("/api/substack/verify", { method: "POST" });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    out.innerHTML = pintarVerificacion(data);
    out.style.display = "";
    msg.textContent = "Export reconocido.";
    msg.className = "msg ok";
  } catch (e) {
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  } finally {
    btn.disabled = false;
  }
}

async function substackBuild() {
  const btn = document.getElementById("btn-substack-build");
  const msg = document.getElementById("substack-build-msg");
  const out = document.getElementById("substack-build-out");
  const seco = document.getElementById("substack-dry-run").checked;
  btn.disabled = true;
  msg.textContent = seco ? "Simulando..." : "Construyendo el vault...";
  msg.className = "msg";
  out.style.display = "none";
  try {
    const res = await fetch("/api/substack/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: seco }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    if (data.salida) {
      out.textContent = data.salida;
      out.style.display = "";
    }
    msg.textContent = seco ? "Simulación terminada: no se ha escrito nada."
                           : "Vault construido. Ábrelo en Obsidian.";
    msg.className = "msg ok";
    if (!seco) loadDashboard(true);
  } catch (e) {
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("btn-substack-verify").addEventListener("click", substackVerify);
document.getElementById("btn-substack-build").addEventListener("click", substackBuild);

function renderTopTemas(stats) {
  const el = document.getElementById("topics-top");
  const cov = document.getElementById("topics-coverage");
  const t = stats.temas;
  if (!t || !t.temas) {
    el.innerHTML = `<div class="empty-note">Sin índice de temas todavía — genéralo desde Cartografía.</div>`;
    cov.textContent = "";
    return;
  }
  // Solo temas de contenido: las redes estructurales (campo=valor puras)
  // ya están contadas en la tarjeta de Proveedores y aquí serían ruido.
  const entries = Object.entries(t.temas)
    .filter(([, v]) => !v.estructural && v.enlaces > 0)
    .map(([nombre, v]) => [nombre, v.enlaces])
    .sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    el.innerHTML = `<div class="empty-note">Aún no hay temas de contenido con enlaces.</div>`;
  } else {
    const top = entries.slice(0, 5);
    const resto = entries.slice(5);
    if (resto.length > 0) {
      top.push([`Otros (${resto.length} temas)`, resto.reduce((s, e) => s + e[1], 0)]);
    }
    const maxN = Math.max(...top.map(e => e[1]));
    el.innerHTML = top.map(par => `<div class="prj-row">
      <div class="prj-name" title="${escapeHtml(par[0])}">${escapeHtml(par[0])}</div>
      <div class="prj-bar"><div class="prj-fill" style="width:${((100 * par[1]) / maxN).toFixed(1)}%"></div></div>
      <div class="prj-count">${par[1]}</div>
    </div>`).join("");
  }
  const pct = t.cobertura_contenido_pct;
  const pend = t.huerfanas_solo_estructural;
  const anom = t.huerfanas_sin_tema;
  let linea = "";
  if (typeof pct === "number") linea += `Cobertura de contenido: ${pct}% de ${t.total_huerfanas} huérfanas`;
  if (typeof pend === "number") linea += ` · ${pend} pendientes de cartografiar`;
  if (anom > 0) linea += ` · ⚠ ${anom} sin ningún tema (anomalías)`;
  cov.textContent = linea;
}

// ─────────────────────────────────────────
// Gizmos pendientes
// ─────────────────────────────────────────
async function loadGizmos() {
  const listEl = document.getElementById("gizmos-list");
  listEl.innerHTML = `<div class="empty-note">Cargando...</div>`;

  const res = await fetch("/api/gizmos-pendientes");
  const gizmos = await res.json();
  const entries = Object.entries(gizmos || {});

  const badge = document.getElementById("gizmo-count-badge");
  badge.textContent = entries.length > 0 ? `(${entries.length})` : "";

  if (entries.length === 0) {
    listEl.innerHTML = `<div class="empty-note">No hay gizmos pendientes de nombrar.</div>`;
    return;
  }

  listEl.innerHTML = entries.map(([gid, info]) => {
    const convs = info.conversaciones || [];
    const first = convs[0] ? convs[0].titulo : "(sin ejemplo)";
    const listHtml = convs
      .slice()
      .sort((a, b) => (a.fecha < b.fecha ? 1 : -1))
      .map(c => `<li>${c.fecha} — ${c.titulo}</li>`)
      .join("");
    return `
    <div class="gizmo-row">
      <div class="gizmo-info">
        <div class="ejemplo">${first} <span style="color:var(--text-dim)">— ${info.count} conversación(es)</span></div>
        <div class="meta">${info.gizmo_id || gid}</div>
        <details class="gizmo-convs">
          <summary>Ver las ${convs.length} conversaciones de este grupo</summary>
          <ul>${listHtml}</ul>
        </details>
      </div>
      <input type="text" data-gid="${gid}" placeholder="Nombre del proyecto">
    </div>
  `;
  }).join("");
}

async function saveGizmos() {
  const inputs = document.querySelectorAll("#gizmos-list input[data-gid]");
  const payload = {};
  inputs.forEach(inp => {
    if (inp.value.trim()) payload[inp.dataset.gid] = inp.value.trim();
  });

  const msg = document.getElementById("gizmos-msg");
  if (Object.keys(payload).length === 0) {
    msg.textContent = "No has rellenado ningún nombre.";
    msg.className = "msg error";
    return;
  }

  msg.textContent = "Guardando y parcheando el vault...";
  msg.className = "msg";

  try {
    const res = await fetch("/api/gizmos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    msg.textContent = `Guardado (${data.patched} nota(s) parcheada(s)). Relanzando desde el paso 2...`;
    msg.className = "msg ok";

    // Cambia a la pestaña de ejecución y lanza --from-merge automáticamente,
    // tal como se decidió: gizmo -> parche -> relanzar sin reimportar.
    showTab("run");
    runPipeline("from_merge");
  } catch (e) {
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  }
}

document.getElementById("btn-save-gizmos").addEventListener("click", saveGizmos);

// ─────────────────────────────────────────
// Reconexión: pendientes de descarga por proveedor + regenerar índices
//
// Dos secciones colapsables (.check-fold, el mismo componente que usa
// Verificación) porque los dos proveedores traen cosas distintas:
//   Grok    -> generaciones propias de V0ra en Imagine, sin binario en el zip
//   ChatGPT -> imágenes de búsqueda web de terceros que salieron en la charla
// La lista de ChatGPT puede tener ~1000 filas: se pinta al desplegar, no al
// cargar la pestaña (ver pintarFilas), o la pestaña se arrastra.
// ─────────────────────────────────────────
let pendientesCache = { grok: [], chatgpt: [] };

async function loadReconexion() {
  const listEl = document.getElementById("pendientes-list");
  listEl.innerHTML = `<div class="empty-note">Cargando...</div>`;

  const res = await fetch("/api/pendientes");
  const data = await res.json();
  pendientesCache = {
    grok: Array.isArray(data.grok) ? data.grok : [],
    chatgpt: Array.isArray(data.chatgpt) ? data.chatgpt : [],
  };
  const total = pendientesCache.grok.length + pendientesCache.chatgpt.length;
  actualizarBadgePendientes(total);

  if (total === 0) {
    listEl.innerHTML = `<div class="empty-note">Nada pendiente — todo lo que el export trae ya está extraído.</div>`;
    return;
  }

  listEl.innerHTML =
    seccionPendientes("grok", "Grok", "generaciones propias de Imagine", pendientesCache.grok) +
    seccionPendientes("chatgpt", "ChatGPT", "imágenes de búsqueda web", pendientesCache.chatgpt);

  listEl.querySelectorAll("details[data-proveedor]").forEach(det => {
    det.addEventListener("toggle", () => {
      if (det.open) pintarFilas(det);
    });
  });
}

function actualizarBadgePendientes(n) {
  document.getElementById("pendientes-count-badge").textContent = n > 0 ? `(${n})` : "";
}

function seccionPendientes(proveedor, titulo, descripcion, items) {
  if (!items.length) return "";
  return `<details class="check-fold check-fold-warn" data-proveedor="${proveedor}" style="margin-bottom:8px; padding:12px 14px;">
    <summary>
      <span class="check-fold-campo">${titulo}</span>
      <span class="badge warn">${items.length}</span>
      <span class="check-fold-sub" style="margin-left:auto;">${descripcion}</span>
    </summary>
    <div class="pendientes-cuerpo" style="margin-top:10px; padding-top:10px; border-top:1px solid var(--border);">
      <div class="empty-note">Cargando lista...</div>
    </div>
  </details>`;
}

// Render perezoso: ~1000 filas con su input de fichero son miles de nodos
// DOM. Construirlas al abrir la sección (y solo una vez) evita que la
// pestaña entera se arrastre desde el primer clic.
function pintarFilas(det) {
  const cuerpo = det.querySelector(".pendientes-cuerpo");
  if (!cuerpo || cuerpo.dataset.pintado === "1") return;
  const proveedor = det.dataset.proveedor;
  const items = pendientesCache[proveedor] || [];

  cuerpo.innerHTML = proveedor === "grok"
    ? items.slice().sort((a, b) => (a.create_time || "") < (b.create_time || "") ? 1 : -1)
           .map(filaGrok).join("")
    : items.map(filaChatgpt).join("");
  cuerpo.dataset.pintado = "1";

  cuerpo.querySelectorAll("[data-pendiente-registrar]").forEach(btn => {
    btn.addEventListener("click", () => registrarPendiente(btn, proveedor));
  });
  cuerpo.querySelectorAll("[data-pendiente-descartar]").forEach(btn => {
    btn.addEventListener("click", () => descartarPendiente(btn, proveedor));
  });
}

function acciones(extra) {
  return `<div class="pendiente-actions">
      <input type="file" accept="image/*,video/*" data-pendiente-file>
      <button class="btn secondary" data-pendiente-registrar>Registrar</button>
      ${extra || ""}
    </div>`;
}

function filaGrok(p) {
  const fecha = (p.create_time || "").slice(0, 10) || "fecha desconocida";
  const prompt = (p.prompt || "").trim() || "(sin prompt)";
  const resumen = prompt.length > 90 ? prompt.slice(0, 90) + "..." : prompt;
  return `
    <div class="gizmo-row" data-pendiente-id="${escapeHtml(p.id || "")}">
      <div class="gizmo-info">
        <div class="ejemplo">${fecha} — ${escapeHtml(p.media_type || "?")} — ${escapeHtml(resumen)}</div>
        <div class="meta"><a href="${escapeHtml(p.link || "#")}" target="_blank" rel="noopener">Ver en grok.com</a></div>
        <div class="msg" data-pendiente-msg></div>
      </div>
      ${acciones(`<button class="btn secondary" data-pendiente-descartar>Descartar</button>`)}
    </div>`;
}

function filaChatgpt(p) {
  const query = (p.queries || [])[0] || "(sin búsqueda)";
  const resumen = query.length > 80 ? query.slice(0, 80) + "..." : query;
  const convs = p.conversaciones || [];
  // Cuántas notas la usaron es justo el dato que dice si una imagen
  // sostenía un argumento o es ruido de una búsqueda cualquiera.
  const contexto = convs.length > 1
    ? `${escapeHtml(convs[0])} · vista en ${convs.length} conversaciones`
    : escapeHtml(convs[0] || "");
  return `
    <div class="gizmo-row" data-pendiente-url="${escapeHtml(p.url || "")}">
      <div class="gizmo-info">
        <div class="ejemplo">“${escapeHtml(resumen)}”</div>
        <div class="meta"><a href="${escapeHtml(p.url || "#")}" target="_blank" rel="noopener">${escapeHtml((p.url || "").slice(0, 70))}</a></div>
        ${contexto ? `<div class="meta">${contexto}</div>` : ""}
        <div class="msg" data-pendiente-msg></div>
      </div>
      ${acciones(`<button class="btn secondary" data-pendiente-descartar>Descartar</button>`)}
    </div>`;
}

function quitarFila(row, restantes) {
  const cuerpo = row.closest(".pendientes-cuerpo");
  const det = row.closest("details[data-proveedor]");
  row.remove();
  if (det) {
    const badge = det.querySelector(".badge");
    const quedan = cuerpo ? cuerpo.querySelectorAll(".gizmo-row").length : 0;
    if (badge) badge.textContent = quedan;
    if (quedan === 0) det.remove();
  }
  const listEl = document.getElementById("pendientes-list");
  const vivos = listEl.querySelectorAll(".gizmo-row").length;
  actualizarBadgePendientes(vivos);
  if (vivos === 0) {
    listEl.innerHTML = `<div class="empty-note">Nada pendiente — todo lo que el export trae ya está extraído.</div>`;
  }
}

async function registrarPendiente(btn, proveedor) {
  const row = btn.closest(".gizmo-row");
  const fileInput = row.querySelector("[data-pendiente-file]");
  const msg = row.querySelector("[data-pendiente-msg]");
  const file = fileInput.files[0];
  if (!file) {
    msg.textContent = "Elige primero el fichero descargado.";
    msg.className = "msg error";
    return;
  }
  btn.disabled = true;
  msg.textContent = "Registrando...";
  msg.className = "msg";
  try {
    const fd = new FormData();
    fd.append("proveedor", proveedor || "grok");
    if (proveedor === "chatgpt") fd.append("url", row.dataset.pendienteUrl);
    else fd.append("id", row.dataset.pendienteId);
    fd.append("file", file);
    const res = await fetch("/api/pendientes/registrar", { method: "POST", body: fd });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    quitarFila(row, data.restantes);
  } catch (e) {
    btn.disabled = false;
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  }
}

async function descartarPendiente(btn, proveedor) {
  const row = btn.closest(".gizmo-row");
  const msg = row.querySelector("[data-pendiente-msg]");
  btn.disabled = true;
  msg.textContent = "Descartando...";
  msg.className = "msg";
  try {
    // La clave del pendiente depende del proveedor: `url` en ChatGPT, `id` en
    // Grok (ver get_pendientes/descartar_pendiente en launcher.py).
    const cuerpo = { proveedor: proveedor || "chatgpt" };
    if (proveedor === "grok") cuerpo.id = row.dataset.pendienteId;
    else cuerpo.url = row.dataset.pendienteUrl;
    const res = await fetch("/api/pendientes/descartar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    quitarFila(row, data.restantes);
  } catch (e) {
    btn.disabled = false;
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  }
}

document.getElementById("btn-reindex").addEventListener("click", async () => {
  const btn = document.getElementById("btn-reindex");
  const msg = document.getElementById("reindex-msg");
  btn.disabled = true;
  msg.textContent = "Regenerando índices (puede tardar unos segundos)...";
  msg.className = "msg";
  try {
    const res = await fetch("/api/reindex", { method: "POST" });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    msg.textContent = "Índices regenerados.";
    msg.className = "msg ok";
  } catch (e) {
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  } finally {
    btn.disabled = false;
  }
});

// ─────────────────────────────────────────
// Sesiones locales de Claude Code / Codex
// ─────────────────────────────────────────
document.getElementById("btn-sessions-ingest").addEventListener("click", async () => {
  const btn = document.getElementById("btn-sessions-ingest");
  const msg = document.getElementById("sessions-msg");
  const nivel = document.getElementById("sessions-nivel").value;
  btn.disabled = true;
  msg.textContent = "Ingiriendo sesiones (puede tardar según cuántas haya)...";
  msg.className = "msg";
  try {
    const res = await fetch("/api/sessions/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nivel: parseInt(nivel, 10) }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    let txt = `${data.sesiones} sesiones ingeridas, ${data.notas} notas escritas.`;
    if (data.activa_omitida) {
      txt += ` La sesión abierta se omitió (relánzalo cuando la cierres para capturarla entera).`;
    }
    msg.textContent = txt;
    msg.className = "msg ok";
  } catch (e) {
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  } finally {
    btn.disabled = false;
  }
});

async function loadSessionsStat() {
  const el = document.getElementById("dashboard-sessions");
  if (!el) return;
  try {
    const data = await (await fetch("/api/sessions/status")).json();
    if (data.error) throw new Error(data.error);
    if (!data.total) {
      el.innerHTML = `<div class="empty-note">Ninguna todavía. Ingiérelas desde Reconexión.</div>`;
      return;
    }
    el.innerHTML =
      statBox("Total", data.total) +
      statBox("Claude Code", data.claude_code) +
      statBox("Codex", data.codex);
  } catch (e) {
    el.innerHTML = `<div class="empty-note">${e.message}</div>`;
  }
}

// ─────────────────────────────────────────
// Ejecutar pipeline (SSE)
// ─────────────────────────────────────────
const logBox = document.getElementById("log-box");
const btnRunFull = document.getElementById("btn-run-full");
const btnRunFromMerge = document.getElementById("btn-run-frommerge");
const btnRunReprocess = document.getElementById("btn-run-reprocess");
let currentSource = null;

function appendLog(text, cls) {
  const line = document.createElement("div");
  line.className = "log-line" + (cls ? ` ${cls}` : "");
  line.textContent = text;
  logBox.appendChild(line);
  logBox.scrollTop = logBox.scrollHeight;
}

function setRunning(running) {
  btnRunFull.disabled = running;
  btnRunFromMerge.disabled = running;
  btnRunReprocess.disabled = running;
}

function runPipeline(mode) {
  // mode: "full" | "from_merge" | "reprocess_all"
  if (currentSource) currentSource.close();
  logBox.innerHTML = "";
  setRunning(true);
  updatePipelineBadge(null);

  let url = "/api/run";
  if (mode === "from_merge") url += "?from_merge=1";
  if (mode === "reprocess_all") url += "?reprocess_all=1";
  currentSource = new EventSource(url);

  currentSource.onmessage = (ev) => appendLog(ev.data);

  currentSource.addEventListener("done", (ev) => {
    appendLog(`\nProceso terminado (código ${ev.data}).`, "done");
    setRunning(false);
    currentSource.close();
    updatePipelineBadge(String(ev.data).trim() === "0");
    loadDashboard();
  });

  currentSource.addEventListener("error", (ev) => {
    if (ev.data) appendLog(`Error: ${ev.data}`, "err");
    setRunning(false);
    if (currentSource) currentSource.close();
  });

  currentSource.onerror = () => {
    // Un EventSource no da el codigo HTTP: si el servidor responde 409
    // ("ya hay una ejecucion en curso") esto salta sin datos y, tal como
    // estaba, no se pintaba nada. Pulsabas y no pasaba absolutamente nada.
    if (!logBox.textContent.trim()) {
      appendLog("No se pudo iniciar. Puede que ya haya una ejecucion en curso: "
                + "espera a que termine o reinicia M3M0R\u00b7IA.", "err");
    }
    setRunning(false);
    if (currentSource) currentSource.close();
  };
}

btnRunFull.addEventListener("click", () => runPipeline("full"));
btnRunFromMerge.addEventListener("click", () => runPipeline("from_merge"));
btnRunReprocess.addEventListener("click", () => {
  if (confirm("Esto reprocesa TODOS los exports válidos de la carpeta, no solo los pendientes. Puede tardar mas. ¿Continuar?")) {
    runPipeline("reprocess_all");
  }
});

// ─────────────────────────────────────────
// Nube de huerfanas (Fase 1: exploracion, solo lectura)
// ─────────────────────────────────────────

document.getElementById("btn-load-cloud").addEventListener("click", loadOrphanCloud);

async function loadOrphanCloud() {
  const el = document.getElementById("orphan-cloud");
  const btn = document.getElementById("btn-load-cloud");
  el.innerHTML = `<div class="empty-note">Escaneando huérfanas... (puede tardar unos segundos)</div>`;
  btn.disabled = true;
  try {
    const res = await fetch("/api/orphan-cloud");
    const data = await res.json();
    if (data.error) {
      el.innerHTML = `<div class="msg error">${data.error}</div>`;
      return;
    }
    if (!data.terminos.length) {
      el.innerHTML = `<div class="empty-note">No hay huérfanas con vocabulario que mostrar. ¿Vault vacío?</div>`;
      return;
    }
    const maxN = data.terminos[0].n;
    const minN = data.terminos[data.terminos.length - 1].n;
    const spans = data.terminos.map(x => {
      // escala tipográfica 12-30px, raíz cuadrada para suavizar la cabeza
      const f = maxN === minN ? 0.5 : Math.sqrt((x.n - minN) / (maxN - minN));
      const px = (12 + f * 18).toFixed(1);
      const cls = x.es_proyecto ? "cloud-term prj" : "cloud-term";
      const titulo = x.es_proyecto ? `${x.n} notas · proyecto: ${x.proyecto}` : `${x.n} notas`;
      return `<span class="${cls}" style="font-size:${px}px" title="${titulo}" data-term="${x.t}">${x.t}</span>`;
    });
    el.innerHTML = `<div class="chart-note" style="margin-bottom:8px">${data.total_huerfanas} huérfanas · términos presentes en 3–${data.techo_df} notas</div>` +
                   `<div class="cloud-box">${spans.join(" ")}</div>`;
    el.querySelectorAll(".cloud-term").forEach(s => {
      s.addEventListener("click", () => loadCloudNotes(s.dataset.term));
    });
  } catch (e) {
    el.innerHTML = `<div class="msg error">Error: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Regenerar nube";
  }
}

async function loadCloudNotes(term) {
  const el = document.getElementById("cloud-notes");
  el.innerHTML = `<div class="empty-note">Buscando notas con «${term}»...</div>`;
  try {
    const res = await fetch("/api/orphan-cloud/notes?term=" + encodeURIComponent(term));
    const data = await res.json();
    if (data.error) {
      el.innerHTML = `<div class="msg error">${data.error}</div>`;
      return;
    }
    const filas = data.notas.map(n =>
      `<li><span class="cloud-note-prov">[${n.provider}]</span> ${n.fecha} — ${n.titulo}</li>`
    ).join("");
    el.innerHTML = `<div class="cloud-notes-box"><strong>«${data.termino}»</strong> aparece en ${data.total} nota(s):` +
                   `<ul>${filas}</ul></div>`;
  } catch (e) {
    el.innerHTML = `<div class="msg error">Error: ${e.message}</div>`;
  }
}

// ─────────────────────────────────────────
// Temas (indice de huerfanas): curacion del topic_map + generacion
// ─────────────────────────────────────────

function addTopicRow(name, words) {
  const el = document.getElementById("topics-list");
  const row = document.createElement("div");
  row.className = "topic-row";
  row.innerHTML = `<input type="text" class="topic-name" placeholder="nombre del tema">` +
    `<input type="text" class="topic-words" placeholder="palabras o frases, separadas por comas">` +
    `<button class="topic-del" title="Quitar tema">×</button>`;
  // valores por asignacion, no por interpolacion: inmune a comillas en nombres
  row.querySelector(".topic-name").value = name;
  row.querySelector(".topic-words").value = words;
  row.querySelector(".topic-del").addEventListener("click", () => row.remove());
  el.appendChild(row);
}

async function loadTopics() {
  try {
    const res = await fetch("/api/topics");
    const data = await res.json();
    const el = document.getElementById("topics-list");
    el.innerHTML = "";
    Object.entries(data.temas || {}).forEach(([n, ws]) => addTopicRow(n, ws.join(", ")));
    if (!el.children.length) addTopicRow("", "");
  } catch (e) { /* servidor sin reiniciar: la tarjeta queda vacia */ }
}

document.getElementById("btn-add-topic").addEventListener("click", () => addTopicRow("", ""));

document.getElementById("btn-save-topics").addEventListener("click", async () => {
  const temas = {};
  document.querySelectorAll("#topics-list .topic-row").forEach(r => {
    const n = r.querySelector(".topic-name").value.trim();
    const ws = r.querySelector(".topic-words").value.split(",").map(s => s.trim()).filter(Boolean);
    if (n && ws.length) temas[n] = ws;
  });
  const msg = document.getElementById("topics-msg");
  try {
    const res = await fetch("/api/topics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ temas }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    msg.textContent = `Guardados ${data.temas} tema(s).`;
    msg.className = "msg ok";
  } catch (e) {
    msg.textContent = "Error: " + e.message;
    msg.className = "msg error";
  }
});

document.getElementById("btn-generate-topics").addEventListener("click", async () => {
  const msg = document.getElementById("topics-msg");
  msg.textContent = "Generando índice...";
  msg.className = "msg";
  try {
    const res = await fetch("/api/topics/generate", { method: "POST" });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    let t = `Índice generado: ${data.temas} tema(s), ${data.enlaces} enlace(s)`;
    if (data.borradas) t += `, ${data.borradas} retirado(s)`;
    if (typeof data.huerfanas_sin_tema === "number") {
      t += ` · ${data.huerfanas_sin_tema} huérfana(s) sin tema todavía (lista en _Temas/_sin-tema)`;
    }
    if (data.sin_coincidencias && data.sin_coincidencias.length) {
      t += ` · sin coincidencias: ${data.sin_coincidencias.join(", ")}`;
    }
    msg.textContent = t;
    msg.className = "msg ok";
  } catch (e) {
    msg.textContent = "Error: " + e.message;
    msg.className = "msg error";
  }
});

loadTopics();

// ─────────────────────────────────────────
// Arranque
// ─────────────────────────────────────────
// ─────────────────────────────────────────
// Autocompletado de rutas: estilo "Ejecutar" de Windows, con un dropdown
// propio en vez de <datalist> nativo -- el datalist del navegador trunca
// rutas largas sin forma de verlas completas (ni scroll ni wrap), y las
// rutas reales de Windows (unidad, espacios y varios niveles) son justo
// el caso que rompía. Cada input tiene un <div class="path-suggest">
// hermano que se posiciona debajo via CSS; las opciones envuelven en vez
// de truncarse. Debounce para no martillar el disco con cada tecla.
// ─────────────────────────────────────────

function attachPathAutocomplete(inputId, suggestId, ext) {
  const input = document.getElementById(inputId);
  const box = document.getElementById(suggestId);
  if (!input || !box) return;
  let timeout = null;
  let opciones = [];
  let activeIdx = -1;

  const cerrar = () => {
    box.classList.remove("open");
    box.innerHTML = "";
    opciones = [];
    activeIdx = -1;
  };

  const escapeHtml = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const pintar = () => {
    if (!opciones.length) { cerrar(); return; }
    box.innerHTML = opciones
      .map((p, i) => `<div class="opt${i === activeIdx ? " active" : ""}" data-idx="${i}">${escapeHtml(p)}</div>`)
      .join("");
    box.classList.add("open");
  };

  const elegir = (idx) => {
    if (idx < 0 || idx >= opciones.length) return;
    input.value = opciones[idx];
    input.setSelectionRange(input.value.length, input.value.length);
    refrescar(); // tras elegir una carpeta, ofrece de inmediato su contenido
  };

  const refrescar = async () => {
    try {
      const params = new URLSearchParams({ path: input.value });
      if (ext) params.set("ext", ext);
      const r = await fetch("/api/browse?" + params.toString());
      const data = await r.json();
      opciones = data.opciones || [];
      activeIdx = -1;
      pintar();
    } catch (_) { cerrar(); /* silencioso: si falla, el usuario simplemente escribe a mano */ }
  };

  input.addEventListener("input", () => {
    if (timeout) clearTimeout(timeout);
    timeout = setTimeout(refrescar, 180);
  });
  input.addEventListener("focus", refrescar);

  input.addEventListener("keydown", (e) => {
    if (!box.classList.contains("open")) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, opciones.length - 1);
      pintar();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
      pintar();
    } else if (e.key === "Enter") {
      if (activeIdx >= 0) { e.preventDefault(); elegir(activeIdx); }
    } else if (e.key === "Escape") {
      cerrar();
    }
  });

  // mousedown (no click) para adelantarse al blur del input al pulsar una opcion
  box.addEventListener("mousedown", (e) => {
    const opt = e.target.closest(".opt");
    if (!opt) return;
    e.preventDefault();
    elegir(Number(opt.dataset.idx));
  });

  document.addEventListener("click", (e) => {
    if (e.target !== input && !box.contains(e.target)) cerrar();
  });
}

attachPathAutocomplete("cfg-base_vault", "suggest-base_vault");
attachPathAutocomplete("cfg-exports_dir", "suggest-exports_dir");
attachPathAutocomplete("cfg-gizmo_map", "suggest-gizmo_map", "json");
attachPathAutocomplete("cfg-suno_backup", "suggest-suno_backup");
attachPathAutocomplete("cfg-suno_vault", "suggest-suno_vault");
attachPathAutocomplete("cfg-flowmusic_backup", "suggest-flowmusic_backup");
attachPathAutocomplete("cfg-flowmusic_vault", "suggest-flowmusic_vault");
attachPathAutocomplete("cfg-substack_vault", "suggest-substack_vault");

loadConfig();
loadDashboard();

// ─────────────────────────────────────────
// MUSIC·0LOGY
// ─────────────────────────────────────────

// Los tokens NUNCA se guardan: ni en la config, ni en localStorage, ni en la
// URL. Se leen del campo, viajan en el cuerpo del POST y se olvidan. Caducan
// solos en minutos, asi que persistirlos no ahorraria nada y a cambio dejaria
// una credencial de la cuenta entera escrita en disco.
async function sunoBackup() {
  const btn = document.getElementById("btn-suno-backup");
  const msg = document.getElementById("suno-backup-msg");
  const log = document.getElementById("suno-log");
  const token = document.getElementById("suno-token").value.trim();

  if (!token) {
    msg.textContent = "Pega el Bearer token primero.";
    msg.className = "msg error";
    return;
  }

  btn.disabled = true;
  msg.textContent = "Descargando. El token caduca en minutos: si se corta, saca uno nuevo y vuelve a lanzarlo — retoma solo.";
  msg.className = "msg";
  log.style.display = "";
  log.textContent = "";

  try {
    // POST con respuesta en streaming, no EventSource: EventSource solo hace
    // GET, y el token acabaria en la query string -> historial del navegador
    // y logs de acceso. En el cuerpo no.
    const res = await fetch("/api/suno/backup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let resto = "";
    let codigo = null;

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      resto += decoder.decode(value, { stream: true });
      const lineas = resto.split("\n");
      resto = lineas.pop();
      for (const linea of lineas) {
        if (linea.startsWith("__DONE__")) { codigo = parseInt(linea.slice(8).trim(), 10); continue; }
        if (linea.startsWith("__ERROR__")) { throw new Error(linea.slice(9).trim()); }
        log.textContent += linea + "\n";
        log.scrollTop = log.scrollHeight;
      }
    }

    if (codigo === 0) {
      msg.textContent = "Biblioteca descargada. Verifica el backup antes de construir.";
      msg.className = "msg ok";
      loadDashboard();   // la tarjeta del Observatorio ya refleja lo nuevo
    } else {
      msg.textContent = "La descarga terminó con errores — mira el log. Si el token caducó, saca uno nuevo y relanza: retoma donde se quedó.";
      msg.className = "msg warn";
    }
  } catch (e) {
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  } finally {
    btn.disabled = false;
  }
}

async function sunoAccion(url, btnId, msgId, outId, textos) {
  const btn = document.getElementById(btnId);
  const msg = document.getElementById(msgId);
  const out = document.getElementById(outId);
  btn.disabled = true;
  msg.textContent = textos.trabajando;
  msg.className = "msg";
  out.style.display = "none";
  try {
    const res = await fetch(url, { method: "POST" });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    if (data.salida) {
      out.textContent = data.salida;
      out.style.display = "";
    }
    msg.textContent = data.ok === false ? textos.problemas : textos.ok;
    msg.className = data.ok === false ? "msg warn" : "msg ok";
  } catch (e) {
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  } finally {
    btn.disabled = false;
  }
}

// Flow Music: mismo pipeline que Suno contra otra API. La descarga se
// calca de sunoBackup -- POST con streaming, nunca EventSource, porque el
// token no puede acabar en una query string.
async function flowmusicBackup() {
  const btn = document.getElementById("btn-flowmusic-backup");
  const msg = document.getElementById("flowmusic-backup-msg");
  const log = document.getElementById("flowmusic-log");
  const token = document.getElementById("flowmusic-token").value.trim();
  const formatos = document.getElementById("flowmusic-formats").value;

  if (!token) {
    msg.textContent = "Pega el Bearer token primero.";
    msg.className = "msg error";
    return;
  }
  // El «…» delata un token copiado del panel Headers, que Chrome trunca.
  // Se avisa aqui para no gastar una peticion en un token que no vale.
  if (token.includes("…")) {
    msg.textContent = "El token viene cortado: contiene «…». Cópialo con «Copy as cURL», no del panel Headers.";
    msg.className = "msg error";
    return;
  }

  btn.disabled = true;
  msg.textContent = "Descargando. El token dura menos de una hora: si se corta, saca uno nuevo y vuelve a lanzarlo — retoma solo.";
  msg.className = "msg";
  log.style.display = "";
  log.textContent = "";

  try {
    const res = await fetch("/api/flowmusic/backup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, formatos }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let resto = "";
    let codigo = null;

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      resto += decoder.decode(value, { stream: true });
      const lineas = resto.split("\n");
      resto = lineas.pop();
      for (const linea of lineas) {
        if (linea.startsWith("__DONE__")) { codigo = parseInt(linea.slice(8).trim(), 10); continue; }
        if (linea.startsWith("__ERROR__")) { throw new Error(linea.slice(9).trim()); }
        log.textContent += linea + "\n";
        log.scrollTop = log.scrollHeight;
      }
    }

    if (codigo === 0) {
      msg.textContent = "Biblioteca descargada. Verifica el backup antes de construir.";
      msg.className = "msg ok";
      loadDashboard();
    } else {
      msg.textContent = "La descarga terminó con errores — mira el log. Si el token caducó, saca uno nuevo y relanza: retoma donde se quedó.";
      msg.className = "msg warn";
    }
  } catch (e) {
    msg.textContent = `Error: ${e.message}`;
    msg.className = "msg error";
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("btn-suno-backup").addEventListener("click", sunoBackup);
document.getElementById("btn-flowmusic-backup").addEventListener("click", flowmusicBackup);

document.getElementById("btn-flowmusic-verify").addEventListener("click", () =>
  sunoAccion("/api/flowmusic/verify", "btn-flowmusic-verify", "flowmusic-verify-msg", "flowmusic-verify-out", {
    trabajando: "Cruzando el índice contra los ficheros...",
    ok: "Backup íntegro.",
    problemas: "Hay huecos o ficheros dañados — mira el detalle.",
  }));

document.getElementById("btn-flowmusic-build").addEventListener("click", () =>
  sunoAccion("/api/flowmusic/build", "btn-flowmusic-build", "flowmusic-build-msg", "flowmusic-build-out", {
    trabajando: "Construyendo el vault...",
    ok: "Vault construido.",
    problemas: "Terminó con avisos — mira el detalle.",
  }));

document.getElementById("btn-suno-verify").addEventListener("click", () =>
  sunoAccion("/api/suno/verify", "btn-suno-verify", "suno-verify-msg", "suno-verify-out", {
    trabajando: "Cruzando el índice contra los ficheros...",
    ok: "Backup íntegro.",
    problemas: "Hay huecos o ficheros dañados — mira el detalle.",
  }));

document.getElementById("btn-suno-build").addEventListener("click", () =>
  sunoAccion("/api/suno/build", "btn-suno-build", "suno-build-msg", "suno-build-out", {
    trabajando: "Construyendo el vault (puede tardar)...",
    ok: "Vault construido. Ábrelo en Obsidian.",
    problemas: "Terminó con avisos — mira el detalle.",
  }));
