/* Panel boards: a page section made of panels that can be dragged by their header, resized from their edges,
   expanded, and closed. Closed panels are listed in the Panels menu (top bar), which can restore them or reset the
   layout. Layouts are saved per board in localStorage. Built on GridStack (MIT, vendored in web/vendor). */
(function () {
  "use strict";
  const BP = (window.BP = window.BP || {});
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* private mode */ } },
  };
  BP.store = store;

  const CELL = 34, GAP = 10;
  const ICON = {
    expand: '<path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    grip: '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
  };
  const svg = (k) => `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;

  class Board {
    /* spec: { key, panels: [{ id, title, sub, x, y, w, h, fit, expand, render(body) }] }
       fit: on a fresh layout, grow the panel's height to its content. expand: hash to open the full view. */
    constructor(container, spec) {
      this.spec = spec;
      this.key = `bp.layout.v1.${spec.key}`;
      const saved = store.get(this.key, null);
      this.hidden = new Set(saved ? saved.hidden : spec.panels.filter((p) => p.hidden).map((p) => p.id));
      this.pos = new Map(((saved && saved.items) || []).map((i) => [i.id, i]));
      this.fresh = !saved;
      container.innerHTML = '<div class="grid-stack"></div>';
      this.el = container.firstElementChild;
      // Phones: one column in the page's own order, no dragging, nothing saved.
      this.narrow = innerWidth < 760;
      this.nextY = 0;
      this.grid = GridStack.init({
        column: this.narrow ? 1 : 12, staticGrid: this.narrow, cellHeight: CELL, margin: GAP / 2, float: false, animate: true,
        handle: ".ph-grip, .ph-title", resizable: { handles: "e, se, s, sw, w" },
        columnOpts: { breakpoints: [{ w: 760, c: 1 }], layout: "list" },
      }, this.el);
      for (const p of spec.panels) if (!this.hidden.has(p.id)) this.add(p);
      this.grid.on("change", () => this.save());
      this.grid.on("dragstart resizestart", () => this.el.classList.add("moving"));
      this.grid.on("dragstop resizestop", () => { this.el.classList.remove("moving"); this.save(); });
      if (this.fresh) requestAnimationFrame(() => this.fit());
      BP.board = this;
      BP.menu && BP.menu.refresh();
    }

    add(p, i) {
      const at = this.narrow ? { x: 0, y: this.nextY, w: 1, h: p.h } : this.pos.get(p.id) || p;
      if (this.narrow) this.nextY += p.h || 4;
      const el = document.createElement("div");
      el.className = "grid-stack-item";
      el.setAttribute("gs-id", p.id);
      for (const k of ["x", "y", "w", "h"]) if (at[k] != null) el.setAttribute("gs-" + k, at[k]);
      el.setAttribute("gs-min-w", p.minW || 3);
      el.setAttribute("gs-min-h", p.minH || 3);
      el.innerHTML = `<div class="grid-stack-item-content panel rise" style="--i:${i == null ? this.grid.engine.nodes.length : i}">
        <header class="ph">
          <span class="ph-grip" title="Drag to move">${svg("grip")}</span>
          <span class="ph-title">${p.title}${p.sub ? ` <span class="ph-sub">${p.sub}</span>` : ""}</span>
          <span class="ph-tools">
            ${p.tools || ""}
            ${p.expand ? `<a class="ib" href="${p.expand}" title="Open the full view" aria-label="Open the full view">${svg("expand")}</a>` : ""}
            <button type="button" class="ib" data-panel-close="${p.id}" title="Hide this panel (bring it back from Panels)" aria-label="Hide panel">${svg("close")}</button>
          </span>
        </header>
        <div class="pb"></div>
      </div>`;
      this.el.appendChild(el);
      this.grid.makeWidget(el);
      p.render(el.querySelector(".pb"), el);
      return el;
    }

    fit() {
      // Fresh layout only: make each "fit" panel tall enough for its content, so nothing starts cut off.
      this.grid.batchUpdate();
      for (const p of this.spec.panels) {
        if (!p.fit || this.hidden.has(p.id)) continue;
        const el = this.el.querySelector(`[gs-id="${p.id}"]`);
        if (!el) continue;
        const body = el.querySelector(".pb"), head = el.querySelector(".ph");
        const need = head.offsetHeight + body.scrollHeight + 4;
        const h = Math.max(p.minH || 3, Math.min(p.maxH || 40, Math.ceil((need + GAP) / CELL)));
        this.grid.update(el, { h });
      }
      this.grid.batchUpdate(false);
      this.save();
    }

    save() {
      if (this.narrow) return;
      const items = this.grid.save(false).map((n) => ({ id: n.id, x: n.x, y: n.y, w: n.w, h: n.h }));
      store.set(this.key, { items, hidden: [...this.hidden] });
    }

    close(id) {
      const el = this.el.querySelector(`[gs-id="${id}"]`);
      if (!el) return;
      this.hidden.add(id);
      el.classList.add("leaving");
      setTimeout(() => { this.grid.removeWidget(el); this.save(); BP.menu && BP.menu.refresh(); }, 180);
    }

    show(id) {
      const p = this.spec.panels.find((x) => x.id === id);
      if (!p || !this.hidden.has(id)) return;
      this.hidden.delete(id);
      const el = this.add(p, 0);
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      this.save();
      BP.menu && BP.menu.refresh();
    }

    reset() { store.del(this.key); BP.route(); }

    destroy() { try { this.grid.destroy(false); } catch (e) { /* already gone */ } if (BP.board === this) BP.board = null; }
  }
  BP.Board = Board;

  // Panels menu in the top bar. Works for panel boards and for split views (which register their own panes).
  BP.menu = {
    refresh() {
      const btn = document.getElementById("panels-btn");
      if (!btn) return;
      const items = this.items();
      btn.hidden = !items;
      const pop = document.getElementById("panels-pop");
      if (!items || pop.hidden) return;
      pop.innerHTML = `<div class="pop-h">Panels on this page</div>` + items.list.map((it) =>
        `<label class="pop-row"><input type="checkbox" data-panel-toggle="${it.id}" ${it.on ? "checked" : ""}><span>${it.title}</span></label>`).join("") +
        `<button type="button" class="pop-reset" data-panel-reset>Reset layout</button>`;
    },
    items() {
      if (BP.board) return { list: BP.board.spec.panels.map((p) => ({ id: p.id, title: p.title.replace(/<[^>]+>/g, ""), on: !BP.board.hidden.has(p.id) })) };
      if (BP.split) return { list: BP.split.panes() };
      return null;
    },
    toggle(id, on) {
      if (BP.board) { on ? BP.board.show(id) : BP.board.close(id); return; }
      if (BP.split) BP.split.toggle(id, on);
    },
    reset() { if (BP.board) BP.board.reset(); else if (BP.split) BP.split.reset(); },
  };
})();
