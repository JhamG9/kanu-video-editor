// EditorVideo — interfaz. El color se calcula en el servidor como LUT 3D (misma fórmula que la exportación)
// y aquí se aplica en tiempo real con WebGL.
const $ = (s) => document.querySelector(s);
const api = async (url, opts = {}) => {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r;
};
const toast = (msg, ms = 2600) => {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
};
const fmt = (s) => { const m = Math.floor(s / 60); return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`; };

const SLIDERS = {
  light: [
    ["exposure", "Exposición", -2, 2, 0.05],
    ["contrast", "Contraste", -100, 100, 1],
    ["highlights", "Altas luces", -100, 100, 1],
    ["shadows", "Sombras", -100, 100, 1],
    ["whites", "Blancos", -100, 100, 1],
    ["blacks", "Negros", -100, 100, 1],
  ],
  color: [
    ["temperature", "Temperatura", -100, 100, 1, "temp"],
    ["tint", "Tinte", -100, 100, 1, "tint"],
    ["vibrance", "Intensidad", -100, 100, 1],
    ["saturation", "Saturación", -100, 100, 1],
  ],
};
// Por color (HSL): 8 gamas, mismo orden y centros (grados) que grade.HSL_COLORS en el motor
const HSL = [["red", "Rojos", 0], ["orange", "Naranjas", 30], ["yellow", "Amarillos", 60], ["green", "Verdes", 120],
  ["aqua", "Aguamarinas", 180], ["blue", "Azules", 225], ["purple", "Morados", 270], ["magenta", "Magentas", 315]];
const ZONES = [["shadows", "Sombras"], ["mid", "Medios tonos"], ["high", "Luces"]];
const HSL_KEYS = HSL.flatMap(([c]) => ["h", "s", "l"].map((p) => `hsl_${c}_${p}`));
const ZONE_KEYS = ZONES.flatMap(([z]) => [`zone_${z}_hue`, `zone_${z}_sat`]);
const COLOR_KEYS = [...SLIDERS.light, ...SLIDERS.color].map((s) => s[0]).concat(HSL_KEYS, ZONE_KEYS);
const hueCss = (h, s = 75, l = 55) => `hsl(${((h % 360) + 360) % 360} ${s}% ${l}%)`;

// ---------------------------------------------------------------- WebGL
class Renderer {
  constructor(canvas) {
    this.c = canvas;
    const gl = (this.gl = canvas.getContext("webgl2", { preserveDrawingBuffer: true }));
    if (!gl) { alert("Tu navegador no soporta WebGL2"); return; }
    const vs = `#version 300 es
      in vec2 p; out vec2 uv;
      void main(){ uv = vec2((p.x+1.)*.5, 1.-(p.y+1.)*.5); gl_Position = vec4(p,0.,1.); }`;
    const fs = `#version 300 es
      precision highp float; precision highp sampler3D;
      in vec2 uv; out vec4 o;
      uniform sampler2D img; uniform sampler3D lut; uniform float split; uniform float N;
      uniform float rot; uniform float zoom; uniform float aspect;
      void main(){
        // enderezar: gira alrededor del centro (positivo = horario) y amplía para no mostrar bordes
        vec2 p = (uv - .5) * vec2(aspect, 1.);
        float cs = cos(rot), sn = sin(rot);
        vec2 q = vec2(cs*p.x + sn*p.y, -sn*p.x + cs*p.y) / zoom;
        vec3 c = texture(img, q / vec2(aspect, 1.) + .5).rgb;
        if (uv.x >= split) c = texture(lut, c * ((N-1.)/N) + .5/N).rgb;
        o = vec4(c, 1.);
      }`;
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) console.error(gl.getShaderInfoLog(s)); return s; };
    const pr = (this.pr = gl.createProgram());
    gl.attachShader(pr, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(pr); gl.useProgram(pr);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(pr, "p"); gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    this.imgTex = gl.createTexture(); this.lutTex = gl.createTexture();
    gl.uniform1i(gl.getUniformLocation(pr, "img"), 0); gl.uniform1i(gl.getUniformLocation(pr, "lut"), 1);
    this.uSplit = gl.getUniformLocation(pr, "split"); this.uN = gl.getUniformLocation(pr, "N");
    this.uRot = gl.getUniformLocation(pr, "rot"); this.uZoom = gl.getUniformLocation(pr, "zoom"); this.uAspect = gl.getUniformLocation(pr, "aspect");
    this.split = 0; this.rot = 0; this.hasImg = false; this.hasLut = false;
  }
  setImage(img) {
    const gl = this.gl;
    this.c.width = img.naturalWidth; this.c.height = img.naturalHeight;
    gl.viewport(0, 0, this.c.width, this.c.height);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.imgTex);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB8, gl.RGB, gl.UNSIGNED_BYTE, img);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.NEAREST],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
    this.hasImg = true; this.draw();
  }
  setVideo(v) {
    const gl = this.gl;
    if (this.c.width !== v.videoWidth || this.c.height !== v.videoHeight) {
      this.c.width = v.videoWidth; this.c.height = v.videoHeight; gl.viewport(0, 0, this.c.width, this.c.height);
    }
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.imgTex);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB8, gl.RGB, gl.UNSIGNED_BYTE, v);
    this.hasImg = true; this.draw();
  }
  setLut(bytes, n) {
    const gl = this.gl;
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_3D, this.lutTex);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGB8, n, n, n, 0, gl.RGB, gl.UNSIGNED_BYTE, bytes);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE]])
      gl.texParameteri(gl.TEXTURE_3D, k, v);
    this.N = n; this.hasLut = true; this.draw();
  }
  draw() {
    if (!this.hasImg || !this.hasLut) return;
    const gl = this.gl; gl.useProgram(this.pr);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.imgTex);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_3D, this.lutTex);
    gl.uniform1f(this.uSplit, this.split); gl.uniform1f(this.uN, this.N);
    const asp = this.c.width / this.c.height, a = Math.abs(this.rot) * Math.PI / 180;
    gl.uniform1f(this.uRot, this.rot * Math.PI / 180); gl.uniform1f(this.uAspect, asp);
    gl.uniform1f(this.uZoom, Math.cos(a) + Math.max(asp, 1 / asp) * Math.sin(a));
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
}

// ---------------------------------------------------------------- estado
const S = {
  clips: [], cur: null, info: null, settings: null, t: 0, mode: "after", split: 0.5,
  lut: null, presets: {}, denoiseLabels: {}, clipboard: null, crop: { x: 0.5, y: 0.6 }, noiseOpen: false,
};
const view = new Renderer($("#view"));
const cropA = new Renderer($("#cropA"));
const cropB = new Renderer($("#cropB"));

function loadImage(url) {
  return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
}

// LUT: pide al servidor solo la última versión; las intermedias se descartan
let lutBusy = false, lutDirty = false;
async function refreshLut() {
  if (lutBusy) { lutDirty = true; return; }
  lutBusy = true;
  try {
    const col = Object.fromEntries(COLOR_KEYS.map((k) => [k, S.settings[k]]));
    const r = await api("/api/lut", { method: "POST", body: JSON.stringify(col) });
    S.lut = new Uint8Array(await r.arrayBuffer());
    const n = Math.round(Math.cbrt(S.lut.length / 3));
    for (const R of [view, cropA, cropB]) R.setLut(S.lut, n);
  } finally {
    lutBusy = false;
    if (lutDirty) { lutDirty = false; refreshLut(); }
  }
}

let saveTimer = null;

// ---------------------------------------------------------------- deshacer / rehacer
// Un historial por clip con fotos de los ajustes. Se anota cada vez que se guarda; como el guardado
// espera 350 ms, arrastrar un control cuenta como un solo paso.
const H = {};
const HIST_MAX = 150;
const LABEL = { exposure: "Exposición", contrast: "Contraste", highlights: "Altas luces", shadows: "Sombras",
  whites: "Blancos", blacks: "Negros", temperature: "Temperatura", tint: "Tinte", vibrance: "Intensidad",
  saturation: "Saturación", rotate: "Enderezar", denoise: "Ruido", stabilize: "Estabilización",
  stab_method: "Método de estabilización", trim_in: "Entrada", trim_out: "Salida", sections: "Cortes",
  segment: "Cortes para stock", spots: "Manchas", status: "Estado" };
// orden de claves estable: el servidor puede devolver los mismos ajustes en otro orden
const canon = (v) => Array.isArray(v) ? `[${v.map(canon).join(",")}]`
  : v && typeof v === "object" ? `{${Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canon(v[k])).join(",")}}`
  : JSON.stringify(v);
const snap = () => canon(S.settings);
function histNote(clip = S.cur) {
  if (!clip || !S.settings) return;
  const cur = snap(), h = H[clip];
  if (!h) { H[clip] = { past: [], future: [], last: cur }; renderHist(); return; }
  if (cur === h.last) return;
  h.past.push(h.last); if (h.past.length > HIST_MAX) h.past.shift();
  h.last = cur; h.future = [];
  renderHist();
}
function renderHist() {
  const h = H[S.cur];
  $("#btnUndo").disabled = !h || !h.past.length;
  $("#btnRedo").disabled = !h || !h.future.length;
}
function describeChange(a, b) {
  const A = JSON.parse(a), B = JSON.parse(b);
  const keys = Object.keys(LABEL).filter((k) => k !== "status" && JSON.stringify(A[k]) !== JSON.stringify(B[k]));
  if (JSON.stringify(A.auto) !== JSON.stringify(B.auto) && keys.length > 2) return `Auto (${keys.length} ajustes)`;
  if (!keys.length) return A.status !== B.status ? "Estado" : "ajuste";
  return keys.length > 3 ? `${keys.length} ajustes` : keys.map((k) => LABEL[k]).join(", ");
}
async function histStep(dir) {
  const clip = S.cur, h = H[clip];
  if (!h) return;
  clearTimeout(saveTimer); histNote();                       // lo que estaba a medio guardar cuenta como paso
  const from = dir < 0 ? h.past : h.future, to = dir < 0 ? h.future : h.past;
  if (!from.length) { toast(dir < 0 ? "No hay nada que deshacer" : "No hay nada que rehacer"); return; }
  const before = h.last;
  to.push(h.last); h.last = from.pop();
  const spotsChangedNow = JSON.stringify(JSON.parse(before).spots) !== JSON.stringify(JSON.parse(h.last).spots);
  S.settings = JSON.parse(h.last);
  renderHist();
  toast(`${dir < 0 ? "↶ Deshecho" : "↷ Rehecho"}: ${describeChange(before, h.last)}`);
  const r = await api(`/api/settings?clip=${encodeURIComponent(clip)}`, { method: "POST", body: JSON.stringify(S.settings) });
  if (S.cur !== clip) return;
  applyInfo(await r.json(), false);
  renderStatus(); refreshLut();
  if (spotsChangedNow && (S.settings.spots || []).length) {
    const info = await (await api(`/api/spot/prepare?clip=${encodeURIComponent(clip)}`, { method: "POST" })).json();
    S.info.stab = info.stab; renderSpots(); watchClean();
  }
  if (!P.playing) loadFrame();
}
function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    histNote();
    const r = await api(`/api/settings?clip=${encodeURIComponent(S.cur)}`, { method: "POST", body: JSON.stringify(S.settings) });
    applyInfo(await r.json(), false);
  }, 350);
}

function markManual() {
  if (S.settings.status !== "manual") { S.settings.status = "manual"; renderStatus(); }
}

// ---------------------------------------------------------------- lista de clips
// cajas de la lista: una por tanda subida o por día de grabación; recuerda cuáles están abiertas
S.openGroups = new Set((() => { try { return JSON.parse(localStorage.getItem("kanu.groups") || "[]"); } catch { return []; } })());
const saveOpenGroups = () => { try { localStorage.setItem("kanu.groups", JSON.stringify([...S.openGroups])); } catch {} };
function renderClipList() {
  const el = $("#clipList"); el.innerHTML = "";
  const groups = new Map();
  for (const c of S.clips) {
    const g = c.group || { id: "x", title: "Videos", sub: "", sort: "" };
    if (!groups.has(g.id)) groups.set(g.id, { ...g, clips: [] });
    groups.get(g.id).clips.push(c);
  }
  const list = [...groups.values()].sort((a, b) => (a.sort < b.sort ? 1 : -1));
  if (!S.openGroups.size && list.length) S.openGroups.add(list[0].id);          // la primera vez: la más reciente abierta
  for (const g of list) {
    const has = g.clips.some((c) => c.name === S.cur);
    const open = S.openGroups.has(g.id) || (has && !S.closedByUser?.has(g.id));
    const box = document.createElement("section");
    box.className = "grp" + (open ? " open" : "");
    const ok = g.clips.filter((c) => c.settings.status === "aprobado").length;
    const head = document.createElement("div");
    head.className = "grp-head";
    head.title = `${g.title} · ${g.clips.length} video${g.clips.length > 1 ? "s" : ""}`;
    head.innerHTML = `<span class="chev">▸</span><span class="cnt">${g.clips.length}</span><div class="grp-t"><div class="nm">${g.title}</div>
      <div class="sub">${g.clips.length} video${g.clips.length > 1 ? "s" : ""}${g.sub ? " · " + g.sub : ""}${ok ? ` · ${ok} aprobado${ok > 1 ? "s" : ""}` : ""}</div></div>`;
    head.onclick = () => {
      if (box.classList.toggle("open")) { S.openGroups.add(g.id); S.closedByUser?.delete(g.id); }
      else { S.openGroups.delete(g.id); (S.closedByUser ||= new Set()).add(g.id); }
      saveOpenGroups();
    };
    const body = document.createElement("div"); body.className = "grp-body";
    box.append(head, body); el.appendChild(box);
    for (const c of g.clips) addClipCard(body, c);
  }
}
function addClipCard(el, c) {
  const d = document.createElement("div");
  d.className = "clip" + (c.name === S.cur ? " on" : "");
  const st = c.settings.status, dn = c.settings.denoise, sb = c.settings.stabilize;
  const t = (c.meta.duration * 0.4).toFixed(2);
  const extra = [sb !== "off" ? `Estab. ${(S.stabLevels || {})[sb] || sb}` : "", dn !== "off" ? `Ruido ${S.denoiseLabels[dn] || dn}` : "",
    (c.settings.spots || []).length ? `${c.settings.spots.length} mancha${c.settings.spots.length > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ");
  d.innerHTML = `<div class="thumb"><img loading="lazy" src="/api/frame?clip=${encodeURIComponent(c.name)}&t=${t}&w=320">
      ${st === "aprobado" ? '<span class="ok-mark" title="Aprobado">✓</span>' : ""}</div>
    <div class="meta"><div class="nm">${c.name.replace(/\.[^.]+$/, "")}</div>
      <div class="sub">${fmt(c.meta.duration)} · ${clipBadge(c)}</div>
      <div class="sub"><span class="status st-${st}">${st}</span></div>
      ${extra ? `<div class="sub dim">${extra}</div>` : ""}</div>`;
  d.title = c.name;
  d.onclick = () => selectClip(c.name);
  el.appendChild(d);
}

function renderStatus() {
  const st = S.settings.status;
  $("#clipStatus").className = "status st-" + st; $("#clipStatus").textContent = st;
  const b = $("#btnApprove"), on = st === "aprobado";
  b.classList.toggle("on", on);
  b.textContent = on ? "✓ Aprobado" : "✓ Aprobar";
  b.title = on ? "Clic para quitar la aprobación (vuelve a como estaba)" : "Marcar el clip como listo: «Corregir todo» no lo toca";
}
// Aprobar y desaprobar con el mismo botón; al quitarlo vuelve al estado de antes (manual, auto…)
function toggleApprove() {
  const s = S.settings;
  if (s.status === "aprobado") {
    s.status = s.status_before && s.status_before !== "aprobado" ? s.status_before : (s.auto ? "auto" : "pendiente");
    toast("Aprobación quitada");
  } else {
    s.status_before = s.status; s.status = "aprobado"; toast("Clip aprobado");
  }
  renderStatus(); scheduleSave(); renderClipListDebounced();
}

async function selectClip(name) {
  stopPlayer();
  S.spotMode = false;
  S.cur = name;
  const r = await api(`/api/clip?clip=${encodeURIComponent(name)}`);
  applyInfo(await r.json(), true);
  renderHist();
  S.t = S.settings.trim_in || 0;                       // cada clip empieza desde el inicio (o su punto de entrada)
  renderClipList();
  await Promise.all([loadFrame(), refreshLut()]);
  if (S.noiseOpen) loadCrops();
  api(`/api/proxy/prepare?clip=${encodeURIComponent(name)}`, { method: "POST" }).catch(() => {});
}

function applyInfo(info, full) {
  S.info = info;
  const i = S.clips.findIndex((c) => c.name === info.name);
  if (i >= 0) S.clips[i] = info;
  if (full) { S.settings = structuredClone(info.settings); if (info.name === S.cur) histNote(info.name); }
  else { S.settings.status = info.settings.status; }
  $("#clipName").textContent = info.name;
  renderStatus(); renderPanel(); renderTimeline();
  renderClipListDebounced();
}
let clTimer; function renderClipListDebounced() { clearTimeout(clTimer); clTimer = setTimeout(renderClipList, 300); }

// ---------------------------------------------------------------- enderezar
// ---------------------------------------------------------------- manchas del sensor
// Flujo: con «Marcar mancha» cada clic pone un círculo SIN medir nada. Se mueven y agrandan con calma y,
// cuando todo está cuadrado, «Empezar» mide todas las manchas de una vez y limpia el video.
// Se marca sobre el ORIGINAL (sin girar ni estabilizar), porque la mancha está fija en el sensor.
function spotPct(sp) { return Math.round(sp.a * 100); }
const draftOf = () => (S.settings.spots || []).map((sp) => ({ ...sp, state: "ok" }));
function renderSpots() {
  const m = S.info.meta, L = $("#spotLayer");
  const list = S.spotMode ? S.spotDraft : (S.settings.spots || []).map((sp) => ({ ...sp, state: "ok" }));
  L.setAttribute("viewBox", `0 0 ${m.width} ${m.height}`);
  L.classList.toggle("hidden", !S.spotMode);
  L.innerHTML = list.map((sp, i) => `<circle class="spot ${sp.state}" data-i="${i}" cx="${sp.x}" cy="${sp.y}" r="${sp.r}"/>
    <circle class="handle" data-h="${i}" cx="${sp.x + sp.r}" cy="${sp.y}" r="${Math.max(9, m.width / 300)}"/>`).join("");
  const label = (sp) => sp.state === "ok" ? `oscurecía ${spotPct(sp)} %` : sp.state === "busy" ? "midiendo…"
    : sp.state === "error" ? "no encontré mancha: ajústalo" : "por medir";
  $("#spotList").innerHTML = list.map((sp, i) =>
    `<div class="spot-item ${sp.state}"><span>◎ Mancha ${i + 1} · ${label(sp)}</span>${S.spotBusy ? "" : `<span class="x" data-del="${i}" title="Quitar">✕</span>`}</div>`).join("");
  $("#spotList").querySelectorAll("[data-del]").forEach((x) => (x.onclick = () => {
    if (S.spotMode) { S.spotDraft.splice(+x.dataset.del, 1); renderSpots(); }
    else { S.settings.spots.splice(+x.dataset.del, 1); spotsChanged(); }
  }));
  const changed = S.spotMode && JSON.stringify(S.spotDraft.map(({ x, y, r, state }) => [x, y, r, state]))
    !== JSON.stringify(draftOf().map(({ x, y, r, state }) => [x, y, r, state]));
  $("#btnSpot").classList.toggle("hidden", !!S.spotMode);
  $("#spotActions").classList.toggle("hidden", !S.spotMode);
  $("#btnSpotGo").disabled = !!S.spotBusy || !changed;
  $("#btnSpotCancel").disabled = !!S.spotBusy;
  const n = S.spotMode ? S.spotDraft.filter((s) => s.state !== "ok").length : 0;
  $("#btnSpotGo").textContent = S.spotBusy ? S.spotBusy : n ? `▶ Empezar (${n})` : "▶ Empezar";
  const cl = (S.info.stab || {}).clean || {};
  $("#spotInfo").textContent = S.spotMode
    ? (S.spotDraft.length ? "Mueve cada círculo arrastrándolo y agrándalo con su punto. Cuando todo esté cuadrado, pulsa Empezar."
      : "Haz clic sobre cada mancha para poner un círculo encima.")
    : !(S.settings.spots || []).length ? "Para el polvo del sensor: un punto difuso que está en el mismo lugar en todo el video."
    : cl.running ? "Quitando las manchas del video… (~1 min)"
    : cl.error ? "Error: " + cl.error.split("\n").pop()
    : cl.ready ? "✓ El visor y la exportación ya van sin manchas." : "Se quitarán al exportar.";
}
function setSpotMode(on) {
  if (on) { pause(); S.spotDraft = draftOf(); }
  S.spotMode = on; S.spotBusy = null;
  view.rot = on ? 0 : +S.settings.rotate || 0; view.draw();        // sin girar, para marcar sobre el sensor
  renderSpots(); loadFrame();
}
async function spotsChanged() {
  markManual(); renderSpots(); await saveNow();
  const info = await (await api(`/api/spot/prepare?clip=${encodeURIComponent(S.cur)}`, { method: "POST" })).json();
  S.info.stab = info.stab; renderSpots(); watchClean();
}
let cleanTimer = null;
function watchClean() {
  if (cleanTimer) return;
  const clip = S.cur;
  cleanTimer = setInterval(async () => {
    if (S.cur !== clip) { clearInterval(cleanTimer); cleanTimer = null; return; }
    const info = await (await api(`/api/clip?clip=${encodeURIComponent(clip)}`)).json();
    S.info.stab = info.stab; renderSpots();
    if (!info.stab.clean.running) {
      clearInterval(cleanTimer); cleanTimer = null;
      if (info.stab.clean.ready) { S.info.src_id = info.src_id; stopPlayer(); if (!S.spotMode) loadFrame(); toast("Manchas quitadas del video"); }
    }
  }, 2000);
}
// «Empezar»: mide todas las manchas por medir y, si hay alguna buena, limpia el video
async function startSpots() {
  const clip = S.cur, todo = S.spotDraft.filter((s) => s.state !== "ok");
  let i = 0;
  for (const sp of todo) {
    i++; S.spotBusy = `Midiendo ${i} de ${todo.length}…`; sp.state = "busy"; renderSpots();
    try {
      const r = await (await api(`/api/spot/measure?clip=${encodeURIComponent(clip)}&x=${sp.x.toFixed(1)}&y=${sp.y.toFixed(1)}&r=${(sp.r / 1.2).toFixed(1)}`,
        { method: "POST" })).json();
      Object.assign(sp, r, { state: "ok" });
    } catch { sp.state = "error"; }
    if (S.cur !== clip) return;
  }
  S.spotBusy = null;
  const bad = S.spotDraft.filter((s) => s.state === "error").length;
  if (bad) { renderSpots(); toast(`${bad} círculo${bad > 1 ? "s" : ""} sin mancha: muévelo justo encima o quítalo y pulsa Empezar otra vez`, 5000); return; }
  S.settings.spots = S.spotDraft.map(({ x, y, r, a, s, fit }) => ({ x, y, r, a, s, fit }));
  setSpotMode(false);
  toast(`${S.settings.spots.length} mancha${S.settings.spots.length > 1 ? "s" : ""} lista${S.settings.spots.length > 1 ? "s" : ""}: quitándolas del video…`);
  await spotsChanged();
}
function initSpots() {
  $("#btnSpot").onclick = () => setSpotMode(true);
  $("#btnSpotGo").onclick = startSpots;
  $("#btnSpotCancel").onclick = () => setSpotMode(false);
  const L = $("#spotLayer");
  const toSrc = (e) => {
    const b = L.getBoundingClientRect(), m = S.info.meta;
    return [(e.clientX - b.left) / b.width * m.width, (e.clientY - b.top) / b.height * m.height];
  };
  let drag = null;
  L.onpointerdown = (e) => {
    if (S.spotBusy) return;
    const [x, y] = toSrc(e), t = e.target;
    if (t.dataset.i != null || t.dataset.h != null) {
      const i = +(t.dataset.i ?? t.dataset.h), sp = S.spotDraft[i];
      drag = { i, resize: t.dataset.h != null, dx: x - sp.x, dy: y - sp.y, moved: false };
      L.setPointerCapture(e.pointerId);
    } else {                                    // clic en vacío: un círculo nuevo, sin medir todavía
      S.spotDraft.push({ x, y, r: 48 * S.info.meta.width / 3840, a: 0, s: 0, state: "pending" });
      renderSpots();
    }
  };
  L.onpointermove = (e) => {
    if (!drag) return;
    const [x, y] = toSrc(e), sp = S.spotDraft[drag.i];
    if (drag.resize) sp.r = Math.max(8, Math.hypot(x - sp.x, y - sp.y));
    else { sp.x = x - drag.dx; sp.y = y - drag.dy; }
    sp.state = "pending"; drag.moved = true; renderSpots();
  };
  L.onpointerup = () => { drag = null; };
}

function renderRotate() {
  const r = +S.settings.rotate || 0, a = Math.abs(r) * Math.PI / 180;
  $("#s_rotate").value = r;
  const v = $("#v_rotate"); v.textContent = (r > 0 ? "+" : "") + r.toFixed(1) + "°"; v.classList.toggle("changed", Math.abs(r) > 0.001);
  const z = Math.cos(a) + (16 / 9) * Math.sin(a);
  $("#rotInfo").textContent = Math.abs(r) > 0.001 ? `Recorta ${((1 - 1 / z) * 100).toFixed(1)} % por lado para no dejar bordes.` : "";
  view.rot = S.spotMode ? 0 : r; view.draw();   // al marcar manchas se ve el sensor sin girar
}
function setRotate(r) {
  S.settings.rotate = Math.round(Math.min(15, Math.max(-15, r)) * 100) / 100;
  renderRotate(); markManual(); scheduleSave();
}
let gridTimer;
function flashGrid(on) {
  clearTimeout(gridTimer);
  if (on) $("#straightGrid").classList.remove("hidden");
  else gridTimer = setTimeout(() => { if (!S.lineMode) $("#straightGrid").classList.add("hidden"); }, 900);
}
function setLineMode(on) {
  S.lineMode = on;
  $("#lineLayer").classList.toggle("hidden", !on);
  $("#btnLine").classList.toggle("on", on);
  $("#line").setAttribute("x2", -1); $("#line").setAttribute("x1", -1);
  if (on) { pause(); flashGrid(true); toast("Traza una línea sobre algo que debería estar recto", 3500); } else flashGrid(false);
}
function initStraighten() {
  const inp = $("#s_rotate");
  inp.oninput = () => { flashGrid(true); setRotate(parseFloat(inp.value)); };
  inp.onchange = () => flashGrid(false);
  inp.ondblclick = () => setRotate(0);
  $("#v_rotate").onclick = () => { const v = prompt("Ángulo en grados (positivo = horario)", S.settings.rotate); if (v !== null && !isNaN(parseFloat(v))) setRotate(parseFloat(v)); };
  $("#btnRotM").onclick = () => setRotate((+S.settings.rotate || 0) - 0.1);
  $("#btnRotP").onclick = () => setRotate((+S.settings.rotate || 0) + 0.1);
  $("#btnRot0").onclick = () => setRotate(0);
  $("#btnLine").onclick = () => setLineMode(!S.lineMode);
  $("#btnRotAuto").onclick = async () => {
    const b = $("#btnRotAuto"); b.disabled = true; b.textContent = "Midiendo…";
    try {
      await saveNow();
      const info = await (await api(`/api/straighten?clip=${encodeURIComponent(S.cur)}`, { method: "POST" })).json();
      S.settings.rotate = info.settings.rotate; applyInfo(info, false); renderRotate();
      flashGrid(true); flashGrid(false); toast(info.message, 4000);
    } catch (e) { toast("Error: " + e.message); }
    b.disabled = false; b.textContent = "✦ Auto";
  };
  const layer = $("#lineLayer"), line = $("#line"); let start = null;
  const pt = (e) => { const r = layer.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  layer.onpointerdown = (e) => { start = pt(e); layer.setPointerCapture(e.pointerId);
    for (const [k, v] of [["x1", start[0]], ["y1", start[1]], ["x2", start[0]], ["y2", start[1]]]) line.setAttribute(k, v); };
  layer.onpointermove = (e) => { if (!start) return; const [x, y] = pt(e); line.setAttribute("x2", x); line.setAttribute("y2", y); };
  layer.onpointerup = (e) => {
    if (!start) return;
    const [x, y] = pt(e), dx = x - start[0], dy = y - start[1]; start = null;
    if (Math.hypot(dx, dy) < 20) { line.setAttribute("x2", -1); return; }
    let phi = Math.atan2(dy, dx) * 180 / Math.PI;           // ángulo de la línea en pantalla
    if (phi > 90) phi -= 180; if (phi <= -90) phi += 180;    // misma línea trazada al revés
    if (Math.abs(phi) > 45) phi -= Math.sign(phi) * 90;      // casi vertical: se endereza como vertical
    setRotate((+S.settings.rotate || 0) - phi);
    toast(`Enderezado ${(-phi > 0 ? "+" : "") + (-phi).toFixed(1)}°`);
    setLineMode(false);
  };
}


// ---------------------------------------------------------------- progreso de la corrección automática
// La corrección tarda (sobre todo medir la vibración, que recorre el video entero): una tarjeta muestra
// en qué paso va según el motor, cuánto lleva y, con varios clips, cuánto falta.
const AUTO_STEPS = { luz: ["Midiendo luz y color", 0.10], ruido: ["Midiendo el ruido", 0.15],
  vibracion: ["Midiendo la vibración (recorre todo el video)", 0.50], estilo: ["Aplicando tu estilo de color", 0.12],
  horizonte: ["Enderezando el horizonte", 0.13] };
async function runAuto(names, onClip) {
  const card = $("#autoCard"), keys = Object.keys(AUTO_STEPS), out = [];
  const t0 = Date.now(); let stage = "luz", stageT = Date.now(), cur = 0;
  $("#acSteps").innerHTML = keys.map((k) => `<li data-k="${k}">${AUTO_STEPS[k][0]}</li>`).join("");
  card.classList.remove("hidden");
  const draw = () => {
    const n = names.length, i = keys.indexOf(stage);
    for (const li of $("#acSteps").children) {
      const j = keys.indexOf(li.dataset.k);
      li.className = j < i ? "done" : j === i ? "now" : "";
    }
    // dentro de una etapa la barra avanza despacio hacia su final, sin pasarse
    const before = keys.slice(0, i).reduce((a, k) => a + AUTO_STEPS[k][1], 0);
    const inStage = AUTO_STEPS[stage][1] * (1 - Math.exp(-(Date.now() - stageT) / 9000));
    $("#acBar").style.width = (100 * (cur + before + inStage) / n).toFixed(1) + "%";
    const secs = Math.round((Date.now() - t0) / 1000);
    $("#acTime").textContent = secs < 60 ? `${secs} s` : `${Math.floor(secs / 60)} min ${secs % 60} s`;
    $("#acTitle").textContent = n > 1 ? `Corrigiendo clip ${cur + 1} de ${n}` : "Corrigiendo con ✦ Auto";
    $("#acClip").textContent = names[cur];
    let note = "Puedes seguir mirando otros clips mientras tanto.";
    if (n > 1 && cur > 0) {
      const left = Math.round((Date.now() - t0) / cur * (n - cur) / 1000);
      note = `Quedan unos ${left < 90 ? left + " s" : Math.round(left / 60) + " min"}. ` + note;
    } else if (n > 1) note = `Unos 30–40 s por clip. ` + note;
    else note = "Suele tardar 30–40 s. " + note;
    $("#acNote").textContent = note;
    $("#panel").classList.toggle("busy", names[cur] === S.cur);   // no se toca el clip que se está corrigiendo
  };
  const poll = setInterval(async () => {
    try {
      const p = (await (await api("/api/auto/progress")).json())[names[cur]];
      if (p && p.stage !== stage) { stage = p.stage; stageT = Date.now(); }
    } catch {}
    draw();
  }, 500);
  try {
    for (cur = 0; cur < names.length; cur++) {
      stage = "luz"; stageT = Date.now(); onClip(cur, names.length); draw();
      try { out.push(await (await api(`/api/auto?clip=${encodeURIComponent(names[cur])}`, { method: "POST" })).json()); }
      catch (e) { if (names.length === 1) throw e; toast(`${names[cur]}: ${e.message}`); }
      const info = out[out.length - 1];
      if (info && names.length > 1) {                       // la lista se va actualizando clip a clip
        const k = S.clips.findIndex((c) => c.name === info.name); if (k >= 0) S.clips[k] = info;
        if (info.name === S.cur) { applyInfo(info, true); refreshLut(); } else renderClipListDebounced();
      }
    }
  } finally {
    clearInterval(poll); $("#panel").classList.remove("busy"); card.classList.add("hidden");
  }
  return out;
}

// ---------------------------------------------------------------- panel
function addSlider(host, [key, label, min, max, step, cls], track) {
  const d = document.createElement("div");
  d.className = "sl " + (cls || "");
  d.innerHTML = `<div class="sl-top"><span>${label}</span><span class="v" id="v_${key}"></span></div>
    <input type="range" id="s_${key}" min="${min}" max="${max}" step="${step}">`;
  host.appendChild(d);
  const inp = d.querySelector("input");
  if (track) inp.style.background = track;
  const set = (v) => { S.settings[key] = v; inp.value = v; showVal(key); markManual(); refreshLut(); scheduleSave(); };
  inp.oninput = () => set(parseFloat(inp.value));
  inp.ondblclick = () => set(0);
  d.querySelector(".v").onclick = () => {
    const v = prompt(label, S.settings[key]);
    if (v === null || isNaN(parseFloat(v))) return;
    set(Math.min(max, Math.max(min, parseFloat(v))));
  };
  return d;
}

let hslCur = "red";
function buildSliders() {
  for (const s of SLIDERS.light) addSlider($("#slLight"), s);
  for (const s of SLIDERS.color) addSlider($("#slColor"), s);

  // Por color: se elige la gama con las muestras y se mueven sus tres controles
  for (const [c, label, h] of HSL) {
    const b = document.createElement("button");
    b.className = "sw"; b.dataset.c = c; b.title = label; b.style.background = hueCss(h);
    b.onclick = () => showHsl(c);
    $("#hslSw").appendChild(b);
    const g = document.createElement("div");
    g.className = "hsl-g"; g.dataset.c = c;
    $("#slHsl").appendChild(g);
    addSlider(g, [`hsl_${c}_h`, `Tono · ${label.toLowerCase()}`, -100, 100, 1],
      `linear-gradient(90deg, ${hueCss(h - 30)}, ${hueCss(h)} 50%, ${hueCss(h + 30)})`);
    addSlider(g, [`hsl_${c}_s`, "Saturación", -100, 100, 1],
      `linear-gradient(90deg, ${hueCss(h, 0, 50)}, ${hueCss(h, 90)})`);
    addSlider(g, [`hsl_${c}_l`, "Luminancia", -100, 100, 1],
      `linear-gradient(90deg, ${hueCss(h, 70, 18)}, ${hueCss(h, 75, 50)} 50%, ${hueCss(h, 80, 82)})`);
  }
  const reset = document.createElement("button");
  reset.className = "small hsl-reset"; reset.textContent = "Restablecer colores";
  reset.title = "Pone en cero los ajustes de las 8 gamas";
  reset.onclick = () => { for (const k of HSL_KEYS) S.settings[k] = 0; markManual(); renderPanel(); refreshLut(); scheduleSave(); };
  $("#slHsl").appendChild(reset);
  showHsl(hslCur);

  // Por zonas: teñir sombras, medios y luces con un tono
  const rainbow = `linear-gradient(90deg, ${[0, 60, 120, 180, 240, 300, 360].map((h) => hueCss(h)).join(",")})`;
  for (const [z, label] of ZONES) {
    const g = document.createElement("div");
    g.className = "zone"; g.innerHTML = `<div class="zone-h"><span class="zone-dot" id="zd_${z}"></span>${label}</div>`;
    $("#slZones").appendChild(g);
    addSlider(g, [`zone_${z}_hue`, "Tono", 0, 360, 1], rainbow);
    addSlider(g, [`zone_${z}_sat`, "Cantidad", 0, 100, 1]);
  }
}
function showHsl(c) {
  hslCur = c;
  for (const b of document.querySelectorAll("#hslSw .sw")) b.classList.toggle("on", b.dataset.c === c);
  for (const g of document.querySelectorAll("#slHsl .hsl-g")) g.classList.toggle("hidden", g.dataset.c !== c);
}
function showVal(key) {
  const v = S.settings[key] || 0, el = $("#v_" + key);
  if (key.endsWith("_hue")) {                                   // tono de una zona: en grados, con muestra
    el.textContent = Math.round(v) + "°";
    const z = key.slice(5, -4), sat = S.settings[`zone_${z}_sat`] || 0;
    el.classList.toggle("changed", sat > 0);
  } else {
    el.textContent = key === "exposure" ? (v > 0 ? "+" : "") + v.toFixed(2) + " EV" : (v > 0 ? "+" : "") + Math.round(v);
    el.classList.toggle("changed", Math.abs(v) > 1e-6);
  }
  if (key.startsWith("zone_")) {
    const z = key.split("_")[1], sat = S.settings[`zone_${z}_sat`] || 0, dot = $("#zd_" + z);
    if (dot) dot.style.background = sat > 0 ? hueCss(S.settings[`zone_${z}_hue`] || 0, 20 + sat * 0.7) : "transparent";
    if (key.endsWith("_sat")) showVal(`zone_${z}_hue`);
  }
  if (key.startsWith("hsl_")) {                                 // punto en la muestra si esa gama tiene cambios
    const c = key.split("_")[1], b = document.querySelector(`#hslSw .sw[data-c="${c}"]`);
    if (b) b.classList.toggle("mod", ["h", "s", "l"].some((p) => Math.abs(S.settings[`hsl_${c}_${p}`] || 0) > 1e-6));
  }
}

function renderPanel() {
  const s = S.settings;
  for (const k of COLOR_KEYS) { $("#s_" + k).value = s[k]; showVal(k); }
  renderRotate(); renderSpots();
  $("#denoise").value = s.denoise;
  const a = s.auto;
  $("#noiseMeasure").textContent = a ? `medido: ${a.noise} (${S.denoiseLabels[a.noise_level]})` : "";
  $("#segOn").checked = s.segment.enabled; $("#segMin").value = s.segment.min; $("#segMax").value = s.segment.max;
  $("#segSlow").value = String(s.segment.max_slow);
  renderSegInfo();
  $("#stabLevel").value = s.stabilize; $("#stabMethod").value = s.stab_method;
  renderStab();
  const why = $("#autoWhy");
  if (a && a.why && a.why.length) {
    why.classList.remove("hidden");
    let open = false; try { open = localStorage.getItem("kanu.whyOpen") === "1"; } catch {}
    why.innerHTML = `<details ${open ? "open" : ""}><summary><b>✦ Corrección automática</b> <span class="hint">· ${a.why.length} cambio${a.why.length > 1 ? "s" : ""}</span></summary>
      <ul>${a.why.map((w) => `<li>${w}</li>`).join("")}</ul></details>`;
    why.querySelector("details").ontoggle = (e) => { try { localStorage.setItem("kanu.whyOpen", e.target.open ? "1" : ""); } catch {} };
  } else why.classList.add("hidden");
  renderDenoisePreview();
  if (S.info.denoise_preview === false) watchDenoise();
  renderSummaries();
}

// vista previa con reducción de ruido: se prepara una copia de reproducción filtrada (~1× tiempo real)
function renderDenoisePreview() {
  const e = $("#dnPreview"); if (!e || !S.info) return;
  const st = S.info.denoise_preview;
  e.textContent = st === null || st === undefined ? "" : st ? "✓ El visor y la reproducción muestran la reducción de ruido."
    : "Preparando la vista con reducción de ruido… (unos segundos por cada segundo de video)";
}
let dnTimer = null;
function watchDenoise() {
  if (dnTimer) return;
  const clip = S.cur;
  renderDenoisePreview();
  dnTimer = setInterval(async () => {
    if (S.cur !== clip) { clearInterval(dnTimer); dnTimer = null; return; }
    const info = await (await api(`/api/clip?clip=${encodeURIComponent(clip)}`)).json();
    S.info.denoise_preview = info.denoise_preview; S.info.src_id = info.src_id; renderDenoisePreview();
    if (info.denoise_preview !== false) {
      clearInterval(dnTimer); dnTimer = null;
      if (info.denoise_preview) { stopPlayer(); if (!P.playing) loadFrame(); toast("Vista con reducción de ruido lista"); }
    }
  }, 2000);
}

function renderSegInfo() {
  const n = S.info.segments.length, p = S.info.plan;
  if ((S.settings.sections || []).length) {
    const secs = S.settings.sections, cuts = S.info.cuts || [];
    let h = `Salen <b>${n} clip${n === 1 ? "" : "s"}</b> de ${secs.length} tramos:`;
    secs.forEach(([a, b, on], i) => {
      const cs = cuts.filter((c) => c.section === i + 1);
      h += `<br>${i + 1}. ` + (!on ? "descartado" : !cs.length ? "muy corto (menos de 0.5 s)"
        : `${cs.length} × ${cs[0].len.toFixed(1)} s${cs[0].speed > 1.001 ? ` a ${cs[0].speed.toFixed(2)}× (${cs[0].fps}p)` : ""}`
          + (S.settings.segment.enabled && cs[0].len < S.settings.segment.min - 0.05 ? ` <span class="warn">corto</span>` : ""));
    });
    $("#segInfo").innerHTML = h; return;
  }
  let html = `Salen <b>${n} clip${n > 1 ? "s" : ""}</b> de <b>${p.clip_len.toFixed(1)} s</b>`;
  html += p.speed > 1.001 ? ` · ralentizado <b>${p.speed.toFixed(2)}×</b> → ${p.fps}p` : ` · velocidad normal (${p.fps}p)`;
  if (p.short) html += `<br><span class="warn">Más corto que ${S.settings.segment.min} s aun ralentizando.</span>`;
  $("#segInfo").innerHTML = html;
}
function clipBadge(c) {
  const n = c.segments.length, p = c.plan;
  return `${n} clip${n > 1 ? "s" : ""}${p.speed > 1.001 ? ` · ${p.speed.toFixed(1)}×` : ""}${p.short ? " · corto" : ""}`;
}

// ---------------------------------------------------------------- estabilización
const METHOD_NAME = { giroscopio: "giroscopio de la cámara", imagen: "análisis de imagen" };
function renderStab() {
  const s = S.settings, st = S.info.stab || {}, info = $("#stabInfo"), btn = $("#btnStabPreview"), bar = $("#stabBar");
  btn.classList.add("hidden"); bar.classList.add("hidden");
  if (!S.stabAvailable) { info.textContent = "Gyroflow no está instalado."; return; }
  if (s.stabilize === "off") { info.textContent = "Sin estabilizar."; return; }
  if (st.running) {
    bar.classList.remove("hidden"); bar.firstElementChild.style.width = Math.round((st.progress || 0) * 100) + "%";
    info.textContent = `Procesando: ${st.stage || "…"} ${Math.round((st.progress || 0) * 100)}%`;
    watchStab(); return;
  }
  btn.classList.remove("hidden");
  if (st.error) info.textContent = "Error: " + st.error.split("\n").pop();
  else if (st.method_used) info.textContent = `✓ Lista (${METHOD_NAME[st.method_used]}). El visor muestra la versión estabilizada.`;
  else if (st.proxy_stab) info.textContent = "✓ Al reproducir se ve estabilizada. Con el video en pausa se muestra el original.";
  else info.textContent = "Se estabilizará al exportar. Para verla antes, usa Comparar (~1 min).";
}
function openCompare() {
  pause();
  const v = $("#cmpVideo"), st = S.info.stab || {};
  $("#cmpLabel").textContent = `${S.cur} · ${S.stabLevels[S.settings.stabilize]} · ${METHOD_NAME[st.method_used] || ""}`;
  v.src = `/api/compare?clip=${encodeURIComponent(S.cur)}&v=${Date.now()}`;
  v.playbackRate = Number($("#cmpRate .on").dataset.r);
  $("#cmpGrid").classList.toggle("hidden", !$("#cmpGridOn").checked);
  $("#stabModal").classList.remove("hidden");
  v.play().catch(() => {});
}
function closeCompare() {
  const v = $("#cmpVideo"); v.pause(); v.removeAttribute("src"); v.load();
  $("#stabModal").classList.add("hidden");
}
let stabTimer = null;
function watchStab() {
  if (stabTimer) return;
  const clip = S.cur;
  stabTimer = setInterval(async () => {
    if (S.cur !== clip) { clearInterval(stabTimer); stabTimer = null; return; }
    const info = await (await api(`/api/clip?clip=${encodeURIComponent(clip)}`)).json();
    S.info.stab = info.stab; S.info.src_id = info.src_id; renderStab();
    if (!info.stab.running) {
      clearInterval(stabTimer); stabTimer = null;
      if (info.stab.method_used) {
        const wasPlaying = P.playing;
        stopPlayer(); loadFrame(); if (S.noiseOpen) loadCrops();
        if (wasPlaying && !(S.compareWanted === clip && info.stab.compare)) play();
        if (S.compareWanted === clip && info.stab.compare) openCompare(); else toast("Vista estabilizada lista");
      }
      S.compareWanted = null;
    }
  }, 1500);
}
async function saveNow() {
  clearTimeout(saveTimer);
  histNote();
  const r = await api(`/api/settings?clip=${encodeURIComponent(S.cur)}`, { method: "POST", body: JSON.stringify(S.settings) });
  applyInfo(await r.json(), false);
}

// ---------------------------------------------------------------- reproducción
// Se reproduce una copia ligera (1080p) que el servidor prepara por clip; el color se aplica encima
// con la misma LUT, así que los controles siguen funcionando mientras el video corre.
const P = { v: null, url: null, playing: false, loading: false, loop: true, muted: true, raf: 0 };
const playRange = () => { const d = S.info.meta.duration; return [S.settings.trim_in || 0, Math.min(S.settings.trim_out || d, d)]; };
const stabPlayable = () => { const st = S.info.stab || {}; return st.method_used || st.proxy_stab || null; };
const proxyUrl = () => `/api/proxy?clip=${encodeURIComponent(S.cur)}&k=${S.settings.stabilize}_${stabPlayable() || "orig"}_${S.settings.denoise}_${S.info.denoise_preview ? 1 : 0}`;
const waitEvent = (el, ok, bad = "error") => new Promise((res, rej) => {
  const a = () => { el.removeEventListener(bad, b); res(); }, b = () => { el.removeEventListener(ok, a); rej(new Error("no se pudo cargar el video")); };
  el.addEventListener(ok, a, { once: true }); el.addEventListener(bad, b, { once: true });
});
function renderTransport() {
  $("#tpPlay").innerHTML = P.playing
    ? '<svg viewBox="0 0 24 24"><rect x="6.5" y="5" width="3.6" height="14" rx="1.2"/><rect x="13.9" y="5" width="3.6" height="14" rx="1.2"/></svg>'
    : '<svg viewBox="0 0 24 24"><path d="M8 5.6v12.8a1 1 0 0 0 1.5.86l10.2-6.4a1 1 0 0 0 0-1.72L9.5 4.74A1 1 0 0 0 8 5.6z"/></svg>';
  $("#tpPlay").classList.toggle("playing", P.playing);
  $("#tpLoop").classList.toggle("on", P.loop);
  $("#tpMute").classList.toggle("on", !P.muted);
  $("#tpMute").innerHTML = P.muted
    ? '<svg class="ic" viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="m22 9-6 6M16 9l6 6"/></svg>'
    : '<svg class="ic" viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/></svg>';
  $("#tpState").textContent = P.loading ? "Preparando reproducción…"
    : P.playing && P.unstab ? "Sin estabilizar todavía · preparando la versión estabilizada (~1 min)…" : "";
}
async function play() {
  if (P.playing || P.loading || !S.cur) return;
  const clip = S.cur, url = proxyUrl();
  // si el clip lleva estabilización y aún no hay versión estabilizada, se prepara sola y luego se cambia
  P.unstab = S.settings.stabilize !== "off" && S.stabAvailable && !stabPlayable();
  if (P.unstab && !(S.info.stab || {}).running && !(S.info.stab || {}).error) {
    api(`/api/stabilize?clip=${encodeURIComponent(clip)}`, { method: "POST" })
      .then((r) => r.json()).then((info) => { if (S.cur === clip) { S.info.stab = info.stab; renderStab(); } }).catch(() => {});
  }
  if (!P.v) {
    P.v = document.createElement("video"); P.v.playsInline = true; P.v.preload = "auto";
    // por si el navegador frena requestAnimationFrame (pestaña en segundo plano): el fin del tramo se controla aquí también
    const guard = () => {
      if (!P.playing) return;
      const [a0, b0] = playRange();
      if (P.v.ended || P.v.currentTime >= b0 - 0.02) {
        if (P.loop) { P.v.currentTime = a0; P.v.play().catch(() => {}); } else pause();
      }
    };
    P.v.addEventListener("timeupdate", guard); P.v.addEventListener("ended", guard);
  }
  const v = P.v; v.muted = P.muted;
  const [a, b] = playRange();
  if (S.t < a || S.t >= b - 0.05) S.t = a;
  try {
    if (P.url !== url) {
      P.loading = true; renderTransport(); $("#loading").classList.remove("hidden");
      P.url = url; v.src = url; await waitEvent(v, "loadeddata");
    }
    if (S.cur !== clip) return;
    v.currentTime = S.t; await waitEvent(v, "seeked");
    P.playing = true; frameReq++;
    await v.play();
    tick();
  } catch (e) { P.url = null; P.playing = false; toast("Error al reproducir: " + e.message); }
  finally { P.loading = false; $("#loading").classList.add("hidden"); renderTransport(); }
}
function tick() {
  if (!P.playing) return;
  const v = P.v, [a, b] = playRange();
  if (v.readyState >= 2) view.setVideo(v);
  S.t = v.currentTime; updateTime();
  if (S.t >= b - 0.02 || v.ended) {
    if (P.loop) { v.currentTime = a; if (v.paused) v.play(); }
    else { pause(); return; }
  }
  P.raf = requestAnimationFrame(tick);
}
function pause(reload = true) {
  if (!P.playing) return;
  P.playing = false; cancelAnimationFrame(P.raf); P.v.pause(); S.t = P.v.currentTime;
  renderTransport();
  if (reload) { loadFrame(); if (S.noiseOpen) loadCrops(); }
}
const togglePlay = () => (P.playing ? pause() : play());
function seekTo(t) {
  S.t = Math.min(Math.max(t, 0), S.info.meta.duration - 0.05);
  if (P.playing) { P.v.currentTime = S.t; updateTime(); } else loadFrame();
}
function stopPlayer() { pause(false); P.url = null; }

// ---------------------------------------------------------------- visor y línea de tiempo
let frameReq = 0;
async function loadFrame() {
  if (P.playing) return;
  const id = ++frameReq;
  $("#loading").classList.remove("hidden");
  try {
    const img = await loadImage(`/api/frame?clip=${encodeURIComponent(S.cur)}&t=${S.t.toFixed(2)}&w=1920${S.spotMode ? "&orig=1" : `&src=${encodeURIComponent(S.info.src_id || "")}`}`);
    if (id === frameReq) view.setImage(img);
  } finally { if (id === frameReq) $("#loading").classList.add("hidden"); }
  updateTime();
}
function updateTime() {
  $("#timeLabel").textContent = `${fmt(S.t)} / ${fmt(S.info.meta.duration)}`;
  $("#scrub").value = Math.round((S.t / S.info.meta.duration) * 1000);
}

function renderTimeline() {
  const d = S.info.meta.duration, s = S.settings;
  const a = (s.trim_in || 0) / d, b = (s.trim_out || d) / d;
  const z = $("#trimZone"); z.style.left = a * 100 + "%"; z.style.width = (b - a) * 100 + "%";
  const m = $("#segMarks"); m.innerHTML = "";
  renderSections(m);
  S.info.segments.forEach(([x0, x1], i) => {
    if (i > 0) { const e = document.createElement("div"); e.className = "seg-mark"; e.style.left = (x0 / d) * 100 + "%"; m.appendChild(e); }
    const l = document.createElement("div"); l.className = "seg-label"; l.style.left = (x0 / d) * 100 + "%";
    l.textContent = S.info.segments.length > 1 ? `#${i + 1}` : ""; m.appendChild(l);
  });
}

// ---------------------------------------------------------------- cortador por tramos
// sections: [[inicio, fin, usar]] cubriendo todo el clip; vacío = sin cortes (comportamiento de siempre)
function renderSections(marks) {
  const d = S.info.meta.duration, secs = S.settings.sections || [], bar = $("#secBar");
  bar.classList.toggle("hidden", !secs.length); $("#btnCutClear").classList.toggle("hidden", !secs.length);
  bar.innerHTML = "";
  secs.forEach(([a, b, on], i) => {
    if (i > 0) { const c = document.createElement("div"); c.className = "cut-mark"; c.style.left = (a / d) * 100 + "%"; marks.appendChild(c); }
    const n = (S.info.cuts || []).filter((c) => c.section === i + 1).length;
    const el = document.createElement("div");
    el.className = "sec" + (on ? "" : " off");
    el.style.left = (a / d) * 100 + "%"; el.style.width = `calc(${((b - a) / d) * 100}% - 2px)`;
    el.textContent = on ? `${i + 1} · ${(b - a).toFixed(1)} s${n > 1 ? ` → ${n} clips` : ""}` : `${i + 1} · descartado`;
    el.title = (on ? "Clic: descartar este tramo" : "Clic: usar este tramo") + " · Clic derecho: unir con el siguiente";
    el.onclick = () => { secs[i][2] = !secs[i][2]; sectionsChanged(); };
    el.oncontextmenu = (e) => {
      e.preventDefault();
      if (i + 1 >= secs.length) return;
      secs.splice(i, 2, [a, secs[i + 1][1], on || secs[i + 1][2]]);
      if (secs.length === 1) secs.length = 0;
      sectionsChanged();
    };
    bar.appendChild(el);
  });
}
function cutAt(t) {
  const d = S.info.meta.duration;
  const secs = (S.settings.sections || []).length ? S.settings.sections : [[0, d, true]];
  const i = secs.findIndex(([a, b]) => t > a + 0.3 && t < b - 0.3);
  if (i < 0) return toast("Muy cerca de otro corte o del borde");
  const [a, b, on] = secs[i], x = +t.toFixed(3);
  secs.splice(i, 1, [a, x, on], [x, b, on]);
  S.settings.sections = secs; sectionsChanged();
  toast(`Corte en ${fmt(t)} · clic en un tramo para descartarlo`);
}
async function sectionsChanged() { markManual(); renderTimeline(); await saveNow(); renderSegInfo(); renderTimeline(); renderSummaries(); }

function setMode(mode) {
  S.mode = mode;
  document.querySelectorAll("#viewMode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  view.split = mode === "after" ? 0 : mode === "before" ? 1.01 : S.split;
  $("#wipe").classList.toggle("hidden", mode !== "split");
  $("#tagBefore").classList.toggle("hidden", mode === "after");
  $("#tagAfter").classList.toggle("hidden", mode === "before");
  $("#wipe").style.left = S.split * 100 + "%";
  view.draw();
}

// ---------------------------------------------------------------- ruido al 100%
async function loadCrops() {
  const c = S.crop, q = `clip=${encodeURIComponent(S.cur)}&t=${S.t.toFixed(2)}&cx=${c.x.toFixed(3)}&cy=${c.y.toFixed(3)}`;
  const dn = S.settings.denoise === "off" ? "media" : S.settings.denoise;
  $("#cropBLabel").textContent = `Con reducción: ${S.denoiseLabels[dn]}` + (S.settings.denoise === "off" ? " (vista previa; el clip está en Apagado)" : "");
  placeCropMark();
  const [a, b] = await Promise.all([loadImage(`/api/crop?${q}&dn=off`), loadImage(`/api/crop?${q}&dn=${dn}`)]);
  cropA.setImage(a); cropB.setImage(b);
}
function placeCropMark() {
  const m = $("#cropMark"), W = S.info.meta.width, H = S.info.meta.height;
  const w = 960 / W, h = 540 / H;
  const x = Math.min(Math.max(S.crop.x - w / 2, 0), 1 - w), y = Math.min(Math.max(S.crop.y - h / 2, 0), 1 - h);
  Object.assign(m.style, { left: x * 100 + "%", top: y * 100 + "%", width: w * 100 + "%", height: h * 100 + "%" });
  m.classList.toggle("hidden", !S.noiseOpen);
}

// ---------------------------------------------------------------- exportación y cola
function openExport() {
  const box = $("#exClips"); box.innerHTML = "";
  for (const c of S.clips) {
    box.insertAdjacentHTML("beforeend", `<label class="check"><input type="checkbox" value="${c.name}" ${c.name === S.cur ? "checked" : ""}>
      ${c.name} <span class="status st-${c.settings.status}">${c.settings.status}</span>
      <span class="hint">${c.segments.length} clip${c.segments.length > 1 ? "s" : ""}</span></label>`);
  }
  const pr = $("#exPresets"); pr.innerHTML = "";
  for (const [k, label] of Object.entries(S.presets))
    pr.insertAdjacentHTML("beforeend", `<label class="check"><input type="checkbox" value="${k}" ${k === "4k_h264" ? "checked" : ""}> ${label}</label>`);
  $("#exportModal").classList.remove("hidden");
  loadExportDir();
  $("#exDirChange").onclick = (e) => { e.preventDefault(); chooseExportDir(); };
  updateExSummary();
}
function updateExSummary() {
  const clips = [...document.querySelectorAll("#exClips input:checked")].map((i) => i.value);
  const presets = [...document.querySelectorAll("#exPresets input:checked")].length;
  const files = S.clips.filter((c) => clips.includes(c.name)).reduce((n, c) => n + c.segments.length, 0) * presets;
  $("#exSummary").textContent = `${files} archivo${files === 1 ? "" : "s"} a generar`;
}

async function pollJobs() {
  try {
    const jobs = await (await api("/api/jobs")).json();
    const pending = jobs.filter((j) => ["en cola", "procesando", "estabilizando"].includes(j.status)).length;
    const b = $("#jobsBadge"); b.textContent = pending; b.classList.toggle("hidden", !pending);
    if (pending !== S.jobsPending) { S.jobsPending = pending; if (atHome()) renderHome(); }
    const list = $("#jobsList");
    list.innerHTML = jobs.length ? "" : `<div class="job hint">No hay exportaciones.</div>`;
    for (const j of jobs.slice().reverse()) {
      const pct = Math.round(j.progress * 100);
      const extra = j.status === "procesando" && j.eta != null ? ` · faltan ~${j.eta}s` : j.status === "listo" ? ` · ${j.seconds}s` : "";
      list.insertAdjacentHTML("beforeend", `<div class="job ${j.status}"><div class="jt"><b>${j.out.split("/").pop()}</b>
        <span class="hint">${j.label}</span><div class="spacer"></div><span>${j.status === "estabilizando" ? (j.stage || "estabilizando") : j.status} ${["procesando", "estabilizando"].includes(j.status) ? pct + "%" : ""}${extra}</span></div>
        <div class="bar"><div style="width:${pct}%"></div></div>${j.error ? `<pre>${j.error}</pre>` : ""}</div>`);
    }
  } catch (e) { /* servidor cerrado */ }
  setTimeout(pollJobs, 1000);
}

// ---------------------------------------------------------------- eventos
function bind() {
  buildSliders();
  const sel = $("#denoise");
  for (const [k, v] of Object.entries(S.denoiseLabels)) sel.insertAdjacentHTML("beforeend", `<option value="${k}">${v}</option>`);
  sel.onchange = async () => {
    S.settings.denoise = sel.value; markManual(); stopPlayer();
    await saveNow(); if (S.noiseOpen) loadCrops();
    if (sel.value !== "off") { api(`/api/proxy/prepare?clip=${encodeURIComponent(S.cur)}`, { method: "POST" }).catch(() => {}); watchDenoise(); }
    loadFrame();
  };

  for (const [k, v] of Object.entries(S.stabLevels)) $("#stabLevel").insertAdjacentHTML("beforeend", `<option value="${k}">${v}</option>`);
  for (const [k, v] of Object.entries(S.stabMethods)) $("#stabMethod").insertAdjacentHTML("beforeend", `<option value="${k}">${v}</option>`);
  const stabChanged = async () => {
    S.settings.stabilize = $("#stabLevel").value; S.settings.stab_method = $("#stabMethod").value;
    stopPlayer(); markManual(); await saveNow(); loadFrame();
  };
  $("#stabLevel").onchange = stabChanged;
  $("#stabMethod").onchange = stabChanged;
  $("#btnStabPreview").onclick = async () => {
    await saveNow();
    if (S.info.stab && S.info.stab.compare) return openCompare();
    S.compareWanted = S.cur;
    const info = await (await api(`/api/stabilize?clip=${encodeURIComponent(S.cur)}`, { method: "POST" })).json();
    S.info.stab = info.stab; renderStab();
  };
  $("#cmpClose").onclick = closeCompare;
  $("#stabModal").onclick = (e) => { if (e.target.id === "stabModal") closeCompare(); };
  $("#cmpGridOn").onchange = () => $("#cmpGrid").classList.toggle("hidden", !$("#cmpGridOn").checked);
  document.querySelectorAll("#cmpRate button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll("#cmpRate button").forEach((x) => x.classList.toggle("on", x === b));
    $("#cmpVideo").playbackRate = Number(b.dataset.r);
  }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#stabModal").classList.contains("hidden")) closeCompare(); });

  document.querySelectorAll("#viewMode button").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));

  // cortina antes/después
  const stage = $("#stage"); let drag = false;
  $("#wipe").onpointerdown = (e) => { drag = true; e.stopPropagation(); $("#wipe").setPointerCapture(e.pointerId); };
  $("#wipe").onpointermove = (e) => {
    if (!drag) return; const r = stage.getBoundingClientRect();
    S.split = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    $("#wipe").style.left = S.split * 100 + "%"; view.split = S.split; view.draw();
  };
  $("#wipe").onpointerup = () => (drag = false);
  stage.onclick = (e) => {
    if (S.noiseOpen) {                                   // con «Ruido al 100%» el clic elige la zona
      const r = stage.getBoundingClientRect();
      S.crop = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }; loadCrops();
      return;
    }
    // clic en el video: pausa o reanuda (salvo al trazar la línea, marcar manchas o mover la cortina)
    if (S.lineMode || S.spotMode || e.target.closest("#wipe")) return;
    const willPlay = !P.playing;
    togglePlay();
    const f = $("#playFlash");
    f.textContent = willPlay ? "▶" : "❚❚";
    f.classList.remove("show"); void f.offsetWidth; f.classList.add("show");
  };

  let scrubTimer;
  $("#scrub").oninput = (e) => {
    S.t = (e.target.value / 1000) * S.info.meta.duration; updateTime();
    if (P.playing) { P.v.currentTime = S.t; return; }
    clearTimeout(scrubTimer); scrubTimer = setTimeout(() => { loadFrame(); if (S.noiseOpen) loadCrops(); }, 120);
  };
  const step = (d) => seekTo(S.t + d);
  $("#tpPlay").onclick = togglePlay;
  $("#tpStart").onclick = () => seekTo(playRange()[0]);
  $("#tpBack").onclick = () => step(-5);
  $("#tpFwd").onclick = () => step(5);
  $("#tpLoop").onclick = () => { P.loop = !P.loop; renderTransport(); };
  $("#tpMute").onclick = () => { P.muted = !P.muted; if (P.v) P.v.muted = P.muted; renderTransport(); };
  renderTransport();
  document.onkeydown = (e) => {
    if (atHome()) return;                      // en Inicio no hay reproductor ni ajustes
    const typing = (e.target.tagName === "INPUT" && e.target.type !== "range") || e.target.tagName === "TEXTAREA";
    const mod = e.metaKey || e.ctrlKey, k = e.key.toLowerCase();
    if (mod && (k === "z" || k === "y") && !typing && [...document.querySelectorAll(".modal")].every((m) => m.classList.contains("hidden"))) {
      e.preventDefault();
      histStep(k === "y" || e.shiftKey ? 1 : -1);
      return;
    }
    if (mod) return;   // no confundir ⌘C, ⌘B… con los atajos de una letra
    if (e.target.tagName === "INPUT" && e.target.type !== "range") return;
    if (e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") return;
    if ([...document.querySelectorAll(".modal")].some((m) => !m.classList.contains("hidden"))) return;   // con una ventana abierta, sin atajos
    if (e.key === "ArrowRight") { step(e.shiftKey ? 0.1 : 1); e.preventDefault(); }
    if (e.key === "ArrowLeft") { step(e.shiftKey ? -0.1 : -1); e.preventDefault(); }
    if (e.key === " " || e.key === "k" || e.key === "K") { if (e.target.tagName === "BUTTON") e.target.blur(); togglePlay(); e.preventDefault(); }
    if (e.key === "Escape" && S.lineMode) setLineMode(false);
    if (e.key === "Escape" && S.spotMode && !S.spotBusy) setSpotMode(false);
    if (e.key === "j" || e.key === "J") step(-5);
    if (e.key === "l" || e.key === "L") step(5);
    if (e.key === "Home") { $("#tpStart").click(); e.preventDefault(); }
    if (e.key === "i" || e.key === "I") $("#btnIn").click();
    if (e.key === "c" || e.key === "C") $("#btnCut").click();
    if (e.key === "b" || e.key === "B") $("#btnSide").click();
    if (e.key === "o" || e.key === "O") $("#btnOut").click();
  };

  $("#btnIn").onclick = () => { S.settings.trim_in = +S.t.toFixed(2); scheduleSave(); renderTimeline(); toast(`Entrada en ${fmt(S.t)}`); };
  $("#btnOut").onclick = () => { S.settings.trim_out = +S.t.toFixed(2); scheduleSave(); renderTimeline(); toast(`Salida en ${fmt(S.t)}`); };
  $("#btnCut").onclick = () => cutAt(S.t);
  $("#btnCutClear").onclick = () => { S.settings.sections = []; sectionsChanged(); };
  $("#btnTrimClear").onclick = () => { S.settings.trim_in = 0; S.settings.trim_out = null; scheduleSave(); renderTimeline(); };
  const segChanged = async () => {
    const g = S.settings.segment;
    g.enabled = $("#segOn").checked;
    g.min = Math.max(3, +$("#segMin").value || 12);
    g.max = Math.max(g.min, +$("#segMax").value || 14);
    g.max_slow = parseFloat($("#segSlow").value);
    await saveNow();
  };
  for (const id of ["#segOn", "#segMin", "#segMax", "#segSlow"]) $(id).onchange = segChanged;

  $("#btnAuto").onclick = async () => {
    const name = S.cur;
    $("#btnAuto").disabled = true; $("#btnAuto").textContent = "Analizando…";
    try {
      const info = await runAuto([name], () => {});
      if (info[0] && S.cur === name) { applyInfo(info[0], true); refreshLut(); }
      toast("✦ Listo: corrección automática aplicada");
    } catch (e) { toast("Error: " + e.message); }
    $("#btnAuto").disabled = false; $("#btnAuto").textContent = "✦ Auto";
  };
  initStraighten();
  initSpots();
  initPanelSections();
  initSettings();
  $("#btnReset").onclick = () => {
    for (const k of COLOR_KEYS) S.settings[k] = 0;
    S.settings.denoise = "off"; markManual(); renderPanel(); refreshLut(); scheduleSave();
  };
  $("#btnApprove").onclick = toggleApprove;
  $("#btnCopy").onclick = () => {
    S.clipboard = Object.fromEntries([...COLOR_KEYS, "denoise"].map((k) => [k, S.settings[k]]));
    $("#btnPaste").disabled = false; toast("Ajustes copiados");
  };
  $("#btnPaste").onclick = () => {
    Object.assign(S.settings, S.clipboard); markManual(); renderPanel(); refreshLut(); scheduleSave(); toast("Ajustes pegados");
  };
  $("#btnPasteAll").onclick = async () => {
    if (!confirm("¿Aplicar el color y la reducción de ruido de este clip a TODOS los clips?")) return;
    const src = Object.fromEntries([...COLOR_KEYS, "denoise"].map((k) => [k, S.settings[k]]));
    for (const c of S.clips) {
      if (c.name === S.cur) continue;
      const s = { ...c.settings, ...src, status: "manual" };
      await api(`/api/settings?clip=${encodeURIComponent(c.name)}`, { method: "POST", body: JSON.stringify(s) });
    }
    await reloadClips(); toast("Aplicado a todos");
  };
  $("#btnAutoAll").onclick = async () => {
    // los clips que ajustaste a mano o aprobaste no se tocan
    const todo = S.clips.filter((c) => !["manual", "aprobado"].includes(c.settings.status));
    const kept = S.clips.length - todo.length;
    if (!todo.length) { toast("Todos los clips tienen ajustes tuyos o están aprobados: no hay nada que corregir"); return; }
    if (!confirm(`Corregir automáticamente ${todo.length} clip${todo.length > 1 ? "s" : ""}?` +
      (kept ? `\n${kept} con ajustes tuyos o aprobados no se tocan.` : ""))) return;
    const b = $("#btnAutoAll"); b.disabled = true;
    await runAuto(todo.map((c) => c.name), (i, n) => { b.textContent = `✦ Analizando ${i + 1}/${n}…`; });
    b.disabled = false; b.textContent = "✦ Corregir todo";
    await reloadClips(); await selectClip(S.cur);
    toast(`${todo.length} clip${todo.length > 1 ? "s" : ""} corregido${todo.length > 1 ? "s" : ""}${kept ? ` · ${kept} tuyos sin tocar` : ""}`);
  };

  $("#btnNoise").onclick = () => { S.noiseOpen = !S.noiseOpen; $("#noisePanel").classList.toggle("hidden", !S.noiseOpen); placeCropMark(); if (S.noiseOpen) loadCrops(); };
  $("#btnNoiseClose").onclick = () => $("#btnNoise").click();

  $("#btnExport").onclick = openExport;
  $("#btnBatch").onclick = openBatch;
  $("#btnUndo").onclick = () => histStep(-1);
  $("#btnRedo").onclick = () => histStep(1);
  const setSide = (mini) => {
    document.body.classList.toggle("side-mini", mini);
    try { localStorage.setItem("kanu.sideMini", mini ? "1" : ""); } catch {}
    // el visor se adapta al nuevo ancho cuando termina la animación
    setTimeout(() => window.dispatchEvent(new Event("resize")), 230);
  };
  $("#btnSide").onclick = () => setSide(!document.body.classList.contains("side-mini"));
  try { if (localStorage.getItem("kanu.sideMini")) setSide(true); } catch {}
  $("#batchCancel").onclick = () => { if (!B.busy) { B.files = B.files.filter((x) => !["listo", "ya estaba"].includes(x.status)); } $("#batchModal").classList.add("hidden"); };
  $("#batchFiles").onchange = (e) => { addBatchFiles(e.target.files); e.target.value = ""; };
  $("#batchUpload").onclick = () => runBatch(false);
  $("#bpHide").onclick = () => $("#batchModal").classList.add("hidden");
  $("#bpDone").onclick = () => { $("#batchModal").classList.add("hidden"); showProgress(false); $("#batchPill").classList.add("hidden"); };
  $("#bpBack").onclick = () => { showProgress(false); $("#batchPill").classList.add("hidden"); };
  $("#batchPill").onclick = () => { showProgress(true); $("#batchModal").classList.remove("hidden"); };
  // si se recarga la página con una tanda en marcha, retomar el avance
  api("/api/batch").then((r) => r.json()).then((d) => { if (d.state.running) { BP.phase = "process"; watchBatch(); } }).catch(() => {});
  $("#batchGo").onclick = () => runBatch(true);
  const dz = $("#dropZone");
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("over"); };
  dz.ondragleave = () => dz.classList.remove("over");
  dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("over"); addBatchFiles(e.dataTransfer.files); };
  // soltar videos en cualquier parte del editor abre la tanda (y evita que el navegador los abra)
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", async (e) => {
    e.preventDefault();
    if (e.target.closest && (e.target.closest("#dropZone") || e.target.closest("#settingsModal"))) return;
    if (e.dataTransfer.files.length) { await openBatch(); addBatchFiles(e.dataTransfer.files); }
  });
  $("#brand").onclick = () => $("#iconModal").classList.remove("hidden");
  $("#iconModal").onclick = () => $("#iconModal").classList.add("hidden");
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    $("#iconModal").classList.add("hidden");
    if (!B.busy) $("#batchModal").classList.add("hidden");
    $("#settingsModal").classList.add("hidden");
  });
  $("#exCancel").onclick = () => $("#exportModal").classList.add("hidden");
  $("#exportModal").onchange = updateExSummary;
  const setAll = (fn) => { document.querySelectorAll("#exClips input").forEach((i) => (i.checked = fn(i.value))); updateExSummary(); };
  // "Todos" alterna: si ya están todos marcados, los desmarca
  $("#exAll").onclick = () => { const all = [...document.querySelectorAll("#exClips input")].every((i) => i.checked); setAll(() => !all); };
  $("#exNone").onclick = () => setAll(() => false);
  $("#exApproved").onclick = () => setAll((n) => S.clips.find((c) => c.name === n).settings.status === "aprobado");
  $("#exGo").onclick = async () => {
    const clips = [...document.querySelectorAll("#exClips input:checked")].map((i) => i.value);
    const presets = [...document.querySelectorAll("#exPresets input:checked")].map((i) => i.value);
    if (!clips.length || !presets.length) return toast("Elige al menos un clip y un formato");
    clearTimeout(saveTimer);
    await api(`/api/settings?clip=${encodeURIComponent(S.cur)}`, { method: "POST", body: JSON.stringify(S.settings) });
    const r = await (await api("/api/export", { method: "POST", body: JSON.stringify({ clips, presets, audio: $("#exAudio").checked, upload: $("#exUpload").checked }) })).json();
    $("#exportModal").classList.add("hidden"); $("#jobsDrawer").classList.remove("hidden");
    toast(`${r.added} archivos en cola`);
  };
  $("#btnJobs").onclick = () => $("#jobsDrawer").classList.toggle("hidden");
  $("#jbClose").onclick = () => $("#jobsDrawer").classList.add("hidden");
  $("#jbClear").onclick = () => api("/api/jobs/clear", { method: "POST" });
  $("#jbCancel").onclick = () => api("/api/jobs/cancel", { method: "POST" });
  $("#jbOpen").onclick = () => api("/api/open-exports", { method: "POST" });
  $("#jbCache").onclick = async () => {
    const gb = ((await (await api("/api/cache")).json()).bytes / 1e9).toFixed(1);
    if (!confirm(`¿Borrar ${gb} GB de archivos temporales (versiones estabilizadas y fotogramas)?\nLos videos originales y los exportados no se tocan; se regeneran solos si hacen falta.`)) return;
    try { const r = await (await api("/api/cache/clean", { method: "POST" })).json(); toast(`Liberados ${(r.freed / 1e9).toFixed(1)} GB`); await selectClip(S.cur); }
    catch (e) { toast(e.message); }
  };
}

// ---------------------------------------------------------------- nueva tanda (subir videos + indicaciones)
const B = { files: [], busy: false, timer: null };
const VIDEO_RE = /\.(mp4|mov|mxf|m4v)$/i;
const fmtSize = (n) => (n >= 1e9 ? (n / 1e9).toFixed(1) + " GB" : Math.max(1, Math.round(n / 1e6)) + " MB");
async function openBatch() {
  const d = await (await api("/api/batch")).json();
  const box = $("#batchOpts");
  if (!box.children.length) {
    for (const [k, label] of Object.entries(d.options))
      box.insertAdjacentHTML("beforeend", `<label class="opt-chip"><input type="checkbox" value="${k}">${label}</label>`);
    box.querySelectorAll("input").forEach((i) => (i.onchange = () => i.parentElement.classList.toggle("on", i.checked)));
  }
  if (d.state.running) { BP.phase = "process"; renderBatchState(d.state); watchBatch(); }
  else if (!B.busy && !BP.phase) showProgress(false);           // tanda nueva: formulario limpio
  renderBatchFiles();
  $("#batchModal").classList.remove("hidden");
}
function addBatchFiles(list) {
  let skipped = 0;
  for (const f of list) {
    if (!VIDEO_RE.test(f.name)) { skipped++; continue; }
    if (B.files.some((x) => x.file.name === f.name && x.file.size === f.size)) continue;
    B.files.push({ file: f, name: f.name, prog: 0, status: "" });
  }
  if (skipped) toast(`${skipped} archivo${skipped > 1 ? "s" : ""} no son video y no se agregaron`);
  renderBatchFiles();
}
function renderBatchFiles() {
  const box = $("#batchList"); box.innerHTML = "";
  B.files.forEach((it, i) => {
    const row = document.createElement("div");
    row.className = "bf" + (it.status === "listo" || it.status === "ya estaba" ? " done" : "") + (it.status.startsWith("error") ? " err" : "");
    row.innerHTML = `<span>${it.name}</span><span class="hint">${fmtSize(it.file.size)}</span>
      <span>${it.status && it.status !== "subiendo" ? it.status : `<div class="bar"><div style="width:${Math.round(it.prog * 100)}%"></div></div>`}</span>
      <span class="x" title="Quitar">${B.busy ? "" : "✕"}</span>`;
    row.querySelector(".x").onclick = () => { if (!B.busy) { B.files.splice(i, 1); renderBatchFiles(); } };
    box.appendChild(row);
  });
  const total = B.files.reduce((n, x) => n + x.file.size, 0);
  $("#batchSummary").textContent = B.files.length ? `${B.files.length} video${B.files.length > 1 ? "s" : ""} · ${fmtSize(total)}` : "";
  $("#batchGo").disabled = $("#batchUpload").disabled = B.busy || !B.files.length;
}
function uploadOne(it) {
  return new Promise((res, rej) => {
    const x = new XMLHttpRequest();
    x.open("PUT", `/api/upload?name=${encodeURIComponent(it.file.name)}${it.dest ? "&dest=" + it.dest : ""}`);
    x.upload.onprogress = (e) => { if (e.lengthComputable) { it.prog = e.loaded / e.total; renderBatchProgress(it); it.onprog && it.onprog(); } };
    x.onload = () => { const r = JSON.parse(x.responseText || "{}"); x.status < 300 ? res(r) : rej(new Error(r.error || x.statusText)); };
    x.onerror = () => rej(new Error("se cortó la conexión"));
    x.send(it.file);
  });
}
function renderBatchProgress(it) {
  const i = B.files.indexOf(it), bar = $("#batchList").children[i]?.querySelector(".bar div");
  if (bar) bar.style.width = Math.round(it.prog * 100) + "%";
}
// avance: una sola vista para subir, corregir y exportar; también como pastilla en el encabezado
const BP = { phase: null };
function showProgress(on) {
  $("#batchProgress").classList.toggle("hidden", !on);
  $("#batchForm").classList.toggle("hidden", on);
}
function setProgress({ title, stage = "", detail = "", frac = 0, done = false, error = null }) {
  showProgress(true);
  const box = $("#batchProgress");
  box.classList.toggle("done", done); box.classList.toggle("err", !!error);
  $("#bpTitle").textContent = title; $("#bpStage").textContent = stage; $("#bpDetail").textContent = detail;
  $("#bpBar").style.width = Math.round(Math.min(1, Math.max(0, frac)) * 100) + "%";
  $("#bpError").classList.toggle("hidden", !error); $("#bpError").textContent = error || "";
  $("#bpHide").classList.toggle("hidden", done || !!error);
  $("#bpDone").classList.toggle("hidden", !done);
  $("#bpBack").classList.toggle("hidden", !error);
  const pill = $("#batchPill");
  pill.classList.toggle("hidden", !!error && !BP.phase);
  pill.classList.toggle("done", done);
  $("#batchPillTxt").textContent = done ? "Tanda lista ✓" : error ? "Error en la tanda"
    : `${BP.phase === "upload" ? "Subiendo" : "Tanda"} · ${Math.round(frac * 100)} %`;
}
async function runBatch(process) {
  B.busy = true; BP.phase = "upload"; renderBatchFiles();
  const names = [], todo = B.files.filter((x) => !["listo", "ya estaba"].includes(x.status));
  const total = todo.reduce((n, x) => n + x.file.size, 0) || 1;
  let sent = 0, i = 0;
  for (const it of B.files) {
    if (it.status === "listo" || it.status === "ya estaba") { names.push(it.name); continue; }
    i++;
    it.status = "subiendo";
    const tick = () => setProgress({ title: "Subiendo videos…", stage: `${i} de ${todo.length} · ${it.file.name}`,
      detail: `${fmtSize(sent + it.prog * it.file.size)} de ${fmtSize(total)}`, frac: (sent + it.prog * it.file.size) / total });
    it.onprog = tick; tick();
    try {
      const r = await uploadOne(it);
      it.name = r.name; it.status = r.skipped ? "ya estaba" : "listo"; names.push(r.name);
    } catch (e) { it.status = "error: " + e.message; }
    sent += it.file.size;
  }
  await reloadClips();
  const failed = B.files.filter((x) => x.status.startsWith("error"));
  if (!names.length) {
    B.busy = false; BP.phase = null; renderBatchFiles();
    setProgress({ title: "No se pudo subir", error: failed.map((x) => `${x.name}: ${x.status.slice(7)}`).join(" · ") || "No había videos para subir" });
    return;
  }
  const options = { min: +$("#batchMin").value || 12, max: +$("#batchMax").value || 14 };
  $("#batchOpts").querySelectorAll("input").forEach((x) => (options[x.value] = x.checked));
  try {
    const info = await (await api("/api/batch", { method: "POST", body: JSON.stringify({ clips: names, options, process,
      note: $("#batchNote").value.trim(), title: $("#batchTitle").value.trim() }) })).json();
    S.openGroups.add("t:" + info.id); saveOpenGroups();
    await reloadClips();
    if (process) { BP.phase = "process"; setProgress({ title: "Preparando la tanda…", stage: info.title, frac: 0.02 }); watchBatch(); }
    else {
      BP.phase = null;
      setProgress({ title: "Videos subidos", stage: `${names.length} en «${info.title}»`, detail: failed.length ? `${failed.length} con error` : "",
        frac: 1, done: true });
    }
    B.files = [];
  } catch (e) {
    BP.phase = null;
    setProgress({ title: "Los videos se subieron, pero no se pudo procesar", error: e.message });
  }
  B.busy = false; renderBatchFiles();
  if (!S.cur && names.length) await selectClip(names[0]);
}
function renderBatchState(st) {
  const el = $("#batchState");
  if (!st || !st.id) { el.textContent = ""; return; }
  el.textContent = st.running ? `«${st.title}» en proceso` : st.stage === "error" ? `«${st.title}»: error` : `«${st.title}»: lista ✓`;
  if (!st.running && BP.phase !== "process") return;
  // corregir ≈ 25 % del tiempo, exportar el resto
  if (st.running && st.stage !== "exportando")
    setProgress({ title: "Corrigiendo color, ruido y enderezado…", stage: st.stage.replace("corrigiendo ", ""),
      detail: `${st.done + 1} de ${st.total}`, frac: 0.03 + 0.22 * (st.done / Math.max(1, st.total)) });
  else if (st.running)
    setProgress({ title: "Estabilizando y exportando en 4K…", stage: `${st.done} de ${st.total} clips listos`,
      detail: "Puedes seguir trabajando: el avance se ve arriba", frac: 0.25 + 0.75 * (st.done / Math.max(1, st.total)) });
  else if (st.stage === "error") setProgress({ title: "La tanda se detuvo", error: st.error || "Error desconocido" });
  else setProgress({ title: "¡Tanda lista!", stage: `${st.total} clip${st.total > 1 ? "s" : ""} en «${folderName(S.exportDir) || "videos subir"}»`,
      detail: st.errors ? `${st.errors} con error: revisa la Cola` : "Revísalos en la lista de la izquierda", frac: 1, done: true });
}
function watchBatch() {
  if (B.timer) return;
  const poll = async () => {
    let st;
    try { st = (await (await api("/api/batch")).json()).state; } catch { return; }
    renderBatchState(st);
    if (!st.running) {
      clearInterval(B.timer); B.timer = null; BP.phase = null;
      await reloadClips(); if (S.cur) await selectClip(S.cur);
      if (st.stage === "listo") toast(`Tanda «${st.title}» lista en «${folderName(S.exportDir) || "videos subir"}»`, 5000);
    }
  };
  B.timer = setInterval(poll, 1500); poll();
}

// ---------------------------------------------------------------- panel en secciones plegables
// Cada título del panel abre o cierra su sección; cerrada, muestra un resumen del ajuste.
const PANEL_OPEN_DEFAULT = ["Enderezar", "Luz", "Color"];
function initPanelSections() {
  const panel = $("#panel");
  let saved = null; try { saved = JSON.parse(localStorage.getItem("kanu.panel") || "null"); } catch {}
  for (const h of [...panel.querySelectorAll(":scope > h3")]) {
    const key = h.firstChild.textContent.trim();
    const sec = document.createElement("section");
    sec.className = "pnl"; sec.dataset.k = key;
    h.before(sec);
    const body = document.createElement("div"); body.className = "pnl-body";
    let n = h.nextSibling;
    while (n && !(n.nodeType === 1 && n.tagName === "H3")) { const next = n.nextSibling; body.appendChild(n); n = next; }
    h.classList.add("pnl-head");
    h.insertAdjacentHTML("afterbegin", '<span class="chev">▸</span>');
    const sum = document.createElement("span"); sum.className = "pnl-sum";
    const btn = h.querySelector("button");
    btn ? btn.before(sum) : h.appendChild(sum);
    sec.append(h, body);
    const open = saved ? saved.includes(key) : PANEL_OPEN_DEFAULT.includes(key);
    sec.classList.toggle("open", open);
    h.onclick = (e) => {
      if (e.target.closest("button")) return;
      sec.classList.toggle("open");
      try { localStorage.setItem("kanu.panel", JSON.stringify([...panel.querySelectorAll(".pnl.open")].map((s) => s.dataset.k))); } catch {}
    };
  }
  panel.addEventListener("input", () => requestAnimationFrame(renderSummaries));
  panel.addEventListener("change", () => requestAnimationFrame(renderSummaries));
}
function renderSummaries() {
  if (!S.info || !S.settings) return;
  const s = S.settings, set = (k, txt) => { const e = document.querySelector(`.pnl[data-k="${k}"] .pnl-sum`); if (e) e.textContent = txt; };
  const changed = (k) => document.querySelectorAll(`.pnl[data-k="${k}"] .sl-top .v.changed`).length;
  const r = +s.rotate || 0;
  set("Enderezar", Math.abs(r) > 0.001 ? `${r > 0 ? "+" : ""}${r.toFixed(1)}°` : "derecho");
  set("Manchas del sensor", (s.spots || []).length ? `${s.spots.length} marcada${s.spots.length > 1 ? "s" : ""}` : "ninguna");
  for (const k of ["Luz", "Color"]) { const n = changed(k); set(k, n ? `${n} ajuste${n > 1 ? "s" : ""}` : "sin cambios"); }
  const hs = HSL.filter(([c]) => ["h", "s", "l"].some((p) => Math.abs(s[`hsl_${c}_${p}`] || 0) > 1e-6)).map(([, l]) => l.toLowerCase());
  set("Por color", hs.length ? (hs.length > 2 ? `${hs.length} gamas` : hs.join(" y ")) : "sin cambios");
  const zs = ZONES.filter(([z]) => (s[`zone_${z}_sat`] || 0) > 0).map(([, l]) => l.toLowerCase());
  set("Por zonas", zs.length ? zs.join(", ") : "sin cambios");
  set("Ruido", S.denoiseLabels[s.denoise] || s.denoise);
  const n = S.info.segments.length;
  set("Cortes para stock", `${n} clip${n > 1 ? "s" : ""} de ${S.info.plan.clip_len.toFixed(1)} s`);
  set("Estabilización", (S.stabLevels || {})[s.stabilize] || s.stabilize);
}

// ---------------------------------------------------------------- carpeta de exportación
const shortPath = (p) => (p || "").replace(/^\/Users\/[^/]+/, "~");
const folderName = (p) => (p || "").replace(/\/+$/, "").split("/").pop() || p;
function renderExportDir(d) {
  if (!d || d.error) return;
  S.exportDir = d.path;
  const el = $("#setExDir");
  if (el) { el.innerHTML = `<span dir="ltr">${esc(shortPath(d.path))}</span>`; el.title = d.path; }
  $("#setExReset")?.classList.toggle("hidden", !d.custom);
  const nm = $("#exDirName");
  if (nm) { nm.textContent = folderName(d.path); nm.title = d.path; }
}
async function refreshHome() {
  if (!document.body.classList.contains("at-home")) return;
  try { HM.data = await (await api("/api/home")).json(); renderHome(); } catch { /* sin datos */ }
}
async function loadExportDir() { renderExportDir(await (await api("/api/export-dir")).json()); }
async function chooseExportDir() {
  toast("Elige la carpeta en la ventana de Mac…", 2500);
  const r = await api("/api/export-dir/choose", { method: "POST" });
  const d = await r.json();
  if (!r.ok) { toast(d.error || "No se pudo cambiar la carpeta", 4000); return; }
  renderExportDir(d);
  if (!d.cancelled) toast(`Los finales se guardarán en «${folderName(d.path)}»`, 3500);
  refreshHome();
}

// ---------------------------------------------------------------- ajustes: mi estilo de color
const ST = { timer: null };
async function openSettings() {
  loadExportDir();
  renderStyle(await (await api("/api/style")).json());
  $("#settingsModal").classList.remove("hidden");
}
function renderStyle(d) {
  const box = $("#setPairs");
  box.innerHTML = d.pairs.length ? "" : '<div class="hint">Todavía no hay pares.</div>';
  for (const p of d.pairs) {
    const st = p.error ? '<span class="bad" title="' + p.error.replace(/"/g, "'") + '">no se pudo leer</span>'
      : !p.editado ? '<span class="no">falta el editado</span>'
      : p.learned ? '<span class="yes">✓ aprendido</span>' : `<span class="no">listo para aprender${p.original ? "" : " (solo final)"}</span>`;
    const row = document.createElement("div"); row.className = "pair";
    row.innerHTML = `<span>${p.name}</span><span class="${p.original ? "yes" : "no"}">${p.original ? "✓ original" : "— sin original"}</span>
      <span class="${p.editado ? "yes" : "no"}">${p.editado ? "✓ editado" : "— editado"}</span>${st}<span class="x" title="Quitar este par">✕</span>`;
    row.querySelector(".x").onclick = async () => {
      if (!confirm(`¿Quitar el par «${p.name}»?`)) return;
      renderStyle(await (await api(`/api/style/delete?name=${encodeURIComponent(p.name)}`, { method: "POST" })).json());
    };
    box.appendChild(row);
  }
  const complete = d.pairs.filter((p) => p.editado).length + (d.config.kanu ? d.kanu_clips.length : 0), s = d.state;
  $("#setKanu").checked = d.config.kanu;
  $("#setKanuTxt").textContent = d.kanu_clips.length
    ? `${d.kanu_clips.length} clip${d.kanu_clips.length > 1 ? "s" : ""} ajustado${d.kanu_clips.length > 1 ? "s" : ""} a mano: ${d.kanu_clips.map((n) => n.replace(/\.[^.]+$/, "")).join(", ")}`
    : "Todavía no ajustaste clips a mano.";
  $("#setLearn").disabled = s.running || !complete;
  $("#setLearn").textContent = d.learned ? "✦ Volver a aprender" : "✦ Aprender mi estilo";
  $("#setLearnBar").classList.toggle("hidden", !s.running);
  $("#setLearnBar").firstElementChild.style.width = Math.round(100 * s.done / Math.max(1, s.total)) + "%";
  $("#setLearnTxt").textContent = s.running ? `Aprendiendo ${s.done + 1} de ${s.total} · ${s.stage} (unos 20 s por video)`
    : s.error ? "Error: " + s.error
    : d.learned ? `Aprendido de ${d.learned} ejemplo${d.learned > 1 ? "s" : ""}${d.kanu_learned ? ` (${d.kanu_learned} de tus ajustes en Kanu)` : ""} · ${d.date}${complete > d.learned ? ` · hay ${complete - d.learned} par(es) nuevos: vuelve a aprender` : ""}`
    : complete ? `${complete} ejemplo${complete > 1 ? "s" : ""} listo${complete > 1 ? "s" : ""}. Pulsa Aprender.` : "Sube videos editados o ajusta clips a mano en Kanu.";
  $("#setEnabled").checked = d.config.enabled && d.learned > 0; $("#setEnabled").disabled = !d.learned;
  $("#setLut").checked = d.config.lut; $("#setLut").disabled = !d.has_lut;
  $("#setLutName").textContent = d.has_lut ? "lut.cube ✓ (subir otra)" : "Subir .cube";
  if (s.running && !ST.timer) ST.timer = setInterval(async () => {
    const n = await (await api("/api/style")).json(); renderStyle(n);
    if (!n.state.running) { clearInterval(ST.timer); ST.timer = null; toast(n.state.error ? "No se pudo aprender el estilo" : `Estilo aprendido de ${n.learned} videos`); }
  }, 1500);
}
async function uploadStyle(files, dest) {
  const list = [...files].filter((f) => dest === "estilo_lut" ? /\.cube$/i.test(f.name) : VIDEO_RE.test(f.name));
  if (!list.length) { toast(dest === "estilo_lut" ? "Elige un archivo .cube" : "Elige archivos de video"); return; }
  const total = list.reduce((n, f) => n + f.size, 0) || 1; let sent = 0;
  for (const [i, f] of list.entries()) {
    const it = { file: f, dest, prog: 0 };
    it.onprog = () => ($("#setUpload").textContent = `Subiendo ${i + 1} de ${list.length} · ${f.name} · ${Math.round(100 * (sent + it.prog * f.size) / total)} %`);
    try { await uploadOne(it); } catch (e) { toast(`${f.name}: ${e.message}`); }
    sent += f.size;
  }
  $("#setUpload").textContent = `✓ ${list.length} archivo${list.length > 1 ? "s" : ""} subido${list.length > 1 ? "s" : ""}`;
  if (dest === "estilo_lut") await api("/api/style/config", { method: "POST", body: JSON.stringify({ lut: true }) });
  renderStyle(await (await api("/api/style")).json());
  if (dest === "estilo_lut") { refreshLut(); }
}
function initSettings() {
  $("#btnSettings").onclick = openSettings;
  $("#setClose").onclick = () => $("#settingsModal").classList.add("hidden");
  $("#setExChoose").onclick = chooseExportDir;
  $("#setExOpen").onclick = () => api("/api/open-exports", { method: "POST" });
  $("#setExReset").onclick = async () => {
    renderExportDir(await (await api("/api/export-dir/reset", { method: "POST" })).json());
    toast("Los finales vuelven a «videos subir»", 3000);
    refreshHome();
  };
  document.querySelectorAll("#settingsModal .drop-zone").forEach((dz) => {
    const inp = dz.querySelector("input");
    inp.onchange = () => { uploadStyle(inp.files, dz.dataset.dest); inp.value = ""; };
    dz.ondragover = (e) => { e.preventDefault(); e.stopPropagation(); dz.classList.add("over"); };
    dz.ondragleave = () => dz.classList.remove("over");
    dz.ondrop = (e) => { e.preventDefault(); e.stopPropagation(); dz.classList.remove("over"); uploadStyle(e.dataTransfer.files, dz.dataset.dest); };
  });
  $("#setLearn").onclick = async () => renderStyle(await (await api("/api/style/learn", { method: "POST" })).json());
  const cfg = async (o) => { renderStyle(await (await api("/api/style/config", { method: "POST", body: JSON.stringify(o) })).json()); };
  $("#setEnabled").onchange = () => cfg({ enabled: $("#setEnabled").checked });
  $("#setKanu").onchange = () => cfg({ kanu: $("#setKanu").checked });
  $("#setLut").onchange = async () => { await cfg({ lut: $("#setLut").checked }); refreshLut(); };
  $("#setWipe").onclick = async () => {
    if (!confirm("¿Borrar todo tu estilo? Se eliminan tus pares, lo aprendido y tu LUT. No se puede deshacer.\nTus videos de trabajo y los finales no se tocan.")) return;
    renderStyle(await (await api("/api/style/delete?all=1", { method: "POST" })).json()); refreshLut(); toast("Estilo borrado");
  };
}

async function reloadClips() {
  const d = await (await api("/api/clips")).json();
  S.clips = d.clips; S.presets = d.presets; S.denoiseLabels = d.denoise;
  S.stabLevels = d.stab_levels; S.stabMethods = d.stab_methods; S.stabAvailable = d.stab_available;
  renderClipList();
  if (atHome()) renderHome();
  return d;
}

// ---------------------------------------------------------------- inicio
const HM = { data: null, tip: 0, tipTimer: null, heroFor: null };
const atHome = () => document.body.classList.contains("at-home");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
const thumbUrl = (c, w = 320) => `/api/frame?clip=${encodeURIComponent(c.name)}&t=${(c.meta.duration * 0.4).toFixed(2)}&w=${w}`;
const ago = (sec) => {
  const d = Date.now() / 1000 - sec;
  if (d < 60) return "ahora"; if (d < 3600) return `hace ${Math.round(d / 60)} min`;
  if (d < 86400) return `hace ${Math.round(d / 3600)} h`; return `hace ${plural(Math.round(d / 86400), "día")}`;
};
const TIPS = [
  ["✦", "Corrige todo de una vez", "<b>✦ Corregir todo</b> analiza cada clip y aplica color natural, ruido, estabilización y horizonte. Los que ajustaste a mano no se tocan."],
  ["⇆", "Antes y después", "En el visor elige <b>Dividido</b> y arrastra la línea para comparar el original con la corrección."],
  ["⌨", "Atajos del reproductor", "<kbd>Espacio</kbd> o <kbd>K</kbd> reproduce, <kbd>J</kbd> / <kbd>L</kbd> saltan 5 s y <kbd>←</kbd> <kbd>→</kbd> mueven 1 s."],
  ["📐", "Horizonte torcido", "En <b>Enderezar</b> usa <b>Trazar línea recta</b> sobre un edificio o el horizonte y el clip se gira solo."],
  ["◎", "Manchas del sensor", "¿Un punto oscuro en el mismo sitio de todo el video? Márcalo en <b>Manchas del sensor</b> y Kanu le devuelve la luz."],
  ["↺", "Deshacer sin miedo", "<kbd>⌘</kbd> <kbd>Z</kbd> deshace cualquier ajuste y <kbd>⌘</kbd> <kbd>⇧</kbd> <kbd>Z</kbd> lo rehace. Doble clic en un control lo pone en 0."],
  ["🎞", "Un clip más por toma", "Si ralentizar un poco permite sacar otro clip de 12 a 14 s, Kanu lo hace sin inventar fotogramas."],
  ["🎨", "Tu propio estilo", "En <b>Ajustes</b> sube pares de antes y después editados por ti y Kanu aprende tu forma de corregir el color."],
];

function groupsOf(clips) {
  const m = new Map();
  for (const c of clips) {
    const g = c.group || { id: "x", title: "Videos", sub: "", sort: "" };
    if (!m.has(g.id)) m.set(g.id, { ...g, clips: [] });
    m.get(g.id).clips.push(c);
  }
  return [...m.values()].sort((a, b) => (a.sort < b.sort ? 1 : -1));
}

function renderHome() {
  const clips = S.clips || [], groups = groupsOf(clips), d = HM.data || { finals: { count: 0, bytes: 0, latest: [] } };
  const ok = clips.filter((c) => c.settings.status === "aprobado").length;
  const empty = !clips.length;
  const h = new Date().getHours();
  $("#homeHello").textContent = h < 12 ? "Buenos días" : h < 19 ? "Buenas tardes" : "Buenas noches";
  $("#homeTitle").innerHTML = empty ? "Bienvenido a Kanu" : "¿Qué preparamos hoy<br>para stock?";
  $("#homeLead").textContent = empty
    ? "Tú sales a grabar. Sube tu primera tanda y Kanu se encarga del resto: color, ruido, estabilización, cortes y exportación en 4K."
    : `Tienes ${plural(clips.length, "video")} en ${plural(groups.length, "tanda")}` +
      (ok ? `, ${plural(ok, "aprobado")}` : "") +
      (d.finals.count ? ` y ${plural(d.finals.count, "final listo", "finales listos")} para subir.` : ".");

  // seguir editando: el último clip que tocaste
  const last = clips.find((c) => c.name === (S.cur || d.last_edited));
  const cont = $("#homeContinue");
  cont.classList.toggle("hidden", !last);
  if (last) {
    cont.innerHTML = `<img src="${thumbUrl(last)}" alt=""><span>Seguir con <b>${esc(last.name.replace(/\.[^.]+$/, ""))}</b><br><small>${esc(last.group?.title || "")}</small></span>`;
    cont.onclick = () => openClip(last.name);
    if (HM.heroFor !== last.name) {                        // fondo: un fotograma grande de ese clip
      HM.heroFor = last.name;
      const bg = $("#heroBg"); bg.classList.remove("on");
      const src = thumbUrl(last, 1600);
      loadImage(src).then(() => { bg.style.backgroundImage = `url("${src}")`; bg.classList.add("on"); }).catch(() => {});
    }
  }

  const pending = S.jobsPending || 0;
  const pct = clips.length ? Math.round((ok / clips.length) * 100) : 0;
  $("#homeStats").innerHTML = `
    <div class="stat"><div class="v">${clips.length}</div><div class="l">${clips.length === 1 ? "video" : "videos"} en ${plural(groups.length, "tanda")}</div></div>
    <div class="stat ok"><div class="v">${ok}<span class="hint" style="font-size:14px;font-weight:500"> / ${clips.length}</span></div><div class="l">aprobados</div><div class="bar"><div style="width:${pct}%"></div></div></div>
    <div class="stat"><div class="v">${d.finals.count}</div><div class="l">finales listos · ${d.finals.bytes ? fmtSize(d.finals.bytes) : "0 MB"}</div></div>
    <div class="stat"><div class="v" id="statQueue">${pending}</div><div class="l">${pending ? "exportando ahora" : "en la cola · todo al día"}</div></div>`;

  $("#homeStats").classList.toggle("hidden", empty);
  $("#homeGyro").classList.toggle("hidden", S.stabAvailable !== false);
  $("#homeSteps").classList.toggle("hidden", !empty);
  $("#homeTandasSec").classList.toggle("hidden", empty);
  $("#homeTandasHint").textContent = groups.length ? `${plural(groups.length, "tanda")} · la más reciente primero` : "";

  const box = $("#homeTandas"); box.innerHTML = "";
  for (const g of groups) {
    const okG = g.clips.filter((c) => c.settings.status === "aprobado").length;
    const man = g.clips.filter((c) => c.settings.status === "manual").length;
    const pics = g.clips.slice(0, 3);
    const card = document.createElement("button");
    card.className = "tanda";
    card.innerHTML = `<div class="mosaic${pics.length < 3 ? " one" : ""}">${(pics.length < 3 ? pics.slice(0, 1) : pics)
        .map((c, i) => `<img loading="lazy" src="${thumbUrl(c, i ? 320 : 640)}" alt="">`).join("")}</div>
      <div class="info"><div class="nm" title="${esc(g.title)}">${esc(g.title)}</div>
        <div class="sub">${plural(g.clips.length, "video")}${g.sub ? " · " + esc(g.sub) : ""}${man ? ` · ${plural(man, "ajustado a mano", "ajustados a mano")}` : ""}</div>
        <div class="prog"><div class="bar"><div style="width:${Math.round((okG / g.clips.length) * 100)}%"></div></div>${okG}/${g.clips.length} aprobados</div></div>`;
    card.onclick = () => {
      S.openGroups.add(g.id); S.closedByUser?.delete(g.id); saveOpenGroups();
      openClip((g.clips.find((c) => c.settings.status !== "aprobado") || g.clips[0]).name);
    };
    box.appendChild(card);
  }

  const fin = $("#homeFinals");
  fin.innerHTML = d.finals.latest.length
    ? d.finals.latest.map((f) => `<div class="final"><span class="dot"></span><span class="nm">${esc(f.name)}</span>
        <span class="hint">${fmtSize(f.bytes)} · ${ago(f.mtime)}</span></div>`).join("") +
      (d.finals.count > d.finals.latest.length ? `<div class="more">y ${plural(d.finals.count - d.finals.latest.length, "más", "más")} en <b title="${esc(d.export_dir || "")}">${esc(folderName(d.export_dir) || "videos subir")}</b></div>` : "")
    : `<div class="final hint">Aún no hay finales. Cuando exportes, aparecen aquí listos para subir al banco de stock.</div>`;
  if (d.export_dir) S.exportDir = d.export_dir;
  $("#homeVersion").textContent = `Kanu ${d.version || ""}`.trim();
}

function showTip(i, animate = true) {
  HM.tip = (i + TIPS.length) % TIPS.length;
  const [ic, t, body] = TIPS[HM.tip], el = $("#homeTip");
  el.innerHTML = `<span class="ti">${ic}</span><div class="tb"><b>${t}</b><span>${body}</span></div>`;
  if (animate) { el.classList.remove("swap"); void el.offsetWidth; el.classList.add("swap"); }
  $("#tipDots").innerHTML = TIPS.map((_, j) => `<button class="${j === HM.tip ? "on" : ""}" data-i="${j}" aria-label="Consejo ${j + 1}"></button>`).join("");
  clearTimeout(HM.tipTimer);
  HM.tipTimer = setTimeout(() => atHome() && showTip(HM.tip + 1), 9000);
}

async function showHome() {
  stopPlayer();
  document.body.classList.add("at-home");
  $("#home").classList.remove("hidden");
  $("#home").scrollTop = 0;
  try { HM.data = await (await api("/api/home")).json(); } catch { /* sin datos extra */ }
  renderHome();
  showTip(HM.tip, false);
}

function showEditor() {
  document.body.classList.remove("at-home");
  $("#home").classList.add("hidden");
  clearTimeout(HM.tipTimer);
}

async function openClip(name) {
  showEditor();
  if (name !== S.cur) await selectClip(name); else renderClipList();
}

function initHome() {
  $("#btnHome").onclick = () => (atHome() ? showEditor() : showHome());
  $("#homeUpload").onclick = openBatch;
  $("#homeOpenFinals").onclick = () => api("/api/open-exports", { method: "POST" });
  $("#homeToucan").onclick = $("#homeAbout").onclick = (e) => { e.preventDefault(); $("#iconModal").classList.remove("hidden"); };
  $("#tipDots").onclick = (e) => { const i = e.target.dataset?.i; if (i != null) showTip(+i); };
}

(async function init() {
  await reloadClips();
  bind();
  initHome();
  setMode("after");
  const home = showHome();                     // Kanu abre en Inicio; el editor se prepara detrás
  await home;
  if (S.clips.length) await selectClip(S.clips.find((c) => c.name === HM.data?.last_edited)?.name || S.clips[0].name);
  else {
    $("#clipName").textContent = "Sin videos todavía";
    $("#clipList").innerHTML = `<div class="empty"><div class="empty-ic">⇪</div><b>Aún no hay videos</b>
      <span class="hint">Sube tu primera tanda o suelta los archivos aquí.</span>
      <button class="primary" id="emptyUpload">Subir videos</button></div>`;
    $("#emptyUpload").onclick = openBatch;
  }
  pollJobs();
})();
