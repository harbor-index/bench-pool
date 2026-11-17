/* Pages, routing and events. */
(function () {
  "use strict";
  const BP = (window.BP = window.BP || {});
  const esc = BP.esc, num = BP.num, S = BP.S;
  const app = document.getElementById("app");
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- shared bits ----------
  const countUp = (root) => {
    root.querySelectorAll("[data-count]").forEach((el) => {
      const to = +el.dataset.count;
      if (reduced() || !to) { el.textContent = num(to); return; }
      const t0 = performance.now(), dur = 900;
      const step = (t) => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 4); el.textContent = num(Math.round(to * e)); if (k < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    });
  };
  const lastDay = () => BP.DATA.meta.snapshots.last;
  const since = (n) => BP.iso(BP.addDays(BP.day(lastDay()), -n));
  const tierChanges = (days) => {
    const from = since(days - 1);
    return BP.DATA.items.filter((it) => !it.covered && it.tier && it.tier_trail.length > 1 && it.tier_trail[it.tier_trail.length - 1][0] >= from)
      .sort((a, b) => BP.TIER_RANK[a.tier.tier] - BP.TIER_RANK[b.tier.tier]);
  };
  const changeRows = (list, max) => list.length ? `<ul class="changes">${list.slice(0, max).map((it) => { const a = it.tier_trail[it.tier_trail.length - 2];
    return `<li><a class="cn" href="#/board/${encodeURIComponent(it.id)}">${esc(it.name)}</a><span class="cw"><span class="tp ${a[1]} ghost"><i></i>${BP.TIER[a[1]][0]}</span><span class="arrow">→</span>${BP.tierPill(it)}</span><span class="cr">${esc(BP.plain(it.tier.reason))}</span></li>`; }).join("")}</ul>${list.length > max ? `<p class="hint">${num(list.length - max)} more.</p>` : ""}` : `<p class="hint">No benchmark changed tier this week.</p>`;

  // ---------- overview ----------
  function overview() {
    const T = BP.DATA.meta.tiering;
    const wk = BP.DATA.items.filter((it) => it.seen && it.seen >= since(6));
    const wkOpen = wk.filter((it) => !it.covered);
    const sat = BP.DATA.items.filter((it) => it.sat && !it.covered).length;
    const cnt = (t) => wkOpen.filter((it) => BP.tierOf(it) === t).length;
    app.innerHTML = `
      <div class="page">
        <header class="hero2 rise">
          <h1><span class="h-a">${num(T.candidates)} candidate benchmarks for Harbor Index v2, ${num(T.tiers.recommend || 0)} recommended.</span>
          <span class="h-b">Collected every day from Benchmark Radar, arXiv, Hugging Face, GitHub and lab blogs, and judged by a model that reads each paper and repository.</span></h1>
          <p class="updated">Updated ${esc(BP.DATA.meta.generated.slice(0, 10))} · records from ${esc(BP.DATA.meta.snapshots.first)} to ${esc(lastDay())}</p>
        </header>
        <div class="stats rise" style="--i:1">
          <a class="stat" href="#/board" data-preset="open"><b data-count="${T.candidates}">0</b><span>new candidates</span></a>
          <a class="stat rec" href="#/board" data-preset="recommend"><b data-count="${T.tiers.recommend || 0}">0</b><span>recommended</span></a>
          <a class="stat" href="#/new?win=week&by=seen"><b data-count="${wkOpen.length}">0</b><span>new this week</span></a>
          <a class="stat" href="#/board" data-preset="sat"><b data-count="${sat}">0</b><span>saturated, 90% or more</span></a>
          <a class="stat" href="#/board" data-preset="covered"><b data-count="${(T.covered.v1 || 0) + (T.covered.adapter || 0)}">0</b><span>already in Harbor</span></a>
        </div>
        <div id="board"></div>
      </div>`;
    countUp(app);
    setNav("overview");
    const recs = wkOpen.filter((it) => BP.tierOf(it) === "recommend").sort((a, b) => BP.attention(b) - BP.attention(a));
    new BP.Board(document.getElementById("board"), { key: "overview", panels: [
      { id: "new", title: "New this week", sub: `${num(wkOpen.length)} first seen ${esc(since(6))} to ${esc(lastDay())}`, x: 0, y: 0, w: 7, h: 9, fit: true, maxH: 16, expand: "#/new",
        render: (b) => { b.innerHTML = `
          <div class="tiersum">${["recommend", "hold", "no"].map((t) => `<span class="tp ${t}"><i></i>${BP.TIER[t][0]} <b>${cnt(t)}</b></span>`).join("")}</div>
          ${recs.length ? `<div class="cards">${recs.slice(0, 6).map((it, i) => `<a class="card rise" style="--i:${i}" href="#/board/${encodeURIComponent(it.id)}">
            <span class="card-h">${BP.icon(it.cls, 15)}<b>${esc(it.name)}</b>${BP.modeTag(it.mode)}</span>
            <span class="card-r">${esc(BP.plain(it.tier.reason))}</span></a>`).join("")}</div>` : `<p class="hint">Nothing new was recommended this week.</p>`}` ; } },
      { id: "changes", title: "Tier changes this week", x: 7, y: 0, w: 5, h: 9, fit: true, maxH: 16,
        render: (b) => { b.innerHTML = changeRows(tierChanges(7), 8); } },
      { id: "ready", title: "Ready to adapt", sub: "recommended, not in Harbor, ordered by solvability evidence", x: 0, y: 9, w: 12, h: 7, fit: true, maxH: 14, render: readyPanel },
      { id: "rank", title: "Most real headroom among popular benchmarks", sub: "best score against the reachable ceiling", x: 0, y: 16, w: 12, h: 9, fit: true, expand: "#/rank", render: rankPanel },
      { id: "flow", title: "How screening works", sub: "click a step", x: 0, y: 25, w: 12, h: 9, fit: true, expand: "#/filter",
        render: (b) => { b.innerHTML = `<div class="flowwrap">${BP.flow.svg({ compact: true, rules: false })}</div>`; } },
      { id: "classes", title: "By class", sub: "new candidates", x: 0, y: 34, w: 6, h: 10, fit: true, render: classesPanel },
      { id: "weeks", title: "New per week", sub: "by publication week", x: 6, y: 34, w: 6, h: 8, fit: true, render: weeksPanel },
      { id: "sat", title: "Saturation by class", sub: "share above 90%", x: 6, y: 44, w: 6, h: 9, fit: true, hidden: false, render: satPanel },
    ] });
  }

  function readyPanel(b) {
    const lv = (it) => BP.ORACLE.findIndex((o) => o[0] === it.readiness.oracle.level);
    const items = BP.DATA.items.filter((it) => it.readiness && !it.covered && !(it.harbor && it.harbor.status))
      .sort((x, y) => lv(y) - lv(x) || BP.attention(y) - BP.attention(x)).slice(0, 8);
    if (!items.length) { b.innerHTML = '<p class="hint">No adapter readiness records yet.</p>'; return; }
    b.innerHTML = `<div class="rk-mini">${items.map((it, i) => { const r = it.readiness;
      return `<a class="rkm rdm" href="#/board/${encodeURIComponent(it.id)}" style="--i:${i}">
        <span class="rkm-n">${esc(it.name)}${BP.harborTag(it)}</span>
        <span class="ladder sm">${BP.ORACLE.map((o, j) => `<span class="rung${j <= lv(it) ? " on" : ""}${j === lv(it) ? " cur" : ""}"></span>`).join("")}</span>
        <span class="rkm-v">${r.tasks.count != null ? `<b>${num(r.tasks.count)}</b> ${esc(r.tasks.unit || "tasks")}` : "—"}</span>
        <span class="small muted rd-why">${esc(BP.ORACLE[Math.max(0, lv(it))][1])}${(r.runtime.network_or_api || []).length ? " · needs " + esc(r.runtime.network_or_api[0]) : ""}</span></a>`; }).join("")}</div>
      <p class="hint">From each release's own README and files, not the paper. Open one for the brief.</p>`;
  }

  function rankPanel(b) {
    const items = BP.DATA.items.filter((it) => it.rank && it.rank.sota && ["real", "unverified"].includes(it.rank.band))
      .sort((x, y) => (x.rank.band === "real" ? 0 : 1) - (y.rank.band === "real" ? 0 : 1) || y.rank.headroom - x.rank.headroom).slice(0, 10);
    b.innerHTML = `<div class="rk-mini">${items.map((it, i) => `<a class="rkm" href="#/rank/${encodeURIComponent(it.id)}" style="--i:${i}">
      <span class="rkm-n">${esc(it.name)}${it.covered ? '<span class="fl hi">in Harbor</span>' : ""}</span>${BP.ceilBar(it.rank)}<span class="rkm-v"><b>${BP.num(it.rank.headroom)}</b> pts</span>${BP.bandPill(it.rank.band)}</a>`).join("")}</div>`;
  }

  function classesPanel(b) {
    const items = BP.DATA.items.filter((it) => !it.covered);
    const rows = BP.CIDS.map((c) => { const m = items.filter((it) => it.cls === c); return { c, n: m.length, r: m.filter((i) => BP.tierOf(i) === "recommend").length, h: m.filter((i) => BP.tierOf(i) === "hold").length, x: m.filter((i) => BP.tierOf(i) === "no").length }; });
    const max = Math.max(...rows.map((r) => r.n));
    b.innerHTML = `<div class="crow-l">${rows.map((r, i) => `<button type="button" class="crow" data-cls-go="${r.c}" style="--i:${i}">
      <span class="crow-n">${BP.icon(r.c, 15)}${esc(BP.SHORT[r.c])}</span>
      <span class="stack" style="--w:${(r.n / max) * 100}%" data-tip="${r.r} recommend · ${r.h} hold · ${r.x} no"><i class="recommend" style="flex:${r.r}"></i><i class="hold" style="flex:${r.h}"></i><i class="no" style="flex:${r.x}"></i></span>
      <span class="crow-c"><b>${num(r.n)}</b>${r.r ? `<span class="tp recommend sm"><i></i>${r.r}</span>` : ""}</span></button>`).join("")}</div>
      <p class="hint legend"><span class="lg recommend"></span>recommend <span class="lg hold"></span>hold <span class="lg no"></span>no</p>`;
  }

  function weeksPanel(b) {
    const end = BP.day(lastDay()), start = BP.monday(BP.addDays(end, -7 * 15));
    const weeks = []; for (let d = start; d <= end; d = BP.addDays(d, 7)) weeks.push(BP.iso(d));
    const col = (it) => Math.floor((BP.day(BP.when(it)) - start) / (7 * 864e5));
    const data = weeks.map(() => ({ recommend: 0, hold: 0, no: 0 }));
    BP.DATA.items.forEach((it) => { if (it.covered || !BP.when(it) || BP.when(it) < weeks[0]) return; const t = BP.tierOf(it); const c = col(it); if (data[c] && data[c][t] != null) data[c][t]++; });
    const tot = data.map((d) => d.recommend + d.hold + d.no), max = Math.max(1, ...tot);
    const W = 560, H = 170, bw = W / weeks.length;
    let s = `<svg class="weeks" viewBox="0 0 ${W} ${H + 20}" preserveAspectRatio="none">`;
    data.forEach((d, i) => {
      let y = H;
      for (const t of ["no", "hold", "recommend"]) {
        const h = (d[t] / max) * (H - 14);
        if (h > 0) { s += `<rect class="wk ${t}" x="${i * bw + 3}" y="${y - h}" width="${bw - 6}" height="${h}" rx="3" style="--i:${i}"/>`; y -= h; }
      }
      s += `<rect class="wk-hit" x="${i * bw}" y="0" width="${bw}" height="${H}" data-week="${weeks[i]}" data-tip="Week of ${weeks[i]}: ${tot[i]} new · ${d.recommend} recommend · ${d.hold} hold · ${d.no} no"/>`;
      if (i % 3 === 0) s += `<text x="${i * bw + bw / 2}" y="${H + 14}" text-anchor="middle">${weeks[i].slice(5)}</text>`;
    });
    b.innerHTML = s + `</svg><p class="hint">Click a week to list it in the board.</p>`;
  }

  function satPanel(b) {
    const items = BP.DATA.items.filter((it) => !it.covered);
    b.innerHTML = `<div class="crow-l">${BP.CIDS.map((c, i) => {
      const m = items.filter((it) => it.cls === c), sc = m.filter((it) => it.best != null), st = sc.filter((it) => it.sat);
      const share = sc.length ? st.length / sc.length : 0;
      return `<button type="button" class="crow" data-cls-go="${c}" data-view-go="saturation" style="--i:${i}"><span class="crow-n">${BP.icon(c, 15)}${esc(BP.SHORT[c])}</span>
        <span class="bar wide hotish"><i style="--w:${Math.max(1, share * 100)}%"></i></span>
        <span class="crow-c"><b>${sc.length ? Math.round(share * 100) + "%" : "—"}</b><span class="muted">${st.length}/${sc.length}</span></span></button>`;
    }).join("")}</div><p class="hint">Of the benchmarks in each class that have a best score, the share above 90%.</p>`;
  }

  // ---------- split view: sidebar | list | inspector ----------
  const SPLIT_KEY = "bp.split.v1";
  function splitFrame(kind) {
    const saved = BP.store.get(SPLIT_KEY, {});
    app.innerHTML = `<div class="split${saved.hideSb ? " no-sb" : ""}${saved.hideIns ? " no-ins" : ""}" id="split" style="--sb:${saved.sb || 248}px;--ins:${saved.ins || 470}px">
      <aside class="sb" id="sb" aria-label="Filters"></aside>
      <div class="dv" data-dv="sb" role="separator" aria-orientation="vertical" title="Drag to resize"></div>
      <section class="center" id="center"><div class="ch" id="ch"></div><div class="cb" id="cb"></div></section>
      <div class="dv" data-dv="ins" role="separator" aria-orientation="vertical" title="Drag to resize"></div>
      <aside class="insp" id="insp" aria-label="Details"></aside>
    </div>`;
    BP.split = {
      kind,
      panes: () => { const el = document.getElementById("split"); return [{ id: "sb", title: "Filters", on: !el.classList.contains("no-sb") }, { id: "ins", title: "Details", on: !el.classList.contains("no-ins") }]; },
      toggle: (id, on) => { const el = document.getElementById("split"); el.classList.toggle("no-" + id, !on); saveSplit(); BP.menu.refresh(); },
      reset: () => { BP.store.del(SPLIT_KEY); BP.route(); },
    };
    BP.menu.refresh();
  }
  function saveSplit() {
    const el = document.getElementById("split");
    if (!el) return;
    BP.store.set(SPLIT_KEY, { sb: parseInt(el.style.getPropertyValue("--sb")), ins: parseInt(el.style.getPropertyValue("--ins")), hideSb: el.classList.contains("no-sb"), hideIns: el.classList.contains("no-ins") });
  }

  function sidebar(kind) {
    const base = kind === "new" ? BP.DATA.items.filter((it) => it.seen && it.seen >= since(29) && (!S.q || it.name.toLowerCase().includes(S.q.toLowerCase()))) : BP.scoped({ base: true, anyMode: true });
    const row = (attr, val, on, label, n, extra) => `<button type="button" class="sr${on ? " on" : ""}" ${attr}="${val}">${extra || ""}<span class="sr-l">${label}</span><span class="sr-n">${n == null ? "" : num(n)}</span></button>`;
    const every = BP.scoped({ base: true, anyCover: true, anyMode: true });
    const inMode = base.filter((i) => !S.mode || i.mode === S.mode);
    const tierRows = ["recommend", "hold", "no"].concat(inMode.some((i) => BP.tierOf(i) === "none") ? ["none"] : [])
      .map((t) => row("data-tier", t, S.tier === t, BP.TIER[t][0], inMode.filter((i) => BP.tierOf(i) === t).length, `<span class="tp ${t} dot"><i></i></span>`)).join("");
    const modeRows = Object.keys(BP.MODE).map((m) => row("data-mode", m, S.mode === m, BP.MODE[m][0], base.filter((i) => i.mode === m).length)).join("");
    const counts = {};
    BP.DATA.items.forEach((it) => { if (BP.inScope(it, { anyClass: true })) counts[it.cls] = (counts[it.cls] || 0) + 1; });
    const clsRows = [0].concat(BP.CIDS).map((c) => {
      let r = row("data-cls", c, S.cls === c, BP.SHORT[c], c ? counts[c] || 0 : Object.values(counts).reduce((a, b) => a + b, 0), BP.icon(c, 15));
      if (c && S.cls === c && BP.CLASS[c].subs.length) r += `<div class="subs">${BP.CLASS[c].subs.map((s) => row("data-sub", esc(s), S.sub === s, esc(s), BP.DATA.items.filter((it) => it.cls === c && it.sub === s && BP.inScope(it, { anyClass: true })).length)).join("")}</div>`;
      return r;
    }).join("");
    const q = BP.scoped({ base: true });
    const pinned = Object.keys(BP.shortlist.get()).length;
    const quick = [["ready", "Reference reported to pass", q.filter((i) => i.readiness && ["reference_passes_reported", "controls_reported"].includes(i.readiness.oracle.level)).length], ["pinned", "★ Shortlist", q.filter((i) => BP.shortlist.has(i.id)).length], ["fresh", "Nothing of it in Harbor", q.filter((i) => !(i.harbor && (i.harbor.status || (i.harbor.family || []).length))).length], ["new", "Published in the last 30 days", q.filter((i) => BP.when(i) && BP.when(i) >= BP.DATA.newSince).length], ["sat", "Saturated, 90%+", q.filter((i) => i.sat).length], ["lb", "Has a leaderboard", q.filter(BP.hasLb).length]]
      .map(([k, l, n]) => row("data-quick", k, S.quick === k, l, n)).join("") + row("data-mm", "1", S.mm, "Multimodal", q.filter((i) => i.mm).length);
    const dirty = S.tier || S.mode || S.cls || S.quick || S.mm || S.q || S.week || S.cover !== "open";
    document.getElementById("sb").innerHTML = `
      <label class="search"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>
        <input id="q" type="search" placeholder="Search benchmarks" autocomplete="off" aria-label="Search benchmarks" value="${esc(S.q)}"><kbd>/</kbd></label>
      ${kind === "board" ? `<div class="seg full" role="group" aria-label="Which benchmarks">
        <button type="button" data-cover="open" aria-pressed="${S.cover === "open"}" data-tip="Not yet in Harbor Index v1 and no merged Harbor adapter">Candidates <b>${num(every.filter((i) => !i.covered).length)}</b></button>
        <button type="button" data-cover="covered" aria-pressed="${S.cover === "covered"}" data-tip="${num(every.filter((i) => i.covered).length)} in Harbor Index v1 or with a merged adapter">In Harbor</button>
        <button type="button" data-cover="all" aria-pressed="${S.cover === "all"}">All</button></div>` : ""}
      ${S.cover !== "covered" ? `<div class="sg"><div class="sg-h">Tier</div>${tierRows}</div>` : ""}
      <div class="sg"><div class="sg-h">Mode</div>${modeRows}</div>
      ${kind === "board" ? `<div class="sg"><div class="sg-h">Class</div>${clsRows}</div><div class="sg"><div class="sg-h">Narrow down</div>${quick}</div>` : ""}
      ${dirty ? `<button type="button" class="clear" data-clear>Clear filters</button>` : ""}`;
  }

  function centerHead(title, sub, views) {
    const chips = [];
    if (S.tier) chips.push(["tier", BP.TIER[S.tier][0]]);
    if (S.mode) chips.push(["mode", BP.MODE[S.mode][0]]);
    if (S.cls) chips.push(["cls", BP.SHORT[S.cls] + (S.sub ? " / " + S.sub : "")]);
    if (S.quick) chips.push(["quick", { new: "Published in the last 30 days", sat: "Saturated", lb: "Has a leaderboard", pinned: "Shortlist", fresh: "Nothing of it in Harbor", ready: "Reference reported to pass" }[S.quick]]);
    if (S.mm) chips.push(["mm", "Multimodal"]);
    if (S.week) chips.push(["week", "Week of " + S.week]);
    if (S.q) chips.push(["q", "“" + S.q + "”"]);
    document.getElementById("ch").innerHTML = `
      <div class="ch-t"><button type="button" class="ib sb-toggle" data-sb-toggle title="Filters" aria-label="Show filters"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 6h16M7 12h10M10 18h4"/></svg></button>
        <h2><span class="h-a">${title}</span> <span class="h-b">${sub}</span></h2>
        <div class="ch-act">
          <button type="button" class="tbtn sm" data-share title="Copy a link to this filtered view">Share link</button>
          <button type="button" class="tbtn sm" data-export="csv" title="Download the rows shown, as CSV">CSV</button>
          <button type="button" class="tbtn sm" data-export="json" title="Download the rows shown, as JSON">JSON</button>
          ${Object.keys(BP.shortlist.get()).length > 1 ? `<a class="tbtn sm" data-cmp href="#/compare/${encodeURIComponent(Object.keys(BP.shortlist.get()).slice(0, 4).join(","))}" title="Compare shortlisted benchmarks side by side">Compare ★</a>` : ""}
        </div>
        ${views ? `<div class="seg" role="group" aria-label="View">${[["list", "List"], ["timeline", "Timeline"], ["saturation", "Saturation"]].map(([k, l]) => `<button type="button" data-view="${k}" aria-pressed="${S.view === k}">${l}</button>`).join("")}</div>` : ""}</div>
      ${chips.length ? `<div class="fchips">${chips.map(([k, l]) => `<button type="button" class="fchip" data-unset="${k}">${esc(l)}<span aria-hidden="true">×</span></button>`).join("")}</div>` : ""}`;
  }

  function sortRows(rows) {
    const key = { tier: (i) => BP.TIER_RANK[BP.tierOf(i)] + "|" + String(99999999 - +(BP.when(i) || "0000-00-00").replace(/-/g, "")), name: (i) => i.name.toLowerCase(), best: (i) => (i.best == null ? -1 : i.best), date: (i) => BP.when(i) || "", att: (i) => BP.attention(i) }[S.sort];
    return rows.sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0) * S.dir || a.name.localeCompare(b.name));
  }
  const rowHtml = (it, dateKey) => `<tr data-id="${esc(it.id)}" class="${S.sel === it.id ? "sel" : ""}" tabindex="-1">
      <td>${BP.tierPill(it)}</td>
      <td class="nm">${BP.star(it)}<span class="nm-t" title="${esc(it.name)}">${BP.mid(it.name, 34)}</span>${BP.flags(it)}${BP.harborTag(it)}</td>
      <td class="hide-n">${BP.modeTag(it.mode)}</td>
      <td class="hide-m cl" data-tip="${esc(BP.CLASS[it.cls].name)}">${BP.icon(it.cls, 14)}<span>${esc(BP.SHORT[it.cls])}</span></td>
      <td class="r">${BP.scoreCell(it)}</td>
      <td class="r hide-n">${BP.attCell(it)}</td>
      ${dateKey === "both" ? `<td class="r dt hide-m" data-tip="Published">${esc(it.date || "—")}</td><td class="r dt" data-tip="First seen">${esc(it.seen || "—")}</td>` : `<td class="r dt">${esc(BP.when(it) || "—")}</td>`}</tr>`;
  const thead = (dateLabel, fixed) => {
    const th = (k, l, cls) => fixed ? `<th class="${cls || ""}">${l}</th>` : `<th class="${cls || ""}"><button type="button" data-sort="${k}" class="${S.sort === k ? "on" : ""}">${l}${S.sort === k ? `<span>${S.dir > 0 ? "↑" : "↓"}</span>` : ""}</button></th>`;
    const dates = dateLabel === "both" ? `<th class="r hide-m">Published</th><th class="r">First seen</th>` : th("date", dateLabel, "r");
    return `<thead><tr>${th("tier", "Tier")}${th("name", "Benchmark")}<th class="hide-n">Mode</th><th class="hide-m">Class</th>${th("best", "Best score", "r")}${th("att", "Attention", "r hide-n")}${dates}</tr></thead>`;
  };

  function listView() {
    const rows = sortRows(BP.scoped());
    BP.rows = rows.map((r) => r.id);
    document.getElementById("cb").innerHTML = rows.length ? `<table class="tbl">${thead("Date")}<tbody>${rows.slice(0, S.limit).map((it) => rowHtml(it)).join("")}</tbody></table>
      ${rows.length > S.limit ? `<button type="button" class="more" data-more>Show ${num(Math.min(200, rows.length - S.limit))} more of ${num(rows.length - S.limit)}</button>` : ""}` : `<div class="empty">Nothing matches these filters.</div>`;
    return rows.length;
  }

  function timelineView() {
    const start = BP.monday(BP.day(BP.DATA.meta.snapshots.first)), end = BP.day(lastDay());
    const weeks = []; for (let d = start; d <= end; d = BP.addDays(d, 7)) weeks.push(BP.iso(d));
    const items = BP.scoped({ anyClass: true, anyWeek: true });
    const grid = {}; let undated = 0;
    BP.CIDS.forEach((c) => { grid[c] = new Array(weeks.length + 1).fill(0); });
    items.forEach((it) => { const d = BP.when(it); if (!d) { undated++; return; } const col = d < weeks[0] ? 0 : Math.min(weeks.length, 1 + Math.floor((BP.day(d) - start) / (7 * 864e5))); grid[it.cls][col]++; });
    const maxCell = Math.max(1, ...Object.values(grid).flatMap((r) => r.slice(1)));
    let h = `<div class="heat" style="grid-template-columns:150px 56px repeat(${weeks.length}, minmax(24px, 1fr)) 48px"><div></div><div class="hc-h">earlier</div>${weeks.map((w, i) => `<div class="hc-h">${i % 2 ? "" : w.slice(5)}</div>`).join("")}<div class="hc-h">all</div>`;
    for (const c of BP.CIDS) {
      h += `<div class="hl${S.cls === c ? " on" : ""}">${BP.icon(c, 14)}${esc(BP.SHORT[c])}</div><div class="hc early">${grid[c][0] || ""}</div>`;
      h += weeks.map((w, i) => { const n = grid[c][i + 1], a = n ? Math.round(14 + Math.sqrt(n / maxCell) * 70) : 0;
        return `<div class="hc${n ? " on" : ""}" ${n ? `data-cell="${c}|${w}" role="button" tabindex="0" style="--a:${a}%"` : ""} data-tip="${esc(BP.CLASS[c].name)} · week of ${w} · ${n} new">${n || ""}</div>`; }).join("");
      h += `<div class="hc tot">${grid[c].reduce((a, b) => a + b, 0)}</div>`;
    }
    document.getElementById("cb").innerHTML = `<div class="padded">${h}</div><p class="hint">By week of first publication. Click a cell to list its benchmarks.${undated ? ` ${undated} undated benchmarks are not shown.` : ""}</p></div>`;
    return items.length;
  }

  function saturationView() {
    const items = BP.scoped({ anyClass: true });
    const usable = (it) => it.best != null && (S.basis === "all" || it.basis !== "paper");
    let h = `<div class="satg"><div></div><div class="axis">${[0, 25, 50, 75, 90, 100].map((t) => `<span style="left:${t}%">${t}</span>`).join("")}</div><div></div>`;
    for (const c of BP.CIDS) {
      const mine = items.filter((it) => it.cls === c), sc = mine.filter(usable), st = sc.filter((it) => it.best > BP.DATA.meta.saturated_above);
      h += `<div class="hl${S.cls === c ? " on" : ""}">${BP.icon(c, 14)}${esc(BP.SHORT[c])}</div><div class="strip"><div class="zone"></div>${sc.map((it) => `<button type="button" class="pt ${BP.kindCls(it.basis)}${it.best > 90 ? " hot" : ""}" style="left:${Math.min(100, Math.max(0, it.best))}%;top:${(14 + BP.hash01(it.id) * 72).toFixed(0)}%" data-pick="${esc(it.id)}" data-tip="${esc(it.name)} · ${BP.pct(it.best)} · ${esc(BP.KIND[it.basis].toLowerCase())}" aria-label="${esc(it.name)}"></button>`).join("")}</div>
        <div class="satc"><b>${sc.length ? Math.round((st.length / sc.length) * 100) + "%" : "—"}</b><span class="muted">${st.length}/${sc.length}</span></div>`;
    }
    document.getElementById("cb").innerHTML = `<div class="padded"><div class="seg" role="group" aria-label="Score basis"><button type="button" data-basis="all" aria-pressed="${S.basis === "all"}">All scores</button><button type="button" data-basis="leaderboard" aria-pressed="${S.basis === "leaderboard"}">Leaderboards only</button></div>${h}</div>
      <p class="hint">Each dot is a benchmark at its best known score. Filled: own leaderboard. Light: aggregator. Hollow: stated in the paper. Click a dot for its details.</p></div>`;
    return items.length;
  }

  function board(sel) {
    if (!document.getElementById("split") || BP.split.kind !== "board") splitFrame("board");
    if (sel !== undefined) S.sel = sel;
    sidebar("board");
    const scope = (S.cover === "covered" ? "Already in Harbor" : S.cover === "all" ? "All benchmarks" : "Candidates");
    const n = S.view === "timeline" ? timelineView() : S.view === "saturation" ? saturationView() : listView();
    centerHead(`${num(n)} ${scope.toLowerCase()}`, S.tier ? `· ${BP.TIER[S.tier][0].toLowerCase()}` : "· sorted by " + { tier: "tier, newest first", name: "name", best: "best score", date: "date", att: "attention" }[S.sort], true);
    inspector();
    setNav("board");
  }

  function inspector(animate) {
    const el = document.getElementById("insp");
    if (!el) return;
    const it = S.sel && BP.byId(S.sel);
    document.getElementById("split").classList.toggle("has-sel", !!it);
    if (!it) {
      el.innerHTML = `<div class="insp-empty"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M13 4v16M16 8h2M16 11h2"/></svg><p><b>Select a benchmark</b><br>Its verdict, the evidence behind it and its scores appear here. Use ↑ ↓ to move through the list.</p></div>`;
      return;
    }
    el.innerHTML = `<button type="button" class="ib insp-close" data-desel aria-label="Close details" title="Close">×</button>` + BP.item.inspector(it);
    if (animate !== false) { el.firstElementChild.nextElementSibling.classList.add("swap"); }
    el.scrollTop = 0;
  }

  function select(id, opts) {
    S.sel = id;
    document.querySelectorAll(".tbl tr.sel").forEach((r) => r.classList.remove("sel"));
    const tr = document.querySelector(`.tbl tr[data-id="${CSS.escape(id)}"]`);
    if (tr) { tr.classList.add("sel"); if (opts && opts.scroll) tr.scrollIntoView({ block: "nearest" }); }
    const base = "#/" + (BP.split ? BP.split.kind : "board") + "/";
    history.replaceState(null, "", base + encodeURIComponent(id));
    inspector();
  }

  // ---------- ranking ----------
  const R = { band: null, cover: "all", scope: "all" };
  const isRec = (it) => it.rank && it.rank.why.length === 1 && it.rank.why[0] === "Recommended new candidate";
  const BAND_ORDER = ["real", "unverified", "suspect", "saturated", "noscore"];
  function rankPool() {
    if (BP.QS) { if (BP.QS.band) R.band = BP.QS.band; if (BP.QS.scope) R.scope = BP.QS.scope; if (BP.QS.rcover) R.cover = BP.QS.rcover; BP.QS = null; }
    return BP.DATA.items.filter((it) => it.rank && (R.scope === "all" || (R.scope === "rec" ? isRec(it) || (it.tier && it.tier.tier === "recommend" && !it.covered) : !isRec(it))) && (!S.cls || it.cls === S.cls) && (!S.mode || it.mode === S.mode)
      && (R.cover === "all" || (R.cover === "in" ? it.covered : !it.covered))
      && (!S.q || (it.name + " " + it.title).toLowerCase().includes(S.q.toLowerCase())));
  }
  function rankSidebar(pool) {
    const row = (attr, val, on, label, n, extra) => `<button type="button" class="sr${on ? " on" : ""}" ${attr}="${val}">${extra || ""}<span class="sr-l">${label}</span><span class="sr-n">${n == null ? "" : num(n)}</span></button>`;
    const all = BP.DATA.items.filter((it) => it.rank);
    document.getElementById("sb").innerHTML = `
      <label class="search"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>
        <input id="q" type="search" placeholder="Search benchmarks" autocomplete="off" aria-label="Search benchmarks" value="${esc(S.q)}"><kbd>/</kbd></label>
      <div class="seg full" role="group" aria-label="Already in Harbor">
        <button type="button" data-rcover="all" aria-pressed="${R.cover === "all"}">All</button>
        <button type="button" data-rcover="out" aria-pressed="${R.cover === "out"}" data-tip="Not yet in Harbor Index v1 and no Harbor adapter">New</button>
        <button type="button" data-rcover="in" aria-pressed="${R.cover === "in"}">In Harbor</button></div>
      <div class="seg full" role="group" aria-label="Which benchmarks">
        <button type="button" data-rscope="all" aria-pressed="${R.scope === "all"}">All</button>
        <button type="button" data-rscope="pop" aria-pressed="${R.scope === "pop"}" data-tip="Widely used: tracked by Epoch AI, Artificial Analysis or Benchmark Saturation, reported by 10+ models on LLM Stats, or in Harbor Index v1">Popular</button>
        <button type="button" data-rscope="rec" aria-pressed="${R.scope === "rec"}" data-tip="New candidates the screening recommends">Recommended</button></div>
      <div class="sg"><div class="sg-h">Group</div>${BAND_ORDER.map((b) => row("data-band", b, R.band === b, BP.BAND[b][0], pool.filter((i) => i.rank.band === b).length, `<span class="bp ${b} dot"><i></i></span>`)).join("")}</div>
      <div class="sg"><div class="sg-h">Mode</div>${Object.keys(BP.MODE).map((m) => row("data-mode", m, S.mode === m, BP.MODE[m][0], all.filter((i) => i.mode === m).length)).join("")}</div>
      <div class="sg"><div class="sg-h">Class</div>${[0].concat(BP.CIDS).map((c) => row("data-cls", c, S.cls === c, BP.SHORT[c], c ? all.filter((i) => i.cls === c).length : all.length, BP.icon(c, 15))).join("")}</div>
      <p class="hint sb-note">Popular: tracked by Epoch AI, Artificial Analysis or Benchmark Saturation, reported by 10+ models on LLM Stats, or used in Harbor Index v1.</p>`;
  }
  function rankPage(sel) {
    if (!document.getElementById("split") || BP.split.kind !== "rank") splitFrame("rank");
    if (sel !== undefined) S.sel = sel;
    const pool = rankPool();
    rankSidebar(pool);
    const head = `<thead><tr><th class="r">#</th><th>Benchmark</th><th class="r">Best</th><th>Best vs reachable ceiling</th><th class="r">Headroom</th><th class="hide-n">Record over time</th><th class="r hide-n">Pace</th><th class="hide-m">Tier</th></tr></thead>`;
    BP.rows = [];
    let total = 0;
    const secs = BAND_ORDER.filter((b) => !R.band || R.band === b).map((b) => {
      const rows = pool.filter((it) => it.rank.band === b).sort((x, y) => (b === "saturated" ? (y.rank.sota.pct - x.rank.sota.pct) : b === "noscore" ? BP.attention(y) - BP.attention(x) : (y.rank.headroom - x.rank.headroom)) || x.name.localeCompare(y.name));
      total += rows.length; BP.rows.push(...rows.map((r) => r.id));
      return `<tbody class="grp"><tr class="gh"><th colspan="8"><span class="gh-t">${BP.bandPill(b)}</span><span class="gh-s">${num(rows.length)} · ${esc(BP.BAND[b][1])}</span></th></tr>
        ${rows.map((it, i) => { const r = it.rank;
          return `<tr data-id="${esc(it.id)}" class="${S.sel === it.id ? "sel" : ""}">
            <td class="r rk-n">${b === "noscore" ? "" : i + 1}</td>
            <td class="nm">${BP.star(it)}<span class="nm-t" title="${esc(it.name)}">${BP.mid(it.name, 30)}</span>${BP.harborTag(it)}${isRec(it) ? '<span class="fl new" data-tip="A recommended new candidate, not one of the popular benchmarks">rec</span>' : ""}${it.mode === "agentic" ? '<span class="fl ag" data-tip="Agentic">agentic</span>' : ""}</td>
            <td class="r"><b>${r.sota ? BP.pct(r.sota.pct) : "—"}</b></td>
            <td class="cbcell">${BP.ceilBar(r)}</td>
            <td class="r hrn ${b}">${r.headroom != null ? BP.num(r.headroom) : "—"}</td>
            <td class="hide-n">${BP.spark(r)}</td>
            <td class="r hide-n pace">${r.velocity != null ? (r.velocity > 0 ? "+" : "") + BP.num(r.velocity) + "<i>/mo</i>" : "—"}</td>
            <td class="hide-m">${it.covered ? "" : BP.tierPill(it)}</td></tr>`; }).join("") || `<tr><td colspan="8" class="empty">None.</td></tr>`}</tbody>`;
    }).join("");
    const M = BP.DATA.meta.ranking;
    centerHead(`${num(total)} benchmarks, ranked by real headroom`, `· ${num(pool.filter((i) => i.rank.band === "real").length)} with verified real headroom · ${M.judged} of ${M.popular} checked`, false);
    document.getElementById("cb").innerHTML = `<table class="tbl rank">${head}${secs}</table>
      <p class="hint pad">Headroom is the reachable ceiling minus the best score anyone reports. The ceiling is 100% unless Epoch AI or an audit shows some tasks cannot be solved. A gap only counts as real when the evidence shows the tasks are sound. Pace: points the record rose per month over the last year (Epoch AI).</p>`;
    inspector();
    setNav("rank");
  }

  // ---------- compare ----------
  function comparePage(ids) {
    const items = (ids || "").split(",").map((x) => BP.byId(x)).filter(Boolean).slice(0, 4);
    if (!items.length) { app.innerHTML = `<div class="page"><div class="empty">Star benchmarks with ★ to compare them here.</div></div>`; return; }
    const c = (it, k) => { const v = it.tier && it.tier.checks && it.tier.checks[k]; return v ? I_fact(v, k) : '<span class="muted">—</span>'; };
    const I_fact = (v, k) => { const d = BP.CHECK[k]; return `<span class="fact sm ${d[2][v.value] || "na"}" ${v.quote ? `data-tip="${esc("“" + v.quote + "”")}"` : ""}><span class="fv">${esc(d[1][v.value] || "not stated")}</span></span>`; };
    const rows = [
      ["Tier", (it) => BP.tierPill(it) + `<p class="small">${esc(BP.plain((it.tier || {}).reason || ""))}</p>`],
      ["Harbor", (it) => BP.harborTag(it) || '<span class="muted">not in Harbor</span>'],
      ["Mode · class", (it) => BP.modeTag(it.mode) + " " + esc(BP.SHORT[it.cls])],
      ["Best score", (it) => BP.scoreCell(it) + (it.score ? `<p class="small">${esc(it.score.source || "")}${it.score.as_of ? ", " + esc(it.score.as_of) : ""}</p>` : "")],
      ["Headroom", (it) => it.rank ? BP.bandPill(it.rank.band) + (it.rank.headroom != null ? ` <b>${BP.num(it.rank.headroom)}</b> points` : "") : '<span class="muted">not ranked</span>'],
      ["Tasks", (it) => { const z = (it.tier && it.tier.checks && it.tier.checks.size) || {}; return z.tasks != null ? `<b>${BP.num(z.tasks)}</b>` + (z.categories ? ` · ${z.categories} categories` : "") : '<span class="muted">—</span>'; }],
      ["Tasks public", (it) => c(it, "data_released")], ["Verifier", (it) => c(it, "verifier")], ["Shown solvable", (it) => c(it, "solvable")],
      ["Runs in", (it) => c(it, "environment")], ["Reviewed by people", (it) => c(it, "human_review")],
      ["To settle", (it) => `<ul class="prov">${((it.tier || {}).risks || []).slice(0, 3).map((r) => `<li>${esc(r.risk)}</li>`).join("") || "<li class='muted'>none listed</li>"}</ul>`],
      ["Published · first seen", (it) => `${esc(it.date || "—")} · ${esc(it.seen || "—")}`],
      ["Your note", (it) => `<span class="small">${esc((BP.shortlist.get()[it.id] || {}).note || "")}</span>`],
    ];
    app.innerHTML = `<div class="page wide"><header class="hero2 sm rise"><h1><span class="h-a">Compare ${items.length} benchmarks.</span> <span class="h-b">From your shortlist (★). Hover a fact for the sentence it rests on.</span></h1></header>
      <div class="cmp-wrap panel rise"><table class="cmpt"><thead><tr><th></th>${items.map((it) => `<th><a href="#/b/${encodeURIComponent(it.id)}">${esc(it.name)}</a> <button type="button" class="ib" data-unpin="${esc(it.id)}" title="Remove from shortlist">×</button></th>`).join("")}</tr></thead>
      <tbody>${rows.map(([k, f]) => `<tr><th>${k}</th>${items.map((it) => `<td>${f(it)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`;
    setNav("");
  }

  function exportRows(kind) {
    const ids = BP.rows && BP.rows.length ? BP.rows : [];
    const items = ids.map((id) => BP.byId(id)).filter(Boolean);
    const pick = (it) => ({ id: it.id, name: it.name, tier: BP.tierOf(it), reason: BP.plain((it.tier || {}).reason || ""), mode: it.mode,
      class: BP.CLASS[it.cls].name, best: it.best, best_source: it.score ? it.score.source : null, best_as_of: it.score ? it.score.as_of : null,
      band: it.rank ? it.rank.band : null, headroom: it.rank ? it.rank.headroom : null, harbor: (it.harbor || {}).status || ((it.harbor || {}).family || []).length ? "family" : null,
      tasks: (((it.tier || {}).checks || {}).size || {}).tasks ?? null, verifier: ((((it.tier || {}).checks || {}).verifier) || {}).value ?? null,
      published: it.date, first_seen: it.seen, links: it.links.map((l) => l.url).join(" "), url: location.origin + location.pathname + "#/b/" + it.id,
      note: (BP.shortlist.get()[it.id] || {}).note || "" });
    const rows = items.map(pick);
    let body, type;
    if (kind === "json") { body = JSON.stringify({ build_id: BP.DATA.meta.build_id, filters: BP.shareUrl(), rows }, null, 1); type = "application/json"; }
    else { const cols = Object.keys(pick(items[0] || BP.DATA.items[0])); const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
      body = [cols.join(","), ...rows.map((r) => cols.map((c) => q(r[c])).join(","))].join("\n"); type = "text/csv"; }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([body], { type }));
    a.download = `bench-pool-${BP.split ? BP.split.kind : "board"}-${BP.DATA.meta.build_id}.${kind}`;
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---------- new ----------
  const N = { by: "seen", win: "week" };
  function newPage(sel) {
    if (!document.getElementById("split") || BP.split.kind !== "new") splitFrame("new");
    if (sel !== undefined) S.sel = sel;
    sidebar("new");
    if (BP.QS) { if (BP.QS.by) N.by = BP.QS.by; if (BP.QS.win) N.win = BP.QS.win; BP.QS = null; }
    const all = [["This week", since(6), "9999"], ["Last week", since(13), since(6)], ["Two to four weeks ago", since(29), since(13)]];
    const groups = N.win === "week" ? all.slice(0, 1) : all;
    const dateOf = (it) => (N.by === "seen" ? it.seen : it.date);
    const pool = BP.DATA.items.filter((it) => dateOf(it) && (!S.mode || it.mode === S.mode) && (!S.tier || BP.tierOf(it) === S.tier) && (!S.q || it.name.toLowerCase().includes(S.q.toLowerCase())));
    const ord = { agentic: 0, modified: 1, non: 2 };
    let total = 0;
    BP.rows = [];
    const secs = groups.map(([title, from, to]) => {
      const rows = pool.filter((it) => dateOf(it) >= from && dateOf(it) < to).sort((a, b) => BP.TIER_RANK[BP.tierOf(a)] - BP.TIER_RANK[BP.tierOf(b)] || ord[a.mode] - ord[b.mode] || BP.attention(b) - BP.attention(a) || a.name.localeCompare(b.name));
      total += rows.length; BP.rows.push(...rows.map((r) => r.id));
      const c = (t) => rows.filter((it) => BP.tierOf(it) === t).length;
      const un = rows.filter((it) => BP.tierOf(it) === "none").length, cov = rows.filter((it) => it.covered).length;
      return `<tbody class="grp"><tr class="gh"><th colspan="8"><span class="gh-t">${title}</span><span class="gh-s">${num(rows.length)} ${N.by === "seen" ? "first seen" : "published"} ${esc(from)}${to === "9999" ? " to " + esc(lastDay()) : ""} · ${c("recommend")} recommend · ${c("hold")} hold · ${c("no")} no${un ? ` · ${un} not judged yet` : ""}${cov ? ` · ${cov} already in Harbor` : ""}</span></th></tr>
        ${rows.map((it) => rowHtml(it, "both")).join("") || `<tr><td colspan="8" class="empty">Nothing new.</td></tr>`}</tbody>`;
    }).join("");
    const ch = tierChanges(7);
    centerHead(`${num(total)} new benchmarks ${N.win === "week" ? "this week" : "in the last four weeks"}`, N.by === "seen" ? "· by the day we first saw them" : "· by publication date", false);
    document.getElementById("ch").insertAdjacentHTML("beforeend", `<div class="ch-ctl">
      <div class="seg" role="group" aria-label="Window"><button type="button" data-nwin="week" aria-pressed="${N.win === "week"}">This week</button><button type="button" data-nwin="month" aria-pressed="${N.win === "month"}">Four weeks</button></div>
      <div class="seg" role="group" aria-label="Date"><button type="button" data-nby="seen" aria-pressed="${N.by === "seen"}" data-tip="When our sources first saw it. An older paper can be first seen today.">First seen</button><button type="button" data-nby="date" aria-pressed="${N.by === "date"}" data-tip="When the paper or repository was published">Published</button></div></div>`);
    document.getElementById("cb").innerHTML = `
      <details class="chg" ${ch.length ? "open" : ""}><summary><span>Tier changes this week</span><b>${ch.length}</b></summary>${changeRows(ch, 40)}</details>
      <table class="tbl">${thead("both", true)}${secs}</table>`;
    inspector();
    setNav("new");
  }

  // ---------- filter ----------
  let flowSel = "newc";
  function filterPage(node) {
    if (node) flowSel = node;
    app.innerHTML = `<div class="page"><header class="hero2 sm rise"><h1><span class="h-a">How screening works.</span> <span class="h-b">What each step keeps, what it turns away and why. Click any step.</span></h1></header><div id="board"></div></div>`;
    new BP.Board(document.getElementById("board"), { key: "filter", panels: [
      { id: "flow", title: "Flow", sub: "click a step · link thickness on a log scale", x: 0, y: 0, w: 12, h: 13, fit: true, render: (b) => { b.innerHTML = `<div class="flowwrap">${BP.flow.svg({ sel: flowSel })}</div>`; } },
      { id: "step", title: "Selected step", x: 0, y: 13, w: 5, h: 15, render: (b) => { b.id = "flow-detail"; b.innerHTML = BP.flow.detail(flowSel); hookDropped(); } },
      { id: "rules", title: "Tiers and what decided them", x: 5, y: 13, w: 7, h: 8, fit: true, render: rulesPanel },
    ] });
    setNav("filter");
  }
  function rulesPanel(b) {
    const T = BP.DATA.meta.tiering;
    b.innerHTML = `<table class="tbl plain"><tbody>${Object.keys(BP.RULE).filter((r) => T.rules[r]).sort((a, b2) => BP.TIER_RANK[BP.RULE_TIER(a)] - BP.TIER_RANK[BP.RULE_TIER(b2)] || T.rules[b2] - T.rules[a]).map((r) => `<tr data-node-row="r-${r}"><td><span class="tp ${BP.RULE_TIER(r)}"><i></i>${BP.TIER[BP.RULE_TIER(r)][0]}</span></td><td>${esc(BP.RULE[r])}</td><td class="r"><b>${num(T.rules[r])}</b></td></tr>`).join("")}</tbody></table>
      <p class="hint">No scores are added up. A benchmark is recommended when its tasks are real, its results can be trusted, and it is still hard or widely noticed, with nothing weak.</p>`;
  }
  function pickNode(id) {
    flowSel = id;
    document.querySelectorAll(".flowsvg .fl-n").forEach((g) => g.classList.toggle("sel", g.dataset.node === id));
    document.querySelectorAll(".flowsvg .fl-l, .flowsvg .fl-f").forEach((p) => p.classList.toggle("lit", p.dataset.to === id));
    const d = document.getElementById("flow-detail");
    if (d) { d.innerHTML = BP.flow.detail(id); d.scrollTop = 0; hookDropped(); const r = d.getBoundingClientRect(); if (r.top > innerHeight - 120) d.closest(".grid-stack-item").scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "start" }); }
  }
  function hookDropped() {
    if (flowSel !== "x-bench") return;
    BP.flow.loadDropped().then(() => { const el = document.getElementById("dropped"); if (el) el.innerHTML = BP.flow.dropped(); });
  }

  // ---------- full page for one benchmark ----------
  function detailPage(id) {
    const it = BP.byId(id);
    if (!it) { app.innerHTML = `<div class="page"><div class="empty">Not in the pool. <a href="#/board">Back to the board</a></div></div>`; return; }
    document.title = `${it.name} · bench-pool`;
    const I = BP.item;
    app.innerHTML = `<div class="page"><a class="back" href="#/board/${encodeURIComponent(it.id)}">← Board</a><div class="dhead rise">${I.head(it)}</div><div id="board"></div></div>`;
    const p = (pid, title, html, x, y, w, h) => (html ? { id: pid, title, x, y, w, h, fit: true, render: (b) => { b.innerHTML = html; } } : null);
    const panels = [
      p("ready", "Adapter readiness", I.readiness(it), 0, 0, 12, 10),
      p("verdict", "Verdict", I.verdict(it) + I.path(it), 0, 10, 5, 8),
      p("evidence", "Why: each dimension and what it rests on", I.evidence(it), 5, 0, 7, 12),
      p("risks", "To settle before bringing it into Harbor", I.risks(it), 0, 8, 5, 5),
      p("facts", "Facts looked up first", I.facts(it), 0, 13, 5, 7),
      p("score", "Best score", I.score(it), 5, 12, 7, 6),
      p("coverage", "What is public", I.coverage(it), 5, 18, 7, 3),
      p("about", "About", I.about(it), 0, 20, 7, 8),
      p("prov", "How it was judged", I.provenance(it), 7, 21, 5, 5),
    ].filter(Boolean);
    const bd = new BP.Board(document.getElementById("board"), { key: "detail", panels });
    requestAnimationFrame(() => bd.fit());
    setNav("");
  }

  // ---------- about ----------
  function about() {
    const L = BP.DATA.meta.leaderboards;
    app.innerHTML = `<div class="page"><header class="hero2 sm rise"><h1><span class="h-a">Where the data comes from.</span> <span class="h-b">What each field is, who wrote it, and what it cannot tell you.</span></h1></header><div id="board"></div></div>`;
    const card = (rows) => `<dl class="kv wide">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
    new BP.Board(document.getElementById("board"), { key: "about", panels: [
      { id: "src", title: "Sources", x: 0, y: 0, w: 6, h: 8, fit: true, render: (b) => { b.innerHTML = card([
        ["Radar", `Most records come from <a href="https://benchmark-radar.org/" target="_blank" rel="noopener">Benchmark Radar</a>'s daily snapshots (CC BY-NC-SA 4.0), ${esc(BP.DATA.meta.snapshots.first)} to ${esc(lastDay())}: titles, dates, authors, links, attention counts and tags, unchanged.`],
        ["Our searches", "Since 2026-10-18 we also search every day ourselves: the arXiv API, Hugging Face Daily Papers and new benchmark datasets, GitHub repositories with at least 10 stars, and the blogs of OpenAI, Anthropic, Google Research, METR, Ai2, Epoch AI and others. Over the first 30 days these found 113 benchmarks Radar did not have."],
        ["Model-read", "The benchmark gate, mode, class, multimodal tag, the realism and value lines and the tier were written by a language model."],
        ["Attention", "GitHub stars and Semantic Scholar citations are fetched again for each benchmark; zero citations on a new paper says nothing."]]); } },
      { id: "lb", title: "Scores", x: 6, y: 0, w: 6, h: 8, fit: true, render: (b) => { b.innerHTML = card([
        ["Own leaderboard", `${num(L.own)} benchmarks with a top score; ${num(L.own_listed)} more where a leaderboard exists but its top score could not be read. A model reads the benchmark's own pages and keeps a score only when the quoted row is on the page.`],
        ["Aggregator", `${num(L.aggregator)} benchmarks: the top row of dated crawls of LLM Stats, Artificial Analysis and Benchmark Saturation. Many rows are vendor self-reported.`],
        ["Paper-reported", `${num(L.paper)} benchmarks: the best score the paper states. The authors' own figure, drawn hollow.`],
        ["Limits", `"None found" (${num(L.searched_none)}) means the search ran and found nothing; it does not use a web search engine. ${num(L.unchecked)} were not searched yet.`]]); } },
      { id: "ranking", title: "How the ranking works", x: 0, y: 8, w: 12, h: 7, fit: true, render: (b) => { b.innerHTML = card([
        ["Popular", "Tracked by Epoch AI, Artificial Analysis or Benchmark Saturation, reported by at least 10 models on LLM Stats, or used in Harbor Index v1."],
        ["Best score", "The highest score any of these sources reports, or the benchmark's own leaderboard. A paper's own figure counts only while the benchmark is under a year old."],
        ["Ceiling", "The best score a perfect agent could reach: 100%, unless Epoch AI estimates less or an audit states a share of tasks are broken, unsolvable or mislabelled."],
        ["Real or not", "A model reads the benchmark's facts, its scores, Epoch AI's record history and up to eight arXiv papers that audit or revise it, and decides whether the gap is models failing valid tasks (real headroom), largely the benchmark's fault (suspect), or not shown either way (not verified). Every claim must quote that text."],
        ["Groups", "Real headroom, not verified and suspect are ordered by headroom. Saturated: within 10 points of the ceiling. Pace: points the record rose per month over the last year."]]); } },
      { id: "modes", title: "Modes", x: 0, y: 15, w: 6, h: 6, fit: true, render: (b) => { b.innerHTML = card(Object.keys(BP.MODE).map((m) => [BP.MODE[m][0], esc(BP.MODE[m][1]) + "."])) + `<p class="hint">Following the Harbor Index v1 paper, Appendix D.2. The mode is a signal for recommending, not a reason to leave a benchmark out.</p>`; } },
      { id: "dims", title: "The six dimensions", x: 6, y: 15, w: 6, h: 6, fit: true, render: (b) => { b.innerHTML = card(Object.keys(BP.DIM).map((k) => [BP.DIM[k], esc(BP.DIM_HELP[k]) + "."])); } },
    ] });
    setNav("about");
  }

  // ---------- routing ----------
  function setNav(name) { document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === name)); }
  let lastPage = null;
  function render() {
    const h = location.hash.replace(/^#\/?/, "").split("?")[0];
    const [page, ...rest] = h.split("/");
    let arg = rest.length ? decodeURIComponent(rest.join("/")) : undefined;
    const kind = page === "b" ? "detail" : ["list", "timeline", "saturation", "board"].includes(page) ? "board" : ["new", "filter", "about", "rank", "compare"].includes(page) ? page : "overview";
    const split = kind === "board" || kind === "new" || kind === "rank";
    if (split || ["board", "new", "rank"].includes(lastPage)) swapState(["board", "new", "rank"].includes(lastPage) ? lastPage : null, split ? kind : null);
    if (split) applyQuery();
    if (BP.board) BP.board.destroy();
    if (!split) BP.split = null;
    document.title = "bench-pool";
    if (page === "timeline" || page === "saturation") S.view = page;
    else if (page === "list") S.view = "list";
    if (arg && BP.byId(arg) && BP.byId(arg).id !== arg) {          // an old id: show the permanent one
      history.replaceState(null, "", "#/" + page + "/" + encodeURIComponent(BP.byId(arg).id));
      arg = BP.byId(arg).id;
    }
    if (kind === "detail") detailPage(arg);
    else if (kind === "board") board(arg === undefined ? (lastPage === "board" ? S.sel : null) : arg);
    else if (kind === "new") newPage(arg === undefined ? null : arg);
    else if (kind === "compare") comparePage(arg);
    else if (kind === "rank") rankPage(arg === undefined ? (lastPage === "rank" ? S.sel : null) : arg);
    else if (kind === "filter") filterPage();
    else if (kind === "about") about();
    else overview();
    if (kind !== lastPage) window.scrollTo(0, 0);
    lastPage = kind;
    BP.menu.refresh();
  }
  // Filters live in the address too (#/board?tier=recommend&cls=1), so a filtered view can be shared.
  function applyQuery() {
    const q = location.hash.split("?")[1];
    if (!q) return;
    const p = new URLSearchParams(q);
    for (const [k, v] of p) {
      if (k === "band" || k === "scope" || k === "rcover" || k === "by" || k === "win") { BP.QS = BP.QS || {}; BP.QS[k] = v; continue; }
      if (!FILTER_KEYS.includes(k)) continue;
      S[k] = ["cls", "dir"].includes(k) ? +v : v === "true" ? true : v === "false" ? false : v;
    }
  }
  BP.shareUrl = () => {
    const p = new URLSearchParams();
    FILTER_KEYS.forEach((k) => { if (S[k] !== DEFAULTS[k] && S[k] != null && S[k] !== "") p.set(k, S[k]); });
    const page = BP.split ? BP.split.kind : "board";
    if (page === "rank") { if (R.band) p.set("band", R.band); if (R.scope !== "all") p.set("scope", R.scope); if (R.cover !== "all") p.set("rcover", R.cover); }
    if (page === "new") { p.set("by", N.by); p.set("win", N.win); }
    return location.origin + location.pathname + "#/" + page + (p.toString() ? "?" + p : "");
  };

  // Each list page keeps its own filters, so a filter set on New does not follow you to Ranking.
  const PAGE_STATE = {};
  const FILTER_KEYS = ["cls", "sub", "mm", "mode", "tier", "cover", "quick", "q", "week", "sort", "dir", "view", "basis"];
  const DEFAULTS = Object.fromEntries(FILTER_KEYS.map((k) => [k, BP.S[k]]));
  function swapState(from, to) {
    if (from === to) return;
    if (from) PAGE_STATE[from] = Object.fromEntries(FILTER_KEYS.map((k) => [k, S[k]]));
    if (to) Object.assign(S, DEFAULTS, PAGE_STATE[to] || {}, BP._preset || {});
    BP._preset = null;
  }
  BP.route = function () {
    const h = location.hash.replace(/^#\/?/, "").split(/[/?]/)[0] || "overview";
    const changing = BP._page !== undefined && BP._page !== h;   // no transition on first load
    BP._page = h;
    if (changing && document.startViewTransition && !reduced()) document.startViewTransition(render);
    else render();
  };
  const refresh = () => { S.limit = 200; const k = BP.split && BP.split.kind; if (k === "new") newPage(); else if (k === "rank") rankPage(); else board(); };

  function toast(text) {
    let t = document.getElementById("toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
    t.textContent = text; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 1600);
  }
  // Starring only touches the Compare button: re-rendering the list would lose its scroll position.
  function centerHeadRefresh() {
    const act = document.querySelector(".ch-act");
    if (!act) return;
    const ids = Object.keys(BP.shortlist.get());
    let btn = act.querySelector("[data-cmp]");
    if (ids.length > 1) {
      if (!btn) { act.insertAdjacentHTML("beforeend", `<a class="tbtn sm" data-cmp title="Compare shortlisted benchmarks side by side">Compare ★</a>`); btn = act.querySelector("[data-cmp]"); }
      btn.href = "#/compare/" + encodeURIComponent(ids.slice(0, 4).join(","));
    } else if (btn) btn.remove();
  }

  // ---------- events ----------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-brief],[data-band],[data-rcover],[data-rscope],[data-nby],[data-nwin],[data-pin],[data-share],[data-export],[data-compare],[data-unpin],[data-theme-set],[data-panel-close],[data-panel-reset],#panels-btn,[data-preset],[data-cls-go],[data-week],[data-node],[data-node-go],[data-node-row],[data-goto-tier],[data-fmore],[data-cover],[data-tier],[data-mode],[data-cls],[data-sub],[data-quick],[data-mm],[data-clear],[data-unset],[data-view],[data-sort],[data-more],[data-basis],[data-cell],[data-pick],[data-desel],[data-sb-toggle],[data-dim],tr[data-id]");
    const pop = document.getElementById("panels-pop");
    if (pop && !pop.hidden && !e.target.closest("#panels-pop, #panels-btn")) pop.hidden = true;
    if (!t) return;
    const d = t.dataset;
    if (d.band) { R.band = R.band === d.band ? null : d.band; rankPage(); return; }
    if (d.rcover) { R.cover = d.rcover; rankPage(); return; }
    if (d.rscope) { R.scope = d.rscope; rankPage(); return; }
    if (d.pin) { e.stopPropagation(); const on = BP.shortlist.toggle(d.pin); document.querySelectorAll(`[data-pin="${CSS.escape(d.pin)}"]`).forEach((b) => b.classList.toggle("on", on)); if (BP.split) { if (S.quick === "pinned") refresh(); else centerHeadRefresh(); } if (document.getElementById("insp") && S.sel === d.pin) inspector(false); return; }
    if (d.unpin) { BP.shortlist.toggle(d.unpin); location.hash = "#/compare/" + encodeURIComponent(Object.keys(BP.shortlist.get()).slice(0, 4).join(",")); return; }
    if (d.share != null) { const u = BP.shareUrl(); (navigator.clipboard ? navigator.clipboard.writeText(u) : Promise.reject()).then(() => toast("Link copied"), () => prompt("Link to this view", u)); return; }
    if (d.export) { exportRows(d.export); return; }
    if (d.brief) { const it = BP.byId(d.brief); const text = BP.brief(it); (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => toast("Adapter brief copied"), () => prompt("Adapter brief", text)); return; }
    if (d.nwin) { N.win = d.nwin; newPage(); return; }
    if (d.nby) { N.by = d.nby; newPage(); return; }
    if (d.themeSet) { document.documentElement.dataset.theme = d.themeSet; BP.store.set("bp.theme", d.themeSet); document.querySelectorAll("[data-theme-set]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.themeSet === d.themeSet)); }
    else if (d.panelClose) BP.board && BP.board.close(d.panelClose);
    else if (d.panelReset != null) { pop.hidden = true; BP.menu.reset(); }
    else if (t.id === "panels-btn") { pop.hidden = !pop.hidden; BP.menu.refresh(); }
    else if (d.preset) { e.preventDefault(); BP._preset = { tier: d.preset === "recommend" ? "recommend" : null, quick: d.preset === "sat" ? "sat" : null, cover: d.preset === "covered" ? "covered" : "open" };
      PAGE_STATE.board = null; location.hash = "#/board"; }
    else if (d.clsGo) { BP._preset = { cls: +d.clsGo, view: d.viewGo || "list" }; PAGE_STATE.board = null; location.hash = "#/board"; }
    else if (d.week) { BP._preset = { week: d.week }; PAGE_STATE.board = null; location.hash = "#/board"; }
    else if (d.node || d.nodeGo || d.nodeRow) { const id = d.node || d.nodeGo || d.nodeRow; if (document.getElementById("flow-detail")) pickNode(id); else location.hash = "#/filter"; if (!document.getElementById("flow-detail")) setTimeout(() => pickNode(id), 60); }
    else if (d.gotoTier) { BP._preset = { tier: d.gotoTier }; PAGE_STATE.board = null; location.hash = "#/board"; }
    else if (d.fmore != null) { BP.flow.limit += 60; document.getElementById("dropped").innerHTML = BP.flow.dropped(); }
    else if (d.cover) { S.cover = d.cover; if (d.cover === "covered") S.tier = null; refresh(); }
    else if (d.tier != null && t.matches("button")) { S.tier = S.tier === d.tier ? null : d.tier; refresh(); }
    else if (d.mode != null && t.matches("button")) { S.mode = S.mode === d.mode ? null : d.mode; refresh(); }
    else if (d.cls != null) { S.cls = +d.cls; S.sub = null; refresh(); }
    else if (d.sub != null) { S.sub = S.sub === d.sub ? null : d.sub; refresh(); }
    else if (d.quick) { S.quick = S.quick === d.quick ? null : d.quick; refresh(); }
    else if (d.mm) { S.mm = !S.mm; refresh(); }
    else if (d.clear != null) { Object.assign(S, { tier: null, mode: null, cls: 0, sub: null, quick: null, mm: false, q: "", week: null, cover: "open" }); refresh(); }
    else if (d.unset) { const k = d.unset; if (k === "cls") { S.cls = 0; S.sub = null; } else if (k === "mm") S.mm = false; else if (k === "q") S.q = ""; else S[k] = null; refresh(); }
    else if (d.view) { S.view = d.view; board(); }
    else if (d.sort) { if (S.sort === d.sort) S.dir = -S.dir; else { S.sort = d.sort; S.dir = d.sort === "name" || d.sort === "tier" ? 1 : -1; } listView(); centerHead(document.querySelector(".ch .h-a").textContent, "· sorted by " + { tier: "tier, newest first", name: "name", best: "best score", date: "date", att: "attention" }[S.sort], true); }
    else if (d.more != null) { S.limit += 200; listView(); }
    else if (d.basis) { S.basis = d.basis; saturationView(); }
    else if (d.cell) { const [c, w] = d.cell.split("|"); Object.assign(S, { cls: +c, sub: null, week: w, view: "list" }); board(); }
    else if (d.pick) { select(d.pick); }
    else if (d.desel != null) { S.sel = null; document.querySelectorAll(".tbl tr.sel").forEach((r) => r.classList.remove("sel")); history.replaceState(null, "", "#/" + (BP.split ? BP.split.kind : "board")); inspector(); }
    else if (d.sbToggle != null) document.getElementById("split").classList.toggle("sb-open");
    else if (d.dim) { const on = !t.classList.contains("pin"); document.querySelectorAll("[data-dim]").forEach((x) => x.classList.toggle("pin", on && x.dataset.dim === d.dim));
      document.querySelectorAll("[data-fact]").forEach((f) => f.classList.toggle("lit", on && (BP.DIM_FACTS[d.dim] || []).includes(f.dataset.fact))); }
    else if (d.id && !e.target.closest("a")) select(d.id);
  });
  document.addEventListener("change", (e) => { if (e.target.dataset && e.target.dataset.panelToggle) BP.menu.toggle(e.target.dataset.panelToggle, e.target.checked); });
  document.addEventListener("input", (e) => {
    if (e.target.id === "q") { S.q = e.target.value.trim(); const pos = e.target.selectionStart; refresh(); const q = document.getElementById("q"); if (q) { q.focus(); q.setSelectionRange(pos, pos); } }
    if (e.target.dataset && e.target.dataset.note) { BP.shortlist.note(e.target.dataset.note, e.target.value); return; }
    if (e.target.id === "fq") { BP.flow.q = e.target.value.trim(); BP.flow.limit = 60; document.getElementById("dropped").innerHTML = BP.flow.dropped(); }
  });
  document.addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement && document.activeElement.tagName);
    if (e.key === "/" && !typing) { const q = document.getElementById("q"); if (q) { e.preventDefault(); q.focus(); } }
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !typing && BP.split && BP.rows && BP.rows.length) {
      e.preventDefault();
      const i = BP.rows.indexOf(S.sel), j = Math.max(0, Math.min(BP.rows.length - 1, i < 0 ? 0 : i + (e.key === "ArrowDown" ? 1 : -1)));
      if (j >= S.limit && BP.split.kind === "board") { S.limit += 200; listView(); }
      select(BP.rows[j], { scroll: true });
    }
    if (e.key === "Escape" && S.sel && BP.split) document.querySelector("[data-desel]") && document.querySelector("[data-desel]").click();
    if (e.key === "Enter" && e.target.dataset && (e.target.dataset.cell || e.target.dataset.node || e.target.dataset.dim)) e.target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });

  // Divider drag (1 px, both neighbours resize together).
  document.addEventListener("pointerdown", (e) => {
    const dv = e.target.closest(".dv");
    if (!dv) return;
    const split = document.getElementById("split"), which = dv.dataset.dv, x0 = e.clientX;
    const w0 = parseInt(split.style.getPropertyValue("--" + which)) || (which === "sb" ? 248 : 470);
    const [lo, hi] = which === "sb" ? [190, 380] : [340, Math.min(900, innerWidth - 560)];
    dv.setPointerCapture(e.pointerId); split.classList.add("dragging");
    const move = (ev) => { const dx = ev.clientX - x0; split.style.setProperty("--" + which, Math.max(lo, Math.min(hi, which === "sb" ? w0 + dx : w0 - dx)) + "px"); };
    const up = () => { dv.removeEventListener("pointermove", move); dv.removeEventListener("pointerup", up); split.classList.remove("dragging"); saveSplit(); };
    dv.addEventListener("pointermove", move); dv.addEventListener("pointerup", up);
  });

  // Tooltip.
  const tip = document.getElementById("tip");
  document.addEventListener("mousemove", (e) => {
    const t = e.target.closest ? e.target.closest("[data-tip]") : null;
    if (!t) { tip.classList.remove("on"); return; }
    if (tip.textContent !== t.dataset.tip) tip.textContent = t.dataset.tip;
    tip.classList.add("on");
    const w = tip.offsetWidth, x = Math.min(innerWidth - w - 10, e.clientX + 14);
    tip.style.left = Math.max(10, x) + "px";
    tip.style.top = (e.clientY + 18 + tip.offsetHeight > innerHeight ? e.clientY - tip.offsetHeight - 12 : e.clientY + 18) + "px";
  });
  window.addEventListener("hashchange", () => { tip.classList.remove("on"); BP.route(); });

  fetch("data/benchmarks.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      d.items.forEach((x) => { if (x.pid) { x.oid = x.id; x.id = x.pid; } });
      BP.DATA = d; BP.CLASS = {}; d.meta.classes.forEach((c) => { BP.CLASS[c.id] = c; });
      BP.CIDS = d.meta.classes.map((c) => c.id);
      d.newSince = BP.iso(BP.addDays(BP.day(d.meta.snapshots.last), -30));
      document.getElementById("foot-date").textContent = d.meta.generated.slice(0, 10);
      BP.route();
    })
    .catch((err) => { app.innerHTML = `<div class="page"><div class="empty">Could not load data/benchmarks.json (${esc(err.message)}). Run scripts/build.py.</div></div>`; });
})();
