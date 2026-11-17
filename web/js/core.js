/* Shared data, labels, helpers and filter state. */
(function () {
  "use strict";
  const BP = (window.BP = window.BP || {});

  BP.ICONS = {
    0: '<circle cx="12" cy="12" r="2.6"/><circle cx="12" cy="12" r="6.4"/><circle cx="12" cy="12" r="10"/>',
    1: '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.6 5l-3.2 14"/>',
    2: '<path d="M17.5 6V4.5h-11l6.2 7.5-6.2 7.5h11V18"/>',
    3: '<path d="M12 6.5C10 5 7 4.5 3.5 4.5v13c3.5 0 6.5.5 8.5 2 2-1.5 5-2 8.5-2v-13C17 4.5 14 5 12 6.5zM12 6.5v13"/>',
    4: '<path d="M9 3h6M10 3v6.2L4.9 18a2 2 0 0 0 1.7 3h10.8a2 2 0 0 0 1.7-3L14 9.2V3M7.6 15h8.8"/>',
    5: '<circle cx="5.5" cy="6" r="2.5"/><circle cx="18.5" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8 6h8M6.8 8.2l3.9 7.6M17.2 8.2l-3.9 7.6"/>',
    6: '<path d="M3.5 20.5h17M7 20.5V13M12 20.5V5M17 20.5V10"/>',
    7: '<path d="M3 7.5h18v12H3zM9 7.5V5.2a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2.3M3 13h18"/>',
    8: '<path d="M12 3l8 3v6c0 4.6-3.2 8-8 9.2C7.2 20 4 16.6 4 12V6l8-3zM9 12l2.2 2.2L15 10.2"/>',
    9: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.6"/><path d="M3 16.5l5-4.5 4 3.5 3.5-3 5.5 4.5"/>',
    10: '<path d="M6.5 8h11a4.5 4.5 0 0 1 4.5 4.5A3.5 3.5 0 0 1 15.8 15H8.2A3.5 3.5 0 0 1 2 12.5 4.5 4.5 0 0 1 6.5 8zM7.5 10.3v3M6 11.8h3"/><circle cx="16" cy="10.8" r=".7"/><circle cx="18" cy="12.8" r=".7"/>',
  };
  BP.SHORT = { 0: "All classes", 1: "Software", 2: "Math", 3: "Knowledge", 4: "Science", 5: "Agents & tools", 6: "Data", 7: "Professional", 8: "Safety", 9: "Multimodal", 10: "Games & embodied" };
  // Agent interaction mode, Harbor Index v1 paper, Appendix D.2.
  BP.MODE = {
    agentic: ["Agentic", "Designed for agents: tasks need multi-step interaction with an environment or tools"],
    modified: ["Modified", "Originally single-pass, but giving an agent an environment changes the result"],
    non: ["Non-agentic", "Single-pass: the model answers from the prompt alone"],
  };
  BP.TIER = {
    recommend: ["Recommend", "Propose for Harbor Index now"],
    hold: ["Hold", "Plausible; a person must settle one point first"],
    no: ["No", "Something rules it out"],
    none: ["Not judged", "Not judged yet"],
  };
  BP.TIER_RANK = { recommend: 0, hold: 1, no: 2, none: 3 };
  BP.COVER = { v1: "Harbor Index v1 already takes tasks from it", adapter: "It already has a merged Harbor adapter" };
  // What decided a tier, in plain words. The codes are internal and never shown.
  BP.RULE = {
    B1: "No task data is public", B2: "Cannot run in a container with a programmatic verifier", B3: "Saturated: 90% or more on a leaderboard",
    B4: "Superseded by a successor", B5: "Not a benchmark on closer reading", B6: "Evaluates trained policies, not a model or agent",
    T0: "Nothing to read yet", T2: "Agentic: real tasks, trustworthy results, still hard or noticed, nothing weak",
    T3: "Non-agentic, but hard, unsaturated and widely noticed", T4: "Held for a person to settle",
  };
  BP.RULE_TIER = (r) => (r[0] === "B" ? "no" : r === "T2" || r === "T3" ? "recommend" : "hold");
  BP.DIM = { real: "Real", diverse: "Diverse", difficult: "Difficult", valuable: "Valuable", solid: "Solid", attention: "Attention" };
  BP.DIM_HELP = {
    real: "Tasks come from real work or real artifacts, not invented",
    diverse: "Many kinds of task inside the benchmark",
    difficult: "Current models are far from solving it",
    valuable: "Models cannot do it yet and it needs domain expertise",
    solid: "Tasks and environment work, so failures are the agent's",
    attention: "People have noticed it: stars, citations, leaderboards",
  };
  // Which looked-up facts bear on which dimension (for linked highlighting).
  BP.DIM_FACTS = {
    real: ["provenance", "human_review", "data_released"],
    diverse: [],
    difficult: [],
    valuable: ["domain_expertise"],
    solid: ["verifier", "judge_validated", "solvable", "environment", "gaming", "variance"],
    attention: [],
  };
  BP.CHECK = {
    data_released: ["Tasks public", { yes: "yes", partial: "partly", no: "no" }, { yes: "good", partial: "mid", no: "bad" }],
    provenance: ["Tasks come from", { real_artifacts: "real artifacts", expert_written: "experts", generated: "generated", mixed: "mixed" }, { real_artifacts: "good", expert_written: "good", generated: "bad", mixed: "mid" }],
    human_review: ["Reviewed by people", { yes: "yes", no: "no" }, { yes: "good", no: "bad" }],
    domain_expertise: ["Needs domain expertise", { yes: "yes", no: "no" }, { yes: "good", no: "mid" }],
    verifier: ["Verifier", { executable: "executable tests", exact_match: "exact match", llm_judge: "model judge", human: "human", mixed: "mixed" }, { executable: "good", exact_match: "good", llm_judge: "mid", human: "mid", mixed: "mid" }],
    judge_validated: ["Judge checked against people", { yes: "yes", no: "no", not_applicable: "no judge" }, { yes: "good", no: "bad", not_applicable: "na" }],
    solvable: ["Shown to be solvable", { yes: "yes", no: "no" }, { yes: "good", no: "bad" }],
    environment: ["Runs in", { container: "a container", live_web: "live websites", simulator: "a simulator", hardware: "hardware" }, { container: "good", live_web: "bad", simulator: "mid", hardware: "bad" }],
    gaming: ["Reward hacking addressed", { yes: "yes", no: "no" }, { yes: "good", no: "bad" }],
    variance: ["Repeated runs", { yes: "yes", no: "no" }, { yes: "good", no: "mid" }],
  };
  BP.KIND = { own: "Own leaderboard", aggregator: "Aggregator", paper: "Paper-reported" };

  // ---------- helpers ----------
  const esc = (BP.esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])));
  BP.icon = (id, size) => `<svg class="ci" viewBox="0 0 24 24" width="${size || 16}" height="${size || 16}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${BP.ICONS[id]}</svg>`;
  BP.pct = (v) => `${+v.toFixed(1)}%`;
  BP.num = (v) => Number(v).toLocaleString("en-US", { maximumFractionDigits: 1 });
  BP.short = (v) => (v >= 10000 ? Math.round(v / 1000) + "k" : v >= 1000 ? (v / 1000).toFixed(1) + "k" : String(v));
  BP.safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  BP.host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return "link"; } };
  BP.hash01 = (s) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 1000) / 1000; };
  BP.day = (d) => new Date(d + "T00:00:00Z");
  BP.iso = (d) => d.toISOString().slice(0, 10);
  BP.addDays = (d, n) => new Date(d.getTime() + n * 864e5);
  BP.monday = (d) => BP.addDays(d, -((d.getUTCDay() + 6) % 7));
  BP.when = (it) => it.date || it.seen;
  BP.tierOf = (it) => (it.covered ? "covered" : it.tier ? it.tier.tier : "none");
  BP.kindCls = (basis) => ({ aggregator: "agg", paper: "paper" }[basis] || "own");
  BP.hasLb = (it) => it.lb !== "none" && it.lb !== "unchecked";
  BP.attention = (it) => ((it.metrics && it.metrics.stars) || 0) + ((it.metrics && it.metrics.citations) || 0) * 5 + ((it.metrics && it.metrics.upvotes) || 0);
  // Long names: ellipsis in the middle (HIG), full name in the title attribute.
  BP.mid = (s, n) => { s = String(s || ""); n = n || 38; if (s.length <= n) return esc(s); const a = Math.ceil((n - 1) * 0.62), b = n - 1 - a; return esc(s.slice(0, a)) + "…" + esc(s.slice(-b)); };

  // The judge writes internal rule codes and field names into its reasons. Readers get plain words.
  BP.plain = (s) => String(s || "")
    .replace(/^\s*(?:T\d|B\d)\s*[:;,-]\s*/, "")
    .replace(/,? so T\d\b[^.;]*/g, "")
    .replace(/\bnew flag\b/g, "allowance for new benchmarks")
    .replace(/\bT2(?:'s)?\b(?: recommend(?:ation)?)?/g, "the recommend rule for agentic benchmarks")
    .replace(/\bT3(?:'s)?\b(?: recommend(?:ation)?)?/g, "the recommend rule for non-agentic benchmarks")
    .replace(/\bT4\b/g, "the hold rule").replace(/\bT0\b/g, "the nothing-to-read rule")
    .replace(/\bB([1-6])\b(?: fires)?/g, (m, n) => `the rule "${BP.RULE["B" + n].toLowerCase()}" applies`)
    .replace(/\bno_evidence\b/g, "no evidence")
    .replace(/the new flag/g, "the allowance for new benchmarks")
    .replace(/\bMode (?:is )?non\b/gi, "Non-agentic").replace(/\bmode non\b/gi, "non-agentic");

  // ---------- small render bits ----------
  BP.tierPill = (it, big) => {
    const t = BP.tierOf(it);
    const label = t === "covered" ? "Covered" : BP.TIER[t][0];
    const tip = t === "covered" ? BP.COVER[it.covered] + ", so it is not a new candidate" : BP.TIER[t][1];
    return `<span class="tp ${t}${big ? " big" : ""}" data-tip="${esc(tip)}"><i></i>${label}</span>`;
  };
  BP.modeTag = (m) => `<span class="mt ${m}" data-tip="${esc(BP.MODE[m][1])}">${BP.MODE[m][0]}</span>`;
  BP.flags = (it) => (it.new ? '<span class="fl new" data-tip="Under 15 days old with no leaderboard yet: missing scores and attention do not count against it">young</span>' : "") +
    (it.mm ? '<span class="fl" data-tip="Multimodal">MM</span>' : "") +
    (it.hi1 ? `<span class="fl hi" data-tip="${it.hi1} task${it.hi1 === 1 ? "" : "s"} in Harbor Index v1">HI v1</span>` : "");

  BP.scoreCell = (it) => {
    const quoted = it.tier && it.tier.checks && it.tier.checks.best_score && it.tier.checks.best_score.percent;
    if (it.best == null && quoted != null) {
      const bs = it.tier.checks.best_score;
      return `<span class="sc quoted" data-tip="${esc("Quoted from the paper" + (bs.system ? " (" + bs.system + ")" : "") + ". No leaderboard score yet.")}"><b>${BP.pct(quoted)}</b><span class="sc-u">paper</span></span>`;
    }
    if (it.best == null) {
      const s = it.own && it.own.raw != null ? it.own : it.agg && it.agg.raw != null ? it.agg : null;
      if (!s) return `<span class="sc none">—</span>`;
      return `<span class="sc" data-tip="${esc((s === it.own ? "Own leaderboard" : s.source) + " top score, not a percentage")}"><b>${BP.num(s.raw)}</b><span class="sc-u">${s.scale ? "/" + BP.num(s.scale) : "pts"}</span></span>`;
    }
    const tip = { own: () => `Own leaderboard · ${it.own.model || ""} · found ${it.own.found}`, aggregator: () => `${it.agg.source} · ${it.agg.model || ""} · crawled ${it.agg.as_of}`, paper: () => "Best score stated in the paper" }[it.basis]();
    return `<span class="sc" data-tip="${esc(tip)}"><b>${BP.pct(it.best)}</b><span class="bar ${BP.kindCls(it.basis)}${it.sat ? " hot" : ""}"><i style="--w:${Math.max(2, Math.min(100, it.best))}%"></i></span></span>`;
  };
  BP.attCell = (it) => {
    const m = it.metrics || {};
    const stars = it.sig && it.sig.repo ? m.stars : m.stars > 0 ? m.stars : null;
    const cites = m.citations > 0 ? m.citations : null;
    const out = (stars != null ? `<span data-tip="GitHub stars">${BP.short(stars)}<i>★</i></span>` : "") + (cites != null ? `<span data-tip="Citations">${BP.short(cites)}<i>cit</i></span>` : "");
    return `<span class="att">${out || '<span class="none">—</span>'}</span>`;
  };

  // ---------- shortlist (this browser only) ----------
  const SL_KEY = "bp.shortlist.v1";
  BP.shortlist = { get() { try { return JSON.parse(localStorage.getItem(SL_KEY)) || {}; } catch (e) { return {}; } },
    set(v) { try { localStorage.setItem(SL_KEY, JSON.stringify(v)); } catch (e) { /* private mode */ } },
    has(id) { return !!this.get()[id]; },
    toggle(id) { const v = this.get(); if (v[id]) delete v[id]; else v[id] = { added: new Date().toISOString().slice(0, 10), note: "" }; this.set(v); return !!v[id]; },
    note(id, text) { const v = this.get(); if (!v[id]) v[id] = { added: new Date().toISOString().slice(0, 10) }; v[id].note = text; this.set(v); } };
  BP.star = (it) => `<button type="button" class="star${BP.shortlist.has(it.id) ? " on" : ""}" data-pin="${esc(it.id)}" aria-label="Add to shortlist" title="Shortlist">★</button>`;
  BP.harborTag = (it) => {
    const h = it.harbor || {};
    if (h.status === "v1") return '<span class="fl hi" data-tip="Harbor Index v1 already takes tasks from it">Index v1</span>';
    if (h.status === "adapter") return '<span class="fl hi" data-tip="A Harbor adapter is merged">adapter</span>';
    if (h.status === "hub" || h.status === "registry") return `<span class="fl hi" data-tip="${esc("Already in Harbor format: " + (h.here || []).join(", "))}">on Harbor</span>`;
    if ((h.family || []).length) return `<span class="fl fam" data-tip="${esc("Another version or subset is already in Harbor: " + h.family.join(", "))}">family in Harbor</span>`;
    return "";
  };

  // ---------- filter state ----------
  BP.S = { cls: 0, sub: null, mm: false, mode: null, tier: null, cover: "open", quick: null, q: "", week: null, sort: "tier", dir: 1, limit: 200, basis: "all", view: "list", sel: null };
  BP.inScope = (it, o) => {
    const S = BP.S; o = o || {};
    if (!o.anyClass && S.cls && it.cls !== S.cls) return false;
    if (!o.anyClass && S.sub && it.sub !== S.sub) return false;
    if (S.q) {
      const hay = (it.name + " " + it.title + " " + it.tags.join(" ") + " " + it.orgs.join(" ")).toLowerCase();
      if (!S.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    if (!o.anyCover && S.cover === "open" && it.covered) return false;
    if (!o.anyCover && S.cover === "covered" && !it.covered) return false;
    if (!o.anyMode && S.mode && it.mode !== S.mode) return false;
    if (o.base) return true;
    if (!o.anyTier && S.tier && BP.tierOf(it) !== S.tier) return false;
    if (S.mm && !it.mm) return false;
    if (S.quick === "lb" && !BP.hasLb(it)) return false;
    if (S.quick === "pinned" && !BP.shortlist.has(it.id)) return false;
    if (S.quick === "ready" && !(it.readiness && ["reference_passes_reported", "controls_reported"].includes(it.readiness.oracle.level))) return false;
    if (S.quick === "fresh" && it.harbor && (it.harbor.status || (it.harbor.family || []).length)) return false;
    if (S.quick === "sat" && !it.sat) return false;
    if (S.quick === "new" && !(BP.when(it) && BP.when(it) >= BP.DATA.newSince)) return false;
    if (!o.anyWeek && S.week && !(BP.when(it) && BP.when(it) >= S.week && BP.when(it) < BP.iso(BP.addDays(BP.day(S.week), 7)))) return false;
    return true;
  };
  BP.scoped = (o) => BP.DATA.items.filter((it) => BP.inScope(it, o));
  // Links use the permanent id (bp-000123). Older ids, from links in reports and messages, redirect.
  BP.byId = (id) => {
    if (!BP._ix) { BP._ix = new Map(); BP.DATA.items.forEach((x) => BP._ix.set(x.id, x)); }
    return BP._ix.get(id) || BP._ix.get((BP.DATA.meta.redirects || {})[id]);
  };
})();
