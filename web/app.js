/* bench-pool: static, no build step. Reads data/benchmarks.json. */
(function () {
  "use strict";

  const ICONS = {
    0: '<circle cx="12" cy="12" r="2.6"/><circle cx="12" cy="12" r="6.4"/><circle cx="12" cy="12" r="10"/>',
    1: '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.6 5l-3.2 14"/>',
    2: '<path d="M17.5 6V4.5h-11l6.2 7.5-6.2 7.5h11V18"/>',
    3: '<path d="M12 6.5C10 5 7 4.5 3.5 4.5v13c3.5 0 6.5.5 8.5 2 2-1.5 5-2 8.5-2v-13C17 4.5 14 5 12 6.5zM12 6.5v13"/>',
    4: '<path d="M9 3h6M10 3v6.2L4.9 18a2 2 0 0 0 1.7 3h10.8a2 2 0 0 0 1.7-3L14 9.2V3M7.6 15h8.8"/>',
    5: '<circle cx="5.5" cy="6" r="2.5"/><circle cx="18.5" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8 6h8M6.8 8.2l3.9 7.6M17.2 8.2l-3.9 7.6"/>',
    6: '<path d="M3.5 20.5h17M7 20.5V13M12 20.5V5M17 20.5V10"/>',
    7: '<path d="M3 7.5h18v12H3zM9 7.5V5.2a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2.3M3 13h18"/>',
    8: '<path d="M12 3l8 3v6c0 4.6-3.2 8-8 9.2C7.2 20 4 16.6 4 12V6l8-3zM9 12l2.2 2.2L15 10.2"/>',
    9: '<rect x="3" y="5" width="18" height="14"/><circle cx="8.5" cy="10" r="1.6"/><path d="M3 16.5l5-4.5 4 3.5 3.5-3 5.5 4.5"/>',
    10: '<path d="M6.5 8h11a4.5 4.5 0 0 1 4.5 4.5A3.5 3.5 0 0 1 15.8 15H8.2A3.5 3.5 0 0 1 2 12.5 4.5 4.5 0 0 1 6.5 8zM7.5 10.3v3M6 11.8h3"/><circle cx="16" cy="10.8" r=".7"/><circle cx="18" cy="12.8" r=".7"/>',
  };
  const LABELS = {
    0: ["All", "classes"],
    1: ["Software", "engineering"],
    2: ["Math", "& reasoning"],
    3: ["Knowledge", "& long context"],
    4: ["Scientific", "research"],
    5: ["Agents", "tools & systems"],
    6: ["Data", "& analytics"],
    7: ["Professional", "domains"],
    8: ["Safety", "& security"],
    9: ["Multimodal", "perception"],
    10: ["Games", "& embodied"],
  };
  // Agent interaction mode, Harbor Index v1 paper, Appendix D.2.
  const MODE = {
    agentic: ["A", "Agentic", "Designed for agents: tasks need multi-step interaction with an environment or tools"],
    modified: ["M", "Modified-agentic", "Originally single-pass, but giving an agent an environment changes the result"],
    non: ["N", "Non-agentic", "Single-pass: the model answers from the prompt alone"],
  };
  // Tiers from docs/tiering-standard.md. "none" = not judged under the current standard.
  const TIER = {
    recommend: ["Recommend", "Propose for Harbor Index now"],
    hold: ["Hold", "Plausible; a person must settle one point"],
    no: ["No", "A blocking rule fires"],
    none: ["—", "Not judged yet"],
  };
  const TIER_RANK = { recommend: 0, hold: 1, no: 2, none: 3 };
  const COVER = { v1: "Harbor Index v1 already takes tasks from it", adapter: "It already has a merged Harbor adapter" };
  const RULE = {
    B1: "No task data is public", B2: "Cannot run in a container with a programmatic verifier", B3: "Saturated: 90% or more on a leaderboard",
    B4: "Superseded by a successor", B5: "Not a benchmark on closer reading", B6: "Evaluates trained policies, not a model or agent",
    T0: "Nothing to read: no paper and no repository found", T2: "Agentic; Real and Solid strong, plus Difficult or Attention; nothing weak",
    T3: "Non-agentic, but hard, unsaturated and widely noticed", T4: "Held for a person to settle",
  };
  const tierOf = (it) => (it.tier ? it.tier.tier : "none");
  const tierBadge = (it) => {
    if (it.covered) return `<span class="tier covered" data-tip="${esc(COVER[it.covered] + ", so it is not a new candidate." + "")}">Covered</span>`;
    const t = tierOf(it); return `<span class="tier ${t}" data-tip="${esc(TIER[t][1] + (it.tier ? ". " + it.tier.rule + ": " + it.tier.reason : ""))}">${TIER[t][0]}</span>`; };
  const PAGE = 100;

  const app = document.getElementById("app");
  const tip = document.getElementById("tip");
  let DATA = null;
  let CLASS = {};
  let CIDS = [];
  const S = { view: "list", cls: 0, sub: null, mm: false, mode: null, tier: null, cover: "open", quick: null, q: "", week: null, sort: "tier", dir: 1, limit: PAGE, basis: "all" };

  // ---------- helpers ----------
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (id, size) => `<svg viewBox="0 0 24 24" width="${size || 18}" height="${size || 18}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[id]}</svg>`;
  const pct = (v) => `${+v.toFixed(1)}%`;
  const num = (v) => Number(v).toLocaleString("en-US", { maximumFractionDigits: 1 });
  const safeUrl = (u) => (/^https?:\/\//i.test(u) ? u : "#");
  const hash01 = (s) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 1000) / 1000; };
  const day = (d) => new Date(d + "T00:00:00Z");
  const iso = (d) => d.toISOString().slice(0, 10);
  const addDays = (d, n) => new Date(d.getTime() + n * 864e5);
  const monday = (d) => addDays(d, -((d.getUTCDay() + 6) % 7));
  const when = (it) => it.date || it.seen;
  // Three kinds of score, never mixed: the benchmark's own leaderboard, an
  // aggregator's leaderboard, and the figure the paper states (drawn hatched).
  const KIND = { own: "Own leaderboard", aggregator: "Aggregator leaderboard", paper: "Paper-reported" };
  const kindCls = (basis) => ({ aggregator: "agg", paper: "paper" }[basis] || "");
  const hasLb = (it) => it.lb !== "none" && it.lb !== "unchecked";

  function inScope(it, o) {
    o = o || {};
    if (!o.anyClass && S.cls && it.cls !== S.cls) return false;
    if (!o.anyClass && S.sub && it.sub !== S.sub) return false;
    if (S.q) {
      const hay = (it.name + " " + it.title + " " + it.tags.join(" ") + " " + it.orgs.join(" ")).toLowerCase();
      if (!S.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    if (!o.anyCover && S.cover === "open" && it.covered) return false;
    if (!o.anyCover && S.cover === "covered" && !it.covered) return false;
    if (S.mode && it.mode !== S.mode) return false;
    if (o.base) return true;
    if (S.tier && tierOf(it) !== S.tier) return false;
    if (S.mm && !it.mm) return false;
    if (S.quick === "hi1" && !it.hi1) return false;
    if (S.quick === "al" && !it.adapter) return false;
    if (S.quick === "diff" && !it.diff.length) return false;
    if (S.quick === "lb" && !hasLb(it)) return false;
    if (S.quick === "unchecked" && it.lb !== "unchecked") return false;
    if (S.quick === "sat" && !it.sat) return false;
    if (S.quick === "new" && !(when(it) && when(it) >= DATA.newSince)) return false;
    if (!o.anyWeek && S.week && !(when(it) && when(it) >= S.week && when(it) < iso(addDays(day(S.week), 7)))) return false;
    return true;
  }
  const scoped = (o) => DATA.items.filter((it) => inScope(it, o));

  // ---------- shell ----------
  function shell() {
    app.innerHTML = `
      <section class="hero">
        <h1>Bench-<i>pool</i></h1>
        <p>Benchmarks for agents and models, screened for Harbor Index</p>
        <p class="status" id="status"></p>
        <div class="chips" id="covers" role="group" aria-label="Candidates or covered"></div>
        <div class="chips" id="tiers" role="group" aria-label="Tier"></div>
        <div class="chips" id="modes" role="group" aria-label="Agent interaction mode"></div>
        <div class="chips" id="chips"></div>
      </section>
      <div class="classes" id="classes" role="group" aria-label="Class filter"></div>
      <div class="subs" id="subs"></div>
      <div class="bar">
        <label class="search">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>
          <input id="q" type="search" placeholder="Search benchmarks" autocomplete="off" aria-label="Search benchmarks">
        </label>
        <span class="grow"></span>
        <div class="views" role="group" aria-label="View">
          <button type="button" data-view="list">List</button>
          <button type="button" data-view="timeline">Timeline</button>
          <button type="button" data-view="saturation">Saturation</button>
        </div>
      </div>
      <section class="panel" id="panel"></section>`;
    document.getElementById("q").value = S.q;
  }

  function controls() {
    const base = scoped({ base: true });
    const chip = (key, label, n, cls) =>
      `<button type="button" class="chip ${cls || ""}" data-quick="${key}" aria-pressed="${key === "mm" ? S.mm : S.quick === key}"><b>${num(n)}</b> ${label}</button>`;
    const anyMode = DATA.items.filter((it) => { const m = S.mode; S.mode = null; const ok = inScope(it, { base: true }); S.mode = m; return ok; });
    document.getElementById("modes").innerHTML =
      `<button type="button" class="chip" data-mode="" aria-pressed="${!S.mode}"><b>${num(anyMode.length)}</b> all modes</button>` +
      Object.keys(MODE).map((m) => `<button type="button" class="chip" data-mode="${m}" aria-pressed="${S.mode === m}" data-tip="${esc(MODE[m][2])}"><span class="mode ${m}">${MODE[m][0]}</span><b>${num(anyMode.filter((i) => i.mode === m).length)}</b> ${MODE[m][1].toLowerCase()}</button>`).join("");
    const T = DATA.meta.tiering, waiting = T.candidates - T.judged;
    document.getElementById("status").innerHTML =
      `Updated ${esc(DATA.meta.generated.slice(0, 10))} · of ${num(T.candidates)} new candidates, an agent has read and judged <b>${num(T.by_agent)}</b>` +
      ` · <b>${num(T.by_rule)}</b> settled without reading (nothing to read, or already saturated)` +
      (waiting ? ` · <b class="wait">${num(waiting)}</b> waiting to be judged` : " · none waiting");
    const every = scoped({ base: true, anyCover: true });
    document.getElementById("covers").innerHTML =
      `<button type="button" class="chip" data-cover="open" aria-pressed="${S.cover === "open"}" data-tip="Not in Harbor Index v1 and no merged adapter"><b>${num(every.filter((i) => !i.covered).length)}</b> new candidates</button>` +
      `<button type="button" class="chip" data-cover="covered" aria-pressed="${S.cover === "covered"}" data-tip="In Harbor Index v1, or a Harbor adapter is merged. Kept as reference"><b>${num(every.filter((i) => i.covered).length)}</b> already covered</button>` +
      `<button type="button" class="chip" data-cover="all" aria-pressed="${S.cover === "all"}"><b>${num(every.length)}</b> all</button>`;
    document.getElementById("tiers").innerHTML =
      `<button type="button" class="chip" data-tier="" aria-pressed="${!S.tier}">all tiers</button>` +
      Object.keys(TIER).filter((t) => t !== "none" || base.some((i) => tierOf(i) === "none")).map((t) => `<button type="button" class="chip" data-tier="${t}" aria-pressed="${S.tier === t}" data-tip="${esc(TIER[t][1])}"><span class="tier ${t}">${t === "none" ? "not judged" : TIER[t][0]}</span><b>${num(base.filter((i) => tierOf(i) === t).length)}</b></button>`).join("");
    document.getElementById("chips").innerHTML =
      chip("sat", "saturated &gt;90%", base.filter((i) => i.sat).length, "hot") +
      chip("new", "new in 30 days", base.filter((i) => when(i) && when(i) >= DATA.newSince).length) +
      chip("mm", "multimodal", base.filter((i) => i.mm).length);

    const counts = {};
    DATA.items.forEach((it) => { if (inScope(it, { anyClass: true })) counts[it.cls] = (counts[it.cls] || 0) + 1; });
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    document.getElementById("classes").innerHTML = [0].concat(CIDS).map((id) => `
      <button type="button" class="cls" data-cls="${id}" aria-pressed="${S.cls === id}" title="${id ? esc(CLASS[id].name) : "All classes"}">
        ${icon(id, 22)}
        <span class="l1">${LABELS[id][0]}</span>
        <span class="l2">${LABELS[id][1]}</span>
        <span class="n">${num(id ? counts[id] || 0 : total)}</span>
      </button>`).join("");

    const subs = S.cls ? CLASS[S.cls].subs : [];
    document.getElementById("subs").innerHTML = subs.map((s) => {
      const n = DATA.items.filter((it) => it.cls === S.cls && it.sub === s && inScope(it, { anyClass: true })).length;
      return `<button type="button" class="sub" data-sub="${esc(s)}" aria-pressed="${S.sub === s}">${esc(s)} · ${n}</button>`;
    }).join("");

    document.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.view === S.view));
    document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === "list"));
  }

  // ---------- list ----------
  function sotaCell(it) {
    if (it.best == null) {
      const s = it.own && it.own.raw != null ? it.own : it.agg && it.agg.raw != null ? it.agg : null;
      if (!s) return `<div class="sota"><span class="v none">—</span></div>`;
      const what = s === it.own ? `Own leaderboard top score${s.metric ? " (" + s.metric + ")" : ""}` : `${s.source} top score`;
      return `<div class="sota" data-tip="${esc(what)}, not a percentage"><span class="v">${num(s.raw)}</span><span class="none">${s.scale ? "of " + num(s.scale) : s === it.own && s.metric ? esc(s.metric.slice(0, 14)) : "pts"}</span></div>`;
    }
    const tipText = {
      own: () => `Own leaderboard · ${it.own.model || ""} · found ${it.own.found}`,
      aggregator: () => `${it.agg.source} · ${it.agg.model || ""} · crawled ${it.agg.as_of}`,
      paper: () => "Best score stated in the paper's abstract",
    }[it.basis]();
    return `<div class="sota ${kindCls(it.basis)}" data-tip="${esc(tipText)}">
      <span class="v">${pct(it.best)}</span>
      <span class="track ${kindCls(it.basis)} ${it.sat ? "hot" : ""}"><i style="width:${Math.max(1, Math.min(100, it.best))}%"></i></span></div>`;
  }
  function lbCell(it) {
    const checked = it.search.checked ? ` · searched ${it.search.checked}` : "";
    const cell = (cls, label, tipText) => `<span class="lb ${cls}" data-tip="${esc(tipText)}"><i class="dot"></i>${label}</span>`;
    if (it.lb === "both") return cell("", "Own + public", `Has its own leaderboard, and is listed on ${it.agg.source}`);
    if (it.lb === "own") return cell("", "Own board", `The benchmark's own leaderboard${checked}`);
    if (it.lb === "aggregator") {
      const own = { listed: "own leaderboard exists, top score not read", none: "no own leaderboard found", unchecked: "own leaderboard not checked" }[it.search.status] || "";
      return cell(it.search.status === "listed" ? "" : "agg", it.search.status === "listed" ? "Own + public" : "Public board", `Listed on ${it.agg.source}; ${own}${checked}`);
    }
    if (it.lb === "listed") return cell("listed", "Own board", `Own leaderboard exists; its top score could not be read${checked}`);
    if (it.lb === "none") return cell("none", "None found", `No public leaderboard found${checked}${it.lb_hint ? " · the abstract mentions one" : ""}`);
    return cell("unchecked", "Not searched", it.search.note || "Not searched yet");
  }

  const short = (v) => (v >= 10000 ? Math.round(v / 1000) + "k" : v >= 1000 ? (v / 1000).toFixed(1) + "k" : String(v));
  // Stars and citations. A dash means no data was found, not zero.
  function attentionCell(it) {
    const m = it.metrics || {}, fetched = it.sig && it.sig.checked;
    const part = (v, unit, tipText) => (v == null ? "" : `<span data-tip="${esc(tipText)}"><b>${short(v)}</b> ${unit}</span>`);
    const stars = it.sig && it.sig.repo ? m.stars : m.stars > 0 ? m.stars : null;
    const cites = m.citations > 0 ? m.citations : null;      // zero citations on a new paper says nothing
    const html = part(stars, "★", `GitHub stars${it.sig && it.sig.repo ? " · " + it.sig.repo : ""}${fetched ? " · fetched " + fetched : " · from Radar"}`) +
      part(cites, "cit", `Citations (Semantic Scholar)${fetched ? " · fetched " + fetched : " · from Radar"}`);
    return `<div class="att">${html || '<span class="none">—</span>'}</div>`;
  }

  function listPanel() {
    const rows = scoped();
    const key = { tier: (i) => TIER_RANK[tierOf(i)] + "|" + String(99999999 - +(when(i) || "0000-00-00").replace(/-/g, "")), name: (i) => i.name.toLowerCase(), best: (i) => (i.best == null ? -1 : i.best), date: (i) => when(i) || "",
      stars: (i) => (i.metrics && i.metrics.stars) || 0, cites: (i) => (i.metrics && i.metrics.citations) || 0 }[S.sort];
    rows.sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0) * S.dir || a.name.localeCompare(b.name));
    const arrow = (k) => (S.sort === k ? (S.dir > 0 ? "↑" : "↓") : "↕");
    const th = (k, label) => `<button type="button" data-sort="${k}">${label} <span>${arrow(k)}</span></button>`;
    const scope = (S.cls ? CLASS[S.cls].name : "All classes") + (S.sub ? " / " + S.sub : "");
    const week = S.week ? ` <button type="button" class="badge ok" data-clear-week>week of ${S.week} ×</button>` : "";
    const body = rows.slice(0, S.limit).map((it, n) => `
      <tr data-id="${esc(it.id)}">
        <td class="num">${n + 1}</td>
        <td>${tierBadge(it)}</td>
        <td class="name"><a href="#/b/${encodeURIComponent(it.id)}">${esc(it.name)}</a>${it.new ? '<span class="tagmm new" data-tip="Under 15 days old, no leaderboard yet, attention under the bar. Judged on what its pages show">new</span>' : ""}${it.mm ? '<span class="tagmm">MM</span>' : ""}${it.hi1 ? `<span class="tagmm hi" data-tip="${it.hi1} task${it.hi1 === 1 ? "" : "s"} in Harbor Index v1">HI v1</span>` : ""}</td>
        <td><span class="mode ${it.mode}" data-tip="${esc(MODE[it.mode][1] + ". " + MODE[it.mode][2])}">${MODE[it.mode][0]}</span></td>
        <td class="hide-s"><span class="cell-cls">${icon(it.cls, 16)}${esc(LABELS[it.cls][0])}${it.sub ? ` · <span class="subname">${esc(it.sub)}</span>` : ""}</span></td>
        <td>${sotaCell(it)}</td>
        <td class="hide-s">${attentionCell(it)}</td>
        <td class="date">${when(it) || "—"}</td>
        <td class="hide-s">${lbCell(it)}</td>
      </tr>`).join("");
    return `
      <div class="panel-head">
        <span><b>${esc(scope)}</b> / ${num(rows.length)} benchmarks${week}</span>
        <span class="legend">
          <span><i class="sw"></i>own leaderboard</span>
          <span><i class="sw agg"></i>aggregator</span>
          <span><i class="sw paper"></i>paper-reported</span>
          <span><i class="sw hot"></i>&gt;90% saturated</span>
        </span>
      </div>
      ${rows.length ? `<div class="scroll"><table class="list">
        <thead><tr><th class="num">#</th><th>${th("tier", "Tier")}</th><th>${th("name", "Benchmark")}</th><th>Mode</th><th class="hide-s">Class</th><th>${th("best", "SOTA")}</th><th class="hide-s">${th("stars", "Stars")} ${th("cites", "Cites")}</th><th>${th("date", "Date")}</th><th class="hide-s">Leaderboard</th></tr></thead>
        <tbody>${body}</tbody></table></div>
        ${rows.length > S.limit ? `<button type="button" class="more" data-more>Show ${Math.min(PAGE, rows.length - S.limit)} more of ${num(rows.length - S.limit)}</button>` : ""}`
        : `<div class="empty">Nothing in the pool matches</div>`}`;
  }

  // ---------- timeline ----------
  function timelinePanel() {
    const start = monday(day(DATA.meta.snapshots.first));
    const end = day(DATA.meta.snapshots.last);
    const weeks = [];
    for (let d = start; d <= end; d = addDays(d, 7)) weeks.push(iso(d));
    const startIso = weeks[0];
    const items = scoped({ anyClass: true, anyWeek: true });
    const grid = {}; // cls -> [earlier, w0, w1, ...]
    let undated = 0;
    for (const c of CIDS) grid[c] = new Array(weeks.length + 1).fill(0);
    items.forEach((it) => {
      const d = when(it);
      if (!d) { undated++; return; }
      const col = d < startIso ? 0 : Math.min(weeks.length, 1 + Math.floor((day(d) - start) / (7 * 864e5)));
      grid[it.cls][col]++;
    });
    const colTot = weeks.map((_, w) => { let t = 0; for (const c of CIDS) t += grid[c][w + 1]; return t; });
    const early = Object.values(grid).reduce((a, r) => a + r[0], 0);
    const maxCol = Math.max(1, ...colTot);
    const maxCell = Math.max(1, ...Object.values(grid).flatMap((r) => r.slice(1)));
    const cols = `max-content 52px repeat(${weeks.length}, minmax(30px, 1fr)) max-content`;

    let html = `<div class="rowlab total">All classes, new per week</div><div class="bars early" data-tip="${early} dated before Radar coverage began"><div style="width:100%"><div class="barsn">${early}</div></div></div>`;
    html += colTot.map((t, w) => `<div class="bars" data-tip="Week of ${weeks[w]}: ${t} new"><div style="width:100%"><div class="barsn">${t}</div><i style="height:${Math.round((t / maxCol) * 44)}px"></i></div></div>`).join("");
    html += `<div class="tot"></div>`;
    for (const c of CIDS) {
      const dim = S.cls && S.cls !== c ? " dim" : "";
      const cell = (n, w, isEarly) => {
        const a = isEarly ? 0 : Math.round(Math.sqrt(n / maxCell) * 92);
        const style = n && !isEarly ? `background:color-mix(in srgb, var(--accent) ${a}%, var(--muted));color:${a > 52 ? "#fff" : "var(--fg)"}` : "";
        const tipText = isEarly ? `${CLASS[c].name}: ${n} dated before ${startIso}` : `${CLASS[c].name} · week of ${weeks[w]} · ${n} new`;
        const attrs = isEarly || !n ? "" : ` role="button" tabindex="0" data-cell="${c}|${weeks[w]}" style="${style};cursor:pointer"`;
        return `<div class="cell${n ? "" : " z"}${dim}" data-tip="${esc(tipText)}"${attrs || (style ? ` style="${style}"` : "")}>${n}</div>`;
      };
      html += `<div class="rowlab${S.cls === c ? " on" : ""}">${icon(c, 16)}${esc(CLASS[c].name)}</div>`;
      html += cell(grid[c][0], 0, true);
      html += weeks.map((_, w) => cell(grid[c][w + 1], w, false)).join("");
      html += `<div class="tot">${grid[c].reduce((a, b) => a + b, 0)}</div>`;
    }
    html += `<div></div><div class="col">earlier</div>` + weeks.map((w, i) => `<div class="col">${i % 2 ? "" : w.slice(5)}</div>`).join("") + `<div></div>`;
    return `
      <div class="panel-head">
        <span><b>New benchmarks per class</b> / by week of first publication</span>
        <span class="legend"><span><i class="sw none"></i>0</span><span><i class="sw" style="opacity:.45"></i>few</span><span><i class="sw"></i>many</span></span>
      </div>
      <div class="scroll"><div class="heat" style="grid-template-columns:${cols}">${html}</div></div>
      <p class="note">Radar snapshots cover ${DATA.meta.snapshots.first} to ${DATA.meta.snapshots.last}. Click a cell to list its benchmarks.${undated ? ` ${undated} undated benchmarks are not shown.` : ""}</p>`;
  }

  // ---------- saturation ----------
  function saturationPanel() {
    const items = scoped({ anyClass: true });
    const usable = (it) => it.best != null && (S.basis === "all" || it.basis !== "paper");
    const ticks = [0, 25, 50, 75, 90, 100];
    let html = `<div></div><div class="strip axis">${ticks.map((t) => `<span class="tick" style="left:${t}%">${t}</span>`).join("")}</div><div></div>`;
    for (const c of CIDS) {
      const mine = items.filter((it) => it.cls === c);
      const scored = mine.filter(usable);
      const sat = scored.filter((it) => it.best > DATA.meta.saturated_above);
      const share = scored.length ? Math.round((sat.length / scored.length) * 100) : null;
      const pts = scored.map((it) => {
        const y = 14 + hash01(it.id) * 72;
        return `<button type="button" class="pt ${kindCls(it.basis)} ${it.best > 90 ? "hot" : ""}" style="left:${Math.min(100, Math.max(0, it.best))}%;top:${y.toFixed(0)}%" data-go="${esc(it.id)}" data-tip="${esc(it.name)} · ${pct(it.best)} · ${esc(KIND[it.basis].toLowerCase())}" aria-label="${esc(it.name)} ${pct(it.best)}"></button>`;
      }).join("");
      const w = (n) => (mine.length ? (n / mine.length) * 100 : 0);
      html += `
        <div class="rowlab${S.cls === c ? " on" : ""}">${icon(c, 16)}${esc(CLASS[c].name)}</div>
        <div class="strip"><div class="zone"></div>${pts}</div>
        <div class="share" data-tip="${sat.length} saturated of ${scored.length} with a score; ${mine.length - scored.length} of ${mine.length} have no score">
          <div class="stack"><i class="a" style="width:${w(sat.length)}%"></i><i class="b" style="width:${w(scored.length - sat.length)}%"></i></div>
          <div class="pc"><b>${share == null ? "—" : share + "%"}</b> <span>${sat.length}/${scored.length}</span></div>
        </div>`;
    }
    return `
      <div class="panel-head">
        <span><b>Share saturated per class</b> / best score above ${DATA.meta.saturated_above}%</span>
        <span class="legend">
          <span><i class="sw hot"></i>saturated</span><span><i class="sw"></i>scored, not saturated</span><span><i class="sw none"></i>no score</span>
          <span class="seg" role="group" aria-label="Score basis">
            <button type="button" data-basis="all" aria-pressed="${S.basis === "all"}">All scores</button>
            <button type="button" data-basis="leaderboard" aria-pressed="${S.basis === "leaderboard"}">Leaderboards only</button>
          </span>
        </span>
      </div>
      <div class="scroll"><div class="sat">${html}</div></div>
      <p class="note">Each dot is one benchmark at its best known score: its own leaderboard if one was found, else an aggregator's, else the paper's. Filled: own leaderboard. Tinted: aggregator. Hollow: stated in the paper's abstract.</p>`;
  }

  function panel() {
    document.getElementById("panel").innerHTML = S.view === "timeline" ? timelinePanel() : S.view === "saturation" ? saturationPanel() : listPanel();
  }

  // ---------- detail ----------
  function coverage(it) {
    const c = it.cov;
    const t = (k, cls, s) => `<div class="covtag ${cls}"><span class="k">${k}</span><span class="s">${s}</span></div>`;
    const data = { public: ["yes", "Public"], partial: ["part", "Partial"], private: ["no", "Private"] }[c.data] || ["unk", "Not stated"];
    const scores = { yes: ["yes", "Reported"], no: ["no", "None"] }[c.scores] || ["unk", "Not stated"];
    const traj = c.traj === "yes" ? ["yes", "Released"] : ["unk", "Not stated"];
    const infra = { yes: ["yes", "Released"], repo: ["part", "Repo linked"] }[c.infra] || ["unk", "Not stated"];
    return t("Data", data[0], data[1]) + t("Scores", scores[0], scores[1]) + t("Trajectories", traj[0], traj[1]) + t("Infra", infra[0], infra[1]);
  }

  function sotaCard(it) {
    const axis = `<div class="axis90"><span style="left:0;transform:none">0</span><span style="left:90%">90</span><span style="left:100%;transform:translateX(-100%)">100</span></div>`;
    const link = (url, text) => `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener"><b>${esc(text)}</b></a>`;
    const host = (url) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch (err) { return "link"; } };
    const o = it.own, a = it.agg, p = it.paper, se = it.search;

    // Headline: the best known percentage, or what is known instead.
    let html = "<h2>SOTA</h2>";
    if (it.best != null) {
      html += `<div class="big"><span class="v ${it.sat ? "hot" : ""}">${pct(it.best)}</span>${it.sat ? '<span class="badge hot">Saturated</span>' : '<span class="badge ok">Not saturated</span>'}<span class="badge">${KIND[it.basis]}</span></div>`;
    } else if ((o && o.raw != null) || (a && a.raw != null)) {
      const s = o && o.raw != null ? o : a;
      html += `<div class="big"><span class="v">${num(s.raw)}</span><span class="badge">${s === a && s.scale ? "of " + num(s.scale) : esc((s === o && s.metric) || "points")} · not a percentage</span><span class="badge">${KIND[s === o ? "own" : "aggregator"]}</span></div>`;
    } else {
      const text = { listed: "Leaderboard exists", none: "No public leaderboard", unchecked: "Not checked" }[it.lb] || "No score";
      const badge = { listed: "Top score not read", none: `Searched ${se.checked || ""}`, unchecked: "Leaderboard search has not covered this one" }[it.lb];
      html += `<div class="big"><span class="v off">${text}</span>${badge ? `<span class="badge">${esc(badge)}</span>` : ""}</div>`;
    }

    // One block per kind of score that exists.
    const block = (kind, value, hot, line, quote) => `
      <div class="kind">
        <div class="kind-head"><span class="kind-name">${KIND[kind]}</span><b>${value}</b></div>
        ${hot == null ? "" : `<div class="track ${kindCls(kind)} ${hot > DATA.meta.saturated_above ? "hot" : ""}"><i style="width:${Math.min(100, Math.max(1, hot))}%"></i></div>${axis}`}
        <p class="src">${line}</p>${quote ? `<p class="quote">“${esc(quote)}”</p>` : ""}
      </div>`;
    if (o) {
      html += block("own", o.pct != null ? pct(o.pct) : num(o.raw), o.pct,
        `Top <b>${esc(o.model || "")}</b>${o.metric ? " · " + esc(o.metric) : ""}${o.pct == null ? " · not a percentage" : ""}${o.entries ? ` · ${o.entries} systems listed` : ""} · ${link(o.url, host(o.url))} · found ${esc(o.found)}${o.checked !== o.found ? ", checked " + esc(o.checked) : ""}`, o.quote);
    }
    if (a) {
      html += block("aggregator", a.pct != null ? pct(a.pct) : num(a.raw), a.pct,
        `${link(a.url, a.source)} · crawled ${esc(a.as_of)}${a.model ? ` · top <b>${esc(a.model)}</b>${a.org ? " (" + esc(a.org) + ")" : ""}` : ""}${a.models ? ` · ${a.models} models listed` : ""}${a.self_reported ? " · vendor self-reported" : ""}${a.pct == null ? " · not a percentage" : ""}`);
    }
    if (p) {
      html += block("paper", pct(p.pct), p.pct,
        `Stated in the abstract${p.metric ? " · " + esc(p.metric) : ""}${p.model ? " · " + esc(p.model) : ""}`, p.quote);
    }

    // What the search for an own leaderboard did.
    if (!o) {
      const pages = `${se.pages || 0} page${se.pages === 1 ? "" : "s"} read`;
      const line = {
        listed: `Own leaderboard: ${se.url ? link(se.url, host(se.url)) : "found"}, top score not read${se.note ? " (" + esc(se.note) + ")" : ""}. Checked ${esc(se.checked || "")}.`,
        none: `Own leaderboard: none found. Searched ${esc(se.checked || "")}, ${pages}${se.note ? " · " + esc(se.note) : ""}.${it.lb_hint ? " The abstract mentions one." : ""}`,
        unchecked: `Own leaderboard: not checked${se.note ? " (" + esc(se.note) + ")" : ""}.${it.lb_hint ? " The abstract mentions one." : ""}`,
      }[se.status];
      if (line) html += `<p class="src searchline">${line}</p>`;
    }
    return html;
  }

  // What the judge was actually given to read.
  function readLine(t) {
    const r = t.read;
    if (!r) return "Read: abstract, README and file list (an earlier run that did not read the paper).";
    const words = (n) => `${num(Math.round(n / 6 / 100) * 100)} words`;
    const parts = [];
    if (r.paper_chars) parts.push(`<b>the whole paper</b> (${words(Math.min(r.paper_chars, 160000))}, ${esc(r.paper)}${r.paper_cut ? `; <b class="cut">cut for length</b>, ${words(r.paper_chars)} in all` : ""})`);
    if (r.readme_chars) parts.push(`the README (${words(r.readme_chars)})`);
    if (r.files) parts.push(`${r.files} top-level file names`);
    if (!parts.length) return "Read: nothing. No paper and no repository could be found.";
    return "Read: " + parts.join(", ") + (r.paper_chars ? "." : ". <b class=\"cut\">No paper was read</b>: none is linked.");
  }

  // Section 3.0 of the standard: facts about the benchmark, looked up before any verdict.
  const CHECK = {
    data_released: ["Tasks public", { yes: "yes", partial: "partly", no: "no" }, { yes: "good", partial: "mid", no: "bad" }],
    provenance: ["Tasks come from", { real_artifacts: "real artifacts", expert_written: "experts", generated: "generated", mixed: "mixed" }, { real_artifacts: "good", expert_written: "good", generated: "bad", mixed: "mid" }],
    human_review: ["Reviewed by people", { yes: "yes", no: "no" }, { yes: "good", no: "bad" }],
    domain_expertise: ["Needs domain expertise", { yes: "yes", no: "no" }, { yes: "good", no: "mid" }],
    verifier: ["Verifier", { executable: "executable tests", exact_match: "exact match", llm_judge: "model judge", human: "human", mixed: "mixed" }, { executable: "good", exact_match: "good", llm_judge: "mid", human: "mid", mixed: "mid" }],
    judge_validated: ["Judge checked against people", { yes: "yes", no: "no", not_applicable: "no judge" }, { yes: "good", no: "bad", not_applicable: "na" }],
    solvable: ["Tasks shown to be solvable", { yes: "yes", no: "no" }, { yes: "good", no: "bad" }],
    environment: ["Runs in", { container: "a container", live_web: "live websites", simulator: "a simulator", hardware: "hardware" }, { container: "good", live_web: "bad", simulator: "mid", hardware: "bad" }],
    gaming: ["Reward hacking addressed", { yes: "yes", no: "no" }, { yes: "good", no: "bad" }],
    variance: ["Repeated runs", { yes: "yes", no: "no" }, { yes: "good", no: "mid" }],
  };
  function checksBlock(t) {
    const c = t.checks;
    if (!c) return "";
    const cell = (k) => { const v = c[k].value, d = CHECK[k]; const shown = d[1][v] || "not stated";
      return `<div class="chk ${d[2][v] || "na"}" ${c[k].quote ? `data-tip="${esc("“" + c[k].quote + "”")}"` : ""}><span class="k">${d[0]}</span><span class="s">${shown}</span></div>`; };
    const b = c.best_score, z = c.size;
    const nums = [b.percent != null ? `best score <b>${num(b.percent)}%</b>${b.system ? " (" + esc(b.system) + (b.run_by ? ", run by " + esc(b.run_by) : "") + ")" : ""}` : "no best score quoted",
      c.top_gap != null ? `top three within <b>${num(c.top_gap)}</b> points` : "", z.tasks != null ? `<b>${num(z.tasks)}</b> tasks` : "",
      z.categories != null ? `<b>${num(z.categories)}</b> task categories` : "", z.sources != null ? `<b>${num(z.sources)}</b> sources` : ""].filter(Boolean).join(" · ");
    const risks = (t.risks || []).map((r) => `<li>${esc(r.risk)}${r.quote ? ` <span class="src-inline">“${esc(r.quote)}”</span>` : ""}</li>`).join("");
    return `
      <h3 class="sub-h">Facts about the benchmark <span class="src-inline">hover for the sentence each rests on; dashed = the paper does not say</span></h3>
      <div class="chks">${Object.keys(CHECK).map(cell).join("")}</div>
      <p class="src">${nums}</p>
      ${risks ? `<h3 class="sub-h">To settle before bringing it into Harbor</h3><ul class="risks">${risks}</ul>` : ""}`;
  }

  function tierCard(it) {
    const t = it.tier;
    if (it.covered) return `<section class="card span2"><h2>Tier</h2><div class="big"><span class="tier big covered">Covered</span></div><p class="reason">${esc(COVER[it.covered])}, so it is not a new candidate. It stays here for reference.</p></section>`;
    if (!t) return `<section class="card span2"><h2>Tier</h2><p class="src" style="margin:0">Not judged yet.</p></section>`;
    const names = { real: "Real", diverse: "Diverse", difficult: "Difficult", valuable: "Valuable", solid: "Solid", attention: "Attention" };
    const dims = Object.keys(names).filter((k) => t.dimensions[k]).map((k) => {
      const d = t.dimensions[k];
      return `<tr><td>${names[k]}</td><td><span class="verdict ${d.verdict}">${d.verdict.replace("_", " ")}</span></td><td>${d.quote ? `“${esc(d.quote)}”` : `<span class="src-inline">${d.verdict === "no_evidence" ? "the pages read do not say" : "rests on the pool's facts (score, stars, citations)"}</span>`}</td></tr>`;
    }).join("");
    const covNames = { data: "Task data", scores: "Scores", task_scores: "Per-task scores", trajectories: "Trajectories", process: "Judge prompts / filter code", infra: "Harness" };
    const cov = Object.keys(covNames).filter((k) => t.coverage[k]).map((k) => `<span class="covdot ${t.coverage[k]}" data-tip="${esc(covNames[k] + ": " + t.coverage[k].replace("_", " "))}">${covNames[k]}</span>`).join("");
    const trail = it.tier_trail.length > 1 ? `<p class="src">Earlier: ${it.tier_trail.slice(0, -1).map((x) => `${esc(TIER[x[1]][0])} (${esc(x[0])})`).join(", ")}</p>` : "";
    const pages = (t.pages || []).map((u) => `<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener">${esc(u.replace(/^https?:\/\//, ""))}</a>`).join(", ");
    return `
      <section class="card span2 tiercard ${t.tier}"><h2>Tier</h2>
        ${it.new ? `<p class="src" style="margin:0 0 12px"><span class="tagmm new" style="margin:0 6px 0 0">new</span>Under 15 days old with no leaderboard: missing scores and attention do not count against it.</p>` : ""}
        <div class="big"><span class="tier big ${t.tier}">${TIER[t.tier][0]}</span><span class="badge">${esc(RULE[t.rule] || "")}</span></div>
        <p class="reason">${esc(t.reason)}</p>
        ${dims ? `<table class="cmp dims"><thead><tr><th>Dimension</th><th>Verdict</th><th>Evidence quoted from the pages</th></tr></thead><tbody>${dims}</tbody></table>` : ""}
        ${checksBlock(t)}
        ${cov ? `<div class="covrow"><span class="kind-name">Public</span>${cov}</div>` : ""}
        ${t.harbor_fit && t.harbor_fit.container ? `<p class="src">Runs in a container with a programmatic verifier: <b>${esc(t.harbor_fit.container)}</b>${t.harbor_fit.blocker ? " · " + esc(t.harbor_fit.blocker) : ""}</p>` : ""}
        ${t.notes && t.notes.length ? `<p class="src">Adjusted automatically: ${esc(t.notes.map((n) => n.replace(/^standard [\d.]+: /, "")).join("; "))}.</p>` : ""}
        <p class="src">${readLine(t)}</p>
        <p class="src">Judged ${esc(t.date)} by ${t.model ? esc(t.model) : "rule, no model"}${pages ? " · " + pages : ""}. Not checked by a person.</p>
        ${trail}
      </section>`;
  }

  function detail(id) {
    const it = DATA.items.find((x) => x.id === id);
    if (!it) { app.innerHTML = `<a class="back" href="#/list">← Pool</a><div class="empty">Not in the pool</div>`; return; }
    document.title = `${it.name} · BENCH-POOL`;
    const kindLabel = { paper: "Paper", code: "Code", data: "Data", leaderboard: "Leaderboard", space: "Space", web: "Link" };
    const links = it.links.map((l) => `<a class="btn" href="${esc(safeUrl(l.url))}" target="_blank" rel="noopener">${kindLabel[l.kind] || "Link"} ↗</a>`).join("");
    const m = it.metrics || {};
    const attention = [["stars", "GitHub stars"], ["citations", "citations"], ["upvotes", "HF upvotes"], ["downloads", "downloads"], ["likes", "likes"]]
      .filter(([k]) => m[k] > 0).map(([k, l]) => `${num(m[k])} ${l}`).join(" · ");
    const who = [it.authors.join(", ") + (it.author_count > it.authors.length ? ` +${it.author_count - it.authors.length}` : ""), it.orgs.join(", ")].filter(Boolean).join(" — ");
    const row = (k, v) => (v ? `<dt>${k}</dt><dd>${v}</dd>` : "");
    app.innerHTML = `
      <a class="back" href="#/${S.view}">← Pool</a>
      <div class="crumb">${icon(it.cls, 18)}<span>${esc(CLASS[it.cls].name)}${it.sub ? " / " + esc(it.sub) : ""}</span></div>
      <h1 class="d-name">${esc(it.name)}</h1>
      <div class="d-badges"><span class="badge ok" data-tip="${esc(MODE[it.mode][2])}">${MODE[it.mode][1]}</span>${it.covered ? `<span class="badge">${it.covered === "v1" ? "Already in Harbor Index v1" : "Already has a Harbor adapter"}</span>` : ""}</div>
      ${it.title && it.title !== it.name ? `<p class="d-title">${esc(it.title)}</p>` : ""}
      <div class="d-grid">
        ${tierCard(it)}
        <section class="card">${sotaCard(it)}</section>
        <section class="card"><h2>Information coverage</h2><div class="cov">${coverage(it)}</div></section>
        <section class="card span2">
          <dl class="lines">
            ${row(it.mode === "non" ? "Model does" : "Agent does", esc(it.does))}
            ${row("Realism", esc(it.real))}
            ${row("Value", esc(it.val))}
          </dl>
        </section>
        <section class="card span2">
          <dl class="lines">
            ${row("Published", esc(it.date || "") + (it.date_basis && it.date_basis !== "radar" ? ` <span class="src-inline">${esc(it.date_basis)} date</span>` : ""))}
            ${row("Seen by Radar", esc(it.seen || ""))}
            ${row("Sources", esc(it.sources.map((x) => (x === "Harbor Adapter List" ? "Established-benchmark list" : x)).join(" · ")))}
            ${row("By", esc(who))}
            ${row("Attention", esc(attention) + (it.sig ? ` <span class="src-inline">fetched ${esc(it.sig.checked)}${it.sig.repo ? " · " + esc(it.sig.repo) + (it.sig.pushed ? ", last push " + esc(it.sig.pushed) : "") + (it.sig.archived ? ", archived" : "") : ""}${it.sig.venue ? " · " + esc(it.sig.venue) : ""}</span>` : attention ? ' <span class="src-inline">from Radar, not refreshed</span>' : ""))}
            ${row("Tags", `<div class="tags">${it.mm ? '<span class="tag mm">multimodal</span>' : ""}${it.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>`)}
            ${row("Links", links ? `<div class="linkrow">${links}</div>` : "")}
          </dl>
        </section>
      </div>`;
    window.scrollTo(0, 0);
  }

  // ---------- data page ----------
  function about() {
    const f = DATA.meta.funnel;
    const steps = [["Radar records read", f.records], ["Candidates after rules and merging", f.candidates], ["Judged to be a benchmark", f.kept_records], ["Benchmarks in the pool, same names merged", f.benchmarks],
      ["· agentic", f.by_mode.agentic || 0], ["· modified-agentic", f.by_mode.modified || 0], ["· non-agentic", f.by_mode.non || 0]];
    const lead = Math.log10(steps[0][1]);
    const L = DATA.meta.leaderboards;
    app.innerHTML = `
      <a class="back" href="#/list">← Pool</a>
      <h1 class="d-name">How the pool is filled</h1>
      <p class="d-title">Benchmark Radar snapshots ${esc(DATA.meta.snapshots.first)} to ${esc(DATA.meta.snapshots.last)} (${DATA.meta.snapshots.days} days). Built ${esc(DATA.meta.generated)}.</p>
      <div class="d-grid">
        <section class="card span2"><h2>Funnel (bar length on a log scale)</h2>
          <div class="funnel">${steps.map(([k, v]) => `<span class="k">${k}</span><span class="w"><i style="width:${Math.max(1, (Math.log10(Math.max(v, 1)) / lead) * 100)}%"></i></span><span class="n">${num(v)}</span>`).join("")}</div>
          ${f.unlabelled ? `<p class="src">${num(f.unlabelled)} candidates are not labelled yet and are missing from the pool.</p>` : ""}
        </section>
        <section class="card span2"><h2>What each field is</h2>
          <table class="real">
            <tr><td><span class="badge ok">Source data</span></td><td>Titles, dates, authors, links, attention counts and fine tags come from Radar unchanged.</td></tr>
            <tr><td><span class="badge ok">Aggregator leaderboard</span></td><td>${num(L.aggregator)} benchmarks. The top row of Radar's dated crawls of LLM Stats, Artificial Analysis and Benchmark Saturation, matched by benchmark name. No protocol is stated and many rows are vendor self-reported. ${num(L.from_crawls)} benchmarks are in the pool because these crawls list them.</td></tr>
            <tr><td><span class="badge ok">Own leaderboard</span></td><td>${num(L.own)} benchmarks with a top score, ${num(L.own_listed)} more where a leaderboard exists but its top score could not be read (tables drawn by script, several tracks with no overall). A search starts from Radar's links and reads the paper's Hugging Face page, the GitHub README, the project page and Hugging Face datasets and spaces; if the paper's record links none of these, it reads the paper's full text for a link. A model reads the pages; a score is kept only when the quoted row is on the page and contains the number and the system's name. Last search ${esc(L.last_search || "never")}; each benchmark is searched again after a week.</td></tr>
            <tr><td><span class="badge">Model-read</span></td><td>The benchmark gate, the mode, the class and sub-class, the multimodal tag, the realism and value lines and the coverage tags were written by a language model from the title and abstract. Not checked by a person.</td></tr>
            <tr><td><span class="badge">Paper-reported</span></td><td>${num(L.paper)} benchmarks. The best score the abstract states, kept only when the quoted words appear in the abstract and contain the number. It is the authors' own figure, not a leaderboard, and is drawn hatched.</td></tr>
            <tr><td><span class="badge hot">Limits</span></td><td>"None" means the search ran and found no leaderboard (${num(L.searched_none)} benchmarks); it did not use a web search engine, so a leaderboard that none of the benchmark's own pages link to is missed. "Not checked" (${num(L.unchecked)}) means there was no link to start from or the pages could not be opened. Papers with Code is closed and was not searched. The best known score is the own leaderboard's if there is one, else the aggregator's, else the paper's. "Not stated" coverage means the abstract does not say. Aggregator crawls date from August to November 2026.</td></tr>
          </table>
        </section>
        <section class="card span2"><h2>Gate</h2>
          <dl class="lines">
            <dt>Keep</dt><dd>Anything that releases a benchmark, evaluation suite or evaluation environment others can run. This is the only inclusion rule.</dd>
            <dt>Drop</dt><dd>Models, methods, frameworks, surveys, training-only datasets, and papers that only use existing benchmarks (${num(f.not_benchmark)} candidates).</dd>
            <dt>Mode</dt><dd>Each benchmark is agentic, modified-agentic or non-agentic, following the Harbor Index v1 paper. The mode is a signal for recommending a benchmark, not a reason to leave it out.</dd>
            <dt>Not covered</dt><dd>Radar records enter only if Radar tagged them agentic or the title names something an agent does. Other benchmarks get in when a public leaderboard lists them, when they are on a hand-kept list of established benchmarks, or when people have clearly noticed them (stars, upvotes, citations).</dd>
          </dl>
        </section>
      </div>`;
    document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === "about"));
    window.scrollTo(0, 0);
  }

  // ---------- new ----------
  const MODE_ORDER = { agentic: 0, modified: 1, non: 2 };
  const attention = (it) => ((it.metrics && it.metrics.stars) || 0) + ((it.metrics && it.metrics.citations) || 0) * 5 + ((it.metrics && it.metrics.upvotes) || 0);
  function newPage() {
    const last = DATA.meta.snapshots.last;
    const back = (n) => iso(addDays(day(last), -n));
    const groups = [["This week", back(6), "9999"], ["Last week", back(13), back(6)], ["Two to four weeks ago", back(29), back(13)]];
    const pool = DATA.items.filter((it) => it.seen && (!S.mode || it.mode === S.mode));
    const chips = `<div class="chips left">` +
      `<button type="button" class="chip" data-mode="" aria-pressed="${!S.mode}">all modes</button>` +
      Object.keys(MODE).map((m) => `<button type="button" class="chip" data-mode="${m}" aria-pressed="${S.mode === m}"><span class="mode ${m}">${MODE[m][0]}</span>${MODE[m][1].toLowerCase()}</button>`).join("") + `</div>`;
    const line = (it) => {
      const old = it.date && (day(it.seen) - day(it.date)) / 864e5 > 60;
      return `<tr data-id="${esc(it.id)}">
        <td>${tierBadge(it)}</td>
        <td><span class="mode ${it.mode}" data-tip="${esc(MODE[it.mode][1])}">${MODE[it.mode][0]}</span></td>
        <td class="name"><a href="#/b/${encodeURIComponent(it.id)}">${esc(it.name)}</a>${it.mm ? '<span class="tagmm">MM</span>' : ""}${old ? `<span class="tagmm" data-tip="First published ${esc(it.date)}; Radar first saw it ${esc(it.seen)}">older paper</span>` : ""}</td>
        <td class="hide-s"><span class="cell-cls">${icon(it.cls, 16)}${esc(LABELS[it.cls][0])}</span></td>
        <td class="does hide-s">${esc(it.does)}</td>
        <td class="hide-s">${attentionCell(it)}</td>
        <td>${sotaCell(it)}</td>
        <td class="date">${esc(it.seen)}</td>
      </tr>`;
    };
    const sections = groups.map(([title, from, to]) => {
      const rows = pool.filter((it) => it.seen >= from && it.seen < to)
        .sort((a, b) => TIER_RANK[tierOf(a)] - TIER_RANK[tierOf(b)] || MODE_ORDER[a.mode] - MODE_ORDER[b.mode] || attention(b) - attention(a) || a.name.localeCompare(b.name));
      const n = (m) => rows.filter((it) => it.mode === m).length;
      return `<section class="panel">
        <div class="panel-head"><span><b>${title}</b> / ${num(rows.length)} new · ${n("agentic")} agentic · ${n("modified")} modified · ${n("non")} non-agentic</span><span class="legend">first seen ${esc(from)}${to === "9999" ? " to " + esc(last) : " to " + esc(iso(addDays(day(to), -1)))}</span></div>
        ${rows.length ? `<div class="scroll"><table class="list"><thead><tr><th>Tier</th><th>Mode</th><th>Benchmark</th><th class="hide-s">Class</th><th class="hide-s">What it tests</th><th class="hide-s">Stars · Cites</th><th>SOTA</th><th>First seen</th></tr></thead><tbody>${rows.map(line).join("")}</tbody></table></div>` : `<div class="empty">Nothing new</div>`}
      </section>`;
    }).join("");
    app.innerHTML = `
      <h1 class="d-name">New benchmarks</h1>
      <p class="d-title">By the day Radar first saw them, up to ${esc(last)}. By tier, then agentic first, then by attention. "Older paper" marks a benchmark first published more than 60 days before Radar saw it.</p>
      ${chips}
      <section class="card notice"><h2>Tier changes this week</h2>${tierChanges(last)}</section>
      ${sections}`;
    setNav("new");
  }

  function tierChanges(last) {
    const since = iso(addDays(day(last), -6));
    const moved = DATA.items.filter((it) => !it.covered && it.tier && it.tier_trail.length > 1 && it.tier_trail[it.tier_trail.length - 1][0] >= since)
      .sort((a, b) => TIER_RANK[tierOf(a)] - TIER_RANK[tierOf(b)]);
    if (!moved.length) return `<p class="src">No benchmark changed tier this week.</p>`;
    return `<table class="cmp"><tbody>${moved.slice(0, 40).map((it) => { const a = it.tier_trail[it.tier_trail.length - 2];
      return `<tr><td><a href="#/b/${encodeURIComponent(it.id)}">${esc(it.name)}</a></td><td>${esc(TIER[a[1]][0])} → <b>${esc(TIER[it.tier.tier][0])}</b></td><td>${esc(it.tier.reason)}</td></tr>`; }).join("")}</tbody></table>
      ${moved.length > 40 ? `<p class="src">${num(moved.length - 40)} more changed.</p>` : ""}`;
  }

  // ---------- filter ----------
  let DROPPED = null;
  const F = { q: "", limit: 60 };
  function droppedTable() {
    if (!DROPPED) return `<div class="empty">Loading…</div>`;
    const words = F.q.toLowerCase().split(/\s+/).filter(Boolean);
    const rows = DROPPED.filter((d) => words.every((w) => (d.title + " " + d.why).toLowerCase().includes(w)));
    return `<div class="panel-head"><span><b>Turned away at the gate</b> / ${num(rows.length)} of ${num(DROPPED.length)} candidates judged not to be a benchmark</span></div>
      <div class="scroll"><table class="list plain"><thead><tr><th>Candidate</th><th>Reason given</th><th class="hide-s">Source</th><th class="hide-s">Date</th></tr></thead><tbody>
      ${rows.slice(0, F.limit).map((d) => `<tr><td class="name">${d.url ? `<a href="${esc(safeUrl(d.url))}" target="_blank" rel="noopener">${esc(d.title)}</a>` : esc(d.title)}</td><td class="does">${esc(d.why)}</td><td class="hide-s date">${esc(d.src.join(", "))}</td><td class="hide-s date">${esc(d.date || "—")}</td></tr>`).join("")}
      </tbody></table></div>
      ${rows.length > F.limit ? `<button type="button" class="more" data-fmore>Show 60 more of ${num(rows.length - F.limit)}</button>` : ""}`;
  }
  function filterPage() {
    const f = DATA.meta.funnel, g = DATA.meta.gate, T = DATA.meta.tiering;
    // eslint-disable-next-line no-unused-vars
    const share = (o) => { const tot = Object.values(o || {}).reduce((a, b) => a + b, 0); return tot ? Object.keys(TIER).filter((k) => o[k]).map((k) => `${o[k]} ${TIER[k][0].toLowerCase()}`).join(", ") + ` of ${tot}` : "none judged yet"; };
    const tierBars = T.judged ? `<div class="tierbars">${["recommend", "hold", "no"].map((k) => `<button type="button" class="tb" data-goto-tier="${k}"><span class="tier ${k}">${TIER[k][0]}</span><span class="w"><i class="${k}" style="width:${((T.tiers[k] || 0) / T.judged) * 100}%"></i></span><b>${num(T.tiers[k] || 0)}</b></button>`).join("")}</div>
      <table class="cmp rules"><thead><tr><th>Decided by</th><th></th><th></th></tr></thead><tbody>${Object.keys(RULE).filter((r) => T.rules[r]).map((r) => `<tr><td><span class="tier ${r[0] === "B" ? "no" : r === "T2" || r === "T3" ? "recommend" : "hold"}">${r[0] === "B" ? "No" : r === "T2" || r === "T3" ? "Recommend" : "Hold"}</span></td><td>${esc(RULE[r])}</td><td><b>${num(T.rules[r])}</b></td></tr>`).join("")}</tbody></table>` : "";
    const bar = Object.entries(g.traction_bar).map(([k, v]) => `${num(v)}+ ${k}`).join(", ");
    const steps = [
      ["1", "Radar records read", f.records, `Every record in ${DATA.meta.snapshots.days} daily snapshots.`],
      ["2", "Candidates", f.candidates, `A Radar record becomes a candidate when Radar tags it as a benchmark and it is about agents, or when people have clearly noticed it (${esc(bar)}). Duplicates are merged. Benchmarks listed on public leaderboards, and a hand-kept list of established ones, are added.`],
      ["3", "Judged to be a benchmark", f.kept_records, `One question: does it release a benchmark others can run? ${num(f.not_benchmark)} candidates were turned away, listed below with the reason.`],
      ["4", "Benchmarks in the pool", f.benchmarks, `Same names merged. ${num(f.by_mode.agentic || 0)} agentic, ${num(f.by_mode.modified || 0)} modified-agentic, ${num(f.by_mode.non || 0)} non-agentic. The mode is a signal, not a filter.`],
      ["5", "New candidates", T.candidates, `${num((T.covered.v1 || 0))} benchmarks that Harbor Index v1 already takes tasks from and ${num(T.covered.adapter || 0)} more with a merged Harbor adapter are set aside as covered. They stay on the board as reference.`],
      ["6", "Tiered", T.judged || null, T.judged ? `Each candidate is Recommend, Hold or No. The judge reads the whole paper and the repository README, and every verdict names the rule that decided and quotes the text it rests on. The paper was read for ${num(T.read.paper)} candidates and only a README for ${num(T.read.readme_only)}; ${num(T.read.nothing)} have neither and are held. Not checked by a person.` : `Recommend / Hold / No. Not run yet.`],
    ];
    const lead = Math.log10(steps[0][2]);
    app.innerHTML = `
      <h1 class="d-name">Filter</h1>
      <p class="d-title">What each step keeps, what it turns away, and why. Built ${esc(DATA.meta.generated)}.</p>
      <section class="card steps">
        ${steps.map(([n, k, v, text]) => `<div class="step${v == null ? " pending" : ""}"><span class="sn">${n}</span><div><div class="sk">${k}<b>${v == null ? "pending" : num(v)}</b></div>${v == null ? "" : `<div class="w"><i style="width:${Math.max(1, (Math.log10(v) / lead) * 100)}%"></i></div>`}<p class="src">${text}</p></div></div>`).join("")}
        <p class="note">Bar length is on a log scale.</p>
      </section>
      <div class="d-grid">
        <section class="card span2"><h2>Tiers, and what decided them</h2>
          ${tierBars || `<p class="src" style="margin:0">Not run yet.</p>`}
          <p class="src">Click a tier to open the board filtered to it. No scores are added up: a benchmark is recommended when its tasks are real, its results can be trusted, and it is either still hard or widely noticed.</p>
        </section>
      </div>
      <div class="bar"><label class="search"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg><input id="fq" type="search" placeholder="Search what was turned away" autocomplete="off" aria-label="Search dropped candidates"></label></div>
      <section class="panel" id="dropped">${droppedTable()}</section>`;
    document.getElementById("fq").value = F.q;
    setNav("filter");
    if (!DROPPED) {
      fetch("data/dropped.json", { cache: "no-cache" }).then((r) => r.json()).then((d) => {
        DROPPED = d;
        const el = document.getElementById("dropped");
        if (el) el.innerHTML = droppedTable();
      }).catch(() => { const el = document.getElementById("dropped"); if (el) el.innerHTML = `<div class="empty">Could not load data/dropped.json</div>`; });
    }
  }
  const setNav = (name) => { document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === name)); window.scrollTo(0, 0); };

  // ---------- routing ----------
  function route() {
    const h = location.hash.replace(/^#\/?/, "");
    document.title = "BENCH-POOL";
    if (h.startsWith("b/")) {
      document.querySelectorAll("[data-nav]").forEach((el) => el.classList.remove("on"));
      return detail(decodeURIComponent(h.slice(2)));
    }
    if (h === "about") return about();
    if (h === "new") return newPage();
    if (h === "filter") return filterPage();
    S.view = ["list", "timeline", "saturation"].includes(h) ? h : "list";
    if (S.view !== "list") S.week = null; // the week filter only belongs to the list
    if (!document.getElementById("panel")) shell();
    controls();
    panel();
  }
  const refresh = () => { S.limit = PAGE; controls(); panel(); };

  // ---------- events ----------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-theme-set],[data-cover],[data-goto-tier],[data-fmore],[data-tier],[data-mode],[data-cls],[data-sub],[data-quick],[data-view],[data-sort],[data-more],[data-basis],[data-cell],[data-go],[data-clear-week],tr[data-id]");
    if (!t) return;
    const d = t.dataset;
    if (d.themeSet) {
      document.documentElement.dataset.theme = d.themeSet;
      try { localStorage.setItem("bench-pool-theme", d.themeSet); } catch (err) { /* private mode */ }
    } else if (d.cover) { S.cover = d.cover; refresh(); }
    else if (d.gotoTier) { S.cover = "open"; S.tier = d.gotoTier; S.mode = null; S.cls = 0; S.quick = null; location.hash = "#/list"; }
    else if (d.tier != null && t.matches("button")) { S.tier = d.tier || null; if (document.getElementById("panel")) refresh(); else route(); }
    else if (d.fmore != null) { F.limit += 60; document.getElementById("dropped").innerHTML = droppedTable(); }
    else if (d.mode != null && t.matches("button")) { S.mode = d.mode || null; if (document.getElementById("panel")) refresh(); else route(); }
    else if (d.cls != null) { S.cls = +d.cls; S.sub = null; refresh(); }
    else if (d.sub != null) { S.sub = S.sub === d.sub ? null : d.sub; refresh(); }
    else if (d.quick) { if (d.quick === "mm") S.mm = !S.mm; else S.quick = S.quick === d.quick ? null : d.quick; refresh(); }
    else if (d.view) { location.hash = "#/" + d.view; }
    else if (d.sort) { if (S.sort === d.sort) S.dir = -S.dir; else { S.sort = d.sort; S.dir = d.sort === "name" || d.sort === "tier" ? 1 : -1; } panel(); }
    else if (d.more != null) { S.limit += PAGE; panel(); }
    else if (d.basis) { S.basis = d.basis; panel(); }
    else if (d.cell) { const [c, w] = d.cell.split("|"); S.cls = +c; S.sub = null; S.week = w; S.limit = PAGE; location.hash = "#/list"; }
    else if (d.clearWeek != null) { S.week = null; refresh(); }
    else if (d.go) { location.hash = "#/b/" + encodeURIComponent(d.go); }
    else if (d.id && !e.target.closest("a")) { location.hash = "#/b/" + encodeURIComponent(d.id); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.dataset && e.target.dataset.cell) e.target.click();
  });
  document.addEventListener("input", (e) => {
    if (e.target.id === "q") { S.q = e.target.value.trim(); refresh(); }
    if (e.target.id === "fq") { F.q = e.target.value.trim(); F.limit = 60; document.getElementById("dropped").innerHTML = droppedTable(); }
  });
  document.addEventListener("mousemove", (e) => {
    const t = e.target.closest ? e.target.closest("[data-tip]") : null;
    if (!t) { tip.hidden = true; return; }
    tip.textContent = t.dataset.tip;
    tip.hidden = false;
    const w = tip.offsetWidth, x = Math.min(window.innerWidth - w - 8, e.clientX + 12);
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = (e.clientY + 16 + tip.offsetHeight > window.innerHeight ? e.clientY - tip.offsetHeight - 10 : e.clientY + 16) + "px";
  });
  window.addEventListener("hashchange", () => { tip.hidden = true; route(); });

  fetch("data/benchmarks.json", { cache: "no-cache" }) // always revalidate, so a rebuild shows on reload
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      DATA = d;
      d.meta.classes.forEach((c) => { CLASS[c.id] = c; });
      CIDS = d.meta.classes.map((c) => c.id);
      d.newSince = iso(addDays(day(d.meta.snapshots.last), -30));
      route();
    })
    .catch((err) => { app.innerHTML = `<p class="loading">Could not load data/benchmarks.json (${esc(err.message)}). Run scripts/build.py.</p>`; });
})();
