/* The filter as a flow chart: Radar records -> candidates -> benchmarks -> pool -> new candidates -> tiers -> what
   decided them. What each step turns away branches down. Link thickness is on a log scale; links flow. */
(function () {
  "use strict";
  const BP = (window.BP = window.BP || {});
  const esc = BP.esc, num = BP.num;
  const F = (BP.flow = {});

  const RULE_SHORT = {
    T2: "Agentic, every bar met", T3: "Non-agentic, hard and noticed", T0: "Nothing to read yet", T4: "A person must settle it",
    B1: "No public task data", B2: "No container or verifier", B3: "Saturated, 90% or more", B4: "Superseded", B5: "Not a benchmark after all", B6: "Trains policies, not agents",
  };
  F.RULE_SHORT = RULE_SHORT;

  F.model = () => {
    const m = BP.DATA.meta, f = m.funnel, T = m.tiering, g = m.gate;
    const covered = (T.covered.v1 || 0) + (T.covered.adapter || 0);
    const N = [
      { id: "records", label: "Records read", n: f.records, col: 0, kind: "spine" },
      { id: "cand", label: "Candidates", n: f.candidates, col: 1, kind: "spine" },
      { id: "bench", label: "Judged a benchmark", n: f.kept_records, col: 2, kind: "spine" },
      { id: "pool", label: "In the pool", n: f.benchmarks, col: 3, kind: "spine" },
      { id: "newc", label: "New candidates", n: T.candidates, col: 4, kind: "spine" },
      { id: "x-cand", label: "Not about agents", n: f.records - f.candidates, col: 1, kind: "drop", from: "records" },
      { id: "x-bench", label: "Not a benchmark", n: f.not_benchmark, col: 2, kind: "drop", from: "cand" },
      { id: "x-merge", label: "Merged duplicates", n: Math.max(0, f.kept_records - f.benchmarks), col: 3, kind: "drop", from: "bench" },
      { id: "x-cover", label: "Already covered", n: covered, col: 4, kind: "drop", from: "pool" },
    ];
    ["recommend", "hold", "no"].forEach((t) => N.push({ id: "t-" + t, label: BP.TIER[t][0], n: T.tiers[t] || 0, col: 5, kind: "tier", tier: t, from: "newc" }));
    Object.keys(RULE_SHORT).forEach((r) => { if (T.rules[r]) N.push({ id: "r-" + r, label: RULE_SHORT[r], n: T.rules[r], col: 6, kind: "rule", tier: BP.RULE_TIER(r), rule: r, from: "t-" + BP.RULE_TIER(r) }); });
    N.forEach((n) => { if (n.kind === "spine" && n.col) n.from = N.find((x) => x.kind === "spine" && x.col === n.col - 1).id; });
    return { nodes: N, max: f.records, gate: g };
  };

  F.svg = (opts) => {
    opts = opts || {};
    const M = F.model();
    const rules = opts.rules !== false;
    const nodes = M.nodes.filter((n) => rules || n.kind !== "rule");
    const colW = 166, nodeW = 140, ruleW = 214, nodeH = 46, x0 = 8;
    const X = (c) => x0 + c * colW;
    const spineY = 70, dropY = 250;
    // tiers and their rules, stacked on the right
    const tierY = { recommend: 46, hold: 168, no: 318 };
    const ruleNodes = nodes.filter((n) => n.kind === "rule");
    const pos = {};
    for (const n of nodes) {
      if (n.kind === "spine") pos[n.id] = [X(n.col), spineY];
      if (n.kind === "drop") pos[n.id] = [X(n.col), dropY];
      if (n.kind === "tier") pos[n.id] = [X(n.col), tierY[n.tier]];
    }
    const groups = { recommend: [], hold: [], no: [] };
    ruleNodes.forEach((n) => groups[n.tier].push(n));
    const rh = 32;
    for (const t of ["recommend", "hold", "no"]) {
      const g = groups[t], top = tierY[t] - ((g.length - 1) * rh) / 2;
      g.forEach((n, i) => { pos[n.id] = [X(6), Math.max(8 + rh / 2, top + i * rh)]; });
    }
    // keep rule rows from overlapping between groups
    let last = -1e9;
    for (const n of ruleNodes.sort((a, b) => pos[a.id][1] - pos[b.id][1])) { if (pos[n.id][1] < last + rh) pos[n.id][1] = last + rh; last = pos[n.id][1]; }
    const W = rules ? X(6) + ruleW + 8 : X(5) + nodeW + 8;
    const H = Math.max(dropY + nodeH / 2 + 14, ...Object.values(pos).map((p) => p[1] + 26));
    const thick = (n) => Math.max(2, 20 * Math.log10(n + 1) / Math.log10(M.max + 1));
    const color = (n) => (n.kind === "drop" ? "drop" : n.tier || "spine");

    let links = "", flows = "", out = "";
    nodes.forEach((n, i) => {
      if (!n.from || !pos[n.from]) return;
      const [sx, sy] = pos[n.from], [tx, ty] = pos[n.id];
      const ax = sx + nodeW, bx = tx;
      const mx = (ax + bx) / 2;
      const d = `M${ax} ${sy} C ${mx} ${sy}, ${mx} ${ty}, ${bx} ${ty}`;
      links += `<path class="fl-l ${color(n)}" data-to="${n.id}" d="${d}" style="stroke-width:${thick(n.n).toFixed(1)}px"/>`;
      flows += `<path class="fl-f ${color(n)}" data-to="${n.id}" d="${d}" style="animation-delay:${(-i * 0.37).toFixed(2)}s"/>`;
    });
    nodes.forEach((n, i) => {
      const [x, y] = pos[n.id];
      const w = n.kind === "rule" ? ruleW : nodeW, h = n.kind === "rule" ? 26 : nodeH;
      const sel = opts.sel === n.id ? " sel" : "";
      if (n.kind === "rule") {
        out += `<g class="fl-n rule ${color(n)}${sel}" data-node="${n.id}" tabindex="0" role="button" aria-label="${esc(n.label)}: ${n.n}" style="--i:${i}">
          <rect x="${x}" y="${y - h / 2}" width="${w}" height="${h}" rx="8"/>
          <text x="${x + 10}" y="${y + 4}" class="lab">${esc(n.label)}</text><text x="${x + w - 10}" y="${y + 4}" class="cnt" text-anchor="end">${num(n.n)}</text></g>`;
      } else {
        out += `<g class="fl-n ${n.kind} ${color(n)}${sel}" data-node="${n.id}" tabindex="0" role="button" aria-label="${esc(n.label)}: ${n.n}" style="--i:${i}">
          <rect x="${x}" y="${y - h / 2}" width="${w}" height="${h}" rx="11"/>
          <text x="${x + 12}" y="${y - 3}" class="cnt">${num(n.n)}</text><text x="${x + 12}" y="${y + 14}" class="lab">${esc(n.label)}</text></g>`;
      }
    });
    return `<svg class="flowsvg${opts.compact ? " compact" : ""}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMinYMin meet" role="group" aria-label="How the pool is filtered">${links}${flows}${out}</svg>`;
  };

  // What a node means, and the items behind it.
  F.detail = (id) => {
    const M = F.model(), n = M.nodes.find((x) => x.id === id);
    if (!n) return "";
    const m = BP.DATA.meta, f = m.funnel, T = m.tiering, g = m.gate;
    const bar = Object.entries(g.traction_bar).map(([k, v]) => `${num(v)}+ ${k}`).join(", ");
    const text = {
      records: `Every record in ${m.snapshots.days} daily Benchmark Radar snapshots (${esc(m.snapshots.first)} to ${esc(m.snapshots.last)}), plus our own daily searches since 2026-10-18: the arXiv API, Hugging Face Daily Papers and datasets, GitHub, and lab and evaluation blogs. A paper or repository is counted once per day it appears.`,
      "x-cand": `A record goes on only if it is tagged as a benchmark <b>and</b> it is about agents (${num(g.no_agent_word_records)} records name nothing an agent does), or if people have clearly noticed it (${esc(bar)}). The rest, and repeats of the same record in later snapshots, stop here.`,
      cand: `Records that passed the first rules, with repeats merged. Benchmarks listed on public leaderboards and a hand-kept list of established benchmarks are added here.`,
      "x-bench": `One question for a language model: does this release a benchmark others can run? Models, methods, frameworks, surveys, training-only datasets and papers that only use existing benchmarks are turned away. Every one is listed below with the reason given.`,
      bench: `Candidates judged to release a benchmark, evaluation suite or environment others can run. This is the only inclusion rule.`,
      "x-merge": `Several records can describe the same benchmark (paper, repository, dataset, a later version). Same names are merged into one benchmark.`,
      pool: `${num(f.by_mode.agentic || 0)} agentic, ${num(f.by_mode.modified || 0)} modified-agentic and ${num(f.by_mode.non || 0)} non-agentic benchmarks. The mode is a signal for recommending, not a filter.`,
      "x-cover": `${num(T.covered.v1 || 0)} benchmarks Harbor Index v1 already takes tasks from, and ${num(T.covered.adapter || 0)} more with a merged Harbor adapter. They stay on the board as reference and are not tiered.`,
      newc: `Every new candidate gets a tier. A model reads the whole paper (arXiv HTML or PDF) and the repository README, answers a fixed list of checks with quotes, then judges six dimensions. Rules turn the dimensions into a tier. The paper was read for ${num(T.read.paper)}, only a README for ${num(T.read.readme_only)}; ${num(T.read.nothing)} have neither.`,
    }[id];
    let body = "";
    if (n.kind === "tier" || n.kind === "rule") {
      const items = BP.DATA.items.filter((it) => !it.covered && it.tier && (n.kind === "tier" ? it.tier.tier === n.tier : it.tier.rule === n.rule))
        .sort((a, b) => BP.attention(b) - BP.attention(a));
      const what = n.kind === "tier" ? BP.TIER[n.tier][1] + "." : esc(BP.RULE[n.rule]) + ".";
      const rules = n.kind === "tier" ? `<div class="chips">${M.nodes.filter((x) => x.kind === "rule" && x.tier === n.tier).map((x) => `<button type="button" class="chip" data-node-go="${x.id}">${esc(x.label)} <b>${num(x.n)}</b></button>`).join("")}</div>` : "";
      body = `<p>${what}</p>${rules}
        <div class="fd-actions"><button type="button" class="btn" data-goto-tier="${n.tier}"${n.rule ? ` data-goto-rule="${n.rule}"` : ""}>Open these ${num(items.length)} in the board</button></div>
        <ul class="mini">${items.slice(0, 80).map((it) => `<li><a href="#/board/${encodeURIComponent(it.id)}">${esc(it.name)}</a><span>${esc(BP.plain(it.tier.reason))}</span></li>`).join("")}</ul>
        ${items.length > 80 ? `<p class="hint">${num(items.length - 80)} more in the board.</p>` : ""}`;
    } else if (id === "x-bench") {
      body = `<p>${text}</p><label class="search"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg><input id="fq" type="search" placeholder="Search what was turned away" autocomplete="off" aria-label="Search turned-away candidates" value="${esc(F.q || "")}"></label><div id="dropped">${F.dropped()}</div>`;
    } else if (id === "x-cover") {
      const items = BP.DATA.items.filter((it) => it.covered).sort((a, b) => a.name.localeCompare(b.name));
      body = `<p>${text}</p><ul class="mini">${items.map((it) => `<li><a href="#/board/${encodeURIComponent(it.id)}">${esc(it.name)}</a><span>${it.covered === "v1" ? "Harbor Index v1" : "Harbor adapter"}</span></li>`).join("")}</ul>`;
    } else body = `<p>${text}</p>`;
    return `<div class="fd rise"><div class="fd-h"><span class="fd-n">${num(n.n)}</span><span class="fd-l">${esc(n.label)}</span></div>${body}</div>`;
  };

  F.q = ""; F.limit = 60; F.DROPPED = null;
  F.dropped = () => {
    if (!F.DROPPED) return `<p class="hint">Loading…</p>`;
    const words = F.q.toLowerCase().split(/\s+/).filter(Boolean);
    const rows = F.DROPPED.filter((d) => words.every((w) => (d.title + " " + d.why).toLowerCase().includes(w)));
    return `<p class="hint">${num(rows.length)} of ${num(F.DROPPED.length)}</p><ul class="mini">${rows.slice(0, F.limit).map((d) => `<li>${d.url ? `<a href="${esc(BP.safeUrl(d.url))}" target="_blank" rel="noopener">${esc(d.title)}</a>` : esc(d.title)}<span>${esc(d.why)}</span></li>`).join("")}</ul>
      ${rows.length > F.limit ? `<button type="button" class="btn ghost" data-fmore>Show 60 more</button>` : ""}`;
  };
  F.loadDropped = () => {
    if (F.DROPPED) return Promise.resolve();
    return fetch("data/dropped.json", { cache: "no-cache" }).then((r) => r.json()).then((d) => { F.DROPPED = d; });
  };
})();
