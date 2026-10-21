/* BookIt single-page frontend. Plain JS: hash router + fetch() against the DRF API. */
"use strict";

// ---------- helpers ----------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (name, cls = "") => `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const mondayOf = (d) => { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate()); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; };
const hm = (mins) => `${pad(Math.floor(mins / 60))}:${pad(mins % 60)}`;
const fmtTime = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
const fmtDay = (iso) => new Date(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
const sameDay = (a, b) => ymd(a) === ymd(b);
function relDay(iso) {
  const d = new Date(iso);
  const today = new Date();
  if (sameDay(d, today)) return "Today";
  if (sameDay(d, addDays(today, 1))) return "Tomorrow";
  if (sameDay(d, addDays(today, -1))) return "Yesterday";
  return fmtDay(iso);
}
function timeAgo(ts) {
  const s = (Date.now() - Date.parse(ts)) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

const OPEN = 8;
const CLOSE = 20;
const HOUR_PX = 44; // keep in sync with --hour in bookit.css

const STATUS_ICON = { pending: "clock", approved: "ok", checked_out: "box", returned: "ok", rejected: "x", cancelled: "x", overdue: "alert" };
const S = { me: null, categories: [], catColor: {}, charts: [], search: "" };

function csrf() {
  return $("input[name=csrfmiddlewaretoken]")?.value || "";
}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(`/api/${path}`, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 403 && /credentials/i.test(data.detail || "")) location.href = "/login/";
    const msg = data.detail || Object.entries(data).map(([k, v]) => `${k === "non_field_errors" ? "" : k + ": "}${[].concat(v).join(" ")}`).join(" · ");
    throw new Error(msg || `Request failed (${res.status})`);
  }
  return data;
}

function toast(message, type = "ok") {
  const el = document.createElement("div");
  el.className = `toast ${type === "error" ? "error" : ""}`;
  el.innerHTML = `${icon(type === "error" ? "alert" : "ok")}<span>${esc(message)}</span>`;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), type === "error" ? 5000 : 2800);
}

const avatar = (u, size = "") =>
  `<span class="avatar ${size}" style="background:${esc(u?.color || "#898781")}" title="${esc(u?.name)}">${esc(u?.initials || "?")}</span>`;
const emptyState = (ico, text) => `<div class="empty">${icon(ico)}<div>${esc(text)}</div></div>`;
const catOf = (name) => S.categories.find((c) => c.name === name) || { icon: "box", name };
const tile = (catName, size = "") => `<span class="tile ${size}" style="background:${S.catColor[catName] || "var(--muted)"}">${icon(catOf(catName).icon)}</span>`;
function statusChip(b) {
  const key = b.is_overdue ? "overdue" : b.status;
  const label = b.is_overdue ? "Overdue return" : b.status_label;
  return `<span class="st ${key}">${icon(STATUS_ICON[key])}${esc(label)}</span>`;
}
const stat = (ico, label, value, hint = "", alert = false) =>
  `<div class="card stat ${alert ? "alert" : ""}"><div class="label">${icon(ico, "sm")}${esc(label)}</div><div class="value tnum">${value}</div>${hint ? `<div class="hint">${esc(hint)}</div>` : ""}</div>`;

// ---------- layers (modal) ----------
const layers = [];
function openLayer(cls, html) {
  const z = 50 + layers.length * 2;
  const overlay = Object.assign(document.createElement("div"), { className: "overlay" });
  const box = Object.assign(document.createElement("div"), { className: cls, innerHTML: html });
  overlay.style.zIndex = z;
  box.style.zIndex = z + 1;
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  document.body.append(overlay, box);
  requestAnimationFrame(() => { overlay.classList.add("show"); box.classList.add("show"); });
  const close = () => {
    const i = layers.indexOf(close);
    if (i >= 0) layers.splice(i, 1);
    overlay.classList.remove("show");
    box.classList.remove("show");
    setTimeout(() => { overlay.remove(); box.remove(); }, 250);
  };
  overlay.addEventListener("click", close);
  box.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) close(); });
  layers.push(close);
  return { box, close };
}

function openForm({ title, body, submit = "Save", danger = false, onSubmit }) {
  const { box, close } = openLayer("modal", `
    <form novalidate>
      <div class="modal-head"><h2>${esc(title)}</h2><button type="button" class="btn ghost icon-only" data-close aria-label="Close">${icon("x")}</button></div>
      <div class="modal-body">${body}<div class="field"><span class="error" data-error></span></div></div>
      <div class="modal-foot"><button type="button" class="btn" data-close>Cancel</button>
        <button class="btn primary" type="submit" ${danger ? 'style="background:var(--critical);border-color:var(--critical);color:#fff"' : ""}>${esc(submit)}</button></div>
    </form>`);
  const form = $("form", box);
  setTimeout(() => $("textarea, input", form)?.focus(), 60);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button[type=submit]", form);
    btn.disabled = true;
    try { await onSubmit(new FormData(form), form); close(); }
    catch (err) { $("[data-error]", form).textContent = err.message; }
    finally { btn.disabled = false; }
  });
  return { box, close };
}

// ---------- shared data ----------
async function loadMe() {
  S.me = await api("me/");
  $("#nav-manager").hidden = !S.me.is_manager;
  $("#count-upcoming").textContent = S.me.counts.upcoming || "";
  const pending = $("#count-pending");
  pending.hidden = !S.me.counts.pending_approvals;
  pending.textContent = S.me.counts.pending_approvals;
  $("#me-box").innerHTML = `
    ${avatar(S.me)}
    <div class="who"><b>${esc(S.me.name)}</b><span>${esc(S.me.role_label)} · ${esc(S.me.department)}</span></div>
    <form method="post" action="/logout/"><input type="hidden" name="csrfmiddlewaretoken" value="${esc(csrf())}">
      <button class="btn ghost icon-only" title="Sign out" aria-label="Sign out">${icon("logout")}</button></form>`;
}

async function loadCategories() {
  S.categories = await api("categories/");
  const slots = ["--series-1", "--series-2", "--series-3", "--series-7", "--series-5", "--series-6", "--series-4", "--series-8"];
  S.categories.forEach((c, i) => { S.catColor[c.name] = `var(${slots[i % slots.length]})`; });
}

// ---------- router ----------
const routes = {
  catalog: viewCatalog,
  equipment: viewEquipment,
  bookings: viewBookings,
  certifications: viewCertifications,
  approvals: viewApprovals,
  reports: viewReports,
  audit: viewAudit,
};

async function route() {
  const [, name = "catalog", param] = (location.hash || "#/catalog").split("/");
  S.charts.forEach((c) => c.destroy());
  S.charts = [];
  $$("#sidebar a[data-route]").forEach((a) => a.classList.toggle("active", a.dataset.route === (name === "equipment" ? "catalog" : name)));
  $("#sidebar").classList.remove("open");
  const view = $("#view");
  view.onclick = null;
  view.innerHTML = `<div class="skeleton" style="height:56px;margin-bottom:20px;max-width:420px"></div>
    <div class="grid equip-grid">${'<div class="skeleton" style="height:200px"></div>'.repeat(6)}</div>`;
  try {
    await (routes[name] || viewCatalog)(view, param);
  } catch (err) {
    view.innerHTML = emptyState("alert", `Couldn't load this page: ${err.message}`);
  }
}
const rerender = () => route();

// ---------- Catalog ----------
async function viewCatalog(view) {
  const items = await api("equipment/");
  const state = { category: "", available: false };
  const certified = new Set(S.me.certified_category_ids);

  view.innerHTML = `
    ${S.me.counts.overdue && !S.me.is_manager ? `<div class="banner warn">${icon("alert")}You have equipment that is overdue for return. Please bring it back to the lab desk.<a class="btn" href="#/bookings">View booking</a></div>` : ""}
    <div class="page-head">
      <div><h1>Equipment</h1><p>${items.length} items in ${S.categories.length} categories · click an item to see its calendar and book.</p></div>
    </div>
    <div class="toolbar">
      <div class="cat-filter" id="cat-filter">
        <button data-c="" class="on">All</button>
        ${S.categories.map((c) => `<button data-c="${c.id}"><span class="sw" style="background:${S.catColor[c.name]}"></span>${esc(c.name)}</button>`).join("")}
      </div>
      <label class="chip" style="cursor:pointer;padding:6px 10px;margin-left:auto"><input type="checkbox" id="avail"> Available now</label>
    </div>
    <div class="grid equip-grid" id="equip-grid"></div>`;

  const render = () => {
    const q = S.search.toLowerCase();
    const list = items.filter((e) =>
      (!state.category || String(e.category.id) === state.category) &&
      (!state.available || (e.bookable && !e.current)) &&
      (!q || `${e.name} ${e.asset_tag} ${e.location} ${e.category.name}`.toLowerCase().includes(q)));
    $("#equip-grid").innerHTML = list.length ? list.map((e) => equipCard(e, certified)).join("") : emptyState("search", "No equipment matches these filters.");
  };
  render();
  S.rerenderCatalog = render;

  $("#cat-filter").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state.category = b.dataset.c;
    $$("#cat-filter button").forEach((x) => x.classList.toggle("on", x === b));
    render();
  });
  $("#avail").addEventListener("change", (e) => { state.available = e.target.checked; render(); });
}

function equipCard(e, certified) {
  let live;
  if (!e.bookable) live = `<div class="live down"><span class="pulse"></span>Out of service · ${esc(e.condition_label.toLowerCase())}</div>`;
  else if (e.current) live = `<div class="live busy"><span class="pulse"></span>In use until ${fmtTime(e.current.end)} · ${esc(e.current.user)}</div>`;
  else live = `<div class="live free"><span class="pulse"></span>Available now${e.next_booking ? `<span class="muted"> · next ${relDay(e.next_booking.start).toLowerCase()} ${fmtTime(e.next_booking.start)}</span>` : ""}</div>`;
  const needsCert = e.category.requires_certification;
  return `<article class="card equip ${e.bookable ? "" : "down"}" data-href="#/equipment/${e.id}" tabindex="0">
    <div class="top">${tile(e.category.name)}<div style="min-width:0"><div class="tag-line">${esc(e.asset_tag)} · ${esc(e.category.name)}</div><h3>${esc(e.name)}</h3></div></div>
    <div class="meta"><span>${icon("pin", "sm")}${esc(e.location)}</span><span>${icon("clock", "sm")}max ${e.max_hours}h</span><span>Condition: ${esc(e.condition_label)}</span></div>
    ${live}
    <div class="badges">
      ${needsCert ? (certified.has(e.category.id) ? `<span class="chip">${icon("badge", "sm")}You're certified</span>` : `<span class="chip critical">${icon("lock", "sm")}Certification required</span>`) : `<span class="chip">${icon("ok", "sm")}Open to all members</span>`}
      ${e.requires_approval ? `<span class="chip">${icon("inbox", "sm")}Needs approval</span>` : `<span class="chip">${icon("ok", "sm")}Instant booking</span>`}
    </div>
  </article>`;
}

// ---------- Equipment page: week calendar + booking panel ----------
async function viewEquipment(view, id) {
  const e = await api(`equipment/${id}/`);
  const certified = S.me.certified_category_ids.includes(e.category.id) || !e.category.requires_certification;
  const st = { week: mondayOf(new Date()), schedule: [], sel: null, check: null, checkTimer: null };

  const startOpts = Array.from({ length: (CLOSE - OPEN) * 2 }, (_, i) => OPEN * 60 + i * 30);
  const endOpts = startOpts.map((m) => m + 30);

  view.innerHTML = `
    <div class="page-head">
      <div>
        <a href="#/catalog" class="muted" style="display:inline-flex;align-items:center;gap:4px;font-size:13px;margin-bottom:6px">${icon("back", "sm")}Equipment</a>
        <h1 style="display:flex;align-items:center;gap:12px">${tile(e.category.name, "sm")}${esc(e.name)}</h1>
        <p>${esc(e.asset_tag)} · ${esc(e.category.name)} · ${esc(e.location)}</p>
      </div>
    </div>
    <div class="equip-layout">
      <section class="card">
        <div class="cal-head">
          <h3 id="week-label"></h3>
          <button class="btn icon-only" id="prev-week" aria-label="Previous week">${icon("back")}</button>
          <button class="btn" id="this-week">Today</button>
          <button class="btn icon-only" id="next-week" aria-label="Next week">${icon("next")}</button>
        </div>
        <div class="cal-scroll"><div class="cal" id="cal"></div></div>
        <div class="cal-legend">
          <span><i style="background:var(--accent)"></i>Your bookings</span>
          <span><i style="background:var(--surface-3);border-left:3px solid var(--muted)"></i>Booked by others</span>
          <span><i style="background:repeating-linear-gradient(135deg,var(--surface-2) 0 3px,var(--surface-3) 3px 6px);border-left:3px solid var(--warning)"></i>Pending approval</span>
          <span><i style="border:2px solid var(--accent);background:var(--accent-soft)"></i>Your selection</span>
          <span class="muted" style="margin-left:auto">Drag across a day to choose a slot</span>
        </div>
      </section>

      <aside class="aside">
        <section class="card"><div class="card-body">
          <h3 style="font-size:15px;margin-bottom:12px">Book this item</h3>
          ${!e.bookable ? `<div class="checkbox bad">${icon("alert")}<div>Out of service (${esc(e.condition_label.toLowerCase())}). Bookings are paused.</div></div>` : ""}
          ${!certified ? `<div class="checkbox bad">${icon("lock")}<div><b>${esc(e.category.name)} need a safety certification.</b><br>Ask a lab manager for an induction. Until then you can view the calendar but not book.</div></div>` : ""}
          <form id="book-form" novalidate>
            ${field("Date", `<input class="input" type="date" name="date" id="f-date" min="${ymd(new Date())}">`)}
            <div class="field-row">
              ${field("From", `<select class="select" name="start" id="f-start">${startOpts.map((m) => `<option value="${m}">${hm(m)}</option>`).join("")}</select>`)}
              ${field("Until", `<select class="select" name="end" id="f-end">${endOpts.map((m) => `<option value="${m}">${hm(m)}</option>`).join("")}</select>`)}
            </div>
            ${field("Purpose", `<input class="input" name="purpose" id="f-purpose" maxlength="200" placeholder="e.g. Debug SPI timing on sensor board">`)}
            <div id="check-box" class="checkbox idle">${icon("calendar")}<div>Pick a slot on the calendar or with the fields above.</div></div>
            <button class="btn primary" id="book-btn" style="width:100%;justify-content:center" disabled>${e.requires_approval ? "Request booking" : "Book now"}</button>
          </form>
        </div></section>
        <section class="card"><div class="card-body">
          <dl class="kv">
            <dt>Asset tag</dt><dd>${esc(e.asset_tag)}</dd>
            <dt>Location</dt><dd>${esc(e.location)}</dd>
            <dt>Condition</dt><dd>${esc(e.condition_label)}</dd>
            <dt>Max booking</dt><dd>${e.max_hours} hours</dd>
            <dt>Approval</dt><dd>${e.requires_approval ? "Lab manager approves each request" : "Instant: confirmed on booking"}</dd>
            <dt>Lab hours</dt><dd>${pad(OPEN)}:00-${CLOSE}:00 daily</dd>
          </dl>
          ${e.description ? `<p class="text-2" style="margin:14px 0 0;font-size:13px">${esc(e.description)}</p>` : ""}
        </div></section>
      </aside>
    </div>`;

  const cal = $("#cal");
  const form = $("#book-form");

  async function loadWeek() {
    $("#week-label").textContent = `${st.week.toLocaleDateString(undefined, { day: "numeric", month: "short" })} – ${addDays(st.week, 6).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`;
    const data = await api(`equipment/${id}/schedule/?start=${ymd(st.week)}&days=7`);
    st.schedule = data.bookings;
    renderCal();
  }

  function renderCal() {
    const now = new Date();
    const days = Array.from({ length: 7 }, (_, i) => addDays(st.week, i));
    const hours = Array.from({ length: CLOSE - OPEN }, (_, i) => OPEN + i);
    const nowMin = now.getHours() * 60 + now.getMinutes();
    cal.innerHTML = `<div></div>${days.map((d) => `<div class="dayhead ${sameDay(d, now) ? "today" : ""}">${d.toLocaleDateString(undefined, { weekday: "short" })}<b>${d.getDate()}</b></div>`).join("")}
      <div class="times">${hours.map((h) => `<span style="top:${(h - OPEN) * HOUR_PX}px">${pad(h)}:00</span>`).join("")}</div>
      ${days.map((d, i) => {
        let past = 0;
        if (ymd(d) < ymd(now)) past = (CLOSE - OPEN) * 60;
        else if (sameDay(d, now)) past = Math.max(0, Math.min((CLOSE - OPEN) * 60, nowMin - OPEN * 60));
        const nowLine = sameDay(d, now) && nowMin > OPEN * 60 && nowMin < CLOSE * 60 ? `<div class="now" style="top:${((nowMin - OPEN * 60) / 60) * HOUR_PX}px"></div>` : "";
        const blocks = st.schedule.filter((b) => sameDay(new Date(b.start), d)).map(blockHtml).join("");
        return `<div class="day ${d.getDay() % 6 === 0 ? "weekend" : ""}" data-i="${i}" data-date="${ymd(d)}">
          ${past ? `<div class="past" style="height:${(past / 60) * HOUR_PX}px"></div>` : ""}${nowLine}${blocks}</div>`;
      }).join("")}`;
    drawSel();
  }

  function blockHtml(b) {
    const s = new Date(b.start);
    const en = new Date(b.end);
    const sm = Math.max(OPEN * 60, s.getHours() * 60 + s.getMinutes());
    const em = Math.min(CLOSE * 60, en.getHours() * 60 + en.getMinutes() || CLOSE * 60);
    const top = ((sm - OPEN * 60) / 60) * HOUR_PX;
    const height = Math.max(18, ((em - sm) / 60) * HOUR_PX - 2);
    const who = b.mine ? "You" : b.user;
    const tipText = `${who} · ${fmtTime(b.start)}–${fmtTime(b.end)} · ${b.status_label}${b.purpose ? ` · ${b.purpose}` : ""}`;
    return `<div class="bk ${b.mine ? "mine" : ""} ${b.status}" style="top:${top + 1}px;height:${height}px" data-tip="${esc(tipText)}">
      <b>${esc(who)}</b><span>${fmtTime(b.start)}–${fmtTime(b.end)}${b.status === "pending" ? " · pending" : ""}</span>${b.purpose && height > 50 ? `<div style="opacity:.8">${esc(b.purpose)}</div>` : ""}</div>`;
  }

  function drawSel() {
    $$(".sel", cal).forEach((x) => x.remove());
    if (!st.sel) return;
    const day = $(`.day[data-date="${st.sel.date}"]`, cal);
    if (!day) return;
    const el = document.createElement("div");
    el.className = `sel ${st.check && !st.check.ok ? "bad" : ""}`;
    el.style.top = `${((st.sel.start - OPEN * 60) / 60) * HOUR_PX}px`;
    el.style.height = `${((st.sel.end - st.sel.start) / 60) * HOUR_PX}px`;
    el.textContent = `${hm(st.sel.start)}–${hm(st.sel.end)}`;
    day.append(el);
  }

  function setSel(date, start, end, { fromForm = false } = {}) {
    st.sel = { date, start, end };
    st.check = null;
    if (!fromForm) {
      form.date.value = date;
      form.start.value = String(start);
      form.end.value = String(end);
    }
    drawSel();
    scheduleCheck();
  }

  function scheduleCheck() {
    clearTimeout(st.checkTimer);
    st.checkTimer = setTimeout(runCheck, 200);
  }

  async function runCheck() {
    if (!st.sel) return;
    const { date, start, end } = st.sel;
    const startDt = new Date(`${date}T${hm(start)}:00`);
    const endDt = new Date(`${date}T${hm(end)}:00`);
    const box = $("#check-box");
    try {
      const q = new URLSearchParams({ equipment: id, start: startDt.toISOString(), end: endDt.toISOString() });
      st.check = await api(`bookings/check/?${q}`);
    } catch (err) {
      st.check = { ok: false, problems: [err.message] };
    }
    if (st.check.ok) {
      box.className = "checkbox ok";
      box.innerHTML = `${icon("ok")}<div><b>Slot is free</b> · ${st.check.hours} h on ${fmtDay(startDt.toISOString())}<br>${st.check.requires_approval ? "A lab manager will review your request." : "Confirmed instantly when you book."}</div>`;
    } else {
      box.className = "checkbox bad";
      box.innerHTML = `${icon("alert")}<div><b>Can't book this slot</b><ul>${st.check.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></div>`;
    }
    drawSel();
    updateButton();
  }

  function updateButton() {
    $("#book-btn").disabled = !(st.check?.ok && form.purpose.value.trim().length >= 4);
  }

  // Drag-to-select on the calendar (pointer events: mouse, pen and touch).
  const minutesAt = (day, y, mode = "floor") => {
    const rect = day.getBoundingClientRect();
    const raw = ((y - rect.top) / HOUR_PX) * 60;
    const snapped = (mode === "floor" ? Math.floor(raw / 30) : Math.round(raw / 30)) * 30;
    return OPEN * 60 + Math.max(0, Math.min((CLOSE - OPEN) * 60, snapped));
  };
  let drag = null;
  cal.addEventListener("pointerdown", (ev) => {
    const day = ev.target.closest(".day");
    if (!day || ev.target.closest(".bk") || ev.button > 0) return;
    const anchor = Math.min(minutesAt(day, ev.clientY), CLOSE * 60 - 30);
    drag = { day, anchor, moved: false };
    day.setPointerCapture(ev.pointerId);
    st.sel = { date: day.dataset.date, start: anchor, end: anchor + 30 };
    drawSel();
  });
  cal.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const cur = minutesAt(drag.day, ev.clientY, "round");
    drag.moved = true;
    const start = cur >= drag.anchor ? drag.anchor : cur;
    const end = cur >= drag.anchor ? Math.max(cur, drag.anchor + 30) : drag.anchor + 30;
    st.sel = { date: drag.day.dataset.date, start, end };
    drawSel();
  });
  cal.addEventListener("pointerup", () => {
    if (!drag) return;
    let { start, end } = st.sel;
    if (end - start === 30 && !drag.moved) end = Math.min(CLOSE * 60, start + 60); // a click books an hour
    drag = null;
    setSel(st.sel.date, start, end);
    if (window.matchMedia("(max-width: 1100px)").matches) $("#book-form").scrollIntoView({ behavior: "smooth" });
  });

  // Form → selection.
  const fromForm = () => {
    const date = form.date.value;
    let start = Number(form.start.value);
    let end = Number(form.end.value);
    if (!date) return;
    if (end <= start) { end = Math.min(CLOSE * 60, start + 60); form.end.value = String(end); }
    const week = mondayOf(new Date(`${date}T00:00:00`));
    if (ymd(week) !== ymd(st.week)) { st.week = week; loadWeek(); }
    setSel(date, start, end, { fromForm: true });
  };
  ["date", "start", "end"].forEach((n) => form[n].addEventListener("change", fromForm));
  form.purpose.addEventListener("input", updateButton);

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if ($("#book-btn").disabled) return;
    const { date, start, end } = st.sel;
    $("#book-btn").disabled = true;
    try {
      const b = await api("bookings/", {
        method: "POST",
        body: {
          equipment_id: Number(id), purpose: form.purpose.value.trim(),
          start: new Date(`${date}T${hm(start)}:00`).toISOString(), end: new Date(`${date}T${hm(end)}:00`).toISOString(),
        },
      });
      toast(b.status === "pending" ? "Request sent to the lab manager" : "Booked! Your slot is confirmed");
      st.sel = null;
      st.check = null;
      form.purpose.value = "";
      $("#check-box").className = "checkbox idle";
      $("#check-box").innerHTML = `${icon("cal-check")}<div>Done. See it under <a href="#/bookings">My bookings</a>, or pick another slot.</div>`;
      await loadWeek();
      loadMe();
    } catch (err) {
      toast(err.message, "error");
      updateButton();
    }
  });

  $("#prev-week").addEventListener("click", () => { st.week = addDays(st.week, -7); loadWeek(); });
  $("#next-week").addEventListener("click", () => { st.week = addDays(st.week, 7); loadWeek(); });
  $("#this-week").addEventListener("click", () => { st.week = mondayOf(new Date()); loadWeek(); });
  if (!certified || !e.bookable) $$("input, select", form).forEach((x) => { x.disabled = true; });
  form.date.value = ymd(new Date());
  await loadWeek();
}

const field = (label, control) => `<div class="field"><label>${label}</label>${control}</div>`;

// ---------- My bookings ----------
async function viewBookings(view, tab = "upcoming") {
  view.innerHTML = `
    <div class="page-head"><div><h1>My bookings</h1><p>Your reservations and requests. Cancel any slot that hasn't started.</p></div>
      <div class="actions"><a class="btn primary" href="#/catalog">${icon("plus")}New booking</a></div></div>
    <div class="toolbar"><div class="segmented" id="b-tabs">
      <button data-t="upcoming">Upcoming</button><button data-t="past">Past</button><button data-t="all">All</button></div></div>
    <div class="bk-list" id="b-list"></div>`;
  const load = async () => {
    $$("#b-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === tab));
    const list = await api(`bookings/${tab === "all" ? "" : `?when=${tab}`}`);
    const now = Date.now();
    $("#b-list").innerHTML = list.length ? list.map((b) => {
      const canCancel = ["pending", "approved"].includes(b.status) && Date.parse(b.start) > now;
      return `<article class="card bk-row ${b.is_overdue ? "overdue" : ""}">
        ${tile(b.equipment.category, "sm")}
        <div class="what"><b>${esc(b.equipment.name)}</b><span>${esc(b.equipment.asset_tag)} · ${esc(b.equipment.location)} · ${esc(b.purpose)}</span></div>
        <div class="when"><b>${relDay(b.start)}</b><span>${fmtTime(b.start)}–${fmtTime(b.end)} · ${b.hours} h</span></div>
        <div class="actions">${statusChip(b)}
          <a class="btn ghost" href="#/equipment/${b.equipment.id}">Calendar</a>
          ${canCancel ? `<button class="btn danger" data-cancel="${b.id}">Cancel</button>` : ""}</div>
        ${b.manager_note ? `<div class="note">${icon("message", "sm")} <b>${esc(b.decided_by || "Lab manager")}:</b> ${esc(b.manager_note)}</div>` : ""}
      </article>`;
    }).join("") : emptyState("calendar", tab === "upcoming" ? "No upcoming bookings. Browse equipment to book a slot." : "Nothing here yet.");
  };
  $("#b-tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; tab = b.dataset.t; load(); });
  $("#b-list").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-cancel]");
    if (!btn || !confirm("Cancel this booking? The slot will be released for others.")) return;
    try {
      await api(`bookings/${btn.dataset.cancel}/cancel/`, { method: "POST" });
      toast("Booking cancelled");
      load();
      loadMe();
    } catch (err) { toast(err.message, "error"); }
  });
  await load();
}

// ---------- Approvals (manager) ----------
async function viewApprovals(view) {
  const [pending, desk, out] = await Promise.all([
    api("bookings/?scope=all&status=pending&when=upcoming"),
    api("bookings/?scope=all&status=approved,checked_out&when=today"),
    api("bookings/?scope=all&status=checked_out"),
  ]);
  const overdue = out.filter((b) => b.is_overdue);
  const deskRows = desk.filter((b) => !b.is_overdue);
  const now = Date.now();

  const deskRow = (b) => {
    const canCheckout = b.status === "approved" && Date.parse(b.start) - now <= 30 * 60 * 1000;
    return `<article class="card bk-row ${b.is_overdue ? "overdue" : ""}">
      ${avatar(b.user)}
      <div class="what"><b>${esc(b.user.name)} · ${esc(b.equipment.name)}</b><span>${esc(b.equipment.asset_tag)} · ${esc(b.equipment.location)} · ${esc(b.purpose)}</span></div>
      <div class="when"><b>${relDay(b.start)} ${fmtTime(b.start)}–${fmtTime(b.end)}</b><span>${b.is_overdue ? `due back ${timeAgo(b.end)}` : `${b.hours} h`}</span></div>
      <div class="actions">${statusChip(b)}
        ${b.status === "approved" ? `<button class="btn" data-act="checkout" data-id="${b.id}" ${canCheckout ? "" : 'disabled title="Opens 30 min before start"'}>${icon("box", "sm")}Check out</button>` : ""}
        ${b.status === "checked_out" ? `<button class="btn primary" data-act="return" data-id="${b.id}">${icon("ok", "sm")}Mark returned</button>` : ""}
      </div></article>`;
  };

  view.innerHTML = `
    <div class="page-head"><div><h1>Approvals & desk</h1><p>Review requests for restricted equipment and hand items over at the lab desk.</p></div></div>
    <div class="grid stats">
      ${stat("inbox", "Waiting for approval", pending.length)}
      ${stat("box", "At the desk today", deskRows.length)}
      ${stat("alert", "Overdue returns", overdue.length, "", overdue.length > 0)}
    </div>
    ${overdue.length ? `<div class="section-head"><h2>Overdue returns</h2><span class="n">${overdue.length}</span></div>
      <div class="bk-list">${overdue.map(deskRow).join("")}</div>` : ""}
    <div class="section-head"><h2>Waiting for approval</h2><span class="n">${pending.length}</span></div>
    <div class="bk-list">${pending.length ? pending.map((b) => `
      <article class="card req">
        ${avatar(b.user, "lg")}
        <div>
          <div><b>${esc(b.user.name)}</b> <span class="muted">· ${esc(b.user.title)} · ${esc(b.user.department)}</span></div>
          <div style="margin-top:4px;font-weight:500">${esc(b.equipment.name)} <span class="muted">(${esc(b.equipment.asset_tag)})</span></div>
          <p class="purpose">“${esc(b.purpose)}”</p>
          <div class="facts"><span>${icon("calendar", "sm")}${relDay(b.start)}</span><span>${icon("clock", "sm")}${fmtTime(b.start)}–${fmtTime(b.end)} · ${b.hours} h</span><span>${icon("message", "sm")}requested ${timeAgo(b.created_at)}</span></div>
        </div>
        <div class="actions">
          <button class="btn" data-act="reject" data-id="${b.id}">${icon("x", "sm")}Reject</button>
          <button class="btn primary" data-act="approve" data-id="${b.id}">${icon("ok", "sm")}Approve</button>
        </div>
      </article>`).join("") : `<div class="card">${emptyState("inbox", "All caught up. No requests waiting.")}</div>`}</div>
    <div class="section-head"><h2>At the desk today</h2><span class="n">${deskRows.length}</span></div>
    <div class="bk-list">${deskRows.length ? deskRows.map(deskRow).join("") : `<div class="card">${emptyState("box", "No hand-overs scheduled for today.")}</div>`}</div>`;

  view.onclick = async (e) => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const { act, id } = btn.dataset;
    if (act === "reject") return rejectForm(id);
    btn.disabled = true;
    try {
      await api(`bookings/${id}/${act}/`, { method: "POST" });
      toast({ approve: "Approved. The member can see it now.", checkout: "Checked out", return: "Marked as returned" }[act]);
      await loadMe();
      rerender();
    } catch (err) {
      toast(err.message, "error");
      btn.disabled = false;
    }
  };
}

function rejectForm(id) {
  const reasons = ["Slot reserved for a scheduled class", "Equipment under maintenance", "Please book a shorter slot", "Certification has expired"];
  const { box } = openForm({
    title: "Reject request",
    submit: "Reject request",
    danger: true,
    body: `${field("Reason (shown to the member)", `<textarea class="input" name="note" rows="3" maxlength="200" required></textarea>`)}
      <div class="quick-notes">${reasons.map((r) => `<button type="button" data-r="${esc(r)}">${esc(r)}</button>`).join("")}</div>`,
    onSubmit: async (fd) => {
      await api(`bookings/${id}/reject/`, { method: "POST", body: { note: fd.get("note") } });
      toast("Request rejected");
      await loadMe();
      rerender();
    },
  });
  box.addEventListener("click", (e) => { const r = e.target.closest("[data-r]"); if (r) $("textarea", box).value = r.dataset.r; });
}

// ---------- Reports (manager) ----------
async function viewReports(view, days = "30") {
  const d = await api(`reports/summary/?days=${days}`);
  const s = d.stats;
  const maxHours = Math.max(1, ...d.top_equipment.map((t) => t.hours));
  const maxDept = Math.max(1, ...d.departments.map((x) => x.bookings));
  const heatMax = Math.max(1, ...d.heatmap.flat());
  const ramp = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
  const heatColor = (v) => (v ? ramp[Math.min(ramp.length - 1, Math.floor((v / heatMax) * ramp.length))] : "var(--surface-2)");
  const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const deptNames = { ECE: "Electronics & Comm.", CSE: "Computer Science", MECH: "Mechanical", PHY: "Physics" };

  view.innerHTML = `
    <div class="page-head">
      <div><h1>Reports</h1><p>How the lab's equipment was used in the last ${d.days} days.</p></div>
      <div class="actions">
        <div class="segmented" id="r-days">${["7", "30", "90"].map((n) => `<button data-d="${n}" class="${n === String(d.days) ? "on" : ""}">${n} days</button>`).join("")}</div>
        <a class="btn" href="/api/reports/export.csv?days=${d.days}" download>${icon("download")}Export CSV</a>
      </div>
    </div>
    <div class="grid stats">
      ${stat("calendar", "Bookings", s.bookings)}
      ${stat("clock", "Hours used", s.hours)}
      ${stat("chart", "Utilisation", `${s.utilization}%`, "of staffed hours across bookable items")}
      ${stat("users", "Active members", s.people)}
      ${stat("inbox", "Pending now", s.pending)}
      ${stat("alert", "Overdue now", s.overdue, "", s.overdue > 0)}
    </div>
    <div class="grid report-grid">
      <section class="card span-2">
        <div class="card-head"><h3>Bookings per day</h3><span class="sub">Approved, in use or returned</span></div>
        <div class="card-body"><div class="chart-box"><canvas id="daily" aria-label="Bar chart of bookings per day"></canvas></div></div>
      </section>
      <section class="card">
        <div class="card-head"><h3>Most-used equipment</h3><span class="sub">by hours booked</span></div>
        <div class="card-body">${d.top_equipment.length ? d.top_equipment.map((t) => `
          <div class="hbar" data-tip="${esc(`${t.name} (${t.asset_tag}): ${t.hours} h across ${t.bookings} bookings`)}">
            <span class="name" title="${esc(t.name)}">${esc(t.asset_tag)} <span class="muted">${esc(t.name)}</span></span>
            <div class="track"><div class="fill" style="width:${(100 * t.hours) / maxHours}%"></div></div>
            <span class="val tnum">${t.hours} h</span>
          </div>`).join("") : emptyState("chart", "No usage in this window.")}</div>
      </section>
      <section class="card">
        <div class="card-head"><h3>Peak lab hours</h3><span class="sub">booked hours by weekday and time</span></div>
        <div class="card-body">
          <div class="heat" role="img" aria-label="Heatmap of booked hours by weekday and hour">
            <span></span>${Array.from({ length: 12 }, (_, i) => `<span class="h">${i % 2 === 0 ? OPEN + i : ""}</span>`).join("")}
            ${d.heatmap.map((row, wd) => `<span class="d">${weekdays[wd]}</span>${row.map((v, h) =>
              `<span class="c" style="background:${heatColor(v)}" data-tip="${weekdays[wd]} ${pad(OPEN + h)}:00–${pad(OPEN + h + 1)}:00 · ${v} booked hour${v === 1 ? "" : "s"}"></span>`).join("")}`).join("")}
          </div>
          <div class="ramp">Fewer ${ramp.map((c) => `<i style="background:${c}"></i>`).join("")} More</div>
        </div>
      </section>
      <section class="card">
        <div class="card-head"><h3>Usage by department</h3><span class="sub">bookings · people</span></div>
        <div class="card-body">${d.departments.map((x) => `
          <div class="hbar" data-tip="${esc(`${deptNames[x.department] || x.department}: ${x.bookings} bookings by ${x.people} people`)}">
            <span class="name">${esc(deptNames[x.department] || x.department)}</span>
            <div class="track"><div class="fill" style="width:${(100 * x.bookings) / maxDept}%"></div></div>
            <span class="val tnum">${x.bookings} · ${x.people}</span>
          </div>`).join("") || emptyState("users", "No usage in this window.")}</div>
      </section>
      <section class="card">
        <div class="card-head"><h3>Booking outcomes</h3><span class="sub">rejection rate ${s.rejection_rate}%</span></div>
        <div class="card-body"><ul class="list">${d.status_breakdown.filter((x) => x.count).map((x) => `
          <li><span class="grow">${statusChip({ status: x.status, status_label: x.label })}</span><b class="tnum">${x.count}</b></li>`).join("")}</ul></div>
      </section>
    </div>`;

  $("#r-days").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) location.hash = `#/reports/${b.dataset.d}`; });
  drawDaily(d.daily);
}

function drawDaily(rows) {
  if (!window.Chart) return;
  Chart.defaults.font.family = cssVar("--font");
  Chart.defaults.color = cssVar("--muted");
  S.charts.push(new Chart($("#daily"), {
    type: "bar",
    data: {
      labels: rows.map((r) => new Date(`${r.date}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" })),
      datasets: [{ label: "Bookings", data: rows.map((r) => r.count), backgroundColor: cssVar("--series-1"),
        borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "bottom", maxBarThickness: 28 }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: cssVar("--text"), titleColor: cssVar("--bg"), bodyColor: cssVar("--bg"), padding: 10, cornerRadius: 8, displayColors: false,
          callbacks: { label: (i) => `${i.raw} bookings` } },
      },
      scales: {
        x: { grid: { display: false }, border: { color: cssVar("--grid") }, ticks: { maxRotation: 0, autoSkipPadding: 12 } },
        y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: cssVar("--grid") }, border: { display: false } },
      },
    },
  }));
}

// ---------- Certifications ----------
async function viewCertifications(view) {
  const certs = await api("certifications/");
  const restricted = S.categories.filter((c) => c.requires_certification);

  if (!S.me.is_manager) {
    const mine = Object.fromEntries(certs.map((c) => [c.category.id, c]));
    view.innerHTML = `
      <div class="page-head"><div><h1>My certifications</h1><p>Some equipment needs a safety induction before you can book it. Ask a lab manager to certify you.</p></div></div>
      <div class="grid cert-cards">${restricted.map((cat) => {
        const c = mine[cat.id];
        const ok = c && c.is_valid;
        return `<article class="card cert-card">${tile(cat.name)}
          <div><b>${esc(cat.name)}</b><p class="text-2" style="margin:4px 0 10px;font-size:13px">${esc(cat.description)}</p>
          ${ok ? `<span class="st approved">${icon("badge")}Certified${c.expires_on ? ` until ${fmtDay(c.expires_on + "T00:00:00")}` : ""}</span>`
              : `<span class="st rejected">${icon("lock")}${c ? "Expired" : "Not certified"}</span>`}</div></article>`;
      }).join("")}</div>`;
    return;
  }

  const users = (await api("users/")).filter((u) => u.role !== "manager");
  const index = Object.fromEntries(certs.map((c) => [`${c.user.id}:${c.category.id}`, c]));
  view.innerHTML = `
    <div class="page-head"><div><h1>Certifications</h1><p>Grant or revoke safety certifications. Members can only book restricted equipment while certified.</p></div></div>
    <section class="card"><div class="table-wrap"><table class="table">
      <thead><tr><th>Member</th>${restricted.map((c) => `<th>${tile(c.name, "sm")} <span style="vertical-align:middle;margin-left:6px">${esc(c.name)}</span></th>`).join("")}</tr></thead>
      <tbody>${users.map((u) => `<tr>
        <td><div style="display:flex;gap:10px;align-items:center">${avatar(u)}<div><b>${esc(u.name)}</b><div class="muted" style="font-size:12px">${esc(u.title)}</div></div></div></td>
        ${restricted.map((cat) => {
          const c = index[`${u.id}:${cat.id}`];
          return `<td>${c ? `<button class="cert-cell on" data-revoke="${c.id}" title="Click to revoke">${icon("ok", "sm")}${c.expires_on ? `until ${fmtDay(c.expires_on + "T00:00:00")}` : "Certified"}</button>`
            : `<button class="cert-cell" data-grant="${u.id}:${cat.id}">${icon("plus", "sm")}Grant</button>`}</td>`;
        }).join("")}
      </tr>`).join("")}</tbody></table></div></section>`;

  view.onclick = async (e) => {
    const grant = e.target.closest("[data-grant]");
    const revoke = e.target.closest("[data-revoke]");
    try {
      if (grant) {
        const [userId, catId] = grant.dataset.grant.split(":").map(Number);
        const expires = new Date();
        expires.setFullYear(expires.getFullYear() + 1);
        await api("certifications/", { method: "POST", body: { user_id: userId, category_id: catId, expires_on: ymd(expires) } });
        toast("Certification granted for 1 year");
        rerender();
      } else if (revoke && confirm("Revoke this certification? Future bookings will need it again.")) {
        await api(`certifications/${revoke.dataset.revoke}/`, { method: "DELETE" });
        toast("Certification revoked");
        rerender();
      }
    } catch (err) { toast(err.message, "error"); }
  };
}

// ---------- Audit log ----------
async function viewAudit(view) {
  const rows = await api("audit/");
  view.innerHTML = `
    <div class="page-head"><div><h1>Audit log</h1><p>The latest 100 actions: who did what, and when.</p></div></div>
    <section class="card"><div class="table-wrap"><table class="table">
      <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Equipment</th><th>Detail</th></tr></thead>
      <tbody>${rows.map((r) => `<tr>
        <td class="text-2" style="white-space:nowrap" title="${esc(new Date(r.created_at).toLocaleString())}">${timeAgo(r.created_at)}</td>
        <td><div style="display:flex;gap:8px;align-items:center">${avatar(r.actor, "sm")}${esc(r.actor?.name || "System")}</div></td>
        <td><span class="chip">${esc(r.action)}</span></td>
        <td>${esc(r.equipment || "—")}</td>
        <td class="text-2">${esc(r.detail || "")}</td>
      </tr>`).join("")}</tbody></table></div></section>`;
}

// ---------- global wiring ----------
function setThemeIcon() {
  const dark = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  $("#theme-btn use").setAttribute("href", dark ? "#i-sun" : "#i-moon");
  return dark;
}

// Shared tooltip for calendar blocks, heatmap cells and bars.
const tip = $("#tip");
document.addEventListener("pointerover", (e) => {
  const t = e.target.closest("[data-tip]");
  if (!t) { tip.classList.remove("show"); return; }
  tip.textContent = t.dataset.tip;
  tip.classList.add("show");
});
document.addEventListener("pointermove", (e) => {
  if (!tip.classList.contains("show")) return;
  const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
  tip.style.left = `${x}px`;
  tip.style.top = `${e.clientY + 16}px`;
});

document.addEventListener("click", (e) => {
  const hrefEl = e.target.closest("[data-href]");
  if (hrefEl && !e.target.closest("button, a")) location.hash = hrefEl.dataset.href;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && layers.length) layers[layers.length - 1]();
  if (e.key === "Enter" && document.activeElement?.matches("[data-href]")) document.activeElement.click();
  if (e.key === "/" && !e.target.closest("input, textarea, select")) { e.preventDefault(); $("#global-search").focus(); }
});

$("#global-search").addEventListener("input", (e) => {
  S.search = e.target.value.trim();
  if (!location.hash.startsWith("#/catalog") && location.hash) location.hash = "#/catalog";
  else S.rerenderCatalog?.();
});
$("#menu-btn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
$("#theme-btn").addEventListener("click", () => {
  const next = setThemeIcon() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("bookit-theme", next); } catch (err) { /* storage unavailable */ }
  setThemeIcon();
  rerender();
});
window.addEventListener("hashchange", route);

(async function init() {
  setThemeIcon();
  try {
    await Promise.all([loadMe(), loadCategories()]);
  } catch (err) {
    $("#view").innerHTML = emptyState("alert", `Couldn't reach the API: ${err.message}`);
    return;
  }
  route();
})();
