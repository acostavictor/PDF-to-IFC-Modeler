// PDF to IFC Modeler: browser side. The PDF is rendered here with PDF.js; only page images are uploaded.
import * as pdfjsLib from "./vendor/pdfjs/pdf.min.mjs";

const VENDOR = new URL("./vendor/pdfjs/", import.meta.url).href;
pdfjsLib.GlobalWorkerOptions.workerSrc = VENDOR + "pdf.worker.min.mjs";

const $ = (id) => document.getElementById(id);
const SOURCES = ["dimensioned", "derived", "scaled", "assumed", "example default"];
const SOURCE_TEXT = {
  "dimensioned": "Written on the drawing",
  "derived": "Calculated from the drawing",
  "scaled": "Measured from the scan",
  "assumed": "Assumed",
  "example default": "Example value",
};
const TILE_PX = 2000;        // long edge of a close-up, within the API limit for many-image requests
const OVERVIEW_PX = 1568;
const OVERLAP = 0.08;

const state = { api: "api/", health: null, templates: [], template: null, pdf: null, page: 1, zoom: 1, rendering: null, py: null };

// Browser preview: when no server answers (for example on GitHub Pages), the Python model builder runs in the page.
const PYODIDE = "https://cdn.jsdelivr.net/npm/pyodide@314.0.7/";
const PREVIEW_FILES = ["app/__init__.py", "app/browser.py", "app/build.py", "app/ifc/__init__.py", "app/ifc/kit.py",
  "app/ifc/writer.py", "app/templates/__init__.py", "app/templates/base.py", "app/templates/caisson_gate.py",
  "app/templates/dry_dock.py", "app/templates/strut_gate.py", "app/templates/strut_gate_staad.py"];

// ---------------------------------------------------------------- server calls
async function call(path, options) {
  const res = await fetch(state.api + path, Object.assign({ credentials: "same-origin" }, options || {}));
  return res;
}
async function postJson(path, body) {
  return call(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
async function errorText(res) {
  try { const j = await res.json(); return j.error || ("Request failed (" + res.status + ")"); }
  catch (e) { return "Request failed (" + res.status + "). The server did not return a readable message."; }
}
async function findApi() {
  for (const base of ["api/", "index.cgi/api/"]) {
    try {
      const res = await fetch(base + "health", { credentials: "same-origin" });
      if (res.ok && (res.headers.get("content-type") || "").includes("json")) { state.api = base; return await res.json(); }
    } catch (e) { /* try the next address */ }
  }
  return null;
}
function banner(text, isError) {
  const b = $("banner");
  b.hidden = !text; b.textContent = text || ""; b.className = "banner" + (isError ? " error" : "");
}

// ---------------------------------------------------------------- start-up and sign-in
function modeNote(text) { const m = $("mode"); m.hidden = !text; m.textContent = text || ""; }
async function startPreview() {
  modeNote("No server is answering, so preview mode is starting: loading the model builder into your browser (about 13 MB the first time).");
  const root = new URL("../", import.meta.url).href;
  const sources = await Promise.all(PREVIEW_FILES.map(async (f) => {
    const r = await fetch(root + f);
    if (!r.ok) throw new Error("could not load " + f);
    return [f, await r.text()];
  }));
  const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");
  const py = await loadPyodide({ indexURL: PYODIDE });
  for (const [f, text] of sources) {
    const path = "/p2i/" + f;
    py.FS.mkdirTree(path.slice(0, path.lastIndexOf("/")));
    py.FS.writeFile(path, text);
  }
  py.runPython("import sys\nsys.path.insert(0, '/p2i')\nimport app.browser as p2i_browser");
  state.py = py.globals.get("p2i_browser");
}
async function start() {
  state.health = await findApi();
  if (!state.health) {
    try { await startPreview(); }
    catch (e) {
      modeNote("");
      banner("The server part of the app is not answering, and preview mode could not start (" + e.message +
        "). On your own host, check that index.cgi can run (see docs/DEPLOY_HOSTGATOR.md).", true);
      return;
    }
    state.templates = JSON.parse(state.py.templates_json()).templates;
    state.health = { ai_ready: false, ai_reason: "Reading with AI is not available in preview mode.", max_images: 60, max_body_mb: 60, login_required: false };
    modeNote("Preview mode: no server is answering, so models are built here in your browser. You can open a PDF, type in values " +
      "and download files. Reading drawings with AI needs the server version.");
  } else {
    const h = state.health;
    if (h.login_required && !h.logged_in) { $("login").hidden = false; $("app").hidden = true; return; }
    const res = await call("templates");
    if (!res.ok) { banner(await errorText(res), true); return; }
    state.templates = (await res.json()).templates;
  }
  const h = state.health;
  $("login").hidden = true; $("logout").hidden = !h.login_required;
  $("app").hidden = false;
  $("ai-state").textContent = h.ai_ready ? "Model: " + h.model : h.ai_reason;
  $("read").disabled = !h.ai_ready;
  renderTemplates();
  chooseTemplate(state.templates[0].id);
}
$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const res = await postJson("login", { password: $("password").value });
  if (!res.ok) { banner(await errorText(res), true); return; }
  banner(""); $("password").value = ""; start();
});
$("logout").addEventListener("click", async () => { await postJson("logout", {}); location.reload(); });

// ---------------------------------------------------------------- step 1: structure type
function renderTemplates() {
  const box = $("templates"); box.textContent = "";
  for (const t of state.templates) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "choice"; b.dataset.id = t.id; b.setAttribute("aria-pressed", "false");
    const title = document.createElement("strong"); title.textContent = t.title;
    const sum = document.createElement("span"); sum.textContent = t.summary;
    const look = document.createElement("small"); look.textContent = "Useful sheets: " + t.look_for + ". Units: " + t.unit + ".";
    b.append(title, sum, look);
    b.addEventListener("click", () => chooseTemplate(t.id));
    box.append(b);
  }
}
function chooseTemplate(id) {
  state.template = state.templates.find((t) => t.id === id);
  for (const b of document.querySelectorAll(".choice")) b.setAttribute("aria-pressed", String(b.dataset.id === id));
  renderForm();
  const extra = $("extra-exports"); extra.textContent = "";
  for (const fmt of state.template.exports.filter((f) => f !== "ifc")) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "ghost";
    b.textContent = fmt === "std" ? "Download STAAD.Pro file" : "Download ." + fmt;
    b.addEventListener("click", () => build(fmt));
    extra.append(b);
  }
  $("ai-notes").hidden = true;
}

// ---------------------------------------------------------------- step 3: the review form
function toText(spec, value) {
  if (value === null || value === undefined) return "";
  if (spec.type === "list") return value.join(", ");
  if (spec.type === "table") return value.map((r) => r.join(", ")).join("\n");
  return String(value);
}
function renderForm() {
  const host = $("params"); host.textContent = "";
  const groups = new Map();
  for (const spec of state.template.params) {
    if (!groups.has(spec.group)) {
      const fs = document.createElement("fieldset");
      const lg = document.createElement("legend"); lg.textContent = spec.group; fs.append(lg);
      groups.set(spec.group, fs); host.append(fs);
    }
    const row = document.createElement("div");
    row.className = "row"; row.dataset.key = spec.key; row.dataset.source = "example default";
    const id = "p-" + spec.key;
    const label = document.createElement("label"); label.htmlFor = id; label.textContent = spec.label + " ";
    if (spec.unit) { const u = document.createElement("span"); u.className = "unit"; u.textContent = "(" + spec.unit + ")"; label.append(u); }
    let input;
    if (spec.type === "table") { input = document.createElement("textarea"); input.rows = Math.min(8, Math.max(3, spec.default.length)); }
    else { input = document.createElement("input"); input.type = "text"; if (spec.type === "number") input.inputMode = "decimal"; }
    input.id = id; input.value = toText(spec, spec.default);
    const sel = document.createElement("select"); sel.setAttribute("aria-label", "Where this value came from");
    for (const s of SOURCES) { const o = document.createElement("option"); o.value = s; o.textContent = SOURCE_TEXT[s]; sel.append(o); }
    sel.value = "example default";
    const hint = document.createElement("div"); hint.className = "hint";
    hint.textContent = spec.hint + (spec.type === "table" ? " One row per line: " + spec.columns.map((c) => c.name).join(", ") + "." : "") +
      (spec.type === "list" ? " Separate values with commas." : "");
    const note = document.createElement("div"); note.className = "note";
    input.addEventListener("input", () => { if (sel.value === "example default") { sel.value = "assumed"; row.dataset.source = "assumed"; tally(); } });
    sel.addEventListener("change", () => { row.dataset.source = sel.value; tally(); });
    row.append(label, input, sel, hint, note);
    groups.get(spec.group).append(row);
  }
  tally();
}
function setValue(key, item) {
  const row = document.querySelector('.row[data-key="' + key + '"]'); if (!row) return;
  const spec = state.template.params.find((p) => p.key === key);
  row.querySelector("input, textarea").value = toText(spec, item.value);
  const src = SOURCES.includes(item.source) ? item.source : "assumed";
  row.querySelector("select").value = src; row.dataset.source = src;
  row.querySelector(".note").textContent = item.note ? "Reader's note: " + item.note : "";
}
function collect() {
  const out = {};
  for (const row of document.querySelectorAll(".row")) {
    out[row.dataset.key] = { value: row.querySelector("input, textarea").value, source: row.querySelector("select").value,
      note: row.querySelector(".note").textContent.replace(/^Reader's note: /, "") };
  }
  return out;
}
function meta() {
  return { project_name: $("m-project").value, facility: $("m-facility").value, source: $("m-source").value, author: $("m-author").value };
}
function tally() {
  const rows = [...document.querySelectorAll(".row")];
  const ex = rows.filter((r) => r.dataset.source === "example default").length;
  const soft = rows.filter((r) => ["scaled", "assumed"].includes(r.dataset.source)).length;
  $("tally").textContent = ex + " of " + rows.length + " values are still example values from the worked example, not from your drawings. " +
    soft + " are marked measured or assumed.";
}

// ---------------------------------------------------------------- step 2: PDF, tiles, AI reading
function gridFor(detail, viewport) {
  let [a, b] = detail.split("x").map(Number);
  return viewport.width >= viewport.height ? { cols: a, rows: b } : { cols: b, rows: a };
}
function selectedPages() { return [...document.querySelectorAll("#pages input:checked")].map((c) => Number(c.value)); }
function updateCount() {
  const [a, b] = $("detail").value.split("x").map(Number);
  const per = a * b > 1 ? 1 + a * b : 1;
  const n = selectedPages().length * per;
  const max = state.health ? state.health.max_images : 60;
  $("image-count").textContent = n + " images to send (limit " + max + ")" + (n > max ? ". Too many: choose fewer pages or less detail." : "");
  $("read").disabled = !(state.health && state.health.ai_ready) || n === 0 || n > max;
}
$("detail").addEventListener("change", updateCount);
$("pdf").addEventListener("change", async (ev) => {
  const file = ev.target.files[0]; if (!file) return;
  try {
    const data = new Uint8Array(await file.arrayBuffer());
    state.pdf = await pdfjsLib.getDocument({ data, wasmUrl: VENDOR + "wasm/", standardFontDataUrl: VENDOR + "standard_fonts/" }).promise;
  } catch (e) { banner("That file could not be opened as a PDF: " + e.message, true); return; }
  banner("");
  $("pdf-info").textContent = file.name + ", " + state.pdf.numPages + " page(s)";
  if (!$("m-source").value) $("m-source").value = file.name;
  const pages = $("pages"); pages.textContent = "";
  for (let n = 1; n <= state.pdf.numPages; n++) {
    const l = document.createElement("label"); const c = document.createElement("input");
    c.type = "checkbox"; c.value = String(n); c.checked = n <= 12; c.addEventListener("change", updateCount);
    l.append(c, " " + n); pages.append(l);
  }
  $("read-options").hidden = false; updateCount();
  state.page = 1; state.zoom = 1; showPage();
});
async function renderCanvas(page, scale) {
  const vp = page.getViewport({ scale });
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(vp.width); canvas.height = Math.ceil(vp.height);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  await page.render({ canvasContext: ctx, viewport: vp, canvas }).promise;
  return canvas;
}
function jpeg(canvas, quality) { return canvas.toDataURL("image/jpeg", quality).split(",")[1]; }
async function pageImages(n, detail) {
  const page = await state.pdf.getPage(n);
  const base = page.getViewport({ scale: 1 });
  const out = [];
  const overview = await renderCanvas(page, OVERVIEW_PX / Math.max(base.width, base.height));
  out.push({ label: "Page " + n + ": whole sheet overview", media_type: "image/jpeg", data: jpeg(overview, 0.8) });
  const g = gridFor(detail, base);
  if (g.cols * g.rows === 1) return out;
  const fw = 1 / (g.cols - (g.cols - 1) * OVERLAP), fh = 1 / (g.rows - (g.rows - 1) * OVERLAP);
  let scale = TILE_PX / Math.max(base.width * fw, base.height * fh);
  scale = Math.min(scale, Math.sqrt(60e6 / (base.width * base.height)));   // keep the full render under ~60 megapixels
  const full = await renderCanvas(page, scale);
  const tw = Math.floor(full.width * fw), th = Math.floor(full.height * fh);
  for (let r = 0; r < g.rows; r++) {
    for (let c = 0; c < g.cols; c++) {
      const x = Math.min(Math.round(c * tw * (1 - OVERLAP)), full.width - tw), y = Math.min(Math.round(r * th * (1 - OVERLAP)), full.height - th);
      const t = document.createElement("canvas"); t.width = tw; t.height = th;
      t.getContext("2d").drawImage(full, x, y, tw, th, 0, 0, tw, th);
      out.push({ label: "Page " + n + ": close-up, row " + (r + 1) + " of " + g.rows + ", column " + (c + 1) + " of " + g.cols +
        " (close-ups overlap slightly)", media_type: "image/jpeg", data: jpeg(t, 0.72) });
    }
  }
  full.width = full.height = 0;
  return out;
}
$("read").addEventListener("click", async () => {
  const pages = selectedPages(); const prog = $("progress"); const btn = $("read");
  btn.disabled = true; banner("");
  try {
    let images = [];
    for (let i = 0; i < pages.length; i++) {
      prog.textContent = "Preparing page " + pages[i] + " (" + (i + 1) + " of " + pages.length + ")";
      images = images.concat(await pageImages(pages[i], $("detail").value));
    }
    const mb = images.reduce((s, im) => s + im.data.length, 0) / 1048576;
    if (mb > state.health.max_body_mb * 0.95) throw new Error("These images total " + mb.toFixed(0) + " MB, over the server limit of " +
      state.health.max_body_mb + " MB. Choose fewer pages or less detail.");
    prog.textContent = "Sending " + images.length + " images (" + mb.toFixed(1) + " MB) and reading. This can take a few minutes.";
    const res = await postJson("extract", { template: state.template.id, images, notes: $("notes").value });
    if (!res.ok) throw new Error(await errorText(res));
    const out = await res.json();
    for (const key of Object.keys(out.params)) setValue(key, out.params[key]);
    tally();
    const u = out.usage || {};
    prog.textContent = "Read " + out.found + " of " + out.total + " values" + (u.input_tokens ? " (" + u.input_tokens + " input and " +
      (u.output_tokens || 0) + " output tokens)" : "") + ". Check each one against the drawing before building.";
    const notes = $("ai-notes"); notes.hidden = !out.general_notes; notes.textContent = out.general_notes ? "Reader's notes: " + out.general_notes : "";
  } catch (e) { prog.textContent = ""; banner(e.message, true); }
  updateCount();
});

// ---------------------------------------------------------------- drawing viewer
async function showPage() {
  if (!state.pdf) return;
  const page = await state.pdf.getPage(state.page);
  const wrap = $("canvas-wrap");
  const fit = (wrap.clientWidth - 4) / page.getViewport({ scale: 1 }).width;
  const vp = page.getViewport({ scale: fit * state.zoom });
  const canvas = $("canvas");
  if (state.rendering) { try { state.rendering.cancel(); } catch (e) { /* already finished */ } }
  canvas.width = Math.ceil(vp.width); canvas.height = Math.ceil(vp.height);
  state.rendering = page.render({ canvasContext: canvas.getContext("2d"), viewport: vp, canvas });
  try { await state.rendering.promise; } catch (e) { /* cancelled by a newer render */ }
  $("page-label").textContent = "Page " + state.page + " of " + state.pdf.numPages + ", zoom " + Math.round(state.zoom * 100) + "%";
}
$("prev").addEventListener("click", () => { if (state.pdf && state.page > 1) { state.page--; showPage(); } });
$("next").addEventListener("click", () => { if (state.pdf && state.page < state.pdf.numPages) { state.page++; showPage(); } });
$("zoom-in").addEventListener("click", () => { state.zoom = Math.min(8, state.zoom * 1.5); showPage(); });
$("zoom-out").addEventListener("click", () => { state.zoom = Math.max(0.5, state.zoom / 1.5); showPage(); });
{ // drag to pan
  const wrap = $("canvas-wrap"); let drag = null;
  wrap.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, l: wrap.scrollLeft, t: wrap.scrollTop }; wrap.setPointerCapture(e.pointerId); });
  wrap.addEventListener("pointermove", (e) => { if (drag) { wrap.scrollLeft = drag.l - (e.clientX - drag.x); wrap.scrollTop = drag.t - (e.clientY - drag.y); } });
  wrap.addEventListener("pointerup", () => { drag = null; });
}

// ---------------------------------------------------------------- outputs
function download(blob, name) {
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
async function build(format) {
  const msg = $("build-msg"); msg.className = ""; msg.textContent = "Building…";
  const req = { template: state.template.id, format, params: collect(), meta: meta() };
  if (state.py) {
    const out = JSON.parse(state.py.generate_json(JSON.stringify(req)));
    if (out.error) { msg.className = "error"; msg.textContent = out.error; return; }
    download(new Blob([out.text], { type: out.content_type }), out.filename);
    msg.className = "ok"; msg.textContent = "Downloaded " + out.filename + ".";
    return;
  }
  const res = await postJson("generate", req);
  if (!res.ok) { msg.className = "error"; msg.textContent = await errorText(res); return; }
  const name = (/filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "") || [])[1] || (state.template.id + "." + format);
  download(await res.blob(), name);
  msg.className = "ok"; msg.textContent = "Downloaded " + name + ".";
}
$("build").addEventListener("click", () => build("ifc"));
$("save").addEventListener("click", () => {
  const data = { app: "pdf-to-ifc-modeler", template: state.template.id, meta: meta(), params: collect() };
  download(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }), state.template.id + "_values.json");
});
$("load").addEventListener("change", async (ev) => {
  const file = ev.target.files[0]; if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    if (!state.templates.some((t) => t.id === data.template)) throw new Error("This file is for a structure type the app does not have.");
    chooseTemplate(data.template);
    for (const key of Object.keys(data.params || {})) {
      const spec = state.template.params.find((p) => p.key === key); if (!spec) continue;
      const item = data.params[key];
      const row = document.querySelector('.row[data-key="' + key + '"]');
      row.querySelector("input, textarea").value = typeof item.value === "string" ? item.value : toText(spec, item.value);
      const src = SOURCES.includes(item.source) ? item.source : "assumed";
      row.querySelector("select").value = src; row.dataset.source = src;
      row.querySelector(".note").textContent = item.note ? "Reader's note: " + item.note : "";
    }
    const m = data.meta || {};
    $("m-project").value = m.project_name || ""; $("m-facility").value = m.facility || ""; $("m-source").value = m.source || ""; $("m-author").value = m.author || "";
    tally(); banner("");
  } catch (e) { banner("Could not load that file: " + e.message, true); }
  ev.target.value = "";
});

start();
