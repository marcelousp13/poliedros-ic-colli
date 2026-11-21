/* ============================================================================
   POLIEDROS — ATLAS VIVO DE RESULTADOS & DESCOBERTAS (MODO DUAL)
   Detecta automaticamente:
     • Modo Local (servidor Python): absorção ao vivo via SSE + PythonSCAD
     • Modo Estático (GitHub Pages): lê ./data/catalog.json e ./renders/*.png
   ============================================================================ */

(() => {
  "use strict";

  const state = {
    mode: "static", // "local" | "static"
    activeTab: "resultados",
    catalog: null,
    catalogVersion: 0,
    systemStatus: null,
    eventSource: null,
    lastRenderSig: { resultados: "", descobertas: "" },
    detailCache: new Map(),

    // Filtros Resultados
    resSearch: "",
    resFamily: "all",
    resStatus: "all",
    resSort: "canonical",
    resView: "grid",

    // Filtros Descobertas
    discSearch: "",
    discFamily: "all",
    discStatus: "all",
    discSort: "canonical",
    discView: "grid",

    // Modal de Dossiê
    modalDetail: null,
    modalSolIndex: 0,
    modalMode: "photo",
    modalPreset: "iso",
    modalDataTab: "vertices",
    viewer3D: null,
  };

  function debounce(fn, waitMs = 120) {
    let timer = null;
    return (...args) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => fn(...args), waitMs);
    };
  }

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtSci(val, digits = 2) {
    if (val === null || val === undefined || Number.isNaN(Number(val))) return "—";
    const n = Number(val);
    if (n === 0) return "0.00e+0";
    if (Math.abs(n) < 1e-3 || Math.abs(n) >= 1e5) return n.toExponential(digits);
    return n.toFixed(Math.min(digits + 2, 6));
  }

  function getRenderUrl(solid, sol, preset = "iso") {
    if (state.mode === "static") {
      return sol?.renders?.[preset] || sol?.renders?.iso || "";
    }
    const v = sol?.geom_hash ? `&v=${encodeURIComponent(sol.geom_hash)}` : "";
    return `/api/render/${encodeURIComponent(solid.id)}/${encodeURIComponent(sol.solution_id)}.png?preset=${encodeURIComponent(preset)}${v}`;
  }

  function getDownloadUrl(solid, sol, kind, preset = "iso") {
    if (state.mode === "static") {
      if (kind === "png") return getRenderUrl(solid, sol, preset);
      return sol?.downloads?.[kind] || "";
    }
    const base = `/api/download/${encodeURIComponent(solid.id)}/${encodeURIComponent(sol.solution_id)}/${encodeURIComponent(kind)}`;
    return kind === "png" ? `${base}?preset=${encodeURIComponent(preset)}` : base;
  }

  function showToast(htmlMsg, variant = "info", duration = 3600) {
    const stack = $("#toast-stack");
    const el = document.createElement("div");
    el.className = `toast ${variant === "discovery" ? "toast-discovery" : variant === "success" ? "toast-success" : ""}`;
    el.innerHTML = htmlMsg;
    stack.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      el.style.transition = "opacity 0.25s ease";
      setTimeout(() => el.remove(), 260);
    }, duration);
  }

  async function fetchJson(url, options = {}) {
    const res = await fetch(url, { cache: "no-cache", ...options });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  // ==========================================================================
  // NAVEGAÇÃO
  // ==========================================================================
  function switchTab(tabName) {
    state.activeTab = tabName;
    $$(".tab-btn").forEach((btn) => {
      const active = btn.dataset.tab === tabName;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", String(active));
    });
    $$(".tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === `panel-${tabName}`);
    });
    if (tabName === "resultados") renderResultados();
    if (tabName === "descobertas") renderDescobertas();
  }

  // ==========================================================================
  // DETECÇÃO DE MODO (LOCAL AO VIVO vs GITHUB PAGES ESTÁTICO)
  // ==========================================================================
  async function loadCatalog(silent = false) {
    let data = null;
    const forceStatic = document.body.dataset.atlasMode === "static";
    if (!forceStatic) {
      try {
        data = await fetchJson("/api/catalog");
        state.mode = "local";
      } catch {
        data = null;
      }
    }
    if (!data) {
      try {
        data = await fetchJson(`./data/catalog.json?t=${Date.now()}`);
        state.mode = "static";
      } catch (err) {
        if (!silent) showToast(`Erro ao carregar catálogo: ${esc(err.message)}`);
        return;
      }
    }

    state.catalog = data;
    state.catalogVersion += 1;
    state.detailCache.clear();
    const s = data.summary || {};
    $("#badge-resultados").textContent = `${s.solids_with_convex_global ?? 0}`;
    $("#badge-descobertas").textContent = `${s.total_nonconvex_solutions ?? 0}`;

    updateStatusPill();
    // Renderiza apenas a aba ativa; a outra é renderizada sob demanda ao alternar
    if (state.activeTab === "resultados") {
      renderResultados();
    } else {
      renderDescobertas();
    }

    if (!silent) {
      showToast(
        `Atlas atualizado · <strong>${s.solids_with_convex_global ?? 0}</strong> convexos · <strong>${s.total_nonconvex_solutions ?? 0}</strong> descobertas`,
        "success",
        2400
      );
    }
  }

  async function loadLocalSystemStatus() {
    if (state.mode !== "local") return;
    try {
      state.systemStatus = await fetchJson("/api/system/status");
      const pushBtn = $("#btn-push-github");
      if (state.systemStatus.github_configured) {
        pushBtn.classList.remove("hidden");
      } else {
        pushBtn.classList.add("hidden");
      }
      updateStatusPill();
    } catch {
      // ignora em modo estático
    }
  }

  function updateStatusPill() {
    const pill = $("#btn-sync-info");
    const txt = $("#live-status-text");
    pill.classList.remove("is-live", "is-static");

    if (state.mode === "local") {
      pill.classList.add("is-live");
      txt.textContent = "Absorção ao vivo";
    } else {
      pill.classList.add("is-static");
      const dt = (state.catalog?.generated_at || "").slice(0, 10);
      txt.textContent = dt ? `Atualizado ${dt}` : "Atlas público";
    }
  }

  function connectLiveWatcherSSE() {
    if (state.mode !== "local") return;
    if (state.eventSource) state.eventSource.close();
    const es = new EventSource("/api/events");
    state.eventSource = es;

    es.addEventListener("catalog_updated", (e) => {
      const info = JSON.parse(e.data || "{}");
      const solids = info.solids || [];
      const discarded = info.discarded_solids || [];
      loadCatalog(true).then(() => {
        if (solids.length > 0) {
          showToast(`Novo resultado absorvido: <strong>${esc(solids.join(", "))}</strong>`, "success", 4200);
        } else if (discarded.length > 0) {
          showToast(`Duplicata isométrica descartada: <strong>${esc(discarded.join(", "))}</strong> (já existe no site)`, "info", 3800);
        } else if (info.pulled_count > 0) {
          showToast(`Atlas atualizado com <strong>${info.pulled_count}</strong> novo(s) mínimo(s) da equipe`, "success", 4200);
        }
      });
    });

    const closeCleanly = () => {
      if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
      }
    };
    window.addEventListener("pagehide", closeCleanly, { once: true });
    window.addEventListener("beforeunload", closeCleanly, { once: true });
  }

  function startStaticAutoRefresh(intervalMs = 30000) {
    if (state.mode !== "static") return;
    setInterval(async () => {
      if (document.visibilityState !== "visible" || !state.catalog) return;
      try {
        const fresh = await fetchJson(`./data/catalog.json?t=${Date.now()}`);
        const prevGen = state.catalog?.generated_at || "";
        const nextGen = fresh?.generated_at || "";
        const prevTotal = state.catalog?.summary?.total_global_solutions ?? 0;
        const nextTotal = fresh?.summary?.total_global_solutions ?? 0;
        if (nextGen !== prevGen || nextTotal !== prevTotal) {
          state.catalog = fresh;
          state.catalogVersion += 1;
          state.detailCache.clear();
          const s = fresh.summary || {};
          $("#badge-resultados").textContent = `${s.solids_with_convex_global ?? 0}`;
          $("#badge-descobertas").textContent = `${s.total_nonconvex_solutions ?? 0}`;
          updateStatusPill();
          if (state.activeTab === "resultados") renderResultados();
          else renderDescobertas();
          showToast(
            `Atlas público atualizado! · <strong>${s.solids_with_convex_global ?? 0}</strong> convexos · <strong>${s.total_nonconvex_solutions ?? 0}</strong> descobertas`,
            "success",
            4200
          );
        }
      } catch {
        // ignora falhas pontuais de rede
      }
    }, intervalMs);
  }

  // ==========================================================================
  // ABA 1: RESULTADOS (MÍNIMOS GLOBAIS CONVEXOS -> minimos_globais/convexos/)
  // ==========================================================================
  function renderResultados() {
    if (!state.catalog) return;
    const sig = `${state.catalogVersion}|${state.resSearch}|${state.resFamily}|${state.resStatus}|${state.resSort}|${state.resView}`;
    if (state.lastRenderSig.resultados === sig) return;
    state.lastRenderSig.resultados = sig;

    const { summary, solids } = state.catalog;

    const convexSolidsCount = summary.solids_with_convex_global ?? 0;
    const totalConvexCount = summary.total_convex_solutions ?? convexSolidsCount;

    $("#resultados-kpis").innerHTML = `
      <span class="stat-item"><span class="stat-val is-accent">${convexSolidsCount}</span><span class="stat-lbl">/ ${summary.total_solids} convexos</span></span>
      <span class="stat-item"><span class="stat-val">${summary.active_topology_solids}</span><span class="stat-lbl">ativos</span></span>
      <span class="stat-item"><span class="stat-val">${totalConvexCount}</span><span class="stat-lbl">soluções</span></span>
    `;

    const q = state.resSearch.trim().toLowerCase();
    let list = solids.filter((s) => {
      if (state.resFamily !== "all" && s.family !== state.resFamily) return false;
      if (state.resStatus === "solved" && !s.has_convex_global) return false;
      if (state.resStatus === "unsolved" && s.has_convex_global) return false;
      if (state.resStatus === "active" && !s.has_topology) return false;
      if (state.resStatus === "pending" && s.has_topology) return false;
      if (q) {
        return (
          s.id.toLowerCase().includes(q) ||
          s.display_code.toLowerCase().includes(q) ||
          s.name_pt.toLowerCase().includes(q) ||
          s.name_en.toLowerCase().includes(q)
        );
      }
      return true;
    });

    if (state.resSort === "vertices") {
      list = [...list].sort((a, b) => (a.topology.vertices || 999) - (b.topology.vertices || 999) || a.sort_key - b.sort_key);
    }

    const withPhotos = list.filter((s) => s.has_convex_global).length;
    $("#res-meta-bar").textContent = `${list.length} sólidos · ${withPhotos} ${withPhotos === 1 ? "convexo" : "convexos"}`;

    const gridEl = $("#res-grid");
    const tableWrap = $("#res-table-wrap");

    if (state.resView === "grid") {
      gridEl.classList.remove("hidden");
      tableWrap.classList.add("hidden");
      renderSplitGallery(gridEl, list, "resultados");
      hydrateLoadedImages(gridEl);
    } else {
      gridEl.classList.add("hidden");
      tableWrap.classList.remove("hidden");
      tableWrap.innerHTML = buildAtlasTableHtml(list, "resultados");
    }
  }

  // ==========================================================================
  // ABA 2: DESCOBERTAS (NÃO CONVEXOS GLOBAIS)
  // ==========================================================================
  function renderDescobertas() {
    if (!state.catalog) return;
    const sig = `${state.catalogVersion}|${state.discSearch}|${state.discFamily}|${state.discStatus}|${state.discSort}|${state.discView}`;
    if (state.lastRenderSig.descobertas === sig) return;
    state.lastRenderSig.descobertas = sig;

    const { summary, solids } = state.catalog;

    const allNonConvex = solids.flatMap((s) => s.nonconvex_solutions || []);
    const maxDihedral = allNonConvex.length
      ? Math.max(...allNonConvex.map((x) => x.convexity.max_dihedral_deg || 0))
      : null;
    const minVolRatio = allNonConvex.length
      ? Math.min(...allNonConvex.map((x) => x.convexity.volume_ratio || 1))
      : null;

    $("#descobertas-kpis").innerHTML = `
      <span class="stat-item"><span class="stat-val is-discovery">${summary.total_nonconvex_solutions}</span><span class="stat-lbl">descobertas</span></span>
      <span class="stat-item"><span class="stat-val">${summary.solids_with_nonconvex_global}</span><span class="stat-lbl">/ ${summary.total_solids} sólidos</span></span>
      <span class="stat-item"><span class="stat-val">${maxDihedral !== null ? `${maxDihedral.toFixed(1)}°` : "—"}</span><span class="stat-lbl">θ máx</span></span>
      <span class="stat-item"><span class="stat-val">${minVolRatio !== null ? minVolRatio.toFixed(3) : "—"}</span><span class="stat-lbl">V/V_CH mín</span></span>
    `;

    const q = state.discSearch.trim().toLowerCase();
    let list = solids.filter((s) => {
      if (state.discFamily !== "all" && s.family !== state.discFamily) return false;
      if (state.discStatus === "discovered" && !s.has_nonconvex_global) return false;
      if (state.discStatus === "undiscovered" && s.has_nonconvex_global) return false;
      if (q) {
        return (
          s.id.toLowerCase().includes(q) ||
          s.display_code.toLowerCase().includes(q) ||
          s.name_pt.toLowerCase().includes(q) ||
          s.name_en.toLowerCase().includes(q)
        );
      }
      return true;
    });

    if (state.discSort === "vertices") {
      list = [...list].sort((a, b) => (a.topology.vertices || 999) - (b.topology.vertices || 999) || a.sort_key - b.sort_key);
    }

    const discPhotos = list.filter((s) => s.has_nonconvex_global).length;
    $("#disc-meta-bar").textContent = `${list.length} sólidos · ${discPhotos} ${discPhotos === 1 ? "descoberta" : "descobertas"}`;

    const gridEl = $("#disc-grid");
    const tableWrap = $("#disc-table-wrap");

    if (state.discView === "grid") {
      gridEl.classList.remove("hidden");
      tableWrap.classList.add("hidden");
      renderSplitGallery(gridEl, list, "descobertas");
      hydrateLoadedImages(gridEl);
    } else {
      gridEl.classList.add("hidden");
      tableWrap.classList.remove("hidden");
      tableWrap.innerHTML = buildAtlasTableHtml(list, "descobertas");
    }
  }

  // ==========================================================================
  // GALERIA EM DUAS FAIXAS LIMPAS + CARDS MINIMALISTAS
  // ==========================================================================
  function getPrimarySolutionForTab(solid, isDiscoveryTab) {
    return isDiscoveryTab ? solid.primary_nonconvex : (solid.primary_convex || null);
  }

  function hydrateLoadedImages(container) {
    $$("img[data-atlas-img]", container).forEach((img) => {
      if (img.complete && img.naturalWidth > 0) {
        img.classList.add("is-loaded");
        const ph = img.previousElementSibling;
        if (ph && ph.classList.contains("photo-loading")) ph.style.display = "none";
      }
    });
  }

  function renderSplitGallery(container, list, mode) {
    const isDiscoveryTab = mode === "descobertas";
    const solved = list.filter((s) => Boolean(getPrimarySolutionForTab(s, isDiscoveryTab)));
    const unsolved = list.filter((s) => !Boolean(getPrimarySolutionForTab(s, isDiscoveryTab)));

    if (solved.length > 0 && unsolved.length > 0) {
      container.innerHTML = `
        <div class="atlas-grid">${solved.map((s, idx) => buildSolidCardHtml(s, mode, idx)).join("")}</div>
        <div class="atlas-section-divider">${isDiscoveryTab ? "Catálogo restante" : "Demais sólidos"} · ${unsolved.length}</div>
        <div class="atlas-grid atlas-grid-index">${unsolved.map((s, idx) => buildSolidCardHtml(s, mode, idx)).join("")}</div>
      `;
    } else if (solved.length > 0) {
      container.innerHTML = `<div class="atlas-grid">${solved.map((s, idx) => buildSolidCardHtml(s, mode, idx)).join("")}</div>`;
    } else {
      container.innerHTML = `<div class="atlas-grid atlas-grid-index">${unsolved.map((s, idx) => buildSolidCardHtml(s, mode, idx)).join("")}</div>`;
    }
  }

  function buildSolidCardHtml(solid, mode, index = 99) {
    const isDiscoveryTab = mode === "descobertas";
    const sol = getPrimarySolutionForTab(solid, isDiscoveryTab);
    const hasPhoto = Boolean(sol);

    const cardClasses = [
      "solid-card",
      hasPhoto ? "is-solved" : "is-unsolved",
      hasPhoto && !sol.is_convex ? "is-discovery" : "",
      !solid.has_topology ? "is-pending" : "",
    ]
      .filter(Boolean)
      .join(" ");

    let photoHtml = "";
    if (hasPhoto) {
      const imgUrl = getRenderUrl(solid, sol, "iso");
      const badgeCls = sol.is_convex ? "badge-convex" : "badge-discovery";
      const badgeTxt = sol.is_convex ? "Convexo" : "Não convexo";
      const isAboveFold = index < 8;

      let rightBadge = "";
      if (!isDiscoveryTab && solid.nonconvex_count > 0) {
        rightBadge = `<span class="badge badge-discovery photo-badge-tr">+${solid.nonconvex_count}</span>`;
      } else if (isDiscoveryTab && solid.nonconvex_count > 1) {
        rightBadge = `<span class="badge badge-discovery photo-badge-tr">×${solid.nonconvex_count}</span>`;
      } else if (!isDiscoveryTab && solid.convex_count > 1) {
        rightBadge = `<span class="badge badge-neutral photo-badge-tr">×${solid.convex_count}</span>`;
      }

      photoHtml = `
        <div class="photo-stage">
          <span class="badge ${badgeCls} photo-badge-tl">${badgeTxt}</span>
          ${rightBadge}
          <div class="photo-loading"><div class="photo-placeholder-mark"></div></div>
          <img
            data-atlas-img="1"
            src="${esc(imgUrl)}"
            alt="${esc(solid.display_code)} — ${esc(solid.name_pt)}"
            width="720"
            height="720"
            loading="${isAboveFold ? "eager" : "lazy"}"
            fetchpriority="${isAboveFold ? "high" : "low"}"
            decoding="async"
            onload="this.classList.add('is-loaded');if(this.previousElementSibling)this.previousElementSibling.style.display='none';"
            onerror="if(this.previousElementSibling)this.previousElementSibling.innerHTML='<span class=muted-xs>—</span>';"
          />
        </div>
      `;
    }

    const topo = solid.topology || {};
    const topoShort = solid.has_topology
      ? `V:${topo.vertices} · F:${topo.faces} · E:${topo.edges}`
      : topo.vertices
        ? `V:${topo.vertices} · pendente`
        : "pendente";

    const redundantCode = solid.display_code.trim().toLowerCase() === solid.name_pt.trim().toLowerCase();
    const codeHtml = redundantCode
      ? `<span class="solid-code" style="color:var(--ink-faint);font-weight:500;">${esc(solid.family)}</span>`
      : `<span class="solid-code">${esc(solid.display_code)}</span>`;

    const topRight = hasPhoto ? `<span class="solid-energy">${fmtSci(sol.fval, 1)}</span>` : "";

    const proofLine =
      hasPhoto && !sol.is_convex
        ? `<div class="solid-proof-line">θ ${sol.convexity.max_dihedral_deg.toFixed(1)}° · V/V_CH ${sol.convexity.volume_ratio.toFixed(3)}</div>`
        : "";

    let footRight = "";
    if (!hasPhoto) {
      if (isDiscoveryTab && solid.has_convex_global) {
        footRight = `<span class="dot-convex-note">● convexo</span>`;
      } else if (!isDiscoveryTab && solid.has_nonconvex_global) {
        footRight = `<span style="color:var(--discovery);">◆ ${solid.nonconvex_count} desc.</span>`;
      }
    } else if (solid.has_topology && topo.face_signature) {
      footRight = `<span>${esc(topo.face_signature)}</span>`;
    }

    return `
      <article class="${cardClasses}" ${hasPhoto ? `data-open-solid="${esc(solid.id)}" data-sol-id="${esc(sol.solution_id)}"` : ""}>
        ${photoHtml}
        <div class="solid-card-body">
          <div class="solid-card-top">
            ${codeHtml}
            ${topRight}
          </div>
          <div class="solid-name-pt">${esc(solid.name_pt)}</div>
          ${proofLine}
          <div class="solid-foot-row">
            <span>${topoShort}</span>
            ${footRight}
          </div>
        </div>
      </article>
    `;
  }

  function buildAtlasTableHtml(list, mode) {
    const isDiscoveryTab = mode === "descobertas";
    const rows = list
      .map((s) => {
        const sol = getPrimarySolutionForTab(s, isDiscoveryTab);
        const hasPhoto = Boolean(sol);
        const thumb = hasPhoto
          ? `<img class="table-thumb" src="${esc(getRenderUrl(s, sol, "iso"))}" alt="${esc(s.display_code)}" loading="lazy"/>`
          : `<span class="mono muted-xs">—</span>`;

        const statusBadge = hasPhoto
          ? sol.is_convex
            ? `<span class="badge badge-convex">Convexo</span>`
            : `<span class="badge badge-discovery">Não convexo</span>`
          : !s.has_topology
            ? `<span class="muted-xs">pendente</span>`
            : `<span class="muted-xs">—</span>`;

        const extraCol = hasPhoto
          ? isDiscoveryTab
            ? `<span class="mono" style="color:var(--discovery);">${sol.convexity.max_dihedral_deg.toFixed(1)}° · ${sol.convexity.volume_ratio.toFixed(3)}</span>`
            : `<span class="mono">${fmtSci(sol.fval, 2)}</span>`
          : `<span class="muted-xs">—</span>`;

        return `
          <tr class="${hasPhoto ? "clickable-row" : ""}" ${hasPhoto ? `data-open-solid="${esc(s.id)}" data-sol-id="${esc(sol.solution_id)}"` : ""}>
            <td>${thumb}</td>
            <td class="mono" style="font-weight:600;">${esc(s.display_code)}</td>
            <td style="font-family:var(--font-serif);font-size:0.98rem;">${esc(s.name_pt)}</td>
            <td class="mono muted-xs">${s.has_topology ? `${s.topology.vertices} · ${s.topology.faces} · ${s.topology.edges}` : "—"}</td>
            <td>${statusBadge}</td>
            <td>${extraCol}</td>
          </tr>
        `;
      })
      .join("");

    return `
      <table class="atlas-table">
        <thead>
          <tr>
            <th></th>
            <th>Código</th>
            <th>Poliedro</th>
            <th>V · F · E</th>
            <th>Classe</th>
            <th>${isDiscoveryTab ? "θ máx · V/V_CH" : "f(x)"}</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function bindDelegatedCatalogClicks() {
    ["#res-grid", "#res-table-wrap", "#disc-grid", "#disc-table-wrap"].forEach((sel) => {
      const container = $(sel);
      if (!container) return;
      container.addEventListener("click", (e) => {
        const card = e.target.closest("[data-open-solid]");
        if (card) openSolidModal(card.dataset.openSolid, card.dataset.solId);
      });
    });
  }

  // ==========================================================================
  // MODAL DE DOSSIÊ CIENTÍFICO
  // ==========================================================================
  async function openSolidModal(solidId, preferredSolId = null) {
    const modal = $("#solid-modal");
    const body = $("#modal-body");
    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
    $("#modal-eyebrow").textContent = solidId;
    $("#modal-title").textContent = "…";
    $("#modal-sub-en").textContent = "";

    try {
      let detail = state.detailCache.get(solidId);
      if (!detail) {
        body.innerHTML = `<div style="padding:36px;text-align:center;"><div class="spinner" style="margin:0 auto;"></div></div>`;
        if (state.mode === "static") {
          const entry = (state.catalog?.solids || []).find((s) => s.id === solidId);
          if (!entry || !entry.detail_url) throw new Error("Dossiê não encontrado.");
          const sep = entry.detail_url.includes("?") ? "&" : "?";
          detail = await fetchJson(`${entry.detail_url}${sep}t=${Date.now()}`);
        } else {
          detail = await fetchJson(`/api/solid/${encodeURIComponent(solidId)}`);
        }
        state.detailCache.set(solidId, detail);
      }

      state.modalDetail = detail;
      state.modalMode = "photo";
      state.modalPreset = "iso";
      state.modalDataTab = "vertices";

      let idx = 0;
      if (preferredSolId && detail.global_solutions.length > 0) {
        const found = detail.global_solutions.findIndex((s) => s.solution_id === preferredSolId);
        if (found >= 0) idx = found;
      }
      state.modalSolIndex = idx;
      renderModalContent();
    } catch (err) {
      body.innerHTML = `<div style="padding:20px;color:#b91c1c;">${esc(err.message)}</div>`;
    }
  }

  function closeSolidModal() {
    destroyViewer3D();
    $("#solid-modal").classList.add("hidden");
    document.body.style.overflow = "";
    state.modalDetail = null;
  }

  function renderModalContent() {
    destroyViewer3D();
    const detail = state.modalDetail;
    if (!detail) return;

    const sol = detail.global_solutions[state.modalSolIndex];
    if (!sol) {
      $("#modal-body").innerHTML = `<p class="muted">Sem solução global.</p>`;
      return;
    }

    $("#modal-eyebrow").textContent = detail.display_code;
    $("#modal-title").textContent = detail.name_pt;
    $("#modal-sub-en").textContent = detail.name_en;

    const switcherHtml =
      detail.global_solutions.length > 1
        ? `<div class="solution-switcher">
            ${detail.global_solutions
              .map(
                (s, i) => `
              <button type="button" class="pill ${i === state.modalSolIndex ? "active" : ""}" data-sol-idx="${i}">
                #${i + 1} · ${s.is_convex ? "Convexo" : "Não convexo"}
              </button>`
              )
              .join("")}
          </div>`
        : "";

    const c = sol.convexity;
    const proofHtml = sol.is_convex
      ? `<div class="proof-box"><span class="proof-title">✓ Convexo</span> <span class="mono" style="margin-left:8px;color:var(--ink-secondary);">V/V_CH = ${c.volume_ratio.toFixed(5)} · θ ∈ [${c.min_dihedral_deg.toFixed(1)}°, ${c.max_dihedral_deg.toFixed(1)}°]</span></div>`
      : `<div class="proof-box is-nonconvex">
           <div class="proof-title">◆ Global Não Convexo</div>
           <ul class="proof-reasons">${(c.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
         </div>`;

    const cameraPresets = [
      { key: "iso", label: "Iso" },
      { key: "front", label: "Frontal" },
      { key: "top", label: "Topo" },
      { key: "alt", label: "Alt" },
    ];

    const imgUrl = getRenderUrl(detail, sol, state.modalPreset);
    const stageContent =
      state.modalMode === "photo"
        ? `<img id="modal-scad-img" src="${esc(imgUrl)}" alt="${esc(detail.display_code)}" />`
        : `<canvas id="modal-3d-canvas" class="stage-canvas"></canvas>`;

    const cameraBar =
      state.modalMode === "photo"
        ? `<div class="camera-bar">
            <span class="mono muted-xs">PythonSCAD</span>
            <div style="display:flex;gap:4px;">
              ${cameraPresets
                .map(
                  (p) =>
                    `<button type="button" class="btn-tiny" style="${p.key === state.modalPreset ? "border-color:var(--ink);background:var(--ink);color:#fff;" : ""}" data-preset="${p.key}">${p.label}</button>`
                )
                .join("")}
            </div>
          </div>`
        : `<div class="camera-bar">
            <span class="mono muted-xs">Arraste · Zoom</span>
            <button type="button" class="btn-tiny" id="btn-reset-3d">Reset</button>
          </div>`;

    const topo = detail.topology;
    const h = sol.hessian;

    const dlScad = getDownloadUrl(detail, sol, "scad");
    const dlJson = getDownloadUrl(detail, sol, "json");
    const dlTxt = getDownloadUrl(detail, sol, "txt");
    const dlPng = getDownloadUrl(detail, sol, "png", state.modalPreset);

    $("#modal-body").innerHTML = `
      ${switcherHtml}
      <div class="dossier-grid">
        <div>
          <div class="stage-card">
            <div class="stage-toolbar">
              <div class="view-toggle">
                <button type="button" class="view-btn ${state.modalMode === "photo" ? "active" : ""}" data-stage-mode="photo">PythonSCAD</button>
                <button type="button" class="view-btn ${state.modalMode === "3d" ? "active" : ""}" data-stage-mode="3d">3D</button>
              </div>
              <span class="badge ${sol.is_convex ? "badge-convex" : "badge-discovery"}">${sol.is_convex ? "Convexo" : "Não convexo"}</span>
            </div>
            <div class="stage-viewport">${stageContent}</div>
            ${cameraBar}
          </div>

          <div class="export-bar">
            ${state.mode === "local" && sol.has_scad ? `<button type="button" class="btn btn-primary btn-sm" id="btn-open-scad-gui">PythonSCAD ↗</button>` : ""}
            ${sol.has_scad && dlScad ? `<a class="btn btn-secondary btn-sm" href="${esc(dlScad)}" download>.py</a>` : ""}
            ${sol.has_json && dlJson ? `<a class="btn btn-secondary btn-sm" href="${esc(dlJson)}" download>.json</a>` : ""}
            ${sol.has_txt && dlTxt ? `<a class="btn btn-secondary btn-sm" href="${esc(dlTxt)}" download>.txt</a>` : ""}
            ${dlPng ? `<a class="btn btn-secondary btn-sm" href="${esc(dlPng)}" download>.png</a>` : ""}
          </div>
        </div>

        <div>
          <div class="dossier-section">${proofHtml}</div>

          <div class="dossier-section">
            <div class="metrics-2col">
              <div class="metric-cell">
                <div class="metric-cell-label">Energia F(x)</div>
                <div class="metric-cell-val">${fmtSci(sol.fval, 4)}</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">V · F · E · χ</div>
                <div class="metric-cell-val">${topo.vertices} · ${topo.faces} · ${topo.edges} · ${topo.euler ?? "—"}</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Volume / V_CH</div>
                <div class="metric-cell-val">${c.volume.toFixed(4)} / ${c.hull_volume.toFixed(4)}</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Diedrais</div>
                <div class="metric-cell-val">${c.min_dihedral_deg.toFixed(2)}° – ${c.max_dihedral_deg.toFixed(2)}°</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Reflexas / Interiores</div>
                <div class="metric-cell-val">${c.reflex_edges} / ${c.interior_vertices}</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Hessiana λ mín</div>
                <div class="metric-cell-val">${h ? fmtSci(h.min_non_rigid, 3) : "—"}</div>
              </div>
            </div>
          </div>

          <div class="dossier-section">
            <div class="filter-group">
              <button type="button" class="pill ${state.modalDataTab === "vertices" ? "active" : ""}" data-data-tab="vertices">Vértices (${sol.vertices.length})</button>
              <button type="button" class="pill ${state.modalDataTab === "dihedrals" ? "active" : ""}" data-data-tab="dihedrals">Diedrais (${(c.interior_dihedrals_deg || []).length})</button>
              <button type="button" class="pill ${state.modalDataTab === "distances" ? "active" : ""}" data-data-tab="distances">Distâncias (${(sol.distancias || []).length})</button>
              <button type="button" class="pill ${state.modalDataTab === "eigen" ? "active" : ""}" data-data-tab="eigen">Hessiana (${(sol.autovalores || []).length})</button>
            </div>
            <pre class="data-pre" id="modal-data-pre">${esc(formatModalDataTab(sol, state.modalDataTab))}</pre>
          </div>
        </div>
      </div>
    `;

    $$("[data-sol-idx]", $("#modal-body")).forEach((btn) => {
      btn.addEventListener("click", () => { state.modalSolIndex = Number(btn.dataset.solIdx); renderModalContent(); });
    });
    $$("[data-stage-mode]", $("#modal-body")).forEach((btn) => {
      btn.addEventListener("click", () => { state.modalMode = btn.dataset.stageMode; renderModalContent(); });
    });
    $$("[data-preset]", $("#modal-body")).forEach((btn) => {
      btn.addEventListener("click", () => { state.modalPreset = btn.dataset.preset; renderModalContent(); });
    });
    $$("[data-data-tab]", $("#modal-body")).forEach((btn) => {
      btn.addEventListener("click", () => {
        state.modalDataTab = btn.dataset.dataTab;
        $$("[data-data-tab]", $("#modal-body")).forEach((b) => b.classList.toggle("active", b === btn));
        $("#modal-data-pre").textContent = formatModalDataTab(sol, state.modalDataTab);
      });
    });

    const openGuiBtn = $("#btn-open-scad-gui");
    if (openGuiBtn) {
      openGuiBtn.addEventListener("click", async () => {
        try {
          const res = await fetchJson("/api/open-pythonscad", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ solid_id: detail.id, solution_id: sol.solution_id }),
          });
          showToast(esc(res.message || "Aberto no PythonSCAD"), "success", 2600);
        } catch (err) {
          showToast(`Erro: ${esc(err.message)}`);
        }
      });
    }

    if (state.modalMode === "3d") {
      initViewer3D($("#modal-3d-canvas"), sol.vertices, sol.faces, !sol.is_convex);
      $("#btn-reset-3d")?.addEventListener("click", () => state.viewer3D?.reset());
    }
  }

  function formatModalDataTab(sol, tab) {
    if (tab === "vertices") {
      return sol.vertices
        .map((v, i) => `v[${String(i).padStart(2, "0")}] = (${v[0].toFixed(8)}, ${v[1].toFixed(8)}, ${v[2].toFixed(8)})`)
        .join("\n");
    }
    if (tab === "dihedrals") {
      const list = sol.convexity?.interior_dihedrals_deg || sol.angulos_salvos || [];
      return list.map((a, i) => `θ[${String(i + 1).padStart(2, "0")}] = ${Number(a).toFixed(4)}°${Number(a) > 180.5 ? "  ← >180°" : ""}`).join("\n");
    }
    if (tab === "distances") {
      return (sol.distancias || []).map((d, i) => `d[${String(i + 1).padStart(3, "0")}] = ${Number(d).toFixed(6)}`).join("\n") || "—";
    }
    if (tab === "eigen") {
      return (sol.autovalores || []).map((e, i) => `λ[${String(i + 1).padStart(3, "0")}] = ${Number(e).toExponential(6)}`).join("\n") || "—";
    }
    return "";
  }

  // ==========================================================================
  // MODAL DE SINCRONIZAÇÃO AUTOMÁTICA
  // ==========================================================================
  function openSyncModal() {
    const modal = $("#sync-modal");
    const body = $("#sync-modal-body");
    const st = state.systemStatus;
    const isLocal = state.mode === "local";

    const statusLine = isLocal
      ? st?.github_configured
        ? `<div class="proof-box" style="margin-bottom:14px;"><span class="proof-title">✓ GitHub conectado</span> <span class="mono" style="margin-left:6px;">${esc(st.github_repo)}</span></div>`
        : `<div class="metric-cell" style="margin-bottom:14px;"><div class="metric-cell-label">Modo Local</div><div style="font-size:0.82rem;margin-top:3px;">Observando <code>solidos/</code> ao vivo. Para publicar no GitHub Pages, rode <code>web\\configurar_github.bat</code>.</div></div>`
      : `<div class="metric-cell" style="margin-bottom:14px;"><div class="metric-cell-label">Atlas Público (GitHub Pages)</div><div class="mono" style="font-size:0.8rem;margin-top:3px;">Atualizado automaticamente via GitHub Actions</div></div>`;

    body.innerHTML = `
      ${statusLine}
      <div class="sync-steps">
        <div class="sync-step">
          <div class="sync-step-title">1. Execução automática em qualquer máquina (Spyder, VS Code ou terminal)</div>
          <div>Basta rodar <code>standbyalone2.py</code> — o envio automático via Cloudflare Worker já está embutido. Na 1ª vez pede apenas seu nome e a <code>TEAM_KEY</code> da equipe.</div>
        </div>
        <div class="sync-step">
          <div class="sync-step-title">2. Deduplicação global entre máquinas (protocolo de 4 passos)</div>
          <div>Cada novo mínimo é conferido por isomorfismo métrico contra o site público e o GitHub; duplicatas são descartadas e apenas mínimos inéditos disparam o GitHub Actions para todos.</div>
        </div>
        <div class="sync-step">
          <div class="sync-step-title">3. Separação automática por convexidade e autointerseção</div>
          <div>O site lê exclusivamente os mínimos globais <strong>sem autointerseção de faces</strong>: <code>minimos_globais/convexos/sem_autointersecao/</code> vai para <strong>Resultados</strong> e <code>minimos_globais/nao_convexos/sem_autointersecao/</code> vai para <strong>Descobertas</strong> (<code>com_autointersecao/</code> e <code>minimos_locais/</code> permanecem apenas locais).</div>
        </div>
      </div>
    `;
    modal.classList.remove("hidden");
  }

  function closeSyncModal() {
    $("#sync-modal").classList.add("hidden");
  }

  // ==========================================================================
  // VISUALIZADOR 3D EM CANVAS
  // ==========================================================================
  function destroyViewer3D() {
    if (state.viewer3D) {
      state.viewer3D.destroy();
      state.viewer3D = null;
    }
  }

  function initViewer3D(canvas, rawVertices, faces, isDiscovery) {
    if (!canvas || !rawVertices?.length || !faces?.length) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    const size = Math.max(280, Math.round(rect.width || 375));
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    const ctx = canvas.getContext("2d");

    let cx = 0, cy = 0, cz = 0;
    for (const v of rawVertices) { cx += v[0]; cy += v[1]; cz += v[2]; }
    cx /= rawVertices.length; cy /= rawVertices.length; cz /= rawVertices.length;

    const verts = rawVertices.map((v) => [v[0] - cx, v[1] - cy, v[2] - cz]);
    let maxR = 1e-6;
    for (const v of verts) {
      const r = Math.hypot(v[0], v[1], v[2]);
      if (r > maxR) maxR = r;
    }
    const normVerts = verts.map((v) => [v[0] / maxR, v[1] / maxR, v[2] / maxR]);

    let rotX = -0.52, rotY = 0.62, zoom = 1.0, dragging = false, lastX = 0, lastY = 0, autoSpin = true, rafId = null;
    const baseRgb = isDiscovery ? [175, 42, 76] : [66, 113, 174];

    function transform(p) {
      const cosY = Math.cos(rotY), sinY = Math.sin(rotY);
      const x1 = p[0] * cosY + p[2] * sinY;
      const z1 = -p[0] * sinY + p[2] * cosY;
      const cosX = Math.cos(rotX), sinX = Math.sin(rotX);
      return [x1, p[1] * cosX - z1 * sinX, p[1] * sinX + z1 * cosX];
    }

    function draw() {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, size, size);

      const tv = normVerts.map(transform);
      const fov = 3.8, scale = size * 0.36 * zoom;
      const project = (p) => {
        const persp = fov / (fov - p[2]);
        return [size / 2 + p[0] * scale * persp, size / 2 - p[1] * scale * persp, p[2]];
      };

      const drawFaces = [];
      for (const f of faces) {
        if (f.length < 3) continue;
        const pts3 = f.map((idx) => tv[idx]);
        let nx = 0, ny = 0, nz = 0;
        for (let i = 0; i < pts3.length; i++) {
          const a = pts3[i], b = pts3[(i + 1) % pts3.length];
          nx += (a[1] - b[1]) * (a[2] + b[2]);
          ny += (a[2] - b[2]) * (a[0] + b[0]);
          nz += (a[0] - b[0]) * (a[1] + b[1]);
        }
        const nlen = Math.hypot(nx, ny, nz) || 1;
        nx /= nlen; ny /= nlen; nz /= nlen;

        const avgZ = pts3.reduce((acc, p) => acc + p[2], 0) / pts3.length;
        const l1 = Math.max(0, Math.abs(nx * -0.45 + ny * 0.65 + nz * 0.62));
        const l2 = Math.max(0, Math.abs(nx * 0.55 + ny * -0.25 + nz * 0.78));
        drawFaces.push({ pts2: pts3.map(project), avgZ, shade: Math.min(1.22, 0.42 + 0.52 * l1 + 0.16 * l2) });
      }

      drawFaces.sort((a, b) => a.avgZ - b.avgZ);

      for (const df of drawFaces) {
        const r = Math.min(248, Math.round(baseRgb[0] * df.shade + 22));
        const g = Math.min(248, Math.round(baseRgb[1] * df.shade + 22));
        const b = Math.min(252, Math.round(baseRgb[2] * df.shade + 24));
        ctx.beginPath();
        df.pts2.forEach((p, idx) => (idx === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1])));
        ctx.closePath();
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fill();
        ctx.strokeStyle = "rgba(15, 23, 42, 0.34)";
        ctx.lineWidth = 1.0;
        ctx.lineJoin = "round";
        ctx.stroke();
      }
    }

    function scheduleDraw() {
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        if (autoSpin && !dragging) {
          rotY += 0.0045;
          draw();
          scheduleDraw();
        } else {
          draw();
        }
      });
    }

    const onDown = (e) => { dragging = true; autoSpin = false; lastX = e.clientX; lastY = e.clientY; };
    const onMove = (e) => {
      if (!dragging) return;
      rotY += (e.clientX - lastX) * 0.009;
      rotX += (e.clientY - lastY) * 0.009;
      lastX = e.clientX; lastY = e.clientY;
      scheduleDraw();
    };
    const onUp = () => { dragging = false; };
    const onWheel = (e) => {
      e.preventDefault();
      zoom = Math.max(0.55, Math.min(2.1, zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
      scheduleDraw();
    };

    canvas.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    scheduleDraw();

    state.viewer3D = {
      reset() { rotX = -0.52; rotY = 0.62; zoom = 1.0; autoSpin = true; scheduleDraw(); },
      destroy() {
        autoSpin = false;
        if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
        canvas.removeEventListener("mousedown", onDown);
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        canvas.removeEventListener("wheel", onWheel);
      },
    };
  }

  // ==========================================================================
  // EVENTOS E BOOTSTRAP
  // ==========================================================================
  function bindEvents() {
    $$(".tab-btn").forEach((btn) => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));

    $("#btn-reload-catalog").addEventListener("click", () => loadCatalog(false));
    $("#btn-sync-info").addEventListener("click", openSyncModal);
    $("#sync-modal-close").addEventListener("click", closeSyncModal);
    $("#sync-modal").addEventListener("click", (e) => { if (e.target.id === "sync-modal") closeSyncModal(); });

    $("#btn-push-github").addEventListener("click", async () => {
      const btn = $("#btn-push-github");
      btn.disabled = true;
      btn.textContent = "Enviando…";
      try {
        const res = await fetchJson("/api/sync-github", { method: "POST" });
        showToast(esc(res.message || "Sincronizado!"), "success", 4200);
      } catch (err) {
        showToast(`Erro: ${esc(err.message)}`);
      } finally {
        btn.disabled = false;
        btn.textContent = "Enviar ao GitHub";
      }
    });

    const onResSearch = debounce((val) => { state.resSearch = val; renderResultados(); }, 120);
    $("#res-search").addEventListener("input", (e) => onResSearch(e.target.value));
    $$("#res-family-filters .pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        $$("#res-family-filters .pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        state.resFamily = pill.dataset.family;
        renderResultados();
      });
    });
    $("#res-status-filter").addEventListener("change", (e) => { state.resStatus = e.target.value; renderResultados(); });
    $("#res-sort").addEventListener("change", (e) => { state.resSort = e.target.value; renderResultados(); });

    const onDiscSearch = debounce((val) => { state.discSearch = val; renderDescobertas(); }, 120);
    $("#disc-search").addEventListener("input", (e) => onDiscSearch(e.target.value));
    $$("#disc-family-filters .pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        $$("#disc-family-filters .pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        state.discFamily = pill.dataset.family;
        renderDescobertas();
      });
    });
    $("#disc-status-filter").addEventListener("change", (e) => { state.discStatus = e.target.value; renderDescobertas(); });
    $("#disc-sort").addEventListener("change", (e) => { state.discSort = e.target.value; renderDescobertas(); });

    $$(".view-btn[data-target]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.target;
        const view = btn.dataset.view;
        $$(`.view-btn[data-target="${target}"]`).forEach((b) => b.classList.toggle("active", b === btn));
        if (target === "res") { state.resView = view; renderResultados(); }
        else { state.discView = view; renderDescobertas(); }
      });
    });

    $("#modal-close").addEventListener("click", closeSolidModal);
    $("#solid-modal").addEventListener("click", (e) => { if (e.target.id === "solid-modal") closeSolidModal(); });
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (!$("#solid-modal").classList.contains("hidden")) closeSolidModal();
        if (!$("#sync-modal").classList.contains("hidden")) closeSyncModal();
      }
    });
  }

  async function init() {
    bindEvents();
    bindDelegatedCatalogClicks();
    await loadCatalog(true);
    if (state.mode === "local") {
      await loadLocalSystemStatus();
      connectLiveWatcherSSE();
    } else {
      startStaticAutoRefresh(30000);
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
