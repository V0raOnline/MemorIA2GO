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

function checkRow(c) {
  const badge = c.ok ? `<span class="badge ok">OK</span>` : `<span class="badge warn">revisar</span>`;
  const detalle = (c.detalle && c.detalle.contenido_encontrado) || c.contenido_encontrado;
  let resumen = "";
  if (c.campo === "exports_dir" && c.candidatos && c.candidatos.length) {
    resumen = `<div class="sub" style="margin-top:4px;">${c.validos} válido(s) · ${c.ya_procesados} ya importado(s) · ${c.pendientes} pendiente(s)</div>`;
  }
  let candidatosHtml = "";
  if (c.candidatos && c.candidatos.length > 0) {
    candidatosHtml = `<div class="sub" style="margin-top:8px;">Archivos encontrados en la carpeta:<ul style="margin:4px 0 0; padding-left:18px;">` +
      c.candidatos.map(cand => `<li>${cand.valido ? "✓" : "✗"} ${cand.nombre} — ${cand.mensaje}</li>`).join("") +
      `</ul></div>`;
  }
  return `<div class="stat-box" style="margin-bottom:8px;">
    <div class="label">${c.campo} ${badge}</div>
    <div style="font-size:13px; margin-top:4px;">${c.mensaje}</div>
    ${resumen}
    ${detalle ? `<div class="sub">Contenido encontrado: ${detalle.join(", ")}</div>` : ""}
    ${candidatosHtml}
  </div>`;
}

async function runVerificar() {
  const el = document.getElementById("verificar-results");
  el.innerHTML = `<div class="empty-note">Verificando...</div>`;
  try {
    const res = await fetch("/api/verificar");
    const report = await res.json();
    if (report.error) {
      el.innerHTML = `<div class="msg error">${report.error}</div>`;
      return;
    }
    el.innerHTML = report.checks.map(checkRow).join("") +
      `<div class="msg ${report.ok ? "ok" : "error"}" style="margin-top:10px;">${
        report.ok ? "Todo en orden, puedes pasar a Pipeline." : "Hay problemas que conviene resolver antes de ejecutar."
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

  try {
    const res = await fetch("/api/stats" + (refresh ? "?refresh=1" : ""));
    const stats = await res.json();
    if (stats.error) {
      summaryEl.innerHTML = `<div class="empty-note">${stats.error} — configura la carpeta base en la pestaña Configuración.</div>`;
      document.getElementById("evolution-chart").innerHTML = `<div class="empty-note">Sin datos.</div>`;
      document.getElementById("projects-top").innerHTML = `<div class="empty-note">Sin datos.</div>`;
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

    const ib = stats.image_bank;
    imagesEl.innerHTML = [
      statBox("Imágenes", ib.num_imagenes, `${ib.num_con_metadatos} con metadatos`),
      statBox("Tamaño", ib.tamano_legible),
    ].join("");

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

function renderProjects(stats) {
  const el = document.getElementById("projects-top");
  const prjKey = Object.keys(stats.vaults || {}).find(k => k !== "RAW_VAULT" && k !== "MERGED_VAULT");
  const pp = (prjKey && stats.vaults[prjKey].notas_por_proyecto) || {};
  const entries = Object.entries(pp).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) {
    el.innerHTML = `<div class="empty-note">No hay proyectos todavía.</div>`;
    return;
  }
  const top = entries.slice(0, 5);
  const resto = entries.slice(5);
  if (resto.length > 0) {
    top.push([`Otros (${resto.length} proyectos)`, resto.reduce((s, e) => s + e[1], 0)]);
  }
  const maxN = Math.max(...top.map(e => e[1]));
  el.innerHTML = top.map(par => {
    const label = par[0] === "none" ? "Sin proyecto" : par[0];
    return `<div class="prj-row">
      <div class="prj-name" title="${escapeHtml(label)}">${escapeHtml(label)}</div>
      <div class="prj-bar"><div class="prj-fill" style="width:${((100 * par[1]) / maxN).toFixed(1)}%"></div></div>
      <div class="prj-count">${par[1]}</div>
    </div>`;
  }).join("");
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
// Autocompletado de rutas: estilo "Ejecutar" de Windows. Cada input tiene
// un <datalist> asociado; al teclear preguntamos al backend por los
// subdirectorios que casan y los pintamos como sugerencias del navegador.
// Debounce para no martillar el disco con cada tecla.
// ─────────────────────────────────────────

function attachPathAutocomplete(inputId, datalistId, ext) {
  const input = document.getElementById(inputId);
  const list = document.getElementById(datalistId);
  if (!input || !list) return;
  let timeout = null;
  const refrescar = async () => {
    try {
      const params = new URLSearchParams({ path: input.value });
      if (ext) params.set("ext", ext);
      const r = await fetch("/api/browse?" + params.toString());
      const data = await r.json();
      list.innerHTML = (data.opciones || [])
        .map(p => `<option value="${p.replace(/"/g, "&quot;")}"></option>`)
        .join("");
    } catch (_) { /* silencioso: si falla, el usuario simplemente escribe a mano */ }
  };
  input.addEventListener("input", () => {
    if (timeout) clearTimeout(timeout);
    timeout = setTimeout(refrescar, 180);
  });
  input.addEventListener("focus", refrescar);
}

attachPathAutocomplete("cfg-base_vault", "browse-base_vault");
attachPathAutocomplete("cfg-exports_dir", "browse-exports_dir");
attachPathAutocomplete("cfg-gizmo_map", "browse-gizmo_map", "json");

loadConfig();
loadDashboard();
