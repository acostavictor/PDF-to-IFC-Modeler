// PDF to IFC Modeler: browser side.
// A model is a list of components (a "scene"). The Python engine checks it, builds the 3D preview and writes the IFC.
// With a server the engine and the database are remote; without one (GitHub Pages) the engine runs here through Pyodide
// and models are kept in this browser.
import * as pdfjsLib from "./vendor/pdfjs/pdf.min.mjs";
import { Viewer } from "./viewer.js";

const VENDOR = new URL("./vendor/pdfjs/", import.meta.url).href;
const ROOT = new URL("../", import.meta.url).href;
pdfjsLib.GlobalWorkerOptions.workerSrc = VENDOR + "pdf.worker.min.mjs";

const PYODIDE = "https://cdn.jsdelivr.net/npm/pyodide@314.0.7/";
const PREVIEW_FILES = ["app/__init__.py", "app/browser.py", "app/service.py", "app/scene.py", "app/geometry.py", "app/mesh.py",
  "app/ifcexport.py", "app/ifc/__init__.py", "app/ifc/kit.py", "app/ifc/writer.py"];
const SOURCE_TEXT = { dimensioned: "Written on the drawing", derived: "Calculated from the drawing", scaled: "Measured from the scan",
  assumed: "Assumed", library: "From the library" };
const SOURCE_CSS = { dimensioned: "#2e8c57", derived: "#1c7394", scaled: "#e0991f", assumed: "#c74033", library: "#6b61b3" };
const TILE_PX = 2000, OVERVIEW_PX = 1568, OVERLAP = 0.08, LOCAL_KEY = "p2i.db.v1";

const $ = (id) => document.getElementById(id);
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
const uid = () => "c" + Math.random().toString(36).slice(2, 9);
const clone = (o) => JSON.parse(JSON.stringify(o));
function reId(comp) { comp.id = uid(); (comp.children || []).forEach(reId); return comp; }
function blank() {
  return { name: "", project: "", structure_type: "", units: "ft", datum: "", description: "", source_drawings: "", author: "", components: [] };
}

const state = { api: "api/", health: null, cat: null, py: null, scene: blank(), modelId: null, selected: null, rev: 0, dirty: false,
  pdf: null, page: 1, zoom: 1, rendering: null, ai: null, error: "", viewer: null, timer: null };

// ---------------------------------------------------------------- messages
let bannerTimer = null;
function banner(text, isError) {
  const b = $("banner"); b.hidden = !text; b.textContent = text || ""; b.className = "banner" + (isError ? " error" : "");
  clearTimeout(bannerTimer);
  if (text && !isError) bannerTimer = setTimeout(() => { b.hidden = true; }, 7000);     // confirmations fade; errors stay until the next action
}
const okToDiscard = () => !(state.dirty && state.scene.components.length) || window.confirm("The model on screen has unsaved changes. Discard them?");
function modeNote(text) { const m = $("mode"); m.hidden = !text; m.textContent = text || ""; }
async function errorText(res) {
  try { const j = await res.json(); return j.error || ("Request failed (" + res.status + ")"); }
  catch (e) { return "Request failed (" + res.status + "). The server did not return a readable message."; }
}
class AppError extends Error {}

// ---------------------------------------------------------------- engine: the Python model builder, remote or in the page
async function api(path, body) {
  const opt = { credentials: "same-origin" };
  if (body !== undefined) Object.assign(opt, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const res = await fetch(state.api + path, opt);
  if (!res.ok) throw new AppError(await errorText(res));
  return res;
}
function py(fn, arg) {
  const out = JSON.parse(arg === undefined ? state.py[fn]() : state.py[fn](JSON.stringify(arg)));
  if (out && out.error) throw new AppError(out.error);
  return out;
}
const engine = {
  async catalogue() { return state.py ? py("catalogue_json") : (await api("catalogue")).json(); },
  async preview(scene) { return state.py ? py("preview_json", scene) : (await api("preview", { scene })).json(); },
  async convert(data) { return state.py ? py("convert_json", data) : (await api("convert", data)).json(); },
  async export(scene, schema) {
    if (state.py) { const o = py("export_json", { scene, schema }); return { blob: new Blob([o.text], { type: "application/x-step" }), name: o.filename }; }
    const res = await api("export", { scene, schema });
    return { blob: await res.blob(), name: (/filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "") || [])[1] || "model.ifc" };
  },
};

// ---------------------------------------------------------------- storage: the server database, or this browser
function localDb() {
  try { return JSON.parse(localStorage.getItem(LOCAL_KEY)) || null; } catch (e) { return null; }
}
function localSave(db) {
  try { localStorage.setItem(LOCAL_KEY, JSON.stringify(db)); }
  catch (e) { throw new AppError("This browser would not store the model (storage is full or blocked)."); }
}
async function localOpen() {
  let db = localDb();
  if (db) return db;
  db = { next: 1, models: [], library: [] };
  try {
    const res = await fetch(state.py ? ROOT + "app/seed.json" : state.api + "seed", { credentials: "same-origin" });
    const seed = await res.json();
    for (const s of seed.models) db.models.push({ id: db.next++, is_example: 1, updated: Date.now() / 1000, scene: s });
    for (const e of seed.library) db.library.push(Object.assign({ id: db.next++, is_seed: 1, type: e.item.type }, e));
  } catch (e) { /* start with an empty library */ }
  try { localSave(db); } catch (e) { /* still usable for this visit */ }
  return db;
}
const match = (text, q) => !q || text.toLowerCase().includes(q.trim().toLowerCase());
const browserStore = {
  async listModels(q) {
    const db = await localOpen();
    return db.models.filter((m) => match([m.scene.name, m.scene.project, m.scene.structure_type, m.scene.description].join(" "), q))
      .map((m) => ({ id: m.id, name: m.scene.name, project: m.scene.project, structure_type: m.scene.structure_type, units: m.scene.units,
        description: m.scene.description, is_example: m.is_example, pieces: m.pieces || null, updated: m.updated }))
      .sort((a, b) => (a.is_example - b.is_example) || (b.updated - a.updated));
  },
  async getModel(id) { const m = (await localOpen()).models.find((x) => x.id === id); if (!m) throw new AppError("That model is no longer stored."); return clone(m); },
  async saveModel(scene, id, pieces) {
    if (!scene.name.trim()) throw new AppError("Give the model a name before saving it.");
    const db = await localOpen();
    let m = db.models.find((x) => x.id === id);
    if (!m) { m = { id: db.next++ }; db.models.push(m); }
    Object.assign(m, { is_example: 0, updated: Date.now() / 1000, scene: clone(scene), pieces });
    localSave(db); return m.id;
  },
  async deleteModel(id) { const db = await localOpen(); db.models = db.models.filter((x) => x.id !== id); localSave(db); },
  async listLibrary(q) {
    const db = await localOpen();
    return db.library.filter((e) => match([e.name, e.category, e.description, e.tags].join(" "), q))
      .sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));
  },
  async getLibraryItem(id) { const e = (await localOpen()).library.find((x) => x.id === id); if (!e) throw new AppError("That library item is no longer stored."); return clone(e); },
  async saveLibraryItem(data) {
    if (!data.name.trim()) throw new AppError("Give the library item a name.");
    const db = await localOpen();
    const item = Object.assign(clone(data.item), { source: "library", library_item: data.name });
    db.library.push(Object.assign({ id: db.next++, is_seed: 0, type: item.type }, data, { item }));
    localSave(db);
  },
  async deleteLibraryItem(id) { const db = await localOpen(); db.library = db.library.filter((x) => x.id !== id); localSave(db); },
};
const serverStore = {
  async listModels(q) { return (await (await api("models?q=" + encodeURIComponent(q || ""))).json()).models; },
  async getModel(id) { return (await api("models/" + id)).json(); },
  async saveModel(scene, id) { return (await (await api("models", { scene, id })).json()).id; },
  async deleteModel(id) { await api("models/" + id + "/delete", {}); },
  async listLibrary(q) { return (await (await api("library?q=" + encodeURIComponent(q || ""))).json()).items; },
  async getLibraryItem(id) { return (await api("library/" + id)).json(); },
  async saveLibraryItem(data) { await api("library", data); },
  async deleteLibraryItem(id) { await api("library/" + id + "/delete", {}); },
};
const store = () => (state.health.storage === "server" ? serverStore : browserStore);

// ---------------------------------------------------------------- start-up and sign-in
async function findApi() {
  for (const base of ["api/", "index.cgi/api/"]) {
    try {
      const res = await fetch(base + "health", { credentials: "same-origin" });
      if (res.ok && (res.headers.get("content-type") || "").includes("json")) { state.api = base; return await res.json(); }
    } catch (e) { /* try the next address */ }
  }
  return null;
}
async function startPreview() {
  modeNote("No server is answering, so preview mode is starting: loading the model builder into your browser (about 13 MB the first time).");
  const sources = await Promise.all(PREVIEW_FILES.map(async (f) => {
    const r = await fetch(ROOT + f);
    if (!r.ok) throw new Error("could not load " + f);
    return [f, await r.text()];
  }));
  const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");
  const p = await loadPyodide({ indexURL: PYODIDE });
  for (const [f, text] of sources) {
    const path = "/p2i/" + f;
    p.FS.mkdirTree(path.slice(0, path.lastIndexOf("/")));
    p.FS.writeFile(path, text);
  }
  p.runPython("import sys\nsys.path.insert(0, '/p2i')\nimport app.browser as p2i_browser");
  state.py = p.globals.get("p2i_browser");
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
    state.health = { storage: "browser", ai_ready: false, ai_reason: "Building with AI needs the server version.", max_images: 60, max_body_mb: 60, login_required: false };
    modeNote("Preview mode: no server is answering, so models are checked, drawn and exported here in your browser, and saved models stay in " +
      "this browser only. Building a model with AI needs the server version.");
  } else if (state.health.login_required && !state.health.logged_in) {
    $("login").hidden = false; $("app").hidden = true; $("toolbar").hidden = true; return;
  } else if (state.health.storage !== "server") {
    modeNote((state.health.db_error ? "The server database could not be opened (" + state.health.db_error + "). " : state.health.storage_reason + " ") +
      "Until then, saved models stay in this browser only.");
  }
  try { state.cat = await engine.catalogue(); }
  catch (e) { banner(e.message, true); return; }
  const hl = state.health;
  $("login").hidden = true; $("logout").hidden = !hl.login_required; $("app").hidden = false; $("toolbar").hidden = false;
  $("ai-state").textContent = hl.ai_ready ? "AI model: " + hl.model : hl.ai_reason;
  $("ai-test").hidden = !hl.ai_ready;
  fill($("m-structure_type"), [""].concat(state.cat.structure_types), (v) => v || "Choose a type");
  fill($("m-units"), state.cat.units, (v) => ({ ft: "Feet", m: "Metres", mm: "Millimetres" }[v]));
  fill($("add-type"), state.cat.types.map((t) => t.id), (v) => typeOf(v).title);
  fill($("sl-category"), state.cat.library_categories);
  state.viewer = new Viewer($("view3d"), (id) => select(id));
  loadScene(blank(), null);
  updateCount();
}
function fill(sel, values, label) {
  sel.textContent = "";
  for (const v of values) sel.append(h("option", { value: v }, label ? label(v) : v));
}
$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try { await api("login", { password: $("password").value }); } catch (e) { banner(e.message, true); return; }
  banner(""); $("password").value = ""; start();
});
$("logout").addEventListener("click", async () => { await api("logout", {}); location.reload(); });

// ---------------------------------------------------------------- the model on screen
const typeOf = (id) => state.cat.types.find((t) => t.id === id);
function find(id, list, parent) {
  list = list || state.scene.components;
  for (let i = 0; i < list.length; i++) {
    if (list[i].id === id) return { comp: list[i], list, index: i, parent: parent || null };
    if (list[i].children) { const f = find(id, list[i].children, list[i]); if (f) return f; }
  }
  return null;
}
function topOf(id) {
  for (const c of state.scene.components) if (c.id === id || (c.children && find(id, c.children, c))) return c.id;
  return null;
}
function copies(c) { return c.positions && c.positions.length ? c.positions.length : (c.array ? c.array.nx * c.array.ny : 1); }
function loadScene(scene, modelId) {
  state.scene = scene; state.modelId = modelId; state.selected = null; state.ai = null; state.error = ""; state.dirty = false;
  for (const k of ["name", "project", "structure_type", "units", "datum", "source_drawings", "description"]) $("m-" + k).value = scene[k] || "";
  if (state.viewer) state.viewer.reset();
  renderEditor(); refresh(true);
}
function touch(rerender) { state.dirty = true; refresh(rerender); }
function refresh(rerender) {
  state.rev++;
  const rev = state.rev;
  $("dirty").textContent = state.dirty ? "(unsaved changes)" : "";
  clearTimeout(state.timer);
  state.timer = setTimeout(async () => {
    try {
      const out = await engine.preview(state.scene);
      if (rev !== state.rev) return;                 // a newer edit is on its way; keep what the person typed
      state.scene = out.scene; state.error = ""; state.pieces = out.parts;
      state.viewer.setMeshes(out); state.viewer.select(topOf(state.selected));
      $("welcome").hidden = out.scene.components.length > 0;
      const by = Object.entries(out.sources).map(([k, v]) => v + " " + k).join(", ");
      $("tally").textContent = out.parts + " piece" + (out.parts === 1 ? "" : "s") + (by ? " · components: " + by : "");
      renderList(); if (rerender) renderEditor();
    } catch (e) {
      if (rev !== state.rev) return;
      state.error = e.message; renderList();
    }
    renderMessages();
  }, rerender ? 0 : 350);
}
for (const k of ["name", "project", "structure_type", "datum", "source_drawings", "description"]) {
  $("m-" + k).addEventListener("input", (ev) => { state.scene[k] = ev.target.value; touch(false); });
}
$("m-units").addEventListener("change", async (ev) => {
  try { loadSceneKeep((await engine.convert({ scene: state.scene, units: ev.target.value })).scene); }
  catch (e) { state.error = e.message; ev.target.value = state.scene.units; renderMessages(); }
});
function loadSceneKeep(scene) { const id = state.modelId, sel = state.selected; state.scene = scene; state.modelId = id; state.selected = sel; state.viewer.reset(); renderEditor(); touch(true); }

function renderMessages() {
  const box = $("messages"); box.textContent = "";
  if (state.error) box.append(h("p", { class: "err" }, "This model cannot be built yet: " + state.error));
  const ai = state.ai;
  if (ai) {
    if (ai.general_notes) box.append(h("h3", {}, "AI notes"), h("p", {}, ai.general_notes));
    if (ai.missing.length) box.append(h("h3", {}, "Left out by the AI"), h("ul", {}, ai.missing.map((m) => h("li", {}, m))));
    if (ai.rejected.length) box.append(h("h3", {}, "Components the AI returned that could not be used"), h("ul", {}, ai.rejected.map((m) => h("li", {}, m))));
  }
  box.hidden = !box.childNodes.length;
}

// ---------------------------------------------------------------- component list
function renderList() {
  const ul = $("comp-list"); ul.textContent = "";
  const row = (c, depth) => {
    const n = copies(c);
    ul.append(h("li", { role: "option", tabindex: "0", "aria-selected": String(c.id === state.selected), style: "padding-left:" + (8 + depth * 18) + "px",
      onclick: () => select(c.id), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(c.id); } } },
      h("span", { class: "dot", style: "background:" + SOURCE_CSS[c.source], title: SOURCE_TEXT[c.source] }),
      h("span", { class: "nm" }, c.name), h("span", { class: "ty" }, typeOf(c.type).title + (n > 1 ? " × " + n : ""))));
    (c.children || []).forEach((k) => row(k, depth + 1));
  };
  state.scene.components.forEach((c) => row(c, 0));
  if (!state.scene.components.length) ul.append(h("li", { class: "empty" }, "No components yet."));
  const legend = $("legend");
  legend.hidden = $("colour").value !== "source" || !state.scene.components.length;
  if (!legend.hidden && !legend.childNodes.length) for (const [k, v] of Object.entries(SOURCE_TEXT)) legend.append(h("span", {}, h("i", { style: "background:" + SOURCE_CSS[k] }), v));
}
function select(id) {
  if (id && !find(id)) id = null;
  state.selected = id; renderList(); renderEditor();
  state.viewer.select(topOf(id));
}
$("colour").addEventListener("change", (e) => { state.viewer.setMode(e.target.value); renderList(); });
$("fit").addEventListener("click", () => state.viewer.fit());

function addComponent(comp) {
  const sel = state.selected && find(state.selected);
  if (sel && sel.comp.type === "assembly") sel.comp.children.push(comp); else state.scene.components.push(comp);
  state.selected = comp.id; touch(true);
}
$("add").addEventListener("click", () => {
  const type = $("add-type").value, t = typeOf(type);
  const comp = { id: uid(), type, name: t.title, kind: "", material: "", at: [0, 0, 0], rotate: 0, source: "assumed", note: "", params: {} };
  if (type === "assembly") comp.children = [{ id: uid(), type: "pile", name: "Pile", source: "assumed", params: {} }];
  addComponent(comp);
});

// ---------------------------------------------------------------- component editor
const text = (v) => (v == null ? "" : String(v));
const rows = (v) => (Array.isArray(v) ? v.map((r) => r.join(", ")).join("\n") : text(v));
function field(label, input, hint) { return h("div", { class: "field" }, h("label", {}, label, input), hint ? h("div", { class: "hint" }, hint) : null); }
function renderEditor() {
  const box = $("editor"); box.textContent = "";
  const f = state.selected && find(state.selected);
  if (!f) { box.append(h("p", { class: "muted" }, "Select a component to edit it, or add one. Click a part in the 3D view to select it.")); return; }
  const c = f.comp, t = typeOf(c.type), u = state.scene.units;
  const cur = () => (find(state.selected) || {}).comp;
  const bind = (set) => (ev) => { const x = cur(); if (x) { set(x, ev.target.value); touch(false); } };
  const inp = (value, set, attrs) => h("input", Object.assign({ type: "text", value: text(value), oninput: bind(set) }, attrs || {}));
  box.append(h("h3", {}, t.title + (f.parent ? " in “" + f.parent.name + "”" : "")), h("div", { class: "hint" }, t.summary));
  const kinds = h("datalist", { id: "kinds" }, t.kinds.map((k) => h("option", { value: k })));
  const src = h("select", { onchange: (ev) => { const x = cur(); x.source = ev.target.value; touch(false); } },
    state.cat.sources.map((s) => h("option", Object.assign({ value: s }, s === c.source ? { selected: true } : {}), SOURCE_TEXT[s])));
  box.append(h("div", { class: "grid2" },
    h("label", {}, "Name", inp(c.name, (x, v) => { x.name = v; })),
    h("label", {}, "Kind", inp(c.kind, (x, v) => { x.kind = v; }, { list: "kinds" }), kinds),
    h("label", {}, "Material", inp(c.material, (x, v) => { x.material = v; }, { placeholder: "Concrete, steel, timber, rock…" })),
    h("label", {}, "Where the sizes came from", src)));
  box.append(field("Note", h("textarea", { rows: "2", oninput: bind((x, v) => { x.note = v; }) }, c.note), "Sheet and view the sizes came from, and anything uncertain."));
  box.append(h("fieldset", {}, h("legend", {}, "Placement (" + u + ")"),
    h("div", { class: "grid4" },
      ...["x", "y", "z"].map((ax, i) => h("label", {}, ax, inp(c.at[i], (x, v) => { x.at[i] = v; }))),
      h("label", {}, "Rotation (deg)", inp(c.rotate, (x, v) => { x.rotate = v; }))),
    h("div", { class: "hint" }, "Added to the component's own coordinates and elevations. Leave z at 0 when the sizes below give true elevations.")));
  const a = c.array || { nx: 1, dx: 0, ny: 1, dy: 0 };
  const setArr = (key) => (x, v) => { x.array = Object.assign({ nx: 1, dx: 0, ny: 1, dy: 0 }, x.array || {}); x.array[key] = v; };
  box.append(h("fieldset", {}, h("legend", {}, "Repeat"),
    h("div", { class: "grid4" },
      h("label", {}, "Count along x", inp(a.nx, setArr("nx"))), h("label", {}, "Spacing x", inp(a.dx, setArr("dx"))),
      h("label", {}, "Count along y", inp(a.ny, setArr("ny"))), h("label", {}, "Spacing y", inp(a.dy, setArr("dy")))),
    field("Or list positions", h("textarea", { class: "mono", rows: "2", oninput: bind((x, v) => { x.positions = v; }) }, rows(c.positions)),
      "One x, y per line, measured from the placement point. When filled in, this is used instead of the counts.")));
  if (c.type === "assembly") {
    box.append(h("p", { class: "muted" }, "Contains " + c.children.length + " component(s). With this assembly selected, Add and From library put new components inside it."));
  } else {
    const fs = h("fieldset", {}, h("legend", {}, "Sizes"));
    for (const spec of t.params) {
      const v = c.params[spec.key];
      const lab = spec.label + (spec.type === "number" && spec.length ? " (" + u + ")" : "");
      let el;
      if (spec.type === "choice") {
        el = h("select", { onchange: (ev) => { cur().params[spec.key] = ev.target.value; touch(false); } },
          spec.options.map((o) => h("option", Object.assign({ value: o }, o === v ? { selected: true } : {}), o)));
      } else if (spec.type === "table") {
        el = h("textarea", { class: "mono", rows: String(Math.min(8, Math.max(2, (v || []).length))), oninput: bind((x, val) => { x.params[spec.key] = val; }) }, rows(v));
      } else el = inp(v, (x, val) => { x.params[spec.key] = val; });
      fs.append(field(lab, el, [spec.hint, spec.type === "table" ? "One row per line: " + spec.columns.map((col) => col.name).join(", ") + "." : ""].filter(Boolean).join(" ")));
    }
    box.append(fs);
  }
  box.append(h("div", { class: "inline" },
    h("button", { class: "ghost small", onclick: () => move(-1) }, "Move up"), h("button", { class: "ghost small", onclick: () => move(1) }, "Move down"),
    h("button", { class: "ghost small", onclick: duplicate }, "Duplicate"), h("button", { class: "ghost small", onclick: openSaveLib }, "Save to library"),
    h("button", { class: "danger small", onclick: remove }, "Delete")));
}
function move(d) { const f = find(state.selected); const j = f.index + d; if (j < 0 || j >= f.list.length) return; f.list.splice(j, 0, f.list.splice(f.index, 1)[0]); touch(false); renderList(); }
function duplicate() { const f = find(state.selected); const c = reId(clone(f.comp)); c.name += " copy"; f.list.splice(f.index + 1, 0, c); state.selected = c.id; touch(true); }
function remove() {
  const f = find(state.selected);
  if (f.parent && f.list.length === 1) { state.error = "An assembly needs at least one component inside it. Delete the assembly instead."; renderMessages(); return; }
  f.list.splice(f.index, 1); state.selected = null; touch(true);
}

// ---------------------------------------------------------------- saved models
const when = (t) => new Date(t * 1000).toLocaleDateString();
async function renderOpen() {
  const ul = $("open-list"); ul.textContent = "";
  let list;
  try { list = await store().listModels($("open-q").value); } catch (e) { ul.append(h("li", { class: "error-text" }, e.message)); return; }
  if (!list.length) ul.append(h("li", { class: "muted" }, "No saved models match."));
  for (const m of list) {
    ul.append(h("li", {},
      h("div", { class: "grow" }, h("strong", {}, m.name), m.is_example ? h("span", { class: "chip" }, "Example") : null,
        h("small", {}, [m.structure_type, m.project, m.pieces ? m.pieces + " pieces" : "", m.units, m.is_example ? "" : "saved " + when(m.updated)].filter(Boolean).join(" · "))),
      h("button", { class: "small", onclick: async () => { if (!okToDiscard()) return; await openModel(m); $("dlg-open").close(); } }, m.is_example ? "Open a copy" : "Open"),
      m.is_example ? null : h("button", { class: "danger small", onclick: async () => { await store().deleteModel(m.id); if (state.modelId === m.id) state.modelId = null; renderOpen(); } }, "Delete")));
  }
}
async function openModel(m) {
  const full = await store().getModel(m.id);
  const scene = full.scene;
  if (full.is_example) { scene.name = scene.name.replace(/^Example: /, ""); scene.name = scene.name.charAt(0).toUpperCase() + scene.name.slice(1); scene.project = ""; }
  loadScene(scene, full.is_example ? null : full.id);
}
$("btn-open").addEventListener("click", () => { $("open-q").value = ""; renderOpen(); $("dlg-open").showModal(); });
$("welcome-open").addEventListener("click", () => { $("open-q").value = "example"; renderOpen(); $("dlg-open").showModal(); });
$("open-q").addEventListener("input", renderOpen);
$("btn-new").addEventListener("click", () => { if (okToDiscard()) loadScene(blank(), null); });
async function save(asCopy) {
  try {
    if (asCopy) state.scene.name = (state.scene.name || "Model") + " copy";
    state.modelId = await store().saveModel(state.scene, asCopy ? null : state.modelId, state.pieces);
    $("m-name").value = state.scene.name; state.dirty = false; $("dirty").textContent = "";
    banner("Saved “" + state.scene.name + "”" + (state.health.storage === "server" ? " to the database." : " in this browser."));
  } catch (e) { banner(e.message, true); }
}
$("btn-save").addEventListener("click", () => save(false));
$("btn-copy").addEventListener("click", () => save(true));

// ---------------------------------------------------------------- component library
async function renderLibrary() {
  const ul = $("lib-list"); ul.textContent = "";
  let list;
  try { list = await store().listLibrary($("lib-q").value); } catch (e) { ul.append(h("li", { class: "error-text" }, e.message)); return; }
  if (!list.length) ul.append(h("li", { class: "muted" }, "No library items match."));
  let cat = null;
  for (const e of list) {
    if (e.category !== cat) { cat = e.category; ul.append(h("li", { class: "cat" }, cat)); }
    ul.append(h("li", {},
      h("div", { class: "grow" }, h("strong", {}, e.name), h("small", {}, [typeOf(e.type).title, e.description, e.units].filter(Boolean).join(" · "))),
      h("button", { class: "small", onclick: () => insertFromLibrary(e.id) }, "Insert"),
      h("button", { class: "danger small", onclick: async () => { await store().deleteLibraryItem(e.id); renderLibrary(); } }, "Delete")));
  }
}
async function insertFromLibrary(id) {
  try {
    const entry = await store().getLibraryItem(id);
    let comp = entry.item;
    if (entry.units !== state.scene.units) comp = (await engine.convert({ component: comp, from: entry.units, to: state.scene.units })).component;
    comp = reId(clone(comp)); comp.source = "library"; comp.library_item = entry.name;
    $("dlg-library").close(); addComponent(comp);
  } catch (e) { banner(e.message, true); }
}
$("btn-library").addEventListener("click", () => { $("lib-q").value = ""; renderLibrary(); $("dlg-library").showModal(); });
$("from-library").addEventListener("click", () => { $("lib-q").value = ""; renderLibrary(); $("dlg-library").showModal(); });
$("lib-q").addEventListener("input", renderLibrary);
function openSaveLib() {
  const c = find(state.selected).comp;
  $("sl-name").value = c.name; $("sl-description").value = ""; $("sl-tags").value = ""; $("sl-msg").textContent = "";
  $("sl-category").value = { pile: "Piles", fender: "Fenders", mooring: "Mooring hardware", assembly: "Assemblies", slab: "Decks", wall: "Walls and bulkheads" }[c.type] || "Other";
  $("dlg-savelib").showModal();
}
$("sl-save").addEventListener("click", async () => {
  try {
    await store().saveLibraryItem({ name: $("sl-name").value, category: $("sl-category").value, description: $("sl-description").value, tags: $("sl-tags").value,
      units: state.scene.units, item: clone(find(state.selected).comp) });
    $("dlg-savelib").close(); banner("Saved “" + $("sl-name").value + "” to the library.");
  } catch (e) { $("sl-msg").textContent = e.message; }
});
for (const b of document.querySelectorAll("[data-close]")) b.addEventListener("click", () => b.closest("dialog").close());

// ---------------------------------------------------------------- IFC download
function download(blob, name) {
  const a = h("a", { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
$("btn-export").addEventListener("click", async () => {
  if (!state.scene.components.length) { banner("Add at least one component before downloading.", true); return; }
  try { const out = await engine.export(state.scene, $("ifc-schema").value); download(out.blob, out.name); banner("Downloaded " + out.name + "."); }
  catch (e) { banner(e.message, true); }
});

// ---------------------------------------------------------------- drawings: PDF, page images, AI
function gridFor(detail, vp) { const [a, b] = detail.split("x").map(Number); return vp.width >= vp.height ? { cols: a, rows: b } : { cols: b, rows: a }; }
function selectedPages() { return [...document.querySelectorAll("#pages input:checked")].map((c) => Number(c.value)); }
function updateCount() {
  const [a, b] = $("detail").value.split("x").map(Number);
  const n = state.pdf ? selectedPages().length * (a * b > 1 ? 1 + a * b : 1) : 0;
  const max = state.health.max_images;
  $("image-count").textContent = n + " images to send (limit " + max + ")" + (n > max ? ". Too many: choose fewer pages or less detail." : "");
  $("read").disabled = !state.health.ai_ready || n > max;
}
$("detail").addEventListener("change", updateCount);
$("pdf").addEventListener("change", async (ev) => {
  const file = ev.target.files[0]; if (!file) return;
  try {
    const data = new Uint8Array(await file.arrayBuffer());
    state.pdf = await pdfjsLib.getDocument({ data, wasmUrl: VENDOR + "wasm/", standardFontDataUrl: VENDOR + "standard_fonts/" }).promise;
  } catch (e) { banner("That file could not be opened as a PDF: " + e.message, true); return; }
  banner("");
  if (!$("m-source_drawings").value) { $("m-source_drawings").value = file.name; state.scene.source_drawings = file.name; }
  const pages = $("pages"); pages.textContent = "";
  for (let n = 1; n <= state.pdf.numPages; n++) {
    pages.append(h("label", {}, h("input", Object.assign({ type: "checkbox", value: String(n), onchange: updateCount }, n <= 8 ? { checked: true } : {})), " " + n));
  }
  $("read-options").hidden = false; $("no-pdf").hidden = true; $("canvas").hidden = false; updateCount();
  state.page = 1; state.zoom = 1; showPage();
});
async function renderCanvas(page, scale) {
  const vp = page.getViewport({ scale });
  const canvas = h("canvas", {}); canvas.width = Math.ceil(vp.width); canvas.height = Math.ceil(vp.height);
  const ctx = canvas.getContext("2d"); ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  await page.render({ canvasContext: ctx, viewport: vp, canvas }).promise;
  return canvas;
}
const jpeg = (canvas, q) => canvas.toDataURL("image/jpeg", q).split(",")[1];
async function pageImages(n, detail) {
  const page = await state.pdf.getPage(n);
  const base = page.getViewport({ scale: 1 });
  const out = [{ label: "Page " + n + ": whole sheet overview", media_type: "image/jpeg", data: jpeg(await renderCanvas(page, OVERVIEW_PX / Math.max(base.width, base.height)), 0.8) }];
  const g = gridFor(detail, base);
  if (g.cols * g.rows === 1) return out;
  const fw = 1 / (g.cols - (g.cols - 1) * OVERLAP), fh = 1 / (g.rows - (g.rows - 1) * OVERLAP);
  const scale = Math.min(TILE_PX / Math.max(base.width * fw, base.height * fh), Math.sqrt(60e6 / (base.width * base.height)));
  const full = await renderCanvas(page, scale);
  const tw = Math.floor(full.width * fw), th = Math.floor(full.height * fh);
  for (let r = 0; r < g.rows; r++) {
    for (let c = 0; c < g.cols; c++) {
      const x = Math.min(Math.round(c * tw * (1 - OVERLAP)), full.width - tw), y = Math.min(Math.round(r * th * (1 - OVERLAP)), full.height - th);
      const t = h("canvas", {}); t.width = tw; t.height = th;
      t.getContext("2d").drawImage(full, x, y, tw, th, 0, 0, tw, th);
      out.push({ label: "Page " + n + ": close-up, row " + (r + 1) + " of " + g.rows + ", column " + (c + 1) + " of " + g.cols + " (close-ups overlap slightly)",
        media_type: "image/jpeg", data: jpeg(t, 0.72) });
    }
  }
  full.width = full.height = 0;
  return out;
}
$("read").addEventListener("click", async () => {
  const prog = $("progress"), btn = $("read"), pages = state.pdf ? selectedPages() : [];
  if (!pages.length && !$("notes").value.trim()) { banner("Choose a PDF and pages to read, or describe the structure in the box.", true); return; }
  if ($("ai-merge").value === "replace" && !okToDiscard()) return;
  btn.disabled = true; banner("");
  try {
    let images = [];
    for (let i = 0; i < pages.length; i++) {
      prog.textContent = "Preparing page " + pages[i] + " (" + (i + 1) + " of " + pages.length + ")";
      images = images.concat(await pageImages(pages[i], $("detail").value));
    }
    const mb = images.reduce((s, im) => s + im.data.length, 0) / 1048576;
    if (mb > state.health.max_body_mb * 0.95) throw new AppError("These images total " + mb.toFixed(0) + " MB, over the server limit of " + state.health.max_body_mb + " MB. Choose fewer pages or less detail.");
    prog.textContent = (images.length ? "Sending " + images.length + " images (" + mb.toFixed(1) + " MB). " : "") + "The AI is building the model. This can take a few minutes.";
    const out = await (await api("compose", { images, notes: $("notes").value, units: state.scene.components.length ? state.scene.units : "" })).json();
    if (out.error) throw new AppError(out.error);      // the server keeps the connection alive during the run, so failures arrive in the body
    const u = out.usage || {};
    prog.textContent = "The AI returned " + out.scene.components.length + " component(s), " + out.pieces + " pieces" +
      (u.input_tokens ? " (" + u.input_tokens + " input and " + (u.output_tokens || 0) + " output tokens)" : "") + ". Check each one against the drawings.";
    const ai = { general_notes: out.general_notes, missing: out.missing, rejected: out.rejected };
    if ($("ai-merge").value === "add" && state.scene.components.length) {
      let comps = out.scene.components;
      if (out.scene.units !== state.scene.units) comps = await Promise.all(comps.map(async (c) => (await engine.convert({ component: c, from: out.scene.units, to: state.scene.units })).component));
      state.scene.components.push(...comps.map((c) => reId(c)));
      state.ai = ai; touch(true);
    } else {
      out.scene.source_drawings = out.scene.source_drawings || $("m-source_drawings").value;
      loadScene(out.scene, null); state.ai = ai; state.dirty = true; renderMessages(); $("dirty").textContent = "(unsaved changes)";
    }
  } catch (e) { prog.textContent = ""; banner(e.message, true); }
  updateCount();
});

$("ai-test").addEventListener("click", async () => {
  const box = $("ai-state"); box.textContent = "Testing the connection to the Claude API…";
  try {
    const r = await (await api("ai-check", {})).json();
    box.textContent = "Connection works: " + (r.display_name || r.model) + " answered, and the key is accepted." + (r.warnings.length ? " Note: " + r.warnings.join(" ") : "");
  } catch (e) { box.textContent = "Connection test failed. " + e.message; }
});

async function showPage() {
  if (!state.pdf) return;
  const page = await state.pdf.getPage(state.page), wrap = $("canvas-wrap");
  const vp = page.getViewport({ scale: ((wrap.clientWidth - 4) / page.getViewport({ scale: 1 }).width) * state.zoom });
  const canvas = $("canvas");
  if (state.rendering) { try { state.rendering.cancel(); } catch (e) { /* already finished */ } }
  canvas.width = Math.ceil(vp.width); canvas.height = Math.ceil(vp.height);
  state.rendering = page.render({ canvasContext: canvas.getContext("2d"), viewport: vp, canvas });
  try { await state.rendering.promise; } catch (e) { /* cancelled by a newer render */ }
  $("page-label").textContent = "Page " + state.page + " of " + state.pdf.numPages + ", " + Math.round(state.zoom * 100) + "%";
}
$("prev").addEventListener("click", () => { if (state.pdf && state.page > 1) { state.page--; showPage(); } });
$("next").addEventListener("click", () => { if (state.pdf && state.page < state.pdf.numPages) { state.page++; showPage(); } });
$("zoom-in").addEventListener("click", () => { state.zoom = Math.min(8, state.zoom * 1.5); showPage(); });
$("zoom-out").addEventListener("click", () => { state.zoom = Math.max(0.5, state.zoom / 1.5); showPage(); });
{ // drag to pan the drawing
  const wrap = $("canvas-wrap"); let drag = null;
  wrap.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, l: wrap.scrollLeft, t: wrap.scrollTop }; wrap.setPointerCapture(e.pointerId); });
  wrap.addEventListener("pointermove", (e) => { if (drag) { wrap.scrollLeft = drag.l - (e.clientX - drag.x); wrap.scrollTop = drag.t - (e.clientY - drag.y); } });
  wrap.addEventListener("pointerup", () => { drag = null; });
}
window.addEventListener("beforeunload", (e) => { if (state.dirty && state.scene.components.length) e.preventDefault(); });

start();
