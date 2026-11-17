/* Sections that describe one benchmark. The inspector stacks them; the full page puts each in its own panel. */
(function () {
  "use strict";
  const BP = (window.BP = window.BP || {});
  const esc = BP.esc, num = BP.num, pct = BP.pct;
  const I = (BP.item = {});
  const link = (url, text) => `<a href="${esc(BP.safeUrl(url))}" target="_blank" rel="noopener">${esc(text)}</a>`;

  I.head = (it, opts) => {
    opts = opts || {};
    const kindLabel = { paper: "Paper", code: "Code", data: "Data", leaderboard: "Leaderboard", space: "Space", web: "Link" };
    const dest = (u, kind) => {
      const h = BP.host(u);
      if (/arxiv\.org\/pdf/.test(u)) return "arXiv PDF";
      if (/arxiv\.org/.test(u)) return "arXiv";
      if (h === "github.com") return "GitHub";
      if (/huggingface\.co\/datasets/.test(u)) return "HF dataset";
      if (/huggingface\.co\/papers/.test(u)) return "HF paper";
      if (/huggingface\.co\/spaces/.test(u)) return "HF space";
      if (/zenodo\.org/.test(u)) return "Zenodo";
      if (/doi\.org/.test(u)) return "DOI";
      if (kind === "leaderboard") return "Leaderboard · " + h;
      return (kindLabel[kind] || "Link") + " · " + h;
    };
    const links = it.links.map((l) => `<a class="btn sm" href="${esc(BP.safeUrl(l.url))}" target="_blank" rel="noopener" title="${esc(l.url)}">${esc(dest(l.url, l.kind))}<span class="ext">↗</span></a>`).join("");
    const cls = BP.CLASS[it.cls];
    return `<div class="ih">
      <div class="crumb">${BP.icon(it.cls, 15)}<span>${esc(cls.name)}${it.sub ? ` <span class="sep">/</span> ${esc(it.sub)}` : ""}</span></div>
      <h1 class="iname">${BP.star(it)}${esc(it.name)}</h1>
      ${it.title && it.title !== it.name ? `<p class="ititle">${esc(it.title)}</p>` : ""}
      <div class="itags">${BP.tierPill(it)}${BP.modeTag(it.mode)}${BP.flags(it)}${BP.harborTag(it)}</div>
      ${(it.harbor && ((it.harbor.here || []).length || (it.harbor.family || []).length)) ? `<p class="small">Already in Harbor: ${esc([...(it.harbor.here || []), ...(it.harbor.family || [])].slice(0, 5).join(" · "))}</p>` : ""}
      ${BP.shortlist.has(it.id) ? `<textarea class="note" data-note="${esc(it.id)}" placeholder="Your note on this benchmark (kept in this browser, exported with CSV/JSON)">${esc((BP.shortlist.get()[it.id] || {}).note || "")}</textarea>` : ""}
      <div class="ilinks">${links}${opts.full ? `<a class="btn sm ghost" href="#/b/${encodeURIComponent(it.id)}">Open full page</a>` : ""}</div>
    </div>`;
  };

  I.verdict = (it) => {
    const t = it.tier;
    if (it.covered) return `<div class="verdict covered">${BP.tierPill(it, true)}<p class="reason">${esc(BP.COVER[it.covered])}, so it is not a new candidate. It stays on the board for reference.</p></div>`;
    if (!t) return `<div class="verdict"><p class="muted">Not judged yet.</p></div>`;
    return `<div class="verdict ${t.tier}">
      <div class="vrow">${BP.tierPill(it, true)}<span class="decided">${esc(BP.RULE[t.rule] || "")}</span></div>
      <p class="reason">${esc(BP.plain(t.reason))}</p>
      ${it.new ? `<p class="note-new"><span class="fl new">new</span>Under 15 days old with no leaderboard: missing scores and attention do not count against it.</p>` : ""}
    </div>`;
  };

  // Flow from the six dimensions to the rule that decided, to the tier.
  I.path = (it) => {
    const t = it.tier;
    if (!t || it.covered) return "";
    const keys = Object.keys(BP.DIM).filter((k) => t.dimensions[k]);
    if (!keys.length) return "";
    const W = 520, rowH = 30, top = 10, H = Math.max(keys.length * rowH + top * 2, 120);
    const ruleX = 250, ruleW = 150, tierX = 432, midY = H / 2;
    const vcls = (v) => ({ strong: "strong", ok: "ok", weak: "weak" }[v] || "none");
    const words = (BP.RULE[t.rule] || "").split(" ");
    const lines = []; let cur = "";
    for (const w of words) { if ((cur + " " + w).trim().length > 24) { lines.push(cur.trim()); cur = w; } else cur += " " + w; }
    if (cur.trim()) lines.push(cur.trim());
    const rl = lines.slice(0, 4);
    const ruleH = 22 + rl.length * 15;
    let s = `<svg class="vpath" viewBox="0 0 ${W} ${H}" role="img" aria-label="How the verdict was reached">`;
    keys.forEach((k, i) => {
      const y = top + i * rowH + rowH / 2, v = t.dimensions[k].verdict;
      s += `<path class="lk ${vcls(v)}" d="M150 ${y} C 200 ${y}, 205 ${midY}, ${ruleX} ${midY}"/>`;
      s += `<g class="dn ${vcls(v)}" data-dim="${k}" tabindex="0"><rect x="4" y="${y - 11}" width="146" height="22" rx="7"/><text x="14" y="${y + 4}">${BP.DIM[k]}</text><text class="v" x="142" y="${y + 4}" text-anchor="end">${esc(v.replace("_", " "))}</text></g>`;
    });
    s += `<rect class="rn" x="${ruleX}" y="${midY - ruleH / 2}" width="${ruleW}" height="${ruleH}" rx="10"/>`;
    s += `<text class="rn-k" x="${ruleX + 12}" y="${midY - ruleH / 2 + 16}">decided by</text>`;
    rl.forEach((l, i) => { s += `<text class="rn-t" x="${ruleX + 12}" y="${midY - ruleH / 2 + 32 + i * 15}">${esc(l)}</text>`; });
    s += `<path class="lk flow ${t.tier}" d="M${ruleX + ruleW} ${midY} L ${tierX - 4} ${midY}"/>`;
    s += `<g class="tn ${t.tier}"><rect x="${tierX}" y="${midY - 15}" width="84" height="30" rx="9"/><text x="${tierX + 42}" y="${midY + 5}" text-anchor="middle">${BP.TIER[t.tier][0]}</text></g>`;
    return s + "</svg>";
  };

  // Each dimension next to the sentence it rests on and the looked-up facts that bear on it.
  I.evidence = (it) => {
    const t = it.tier;
    if (!t || it.covered) return "";
    const c = t.checks || {};
    const keys = Object.keys(BP.DIM).filter((k) => t.dimensions[k]);
    return `<div class="dims">${keys.map((k) => {
      const d = t.dimensions[k];
      const facts = (BP.DIM_FACTS[k] || []).filter((f) => c[f]).map((f) => I.fact(c, f, true)).join("");
      return `<div class="dim" data-dim="${k}" tabindex="0">
        <div class="dim-h"><span class="dim-n" data-tip="${esc(BP.DIM_HELP[k])}">${BP.DIM[k]}</span><span class="vd ${d.verdict}">${esc(d.verdict.replace("_", " "))}</span></div>
        <p class="dim-q">${d.quote ? `“${esc(d.quote)}”` : `<span class="muted">${d.verdict === "no_evidence" ? "The pages read do not say." : "Rests on the pool's own facts (score, stars, citations)."}</span>`}</p>
        ${facts ? `<div class="dim-f">${facts}</div>` : ""}
      </div>`;
    }).join("")}</div>`;
  };

  I.fact = (c, k, small) => {
    const v = c[k].value, d = BP.CHECK[k];
    const shown = d[1][v] || "not stated";
    return `<span class="fact ${d[2][v] || "na"}${small ? " sm" : ""}" data-fact="${k}" ${c[k].quote ? `data-tip="${esc("“" + c[k].quote + "”")}"` : `data-tip="The pages read do not say"`}><span class="fk">${d[0]}</span><span class="fv">${esc(shown)}</span></span>`;
  };

  I.facts = (it) => {
    const t = it.tier;
    if (!t || !t.checks) return "";
    const c = t.checks, b = c.best_score || {}, z = c.size || {};
    const nums = [
      b.percent != null ? [`${num(b.percent)}%`, "best score" + (b.system ? ` · ${esc(b.system)}` : "")] : ["—", "no best score quoted"],
      c.top_gap != null ? [num(c.top_gap), "points between the top three"] : null,
      z.tasks != null ? [num(z.tasks), "tasks"] : null,
      z.categories != null ? [num(z.categories), "task categories"] : null,
      z.sources != null ? [num(z.sources), "sources"] : null,
    ].filter(Boolean);
    return `<div class="nums">${nums.map(([v, k]) => `<div class="numc"><b>${v}</b><span>${k}</span></div>`).join("")}</div>
      <div class="facts">${Object.keys(BP.CHECK).filter((k) => c[k]).map((k) => I.fact(c, k)).join("")}</div>
      <p class="hint">Hover a fact for the sentence it rests on. Dashed: the pages do not say.</p>`;
  };

  I.risks = (it) => {
    const r = (it.tier && it.tier.risks) || [];
    if (!r.length) return "";
    return `<ul class="risks">${r.map((x) => `<li><span class="rk">${esc(x.risk)}</span>${x.quote ? `<span class="rq">“${esc(x.quote)}”</span>` : ""}</li>`).join("")}</ul>`;
  };

  I.coverage = (it) => {
    const t = it.tier;
    const names = { data: "Task data", scores: "Scores", task_scores: "Per-task scores", trajectories: "Trajectories", process: "Judge prompts / filter code", infra: "Harness" };
    if (t && t.coverage) {
      const cls = { yes: "good", partial: "mid", no: "bad" };
      return `<div class="facts">${Object.keys(names).filter((k) => t.coverage[k]).map((k) => `<span class="fact ${cls[t.coverage[k]] || "na"}"><span class="fk">${names[k]}</span><span class="fv">${esc(t.coverage[k].replace("_", " "))}</span></span>`).join("")}</div>`;
    }
    const c = it.cov || {};
    const m = { data: { public: ["good", "public"], partial: ["mid", "partial"], private: ["bad", "private"] }, scores: { yes: ["good", "reported"], no: ["bad", "none"] }, traj: { yes: ["good", "released"] }, infra: { yes: ["good", "released"], repo: ["mid", "repo linked"] } };
    const lab = { data: "Task data", scores: "Scores", traj: "Trajectories", infra: "Harness" };
    return `<div class="facts">${Object.keys(lab).map((k) => { const v = (m[k] || {})[c[k]] || ["na", "not stated"]; return `<span class="fact ${v[0]}"><span class="fk">${lab[k]}</span><span class="fv">${v[1]}</span></span>`; }).join("")}</div>`;
  };

  I.score = (it) => {
    const o = it.own, a = it.agg, p = it.paper, se = it.search || {};
    let html = "";
    if (it.best != null) {
      html += `<div class="bigscore"><b class="${it.sat ? "hot" : ""}">${pct(it.best)}</b><span>${BP.KIND[it.basis]}${it.sat ? ' · <span class="hot">saturated</span>' : " · not saturated"}</span></div>`;
    } else if ((o && o.raw != null) || (a && a.raw != null)) {
      const s = o && o.raw != null ? o : a;
      html += `<div class="bigscore"><b>${num(s.raw)}</b><span>${s === a && s.scale ? "of " + num(s.scale) : esc((s === o && s.metric) || "points")} · not a percentage</span></div>`;
    } else {
      html += `<div class="bigscore off"><b>${{ listed: "Leaderboard exists", none: "No public leaderboard", unchecked: "Not searched yet" }[it.lb] || "No score"}</b><span>${{ listed: "top score could not be read", none: "searched " + esc(se.checked || ""), unchecked: "the leaderboard search will reach it" }[it.lb] || ""}</span></div>`;
    }
    const row = (kind, value, w, line, quote) => `<div class="srow">
      <div class="srow-h"><span>${BP.KIND[kind]}</span><b>${value}</b></div>
      ${w == null ? "" : `<span class="bar wide ${BP.kindCls(kind)}${w > BP.DATA.meta.saturated_above ? " hot" : ""}"><i style="--w:${Math.min(100, Math.max(1, w))}%"></i><em style="left:90%"></em></span>`}
      <p class="small">${line}</p>${quote ? `<p class="quote">“${esc(quote)}”</p>` : ""}</div>`;
    if (o) html += row("own", o.pct != null ? pct(o.pct) : num(o.raw), o.pct, `Top: <b>${esc(o.model || "")}</b>${o.metric ? " · " + esc(o.metric) : ""}${o.entries ? ` · ${o.entries} systems` : ""} · ${link(o.url, BP.host(o.url))} · found ${esc(o.found)}`, o.quote);
    if (a) html += row("aggregator", a.pct != null ? pct(a.pct) : num(a.raw), a.pct, `${link(a.url, a.source)} · crawled ${esc(a.as_of)}${a.model ? ` · top <b>${esc(a.model)}</b>` : ""}${a.self_reported ? " · vendor self-reported" : ""}`);
    if (p) html += row("paper", pct(p.pct), p.pct, `Stated in the paper${p.metric ? " · " + esc(p.metric) : ""}${p.model ? " · " + esc(p.model) : ""}`, p.quote);
    if (!o && se.status) {
      const line = { listed: `Own leaderboard ${se.url ? link(se.url, BP.host(se.url)) : "found"}; its top score could not be read.`, none: `No own leaderboard found (searched ${esc(se.checked || "")}).`, unchecked: "Own leaderboard not searched yet." }[se.status];
      if (line) html += `<p class="small muted">${line}</p>`;
    }
    return html;
  };

  I.about = (it) => {
    const m = it.metrics || {};
    const att = [["stars", "GitHub stars"], ["citations", "citations"], ["upvotes", "HF upvotes"], ["downloads", "downloads"], ["likes", "likes"]].filter(([k]) => m[k] > 0).map(([k, l]) => `<b>${num(m[k])}</b> ${l}`).join(" · ");
    const who = [it.authors.join(", ") + (it.author_count > it.authors.length ? ` +${it.author_count - it.authors.length}` : ""), it.orgs.join(", ")].filter(Boolean).join(" — ");
    const row = (k, v) => (v ? `<dt>${k}</dt><dd>${v}</dd>` : "");
    return `<dl class="kv">
      ${row(it.mode === "non" ? "Model does" : "Agent does", esc(it.does))}
      ${row("Realism", esc(it.real))}
      ${row("Value", esc(it.val))}
      ${row("Published", esc(it.date || "—"))}
      ${row("First seen", esc(it.seen || ""))}
      ${row("By", esc(who))}
      ${row("Attention", att + (it.sig && it.sig.checked ? ` <span class="muted">· fetched ${esc(it.sig.checked)}</span>` : ""))}
      ${row("Sources", esc(it.sources.map((x) => (x === "Harbor Adapter List" ? "Established-benchmark list" : x)).join(" · ")))}
      ${row("Tags", it.tags.length ? `<span class="tags">${it.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</span>` : "")}
    </dl>`;
  };

  I.provenance = (it) => {
    const t = it.tier;
    if (!t) return "";
    const r = t.read, words = (n) => `${num(Math.round(n / 6 / 100) * 100)} words`;
    let read;
    if (!r) read = "the abstract, README and file list";
    else {
      const parts = [];
      if (r.paper_chars) parts.push(`the whole paper (${words(Math.min(r.paper_chars, 160000))}${r.paper_cut ? ", cut for length" : ""})`);
      if (r.readme_chars) parts.push(`the README (${words(r.readme_chars)})`);
      if (r.files) parts.push(`${r.files} top-level file names`);
      if (r.page_chars) parts.push(`the benchmark's own page (${words(r.page_chars)})`);
      read = parts.length ? parts.join(", ") + (r.paper_chars ? "" : "; no paper is linked") : "nothing: no paper, repository or readable page was found";
    }
    const trail = it.tier_trail && it.tier_trail.length > 1 ? `<li>Earlier: ${it.tier_trail.slice(0, -1).map((x) => `${esc(BP.TIER[x[1]][0])} (${esc(x[0])})`).join(", ")}</li>` : "";
    return `<ul class="prov">
      <li>Read ${read}.</li>
      <li>Judged ${esc(t.date)} by ${t.model ? esc(t.model) : "a rule, no model"}.</li>
      ${t.harbor_fit && t.harbor_fit.container ? `<li>Runs in a container with a programmatic verifier: <b>${esc(t.harbor_fit.container)}</b>${t.harbor_fit.blocker ? " · " + esc(t.harbor_fit.blocker) : ""}</li>` : ""}
      ${trail}
    </ul>`;
  };

  // ---------- ranking: best score against the reachable ceiling ----------
  BP.BAND = {
    real: ["Real headroom", "Models fail tasks that are shown to be valid"],
    unverified: ["Not verified", "There is a gap, but no evidence yet on whether the tasks are sound"],
    suspect: ["Gap looks suspect", "Much of the gap looks like broken tasks, environment or grading"],
    saturated: ["Saturated", "Within 10 points of the best reachable score"],
    noscore: ["No score", "No percentage score found anywhere"],
  };
  BP.CAUSE = { model: "models failing valid tasks", tasks: "broken or ambiguous tasks", environment: "the environment", grader: "the grader", mixed: "a mix of causes", unknown: "unclear" };
  BP.bandPill = (b) => `<span class="bp ${b}" data-tip="${esc(BP.BAND[b][1])}"><i></i>${BP.BAND[b][0]}</span>`;
  // 0-100 track: filled to the best score, a marker at the ceiling, the gap between them tinted by band.
  BP.ceilBar = (r, wide) => {
    const s = r.sota ? Math.max(0, Math.min(100, r.sota.pct)) : null, c = Math.max(0, Math.min(100, r.ceiling));
    return `<span class="cbar ${r.band}${wide ? " wide" : ""}" data-tip="${esc(s == null ? "No score" : `Best ${BP.pct(s)} · ceiling ${BP.pct(c)} · ${r.headroom > 0 ? BP.num(r.headroom) + " points left" : "at the ceiling"}`)}">
      ${s != null ? `<i class="cb-s" style="--w:${s}%"></i><i class="cb-g" style="left:${Math.min(s, c)}%;width:${Math.max(0, c - s)}%"></i>` : ""}
      ${c < 100 ? `<i class="cb-x" style="left:${c}%"></i>` : ""}<em style="left:${c}%"></em></span>`;
  };
  BP.spark = (r, w, h) => {
    w = w || 92; h = h || 26;
    const pts = r.history || [];
    if (pts.length < 2) return `<span class="spark none">—</span>`;
    const t0 = BP.day(pts[0].date).getTime(), t1 = Math.max(t0 + 1, BP.day(BP.DATA.meta.ranking.epoch_as_of || pts[pts.length - 1].date).getTime());
    const X = (d) => 2 + ((BP.day(d).getTime() - t0) / (t1 - t0)) * (w - 4), Y = (v) => h - 2 - v * (h - 4);
    let d = "", last = null;
    pts.forEach((p, i) => { const x = X(p.date).toFixed(1), y = Y(p.score).toFixed(1); d += (i ? ` H${x} V${y}` : `M${x} ${y}`); last = [x, y]; });
    d += ` H${w - 2}`;
    const cy = Y(r.ceiling / 100).toFixed(1);
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" data-tip="${esc("Record over time (Epoch AI): " + pts.slice(-4).map((p) => p.date.slice(0, 7) + " " + BP.pct(p.score * 100)).join(" → "))}"><line x1="0" x2="${w}" y1="${cy}" y2="${cy}" class="sp-c"/><path d="${d}"/><circle cx="${last[0]}" cy="${last[1]}" r="2.2"/></svg>`;
  };

  I.headroom = (it) => {
    const r = it.rank;
    if (!r) return "";
    const s = r.sota;
    const pace = r.velocity != null ? `${r.velocity > 0 ? "+" : ""}${BP.num(r.velocity)} points a month over the last year` + (r.months_left != null ? ` · about <b>${BP.num(r.months_left)} months</b> to saturation at this pace` : "") : "";
    const ev = (r.evidence || []).map((e) => `<li><span class="rk">${esc(e.claim)}</span><span class="rq">“${esc(e.quote)}” <span class="muted">· ${esc((e.from || "").replace(/^AUDITS: /, ""))}</span></span></li>`).join("");
    const aud = (r.audits || []).map((a) => `<li><a href="${esc(BP.safeUrl(a.url))}" target="_blank" rel="noopener">${esc(a.title)}</a> <span class="muted">${esc(a.date)}</span></li>`).join("");
    return `<div class="hr">
      <div class="vrow">${BP.bandPill(r.band)}${r.cause && r.cause !== "unknown" ? `<span class="decided">gap is mostly ${esc(BP.CAUSE[r.cause])}</span>` : ""}</div>
      <div class="hr-nums">
        <div class="numc"><b>${s ? BP.pct(s.pct) : "—"}</b><span>best score${s ? ` · ${esc(s.source)}${s.self_reported ? ", self-reported" : ""}` : ""}</span></div>
        <div class="numc"><b>${BP.pct(r.ceiling)}</b><span>reachable ceiling</span></div>
        <div class="numc"><b>${r.headroom != null ? BP.num(r.headroom) : "—"}</b><span>points of headroom</span></div>
      </div>
      ${BP.ceilBar(r, true)}
      ${s && s.model ? `<p class="small">Best by ${esc(s.model)}${s.as_of ? ", " + esc(s.as_of) : ""}.</p>` : ""}
      <p class="small">Ceiling: ${esc(r.ceiling_basis)}${r.ceiling_quote ? ` — <span class="quote-in">“${esc(r.ceiling_quote)}”</span>` : ""}.</p>
      ${r.history && r.history.length > 1 ? `<div class="hr-spark">${BP.spark(r, 420, 70)}<p class="small">${pace}</p></div>` : pace ? `<p class="small">${pace}</p>` : ""}
      ${r.summary ? `<p class="reason">${esc(r.summary)}</p>` : r.judged ? "" : `<p class="small muted">Not judged yet: whether the gap is real has not been checked.</p>`}
      ${ev ? `<ul class="risks ev">${ev}</ul>` : ""}
      ${aud ? `<details class="aud"><summary>Papers searched for audits (${(r.audits || []).length})</summary><ul>${aud}</ul></details>` : ""}
      <p class="small muted">Popular because: ${esc(r.why.join(" · "))}.${r.superseded_by ? ` Superseded by ${esc(r.superseded_by)}.` : ""}${r.judged ? ` Judged ${esc(r.date)} by ${esc(r.model)}.` : ""}</p>
    </div>`;
  };

  // ---------- adapter readiness ----------
  const ORACLE = [["none", "No solvability evidence"], ["offline_answers", "Gold answers only"], ["reference_solution", "Reference solution shipped"],
    ["reference_passes_reported", "Reference reported to pass"], ["controls_reported", "Reference passes, no-op fails"]];
  BP.ORACLE = ORACLE;
  I.readiness = (it) => {
    const r = it.readiness;
    if (!r) return "";
    if (r.no_release) return `<div class="rd"><p class="reason"><b>No public release found.</b> Neither the pool's links, Hugging Face's paper record nor the paper's own links lead to a repository or dataset with the tasks.</p><p class="small muted">Checked ${esc(r.date)}. ${esc(r.next_action)}</p></div>`;
    const q = (sec) => sec && sec.quote ? ` data-tip="${esc("“" + sec.quote + "”")}"` : "";
    const ev = (sec) => `<span class="evd ${sec.evidence}" data-tip="${esc({ inspected: "A file it names was found in the repository", reported: "Stated in the release's text", unknown: "The release does not say" }[sec.evidence] || "")}">${esc(sec.evidence)}</span>`;
    const lvl = ORACLE.findIndex((o) => o[0] === (r.oracle.level || "none"));
    const ladder = `<div class="ladder">${ORACLE.map((o, i) => `<span class="rung${i <= lvl ? " on" : ""}${i === lvl ? " cur" : ""}" data-tip="${esc(o[1])}"></span>`).join("")}</div>`;
    const list = (a) => (a || []).filter(Boolean).map((x) => `<span class="tag">${esc(x)}</span>`).join("");
    const src = r.sources.map((s) => `<a href="${esc(BP.safeUrl(s.url))}" target="_blank" rel="noopener">${esc(s.kind === "github" ? s.id : s.kind + ": " + s.id)}</a>${s.commit ? ` <code>${esc(String(s.commit).slice(0, 8))}</code>` : ""}${s.license ? ` · ${esc(s.license)}` : ""}`).join("<br>");
    return `<div class="rd">
      <div class="rd-or"><div class="rd-k">Solvability evidence</div>${ladder}<div class="rd-v"${q(r.oracle)}><b>${esc(ORACLE[Math.max(0, lvl)][1])}</b> ${ev(r.oracle)}${r.oracle.path ? ` · <code>${esc(r.oracle.path)}</code>` : ""}${r.oracle.command ? `<br><code>${esc(r.oracle.command)}</code>` : ""}</div></div>
      <dl class="kv">
        <dt>Release</dt><dd>${src || "—"}</dd>
        <dt>Tasks</dt><dd${q(r.tasks)}>${r.tasks.count != null ? `<b>${num(r.tasks.count)}</b> ${esc(r.tasks.unit || "")}` : "—"}${r.tasks.manifest_path ? ` · manifest <code>${esc(r.tasks.manifest_path)}</code>${r.tasks.manifest_path_found ? " ✓" : ""}` : ""}${(r.tasks.splits || []).length ? `<br>${list(r.tasks.splits)}` : ""}${r.tasks.pilot ? `<br>Pilot: <code>${esc(r.tasks.pilot)}</code>` : ""} ${ev(r.tasks)}</dd>
        <dt>Verifier</dt><dd${q(r.verifier)}>${esc((r.verifier.kind || "unknown").replace(/_/g, " "))}${r.verifier.entry_point ? ` · <code>${esc(r.verifier.entry_point)}</code>` : ""}${r.verifier.full_credit ? `<br><span class="muted">Full credit: ${esc(r.verifier.full_credit)}</span>` : ""} ${ev(r.verifier)}</dd>
        <dt>Licences</dt><dd${q(r.rights)}>code: <b>${esc(r.rights.code_license || "not stated")}</b> · data: <b>${esc(r.rights.data_license || "not stated")}</b>${(r.rights.redistribution_questions || []).length ? `<br><span class="muted">${esc(r.rights.redistribution_questions.join(" "))}</span>` : ""}</dd>
        <dt>Runtime</dt><dd${q(r.runtime)}>docker: <b>${esc(r.runtime.docker || "unclear")}</b> · GPU: <b>${esc(r.runtime.gpu || "unclear")}</b>${(r.runtime.services || []).length ? `<br>${list(r.runtime.services)}` : ""}${(r.runtime.network_or_api || []).length ? `<br><span class="warn">Needs: ${esc(r.runtime.network_or_api.join(", "))}</span>` : ""}${(r.runtime.credentials || []).length ? `<br><span class="warn">Credentials: ${esc(r.runtime.credentials.join(", "))}</span>` : ""}${(r.runtime.exceptions || []).length ? `<br><span class="muted">Exceptions: ${esc(r.runtime.exceptions.join("; "))}</span>` : ""}</dd>
      </dl>
      ${(r.questions || []).length ? `<ul class="risks">${r.questions.map((x) => `<li><span class="rk">${esc(x)}</span></li>`).join("")}</ul>` : ""}
      ${r.next_action ? `<p class="reason"><b>First step:</b> ${esc(r.next_action)}</p>` : ""}
      <div class="ilinks"><button type="button" class="btn sm" data-brief="${esc(it.id)}">Copy adapter brief</button><a class="btn sm ghost" href="data/v1/benchmarks/${esc(it.id)}.json" target="_blank" rel="noopener">JSON</a></div>
      <p class="small muted">Read ${esc(r.date)} by ${esc(r.model)} from the release itself. Hover a line for the words it rests on.</p>
    </div>`;
  };
  BP.brief = (it) => {
    const r = it.readiness;
    const L = [`## Adapter brief: ${it.name}`, "", `Site: ${location.origin + location.pathname}#/b/${it.id}`,
      `Recommendation: ${BP.TIER[BP.tierOf(it)] ? BP.TIER[BP.tierOf(it)][0] : ""} — ${BP.plain((it.tier || {}).reason || "")}`,
      `Harbor: ${((it.harbor || {}).here || []).concat((it.harbor || {}).family || []).join("; ") || "nothing yet"}`, ""];
    if (r) {
      L.push("### Release", ...r.sources.map((s) => `- ${s.kind} ${s.id} @ ${s.commit || "?"} (licence: ${s.license || "not stated"}) ${s.url}`), "");
      L.push("### Tasks", `- ${r.tasks.count ?? "?"} ${r.tasks.unit || ""}${r.tasks.manifest_path ? `, manifest ${r.tasks.manifest_path}` : ""}`, ...(r.tasks.pilot ? [`- Pilot: ${r.tasks.pilot}`] : []), "");
      L.push("### Verifier", `- ${r.verifier.kind}${r.verifier.entry_point ? ` (${r.verifier.entry_point})` : ""}: ${r.verifier.full_credit || ""}`, "");
      L.push("### Solvability evidence", `- ${(BP.ORACLE.find((o) => o[0] === r.oracle.level) || ["", "?"])[1]}${r.oracle.command ? `: \`${r.oracle.command}\`` : ""}`, "");
      L.push("### Runtime", `- docker ${r.runtime.docker}, GPU ${r.runtime.gpu}`, ...(r.runtime.services || []).map((x) => `- service: ${x}`), ...(r.runtime.network_or_api || []).map((x) => `- needs: ${x}`), "");
      L.push("### Licences", `- code: ${r.rights.code_license || "not stated"}; data: ${r.rights.data_license || "not stated"}`, "");
      if ((r.questions || []).length) L.push("### To settle first", ...r.questions.map((x) => `- [ ] ${x}`), "");
      if (r.next_action) L.push(`**First step:** ${r.next_action}`);
    }
    const risks = ((it.tier || {}).risks || []).map((x) => `- ${x.risk}`);
    if (risks.length) L.push("", "### Risks noted when screening", ...risks);
    return L.join("\n");
  };

  // The inspector: everything about one benchmark in one scrolling column.
  I.inspector = (it) => {
    const sec = (title, body, cls) => (body ? `<section class="isec ${cls || ""}"><h3>${title}</h3>${body}</section>` : "");
    return `<div class="insp-in">
      ${I.head(it, { full: true })}
      ${it.readiness ? sec("Adapter readiness: what the release itself shows", I.readiness(it), "v") : ""}
      ${it.rank ? sec("Headroom: is the gap to 100% real?", I.headroom(it), "v") : ""}
      ${sec("Verdict", I.verdict(it) + I.path(it), "v")}
      ${sec("Why: each dimension and what it rests on", I.evidence(it))}
      ${sec("To settle before bringing it into Harbor", I.risks(it))}
      ${sec("Facts looked up first", I.facts(it))}
      ${sec("Best score", I.score(it))}
      ${sec("What is public", I.coverage(it))}
      ${sec("About", I.about(it))}
      ${sec("How it was judged", I.provenance(it))}
    </div>`;
  };
})();
