/* ============================================================================
   SÓLIDOS DE JOHNSON — CATÁLOGO COMPUTACIONAL (IME-USP · IC COM COLLI)
   Modo Dual:
     • Modo Local (servidor Python): absorção ao vivo via SSE + PythonSCAD
     • Modo Estático (GitHub Pages): ./data/catalog.json + WebP otimizado
   ============================================================================ */

(() => {
  "use strict";

  const DEFAULT_SEGMENT_DEFS = {
    all: "Catálogo completo da pesquisa: Sólidos de Johnson, Platônicos, Arquimedianos, Prismas e Antiprismas.",
    johnson: "Os 92 poliedros estritamente convexos de faces regulares que não são platônicos, arquimedianos, prismas nem antiprismas (J1–J92).",
    elementares: "Poliedros convexos de faces regulares irredutíveis por planos de corte em dois poliedros menores de faces regulares (Zalgaller, 1969).",
    prismas: "Poliedros uniformes formados por duas bases poligonais regulares congruentes e paralelas unidas por faces quadradas.",
    antiprismas: "Poliedros uniformes com duas bases poligonais regulares paralelas e rotacionadas entre si, ligadas por uma faixa alternada de triângulos equiláteros.",
    arquimedianos: "Poliedros convexos semirregulares vértice-transitivos compostos por dois ou mais tipos de polígonos regulares (excluindo prismas e antiprismas).",
    platonicos: "Os cinco poliedros convexos regulares com faces congruentes a um mesmo polígono regular e mesmo grau em todos os vértices.",
  };

  const state = {
    mode: "static", // "local" | "static"
    catalog: null,
    catalogVersion: 0,
    systemStatus: null,
    eventSource: null,
    lastRenderSig: "",
    detailCache: new Map(),
    prefetchInFlight: new Set(),

    // Filtros do Catálogo Unificado
    segment: "all", // all | johnson | elementares | prismas | antiprismas | arquimedianos | platonicos
    search: "",
    statusFilter: "all", // all | solved | convex | nonconvex | unsolved | active | pending
    sort: "canonical", // canonical | vertices | minima
    view: "grid", // grid | table
    galleryShowDiagonals: true,

    // Modal Ficha do Sólido
    modalDetail: null,
    modalClassFilter: "all", // all | convex | nonconvex
    modalCompareMode: false,
    modalSolId: null,
    modalMode: "photo", // photo | 3d
    modalPreset: "iso",
    modalDataTab: "vertices", // vertices | initial | dihedrals | distances | eigen
    modalShowDiagonals: true,
    modalShowVertices3D: false,
    viewer3D: null,
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function debounce(fn, waitMs = 110) {
    let timer = null;
    return (...args) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => fn(...args), waitMs);
    };
  }

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

  function fmtInt(val) {
    if (val === null || val === undefined || Number.isNaN(Number(val))) return "—";
    return Number(val).toLocaleString("pt-BR");
  }

  function fmtDateShort(ts) {
    if (!ts) return "—";
    const s = String(ts);
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return `${m[3]}/${m[2]}/${m[1]}`;
    return s.slice(0, 10);
  }

  function getRenderUrl(solid, sol, preset = "iso", showDiagonals = true, thumb = false) {
    if (!sol) return "";
    if (state.mode === "static") {
      if (thumb && preset === "iso") {
        if (showDiagonals && sol.thumb) return sol.thumb;
        if (!showDiagonals && sol.thumb_clean) return sol.thumb_clean;
      }
      const map = showDiagonals ? sol.renders : (sol.renders_clean || sol.renders);
      if (map?.[preset]) return map[preset];
      if (map?.iso) return map.iso;
      return showDiagonals ? (sol.thumb || "") : (sol.thumb_clean || sol.thumb || "");
    }
    const v = sol.geom_hash ? `&v=${encodeURIComponent(sol.geom_hash)}` : "";
    const d = showDiagonals ? "" : "&diagonals=0";
    const t = thumb && preset === "iso" ? "&thumb=1" : "";
    return `/api/render/${encodeURIComponent(solid.id)}/${encodeURIComponent(sol.solution_id)}.webp?preset=${encodeURIComponent(preset)}${d}${t}${v}`;
  }

  function getDownloadUrl(solid, sol, kind, preset = "iso", showDiagonals = true) {
    if (!sol) return "";
    if (state.mode === "static") {
      if (kind === "png") return getRenderUrl(solid, sol, preset, showDiagonals, false);
      return sol.downloads?.[kind] || "";
    }
    const base = `/api/download/${encodeURIComponent(solid.id)}/${encodeURIComponent(sol.solution_id)}/${encodeURIComponent(kind)}`;
    if (kind !== "png") return base;
    const d = showDiagonals ? "" : "&diagonals=0";
    return `${base}?preset=${encodeURIComponent(preset)}${d}`;
  }

  function showToast(htmlMsg, variant = "info", duration = 3400) {
    const stack = $("#toast-stack");
    const el = document.createElement("div");
    el.className = `toast ${variant === "nonconvex" ? "toast-nonconvex" : variant === "success" ? "toast-success" : ""}`;
    el.innerHTML = htmlMsg;
    stack.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      el.style.transition = "opacity 0.25s ease";
      setTimeout(() => el.remove(), 260);
    }, duration);
  }

  async function copyText(text, label = "Copiado") {
    try {
      await navigator.clipboard.writeText(text);
      showToast(`${esc(label)} para a área de transferência.`, "success", 2200);
    } catch {
      showToast("Não foi possível copiar automaticamente.", "info", 2400);
    }
  }

  async function downloadPngFromImageUrl(imgUrl, filename) {
    try {
      const img = new Image();
      img.crossOrigin = "anonymous";
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
        img.src = imgUrl;
      });
      const canvas = document.createElement("canvas");
      canvas.width = img.naturalWidth || 720;
      canvas.height = img.naturalHeight || 720;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      if (!blob) throw new Error("Falha ao converter PNG");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      window.open(imgUrl, "_blank");
    }
  }

  async function fetchJson(url, options = {}) {
    const res = await fetch(url, { cache: "no-cache", ...options });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  // ==========================================================================
  // SEGMENTAÇÃO DOS SÓLIDOS
  // ==========================================================================
  function matchesSegment(solid, segKey) {
    if (segKey === "all") return true;
    if (segKey === "elementares") return Boolean(solid.is_elementary);
    if (solid.segment) return solid.segment === segKey;
    const fam = (solid.family || "").toLowerCase();
    if (segKey === "johnson") return fam.includes("johnson");
    if (segKey === "prismas") return fam === "prismas";
    if (segKey === "antiprismas") return fam === "antiprismas";
    if (segKey === "arquimedianos") return fam.includes("arquimed");
    if (segKey === "platonicos") return fam.includes("plat");
    return true;
  }

  function getSegmentDefinition(segKey) {
    const list = state.catalog?.segments;
    if (Array.isArray(list)) {
      const hit = list.find((s) => s.key === segKey);
      if (hit?.definition) return hit.definition;
    }
    return DEFAULT_SEGMENT_DEFS[segKey] || "";
  }

  // ==========================================================================
  // CARREGAMENTO DO CATÁLOGO (LOCAL vs ESTÁTICO)
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
    state.lastRenderSig = "";

    updateHeaderStatsAndCounts();
    updateStatusPill();
    renderCatalog();

    if (!silent) {
      const s = data.summary || {};
      showToast(
        `Catálogo atualizado · <strong>${s.solids_with_global ?? 0}</strong> sólidos · <strong>${s.total_global_solutions ?? 0}</strong> mínimos globais`,
        "success",
        2400
      );
    }
  }

  function updateHeaderStatsAndCounts() {
    if (!state.catalog) return;
    const { summary, solids } = state.catalog;
    const solvedSolids = summary.solids_with_global ?? 0;
    const totalSolids = summary.total_solids ?? solids.length;
    const totalGlobals = summary.total_global_solutions ?? 0;
    const totalConvex = summary.total_convex_solutions ?? 0;
    const totalNonConvex = summary.total_nonconvex_solutions ?? 0;

    $("#catalog-kpis").innerHTML = `
      <span class="stat-item"><span class="stat-val is-accent">${solvedSolids}</span><span class="stat-lbl">/ ${totalSolids} sólidos</span></span>
      <span class="stat-item"><span class="stat-val">${totalGlobals}</span><span class="stat-lbl">mínimos globais</span></span>
      <span class="stat-item"><span class="stat-val is-convex">${totalConvex}</span><span class="stat-lbl">${totalConvex === 1 ? "convexo" : "convexos"}</span></span>
      <span class="stat-item"><span class="stat-val is-nonconvex">${totalNonConvex}</span><span class="stat-lbl">${totalNonConvex === 1 ? "não convexo" : "não convexos"}</span></span>
    `;

    const segKeys = ["all", "johnson", "elementares", "prismas", "antiprismas", "arquimedianos", "platonicos"];
    for (const key of segKeys) {
      const el = $(`#seg-count-${key}`);
      if (el) el.textContent = String(solids.filter((s) => matchesSegment(s, key)).length);
    }
  }

  async function loadLocalSystemStatus() {
    if (state.mode !== "local") return;
    try {
      state.systemStatus = await fetchJson("/api/system/status");
      const pushBtn = $("#btn-push-github");
      if (state.systemStatus.github_configured) pushBtn.classList.remove("hidden");
      else pushBtn.classList.add("hidden");
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
      const dt = fmtDateShort(state.catalog?.generated_at);
      txt.textContent = dt !== "—" ? `Atualizado ${dt}` : "Catálogo público";
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
          showToast(`Novo mínimo global absorvido: <strong>${esc(solids.join(", "))}</strong>`, "success", 4200);
        } else if (discarded.length > 0) {
          showToast(`Duplicata isométrica ignorada: <strong>${esc(discarded.join(", "))}</strong>`, "info", 3400);
        } else if (info.pulled_count > 0) {
          showToast(`Catálogo atualizado com <strong>${info.pulled_count}</strong> novo(s) mínimo(s) da equipe`, "success", 4200);
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
          state.lastRenderSig = "";
          updateHeaderStatsAndCounts();
          updateStatusPill();
          renderCatalog();
          showToast(`Catálogo público atualizado · <strong>${nextTotal}</strong> mínimos globais`, "success", 3600);
        }
      } catch {
        // ignora falhas pontuais de rede
      }
    }, intervalMs);
  }

  // ==========================================================================
  // RENDERIZAÇÃO DO CATÁLOGO UNIFICADO
  // ==========================================================================
  function hydrateLoadedImages(container) {
    $$("img[data-atlas-img]", container).forEach((img) => {
      if (img.complete && img.naturalWidth > 0) {
        img.classList.add("is-loaded");
        const ph = img.previousElementSibling;
        if (ph && ph.classList.contains("photo-loading")) ph.style.display = "none";
      }
    });
  }

  function renderCatalog() {
    if (!state.catalog) return;
    const sig = `${state.catalogVersion}|${state.segment}|${state.search}|${state.statusFilter}|${state.sort}|${state.view}|${state.galleryShowDiagonals}`;
    if (state.lastRenderSig === sig) return;
    state.lastRenderSig = sig;

    const solids = state.catalog.solids || [];
    const q = state.search.trim().toLowerCase();

    let list = solids.filter((s) => {
      if (!matchesSegment(s, state.segment)) return false;
      if (state.statusFilter === "solved" && !s.has_global) return false;
      if (state.statusFilter === "convex" && !s.has_convex_global) return false;
      if (state.statusFilter === "nonconvex" && !s.has_nonconvex_global) return false;
      if (state.statusFilter === "unsolved" && s.has_global) return false;
      if (state.statusFilter === "active" && !s.has_topology) return false;
      if (state.statusFilter === "pending" && s.has_topology) return false;

      if (q) {
        return (
          s.id.toLowerCase().includes(q) ||
          s.display_code.toLowerCase().includes(q) ||
          s.name_pt.toLowerCase().includes(q) ||
          s.name_en.toLowerCase().includes(q) ||
          (s.family || "").toLowerCase().includes(q)
        );
      }
      return true;
    });

    if (state.sort === "vertices") {
      list = [...list].sort((a, b) => (a.topology.vertices || 999) - (b.topology.vertices || 999) || a.sort_key - b.sort_key);
    } else if (state.sort === "minima") {
      list = [...list].sort((a, b) => (b.global_count || 0) - (a.global_count || 0) || (b.nonconvex_count || 0) - (a.nonconvex_count || 0) || a.sort_key - b.sort_key);
    }

    $("#segment-def-text").textContent = getSegmentDefinition(state.segment);
    const solvedCount = list.filter((s) => s.has_global).length;
    const totalMinima = list.reduce((acc, s) => acc + (s.global_count || 0), 0);
    $("#catalog-meta-bar").textContent = `${list.length} sólidos · ${solvedCount} com mínimo global (${totalMinima} soluções)`;

    const gridEl = $("#cat-grid");
    const tableWrap = $("#cat-table-wrap");

    if (list.length === 0) {
      gridEl.classList.remove("hidden");
      tableWrap.classList.add("hidden");
      gridEl.innerHTML = `<div class="empty-state">Nenhum sólido encontrado para os filtros selecionados.</div>`;
      return;
    }

    if (state.view === "grid") {
      gridEl.classList.remove("hidden");
      tableWrap.classList.add("hidden");
      renderUnifiedGrid(gridEl, list);
      hydrateLoadedImages(gridEl);
    } else {
      gridEl.classList.add("hidden");
      tableWrap.classList.remove("hidden");
      tableWrap.innerHTML = buildCatalogTableHtml(list);
    }
  }

  function renderUnifiedGrid(container, list) {
    const solved = list.filter((s) => Boolean(s.has_global && s.primary_global));
    const unsolved = list.filter((s) => !Boolean(s.has_global && s.primary_global));

    if (solved.length > 0 && unsolved.length > 0) {
      container.innerHTML = `
        <div class="atlas-grid">${solved.map((s, idx) => buildSolidCardHtml(s, idx)).join("")}</div>
        <div class="atlas-section-divider">Demais sólidos do segmento · ${unsolved.length}</div>
        <div class="atlas-grid atlas-grid-index">${unsolved.map((s, idx) => buildSolidCardHtml(s, idx + solved.length)).join("")}</div>
      `;
    } else if (solved.length > 0) {
      container.innerHTML = `<div class="atlas-grid">${solved.map((s, idx) => buildSolidCardHtml(s, idx)).join("")}</div>`;
    } else {
      container.innerHTML = `<div class="atlas-grid atlas-grid-index">${unsolved.map((s, idx) => buildSolidCardHtml(s, idx)).join("")}</div>`;
    }
  }

  function buildSolidCardHtml(solid, index = 99) {
    const sol = solid.primary_global || null;
    const hasPhoto = Boolean(solid.has_global && sol);
    const hasNonConvex = Boolean(solid.has_nonconvex_global);

    const cardClasses = [
      "solid-card",
      hasPhoto ? "is-solved" : "is-unsolved",
      hasNonConvex ? "has-nonconvex" : "",
      !solid.has_topology ? "is-pending" : "",
    ]
      .filter(Boolean)
      .join(" ");

    let photoHtml = "";
    if (hasPhoto) {
      const imgUrl = getRenderUrl(solid, sol, "iso", state.galleryShowDiagonals, true);
      const isAboveFold = index < 8;

      const leftBadge = sol.is_convex
        ? `<span class="badge badge-convex photo-badge-tl">Convexo</span>`
        : `<span class="badge badge-nonconvex photo-badge-tl">Não convexo</span>`;

      let rightBadge = "";
      if (solid.convex_count > 0 && solid.nonconvex_count > 0) {
        rightBadge = `<span class="badge badge-nonconvex photo-badge-tr">+${solid.nonconvex_count} não conv.</span>`;
      } else if (solid.global_count > 1) {
        rightBadge = `<span class="badge ${sol.is_convex ? "badge-ime" : "badge-nonconvex"} photo-badge-tr">${solid.global_count} globais</span>`;
      }

      photoHtml = `
        <div class="photo-stage">
          ${leftBadge}
          ${rightBadge}
          <div class="photo-loading"><div class="photo-placeholder-mark"></div></div>
          <img
            data-atlas-img="1"
            src="${esc(imgUrl)}"
            alt="${esc(solid.display_code)} — ${esc(solid.name_pt)}"
            width="360"
            height="360"
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
      ? `<span class="solid-code" style="color:var(--ink-muted);font-weight:500;">${esc(solid.family)}</span>`
      : `<span class="solid-code">${esc(solid.display_code)}</span>`;

    let topRight = "";
    if (hasPhoto) {
      if (solid.global_count > 1) {
        topRight = `<span class="badge badge-ime">${solid.global_count} globais</span>`;
      } else {
        topRight = `<span class="solid-energy">${fmtSci(sol.fval, 1)}</span>`;
      }
    } else if (solid.is_elementary && state.segment !== "elementares") {
      topRight = `<span class="badge badge-elem">Elementar</span>`;
    }

    const subTags = [];
    if (hasPhoto && solid.is_elementary && state.segment !== "elementares") {
      subTags.push(`<span class="badge badge-elem">Elementar</span>`);
    }
    if (hasPhoto && state.segment === "all" && !redundantCode) {
      subTags.push(`<span class="badge badge-neutral">${esc(solid.family === "Sólidos de Johnson" ? "Johnson" : solid.family)}</span>`);
    }

    const subTagsHtml = subTags.length ? `<div class="solid-sub-tags">${subTags.join("")}</div>` : "";
    const footRight = solid.has_topology && topo.face_signature ? `<span>${esc(topo.face_signature)}</span>` : "";

    return `
      <article class="${cardClasses}" data-open-solid="${esc(solid.id)}" tabindex="0" role="button" aria-label="Abrir ficha de ${esc(solid.display_code)} — ${esc(solid.name_pt)}">
        ${photoHtml}
        <div class="solid-card-body">
          <div class="solid-card-top">
            ${codeHtml}
            <div class="solid-top-tags">${topRight}</div>
          </div>
          <div class="solid-name-pt">${esc(solid.name_pt)}</div>
          ${subTagsHtml}
          <div class="solid-foot-row">
            <span>${topoShort}</span>
            ${footRight}
          </div>
        </div>
      </article>
    `;
  }

  function buildCatalogTableHtml(list) {
    const rows = list
      .map((s) => {
        const sol = s.primary_global || null;
        const hasPhoto = Boolean(s.has_global && sol);
        const thumb = hasPhoto
          ? `<img class="table-thumb" src="${esc(getRenderUrl(s, sol, "iso", state.galleryShowDiagonals, true))}" alt="${esc(s.display_code)}" loading="lazy" width="42" height="42" />`
          : `<span class="mono muted-xs">—</span>`;

        const badges = [];
        if (s.convex_count > 0) badges.push(`<span class="badge badge-convex">${s.convex_count} convexo${s.convex_count > 1 ? "s" : ""}</span>`);
        if (s.nonconvex_count > 0) badges.push(`<span class="badge badge-nonconvex">${s.nonconvex_count} não conv.</span>`);
        if (!badges.length) {
          badges.push(`<span class="muted-xs">${s.has_topology ? "aguardando" : "pendente"}</span>`);
        }

        const segTag = s.is_elementary
          ? `<span class="badge badge-elem" style="margin-left:5px;">Elem.</span>`
          : "";

        return `
          <tr class="clickable-row" data-open-solid="${esc(s.id)}">
            <td>${thumb}</td>
            <td class="mono" style="font-weight:600;color:var(--ime-navy);">${esc(s.display_code)}</td>
            <td style="font-family:var(--font-serif);font-size:0.98rem;">${esc(s.name_pt)}</td>
            <td class="muted-xs">${esc(s.family === "Sólidos de Johnson" ? "Johnson" : s.family)}${segTag}</td>
            <td class="mono muted-xs">${s.has_topology ? `${s.topology.vertices} · ${s.topology.faces} · ${s.topology.edges}` : "—"}</td>
            <td><div style="display:flex;gap:5px;flex-wrap:wrap;">${badges.join("")}</div></td>
            <td class="mono muted-xs">${hasPhoto ? fmtSci(sol.fval, 1) : "—"}</td>
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
            <th>Segmento</th>
            <th>V · F · E</th>
            <th>Mínimos Globais</th>
            <th>F(x)</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  // Prefetch suave do dossiê ao passar o mouse (abertura instantânea < 5ms)
  function prefetchSolidDetail(solidId) {
    if (!solidId || state.detailCache.has(solidId) || state.prefetchInFlight.has(solidId)) return;
    const entry = (state.catalog?.solids || []).find((s) => s.id === solidId);
    if (!entry || !entry.has_global) return;
    const url = state.mode === "static" ? entry.detail_url : `/api/solid/${encodeURIComponent(solidId)}`;
    if (!url) return;

    state.prefetchInFlight.add(solidId);
    fetchJson(url)
      .then((detail) => {
        state.detailCache.set(solidId, detail);
      })
      .catch(() => {})
      .finally(() => {
        state.prefetchInFlight.delete(solidId);
      });
  }

  function bindDelegatedCatalogClicks() {
    ["#cat-grid", "#cat-table-wrap"].forEach((sel) => {
      const container = $(sel);
      if (!container) return;

      container.addEventListener("click", (e) => {
        const card = e.target.closest("[data-open-solid]");
        if (card) openSolidModal(card.dataset.openSolid);
      });

      container.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          const card = e.target.closest("[data-open-solid]");
          if (card) {
            e.preventDefault();
            openSolidModal(card.dataset.openSolid);
          }
        }
      });

      container.addEventListener("pointerenter", (e) => {
        const card = e.target.closest("[data-open-solid]");
        if (card) prefetchSolidDetail(card.dataset.openSolid);
      }, true);
    });
  }

  // ==========================================================================
  // MODAL FICHA UNIFICADA DO SÓLIDO
  // ==========================================================================
  async function openSolidModal(solidId, preferredSolId = null) {
    const modal = $("#solid-modal");
    const body = $("#modal-body");
    const entry = (state.catalog?.solids || []).find((s) => s.id === solidId);

    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
    $("#modal-eyebrow").textContent = entry?.display_code || solidId;
    $("#modal-title").textContent = entry?.name_pt || "…";
    $("#modal-sub-en").textContent = entry?.name_en || "";
    $("#modal-meta-row").innerHTML = "";

    // Caso o sólido ainda não possua mínimo global, exibe ficha topológica limpa imediatamente
    if (entry && !entry.has_global) {
      state.modalDetail = {
        ...entry,
        convex_solutions: [],
        nonconvex_solutions: [],
        global_solutions: [],
      };
      renderModalContent();
      return;
    }

    try {
      let detail = state.detailCache.get(solidId);
      if (!detail) {
        body.innerHTML = `<div style="padding:44px;text-align:center;"><div class="spinner" style="margin:0 auto;"></div></div>`;
        if (state.mode === "static") {
          if (!entry || !entry.detail_url) throw new Error("Ficha do sólido não encontrada.");
          const sep = entry.detail_url.includes("?") ? "&" : "?";
          detail = await fetchJson(`${entry.detail_url}${sep}t=${Date.now()}`);
        } else {
          detail = await fetchJson(`/api/solid/${encodeURIComponent(solidId)}`);
        }
        state.detailCache.set(solidId, detail);
      }

      state.modalDetail = detail;
      state.modalClassFilter = "all";
      state.modalCompareMode = false;
      state.modalMode = "photo";
      state.modalPreset = "iso";
      state.modalDataTab = "vertices";
      state.modalShowDiagonals = state.galleryShowDiagonals;
      state.modalShowVertices3D = false;

      const allSols = detail.global_solutions || [];
      if (preferredSolId && allSols.some((s) => s.solution_id === preferredSolId)) {
        state.modalSolId = preferredSolId;
      } else {
        state.modalSolId = allSols[0]?.solution_id || null;
      }
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

  function getFilteredModalSolutions(detail) {
    const conv = detail.convex_solutions || [];
    const nconv = detail.nonconvex_solutions || [];
    if (state.modalClassFilter === "convex") return conv;
    if (state.modalClassFilter === "nonconvex") return nconv;
    return detail.global_solutions || [...conv, ...nconv];
  }

  function formatRunSummary(sol) {
    const ex = sol?.execucao || null;
    if (!ex) {
      return {
        hasRunData: false,
        metodo: "Não registrado",
        amostra: "Não registrado",
        tentativa: "Não registrado",
        convergencia: fmtDateShort(sol?.timestamp),
        hasInitialCoords: false,
        shortHint: fmtDateShort(sol?.timestamp),
      };
    }

    let metodoTxt = ex.metodo_inicial || "Não registrado";
    if (ex.lado_L && metodoTxt.toLowerCase().includes("hipercubo")) {
      metodoTxt = `${metodoTxt} · L = ${Number(ex.lado_L).toFixed(3)}`;
    }
    const amostraTxt =
      ex.tamanho_amostra === null || ex.tamanho_amostra === undefined
        ? ex.tentativa
          ? "Ilimitada"
          : "Não registrado"
        : `${fmtInt(ex.tamanho_amostra)} amostras`;
    const tentativaTxt =
      ex.tentativa !== null && ex.tentativa !== undefined
        ? `Tentativa #${fmtInt(ex.tentativa)}`
        : "Não registrado";

    const convParts = [];
    if (ex.iteracoes_otimizador) convParts.push(`${fmtInt(ex.iteracoes_otimizador)} it.`);
    if (ex.tempo_segundos !== null && ex.tempo_segundos !== undefined) convParts.push(`${Number(ex.tempo_segundos).toFixed(2)}s`);
    const convTxt = convParts.length ? convParts.join(" · ") : fmtDateShort(sol?.timestamp);

    const shortHint = ex.tentativa ? `Tent. #${ex.tentativa}` : fmtDateShort(sol?.timestamp);

    return {
      hasRunData: true,
      metodo: metodoTxt,
      amostra: amostraTxt,
      tentativa: tentativaTxt,
      convergencia: convTxt,
      hasInitialCoords: Boolean(ex.vc_inicial && ex.vc_inicial.length),
      shortHint,
    };
  }

  function renderModalContent() {
    destroyViewer3D();
    const detail = state.modalDetail;
    if (!detail) return;

    const topo = detail.topology || {};
    $("#modal-eyebrow").textContent = detail.display_code;
    $("#modal-title").textContent = detail.name_pt;
    $("#modal-sub-en").textContent = detail.name_en;

    const headerBadges = [
      `<span class="badge badge-ime">${esc(detail.family)}</span>`,
      detail.is_elementary ? `<span class="badge badge-elem">Elementar · Zalgaller</span>` : "",
      detail.has_topology
        ? `<span class="mono">V = ${topo.vertices} · F = ${topo.faces} · E = ${topo.edges} · χ = ${topo.euler ?? "—"}</span>`
        : `<span class="mono">Topologia pendente</span>`,
      detail.has_topology && topo.face_signature ? `<span class="mono">${esc(topo.face_signature)}</span>` : "",
    ]
      .filter(Boolean)
      .join("");
    $("#modal-meta-row").innerHTML = headerBadges;

    const allSols = detail.global_solutions || [];
    const convSols = detail.convex_solutions || [];
    const nconvSols = detail.nonconvex_solutions || [];

    // Ficha limpa para sólido sem mínimo global ainda
    if (allSols.length === 0) {
      $("#modal-body").innerHTML = `
        <div class="unsolved-ficha">
          <div class="unsolved-banner">
            ${
              detail.has_topology
                ? `<strong>Topologia ativa</strong> — Nenhum mínimo global sem autointerseção de faces foi catalogado ainda para <strong>${esc(detail.display_code)}</strong>.`
                : `<strong>Topologia pendente</strong> — A definição combinatória das faces de <strong>${esc(detail.display_code)}</strong> ainda não foi inserida em <code>faces.txt</code>.`
            }
          </div>
          <div class="tech-grid">
            <div class="metric-cell">
              <div class="metric-cell-label">Vértices · Faces · Arestas</div>
              <div class="metric-cell-val">${detail.has_topology ? `${topo.vertices} · ${topo.faces} · ${topo.edges}` : topo.vertices ? `${topo.vertices} · — · —` : "—"}</div>
            </div>
            <div class="metric-cell">
              <div class="metric-cell-label">Composição de Faces</div>
              <div class="metric-cell-val" style="font-family:var(--font-sans);font-size:0.8rem;">${esc(topo.face_description || topo.face_signature || "Pendente")}</div>
            </div>
            <div class="metric-cell">
              <div class="metric-cell-label">Classificação</div>
              <div class="metric-cell-val" style="font-family:var(--font-sans);font-size:0.8rem;">${esc(detail.family)}${detail.is_elementary ? " · Elementar" : ""}</div>
            </div>
            <div class="metric-cell">
              <div class="metric-cell-label">Mínimos Globais (sem autointerseção)</div>
              <div class="metric-cell-val">0 convexos · 0 não convexos</div>
            </div>
          </div>
        </div>
      `;
      return;
    }

    const filteredSols = getFilteredModalSolutions(detail);
    let activeSol = filteredSols.find((s) => s.solution_id === state.modalSolId) || filteredSols[0] || allSols[0];
    state.modalSolId = activeSol.solution_id;

    // 1. Barra de separação Convexo vs Não Convexo (sem autointerseção) + Comparação
    const classBarHtml = `
      <div class="ficha-class-bar">
        <div class="ficha-filter-pills" role="tablist" aria-label="Separação de mínimos globais">
          <button type="button" class="pill ${state.modalClassFilter === "all" ? "active" : ""}" data-class-filter="all">
            Todos os Globais (${allSols.length})
          </button>
          <button type="button" class="pill pill-convex ${state.modalClassFilter === "convex" ? "active" : ""}" data-class-filter="convex" ${convSols.length ? "" : "disabled"}>
            Globais Convexos (${convSols.length})
          </button>
          <button type="button" class="pill pill-nonconvex ${state.modalClassFilter === "nonconvex" ? "active" : ""}" data-class-filter="nonconvex" ${nconvSols.length ? "" : "disabled"}>
            Globais Não Convexos · sem autointerseção (${nconvSols.length})
          </button>
        </div>
        ${
          filteredSols.length > 1
            ? `<button type="button" class="btn btn-sm ${state.modalCompareMode ? "btn-primary" : "btn-secondary"}" id="btn-toggle-compare">
                ${state.modalCompareMode ? "Voltar ao inspetor" : `Comparar lado a lado (${filteredSols.length})`}
               </button>`
            : ""
        }
      </div>
    `;

    // 2. Modo Comparação Lado a Lado (útil para reuniões com Prof. Colli, ex.: J86 convexo vs não convexo)
    if (state.modalCompareMode && filteredSols.length > 1) {
      const compareCards = filteredSols
        .map((s, idx) => {
          const c = s.convexity || {};
          const run = formatRunSummary(s);
          const img = getRenderUrl(detail, s, "iso", state.modalShowDiagonals, false);
          return `
            <div class="compare-card ${s.is_convex ? "" : "is-nonconvex"}">
              <div class="compare-card-head">
                <span class="mono" style="font-size:0.78rem;font-weight:600;">Mínimo #${idx + 1}</span>
                <span class="badge ${s.is_convex ? "badge-convex" : "badge-nonconvex"}">
                  ${s.is_convex ? "Convexo" : "Não convexo · sem autointerseção"}
                </span>
              </div>
              <div class="compare-stage">
                <img src="${esc(img)}" alt="${esc(detail.display_code)} #${idx + 1}" loading="lazy" />
              </div>
              <div class="compare-body">
                <div class="tech-grid">
                  <div class="metric-cell">
                    <div class="metric-cell-label">Energia F(x)</div>
                    <div class="metric-cell-val">${fmtSci(s.fval, 2)}</div>
                  </div>
                  <div class="metric-cell">
                    <div class="metric-cell-label">Volume / V_CH</div>
                    <div class="metric-cell-val">${Number(c.volume_ratio ?? 1).toFixed(4)}</div>
                  </div>
                  <div class="metric-cell">
                    <div class="metric-cell-label">Diedrais</div>
                    <div class="metric-cell-val">${Number(c.min_dihedral_deg ?? 0).toFixed(1)}° – ${Number(c.max_dihedral_deg ?? 0).toFixed(1)}°</div>
                  </div>
                  <div class="metric-cell">
                    <div class="metric-cell-label">Tentativa / Amostra</div>
                    <div class="metric-cell-val ${run.hasRunData ? "" : "is-unrecorded"}">${esc(run.tentativa)}</div>
                  </div>
                </div>
                <div style="display:flex;gap:6px;">
                  <button type="button" class="btn btn-secondary btn-sm" style="flex:1;" data-inspect-sol="${esc(s.solution_id)}" data-inspect-mode="photo">
                    Abrir ficha completa
                  </button>
                  <button type="button" class="btn btn-primary btn-sm" data-inspect-sol="${esc(s.solution_id)}" data-inspect-mode="3d">
                    3D
                  </button>
                </div>
              </div>
            </div>
          `;
        })
        .join("");

      $("#modal-body").innerHTML = `
        ${classBarHtml}
        <div class="compare-grid">${compareCards}</div>
      `;
      bindModalCommonControls(detail, activeSol);
      $$("[data-inspect-sol]", $("#modal-body")).forEach((btn) => {
        btn.addEventListener("click", () => {
          state.modalSolId = btn.dataset.inspectSol;
          state.modalMode = btn.dataset.inspectMode || "photo";
          state.modalCompareMode = false;
          renderModalContent();
        });
      });
      return;
    }

    // 3. Faixa Visual de TODOS os Mínimos Globais do Sólido (sempre renderiza construção visual de cada mínimo)
    const visualStripHtml = `
      <div class="minima-visual-strip" aria-label="Construções visuais dos mínimos globais">
        ${filteredSols
          .map((s, idx) => {
            const isSel = s.solution_id === activeSol.solution_id;
            const c = s.convexity || {};
            const run = formatRunSummary(s);
            const thumbUrl = getRenderUrl(detail, s, "iso", state.modalShowDiagonals, true);
            return `
              <button type="button" class="min-thumb-card ${isSel ? "is-selected" : ""} ${s.is_convex ? "" : "is-nonconvex"}" data-select-sol="${esc(s.solution_id)}">
                <img class="min-thumb-img" src="${esc(thumbUrl)}" alt="${esc(detail.display_code)} mínimo #${idx + 1}" width="58" height="58" />
                <div class="min-thumb-info">
                  <div class="min-thumb-title">
                    <span class="mono">#${idx + 1}</span>
                    <span class="badge ${s.is_convex ? "badge-convex" : "badge-nonconvex"}">${s.is_convex ? "Convexo" : "Não convexo"}</span>
                  </div>
                  <div class="min-thumb-meta">F(x) ${fmtSci(s.fval, 1)} · θ≤${Number(c.max_dihedral_deg ?? 0).toFixed(1)}°</div>
                  <div class="min-thumb-meta">V/V_CH ${Number(c.volume_ratio ?? 1).toFixed(3)} · ${esc(run.shortHint)}</div>
                </div>
              </button>
            `;
          })
          .join("")}
      </div>
    `;

    // 4. Inspetor Principal 2 Colunas do Mínimo Selecionado
    const c = activeSol.convexity || {};
    const h = activeSol.hessian;
    const run = formatRunSummary(activeSol);
    const siCount = activeSol.self_intersection?.intersection_count ?? 0;

    const proofHtml = activeSol.is_convex
      ? `<div class="proof-box">
           <span class="proof-title">✓ Global Convexo · Sem autointerseção de faces</span>
           <span class="mono" style="margin-left:8px;color:var(--ink-secondary);">V/V_CH = ${Number(c.volume_ratio ?? 1).toFixed(5)} · θ ∈ [${Number(c.min_dihedral_deg ?? 0).toFixed(1)}°, ${Number(c.max_dihedral_deg ?? 0).toFixed(1)}°]</span>
         </div>`
      : `<div class="proof-box is-nonconvex">
           <div class="proof-title">◆ Global Não Convexo · Sem autointerseção de faces</div>
           <ul class="proof-reasons">${(c.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
         </div>`;

    const cameraPresets = [
      { key: "iso", label: "Iso" },
      { key: "front", label: "Frontal" },
      { key: "top", label: "Topo" },
      { key: "alt", label: "Alt" },
    ];

    const diagCount = countFaceDiagonals(activeSol.faces);
    const hasDiags = diagCount > 0;
    const diagActive = hasDiags && state.modalShowDiagonals;
    const diagLabel = hasDiags ? `Diagonais (${diagCount}): ${diagActive ? "On" : "Off"}` : "Diagonais (0)";

    const imgUrl = getRenderUrl(detail, activeSol, state.modalPreset, diagActive, false);
    const stageContent =
      state.modalMode === "photo"
        ? `<img id="modal-scad-img" src="${esc(imgUrl)}" alt="${esc(detail.display_code)}" />`
        : `<canvas id="modal-3d-canvas" class="stage-canvas"></canvas>`;

    const cameraBar =
      state.modalMode === "photo"
        ? `<div class="camera-bar">
            <button type="button" class="btn-tiny ${diagActive ? "is-active" : ""}" id="btn-toggle-diagonals-scad" ${hasDiags ? "" : "disabled"} title="Alternar diagonais reais no PythonSCAD">${diagLabel}</button>
            <div class="camera-btn-group">
              ${cameraPresets
                .map(
                  (p) =>
                    `<button type="button" class="btn-tiny ${p.key === state.modalPreset ? "is-active" : ""}" data-preset="${p.key}">${p.label}</button>`
                )
                .join("")}
            </div>
          </div>`
        : `<div class="camera-bar">
            <div class="camera-btn-group">
              <button type="button" class="btn-tiny ${diagActive ? "is-active" : ""}" id="btn-toggle-diagonals-3d" ${hasDiags ? "" : "disabled"}>${diagLabel}</button>
              <button type="button" class="btn-tiny ${state.modalShowVertices3D ? "is-active" : ""}" id="btn-toggle-verts-3d">Vértices</button>
            </div>
            <div class="camera-btn-group">
              <button type="button" class="btn-tiny" id="btn-zoom-in-3d" title="Aproximar">+</button>
              <button type="button" class="btn-tiny" id="btn-zoom-out-3d" title="Afastar">−</button>
              <button type="button" class="btn-tiny" id="btn-spin-3d">Girar</button>
              <button type="button" class="btn-tiny" id="btn-reset-3d">Reset</button>
            </div>
          </div>`;

    const dlScad = getDownloadUrl(detail, activeSol, "scad");
    const dlJson = getDownloadUrl(detail, activeSol, "json");
    const dlTxt = getDownloadUrl(detail, activeSol, "txt");
    const dlPng = getDownloadUrl(detail, activeSol, "png", state.modalPreset, diagActive);

    const initTabBadge = run.hasInitialCoords ? ` (${activeSol.execucao.vc_inicial.length})` : "";

    $("#modal-body").innerHTML = `
      ${classBarHtml}
      ${visualStripHtml}
      <div class="dossier-grid">
        <div>
          <div class="stage-card">
            <div class="stage-toolbar">
              <div class="view-toggle">
                <button type="button" class="view-btn ${state.modalMode === "photo" ? "active" : ""}" data-stage-mode="photo">PythonSCAD</button>
                <button type="button" class="view-btn ${state.modalMode === "3d" ? "active" : ""}" data-stage-mode="3d">3D Interativo</button>
              </div>
              <span class="badge ${activeSol.is_convex ? "badge-convex" : "badge-nonconvex"}">${activeSol.is_convex ? "Convexo" : "Não convexo"}</span>
            </div>
            <div class="stage-viewport">${stageContent}</div>
            ${cameraBar}
          </div>

          <div class="export-bar">
            ${state.mode === "local" && activeSol.has_scad ? `<button type="button" class="btn btn-primary btn-sm" id="btn-open-scad-gui">PythonSCAD ↗</button>` : ""}
            ${activeSol.has_scad && dlScad ? `<a class="btn btn-secondary btn-sm" href="${esc(dlScad)}" download>.py</a>` : ""}
            ${activeSol.has_json && dlJson ? `<a class="btn btn-secondary btn-sm" href="${esc(dlJson)}" download>.json</a>` : ""}
            ${activeSol.has_txt && dlTxt ? `<a class="btn btn-secondary btn-sm" href="${esc(dlTxt)}" download>.txt</a>` : ""}
            ${
              dlPng
                ? state.mode === "static"
                  ? `<button type="button" class="btn btn-secondary btn-sm" id="btn-download-png-static">.png</button>`
                  : `<a class="btn btn-secondary btn-sm" id="btn-download-png" href="${esc(dlPng)}" download>.png</a>`
                : ""
            }
            ${run.hasInitialCoords ? `<button type="button" class="btn btn-secondary btn-sm" id="btn-copy-ci-quick">Copiar x₀</button>` : ""}
          </div>
        </div>

        <div>
          <div class="dossier-section">${proofHtml}</div>

          <div class="dossier-section">
            <div class="section-label">
              <span>Informações Técnicas da Busca</span>
              ${run.hasInitialCoords ? `<button type="button" class="btn-tiny" id="btn-jump-ci">Ver x₀</button>` : ""}
            </div>
            <div class="tech-grid">
              <div class="metric-cell ${run.hasRunData ? "is-highlight" : ""}">
                <div class="metric-cell-label">Condição Inicial</div>
                <div class="metric-cell-val ${run.hasRunData ? "" : "is-unrecorded"}">${esc(run.metodo)}</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Tamanho da Amostra</div>
                <div class="metric-cell-val ${run.hasRunData ? "" : "is-unrecorded"}">${esc(run.amostra)}</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Tentativas Necessárias</div>
                <div class="metric-cell-val ${run.hasRunData ? "" : "is-unrecorded"}">${esc(run.tentativa)}</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">${run.hasRunData ? "Convergência" : "Data do Registro"}</div>
                <div class="metric-cell-val">${esc(run.convergencia)}</div>
              </div>
            </div>
          </div>

          <div class="dossier-section">
            <div class="section-label"><span>Métricas Geométricas</span></div>
            <div class="tech-grid">
              <div class="metric-cell">
                <div class="metric-cell-label">Energia F(x)</div>
                <div class="metric-cell-val">${fmtSci(activeSol.fval, 4)}</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Volume / V_CH</div>
                <div class="metric-cell-val">${Number(c.volume ?? 0).toFixed(4)} / ${Number(c.hull_volume ?? 0).toFixed(4)}</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Diedrais Internos</div>
                <div class="metric-cell-val">${Number(c.min_dihedral_deg ?? 0).toFixed(2)}° – ${Number(c.max_dihedral_deg ?? 0).toFixed(2)}°</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Reflexas / Interiores</div>
                <div class="metric-cell-val">${c.reflex_edges ?? 0} / ${c.interior_vertices ?? 0}</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Autointerseção de Faces</div>
                <div class="metric-cell-val" style="color:var(--convex);">${siCount} ocorrências ✓</div>
              </div>
              <div class="metric-cell">
                <div class="metric-cell-label">Hessiana λ mín (não ríg.)</div>
                <div class="metric-cell-val">${h ? fmtSci(h.min_non_rigid, 3) : "—"}</div>
              </div>
            </div>
          </div>

          <div class="dossier-section" style="margin-bottom:0;">
            <div class="data-tab-header">
              <div class="ficha-filter-pills">
                <button type="button" class="pill ${state.modalDataTab === "vertices" ? "active" : ""}" data-data-tab="vertices">Vértices (${activeSol.vertices.length})</button>
                <button type="button" class="pill ${state.modalDataTab === "initial" ? "active" : ""}" data-data-tab="initial">Condição Inicial${initTabBadge}</button>
                <button type="button" class="pill ${state.modalDataTab === "dihedrals" ? "active" : ""}" data-data-tab="dihedrals">Diedrais (${(c.interior_dihedrals_deg || []).length})</button>
                <button type="button" class="pill ${state.modalDataTab === "distances" ? "active" : ""}" data-data-tab="distances">Distâncias (${(activeSol.distancias || []).length})</button>
                <button type="button" class="pill ${state.modalDataTab === "eigen" ? "active" : ""}" data-data-tab="eigen">Hessiana (${(activeSol.autovalores || []).length})</button>
              </div>
              <button type="button" class="btn-tiny" id="btn-copy-data-pre">Copiar</button>
            </div>
            <pre class="data-pre" id="modal-data-pre">${esc(formatModalDataTab(activeSol, state.modalDataTab))}</pre>
          </div>
        </div>
      </div>
    `;

    bindModalCommonControls(detail, activeSol);

    $$("[data-select-sol]", $("#modal-body")).forEach((btn) => {
      btn.addEventListener("click", () => {
        state.modalSolId = btn.dataset.selectSol;
        renderModalContent();
      });
    });

    $$("[data-stage-mode]", $("#modal-body")).forEach((btn) => {
      btn.addEventListener("click", () => {
        state.modalMode = btn.dataset.stageMode;
        renderModalContent();
      });
    });

    $$("[data-preset]", $("#modal-body")).forEach((btn) => {
      btn.addEventListener("click", () => {
        state.modalPreset = btn.dataset.preset;
        renderModalContent();
      });
    });

    $$("[data-data-tab]", $("#modal-body")).forEach((btn) => {
      btn.addEventListener("click", () => {
        state.modalDataTab = btn.dataset.dataTab;
        $$("[data-data-tab]", $("#modal-body")).forEach((b) => b.classList.toggle("active", b === btn));
        $("#modal-data-pre").textContent = formatModalDataTab(activeSol, state.modalDataTab);
      });
    });

    $("#btn-copy-data-pre")?.addEventListener("click", () => {
      copyText(formatModalDataTab(activeSol, state.modalDataTab), "Dados copiados");
    });

    $("#btn-jump-ci")?.addEventListener("click", () => {
      state.modalDataTab = "initial";
      $$("[data-data-tab]", $("#modal-body")).forEach((b) => b.classList.toggle("active", b.dataset.dataTab === "initial"));
      $("#modal-data-pre").textContent = formatModalDataTab(activeSol, "initial");
      $("#modal-data-pre").scrollIntoView({ behavior: "smooth", block: "nearest" });
    });

    $("#btn-copy-ci-quick")?.addEventListener("click", () => {
      const ci = activeSol.execucao?.vc_inicial;
      if (ci) copyText(`vc_inicial = ${JSON.stringify(ci)}`, "Condição inicial x₀ copiada");
    });

    $("#btn-download-png-static")?.addEventListener("click", () => {
      const curDiag = hasDiags && state.modalShowDiagonals;
      const curUrl = getRenderUrl(detail, activeSol, state.modalPreset, curDiag, false);
      const suf = curDiag ? "" : "_sem_diagonais";
      downloadPngFromImageUrl(curUrl, `${detail.slug || detail.id}_${activeSol.solution_id}_${state.modalPreset}${suf}.png`);
    });

    $("#btn-open-scad-gui")?.addEventListener("click", async () => {
      try {
        const res = await fetchJson("/api/open-pythonscad", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ solid_id: detail.id, solution_id: activeSol.solution_id }),
        });
        showToast(esc(res.message || "Aberto no PythonSCAD"), "success", 2600);
      } catch (err) {
        showToast(`Erro: ${esc(err.message)}`);
      }
    });

    if (state.modalMode === "photo") {
      const scadDiagBtn = $("#btn-toggle-diagonals-scad");
      if (scadDiagBtn && !scadDiagBtn.disabled) {
        scadDiagBtn.addEventListener("click", () => {
          state.modalShowDiagonals = !state.modalShowDiagonals;
          const active = state.modalShowDiagonals;
          scadDiagBtn.textContent = `Diagonais (${diagCount}): ${active ? "On" : "Off"}`;
          scadDiagBtn.classList.toggle("is-active", active);
          const imgEl = $("#modal-scad-img");
          if (imgEl) imgEl.src = getRenderUrl(detail, activeSol, state.modalPreset, active, false);
          const dlPngEl = $("#btn-download-png");
          if (dlPngEl) dlPngEl.href = getDownloadUrl(detail, activeSol, "png", state.modalPreset, active);
        });
      }
    }

    if (state.modalMode === "3d") {
      initViewer3D(
        $("#modal-3d-canvas"),
        activeSol.vertices,
        activeSol.faces,
        !activeSol.is_convex,
        diagActive,
        state.modalShowVertices3D
      );
      const diagBtn = $("#btn-toggle-diagonals-3d");
      if (diagBtn && !diagBtn.disabled) {
        diagBtn.addEventListener("click", () => {
          state.modalShowDiagonals = !state.modalShowDiagonals;
          const active = state.modalShowDiagonals;
          diagBtn.textContent = `Diagonais (${diagCount}): ${active ? "On" : "Off"}`;
          diagBtn.classList.toggle("is-active", active);
          state.viewer3D?.setShowDiagonals(active);
        });
      }
      const vertsBtn = $("#btn-toggle-verts-3d");
      vertsBtn?.addEventListener("click", () => {
        state.modalShowVertices3D = !state.modalShowVertices3D;
        vertsBtn.classList.toggle("is-active", state.modalShowVertices3D);
        state.viewer3D?.setShowVertices(state.modalShowVertices3D);
      });
      $("#btn-zoom-in-3d")?.addEventListener("click", () => state.viewer3D?.zoomBy(1.16));
      $("#btn-zoom-out-3d")?.addEventListener("click", () => state.viewer3D?.zoomBy(0.86));
      $("#btn-spin-3d")?.addEventListener("click", (e) => {
        const spinning = state.viewer3D?.toggleSpin();
        e.currentTarget.classList.toggle("is-active", Boolean(spinning));
      });
      $("#btn-reset-3d")?.addEventListener("click", () => state.viewer3D?.reset());
    }
  }

  function bindModalCommonControls(detail, activeSol) {
    $$("[data-class-filter]", $("#modal-body")).forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.disabled) return;
        state.modalClassFilter = btn.dataset.classFilter;
        const nextList = getFilteredModalSolutions(detail);
        if (nextList.length && !nextList.some((s) => s.solution_id === state.modalSolId)) {
          state.modalSolId = nextList[0].solution_id;
        }
        if (nextList.length <= 1) state.modalCompareMode = false;
        renderModalContent();
      });
    });

    $("#btn-toggle-compare")?.addEventListener("click", () => {
      state.modalCompareMode = !state.modalCompareMode;
      renderModalContent();
    });
  }

  function formatModalDataTab(sol, tab) {
    if (tab === "vertices") {
      return (sol.vertices || [])
        .map((v, i) => `v[${String(i).padStart(2, "0")}] = (${v[0].toFixed(8)}, ${v[1].toFixed(8)}, ${v[2].toFixed(8)})`)
        .join("\n");
    }
    if (tab === "initial") {
      const ci = sol.execucao?.vc_inicial;
      if (Array.isArray(ci) && ci.length > 0) {
        const header = [
          `# Método: ${sol.execucao.metodo_inicial || "—"}`,
          `# Amostra: ${sol.execucao.tamanho_amostra ?? "Ilimitada"} | Tentativa: #${sol.execucao.tentativa ?? "—"}`,
        ].join("\n");
        const coords = ci
          .map((v, i) => `x0[${String(i).padStart(2, "0")}] = (${Number(v[0]).toFixed(8)}, ${Number(v[1]).toFixed(8)}, ${Number(v[2]).toFixed(8)})`)
          .join("\n");
        return `${header}\n${coords}`;
      }
      return "Condição inicial não registrada nesta execução anterior.\nAs novas execuções de standbyalone2.py gravam automaticamente x₀, método, tamanho da amostra e nº de tentativas.";
    }
    if (tab === "dihedrals") {
      const list = sol.convexity?.interior_dihedrals_deg || sol.angulos_salvos || [];
      return list.map((a, i) => `θ[${String(i + 1).padStart(2, "0")}] = ${Number(a).toFixed(4)}°${Number(a) > 180.5 ? "  ← reflexo (>180°)" : ""}`).join("\n");
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
  // MODAL DE INFORMAÇÕES / SINCRONIZAÇÃO
  // ==========================================================================
  function openSyncModal() {
    const modal = $("#sync-modal");
    const body = $("#sync-modal-body");
    const st = state.systemStatus;
    const isLocal = state.mode === "local";

    const statusLine = isLocal
      ? st?.github_configured
        ? `<div class="proof-box" style="margin-bottom:14px;"><span class="proof-title">✓ GitHub conectado</span> <span class="mono" style="margin-left:6px;">${esc(st.github_repo)}</span></div>`
        : `<div class="metric-cell" style="margin-bottom:14px;"><div class="metric-cell-label">Modo Local</div><div style="font-size:0.82rem;margin-top:3px;">Observando <code>solidos/</code> ao vivo.</div></div>`
      : `<div class="metric-cell is-highlight" style="margin-bottom:14px;"><div class="metric-cell-label">Catálogo Público · GitHub Pages</div><div class="mono" style="font-size:0.8rem;margin-top:3px;">Atualizado automaticamente via GitHub Actions</div></div>`;

    body.innerHTML = `
      ${statusLine}
      <div class="sync-steps">
        <div class="sync-step">
          <div class="sync-step-title">1. Critério de catalogação</div>
          <div>Todo mínimo global <strong>sem autointerseção de faces</strong> (<code>|F(x)| &lt; 10⁻⁶</code>), seja <strong>convexo</strong> ou <strong>não convexo</strong>, integra a ficha unificada do sólido com sua construção visual e dados técnicos.</div>
        </div>
        <div class="sync-step">
          <div class="sync-step-title">2. Execução automática da equipe</div>
          <div>Ao rodar <code>standbyalone2.py</code>, novos mínimos globais inéditos registram condição inicial (<code>x₀</code>), método, tamanho da amostra e tentativa, sendo enviados ao repositório via Cloudflare Worker.</div>
        </div>
        <div class="sync-step">
          <div class="sync-step-title">3. Otimização de desempenho</div>
          <div>Miniaturas WebP leves (~15 KB), carregamento sob demanda das fichas individuais e visualizador 3D nativo em Canvas sem dependências externas.</div>
        </div>
      </div>
    `;
    modal.classList.remove("hidden");
  }

  function closeSyncModal() {
    $("#sync-modal").classList.add("hidden");
  }

  // ==========================================================================
  // VISUALIZADOR 3D INTERATIVO EM CANVAS (MOUSE + TOUCH + VÉRTICES)
  // ==========================================================================
  function countFaceDiagonals(faces) {
    let total = 0;
    for (const f of faces || []) {
      const m = f.length;
      if (m >= 4) total += (m * (m - 3)) / 2;
    }
    return total;
  }

  function destroyViewer3D() {
    if (state.viewer3D) {
      state.viewer3D.destroy();
      state.viewer3D = null;
    }
  }

  function initViewer3D(canvas, rawVertices, faces, isNonConvex, initialShowDiagonals = true, initialShowVertices = false) {
    if (!canvas || !rawVertices?.length || !faces?.length) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    const size = Math.max(280, Math.round(rect.width || 390));
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

    let rotX = -0.52, rotY = 0.62, zoom = 1.0;
    let dragging = false, lastX = 0, lastY = 0, autoSpin = true, rafId = null;
    let showDiagonals = Boolean(initialShowDiagonals);
    let showVertices = Boolean(initialShowVertices);
    const baseRgb = isNonConvex ? [175, 42, 76] : [58, 102, 166];

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
      const projVerts = tv.map(project);

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
        drawFaces.push({
          pts2: f.map((idx) => projVerts[idx]),
          avgZ,
          shade: Math.min(1.22, 0.42 + 0.52 * l1 + 0.16 * l2),
        });
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

        if (showDiagonals && df.pts2.length >= 4) {
          const m = df.pts2.length;
          ctx.beginPath();
          for (let i = 0; i < m; i++) {
            for (let j = i + 2; j < m; j++) {
              if (i === 0 && j === m - 1) continue;
              ctx.moveTo(df.pts2[i][0], df.pts2[i][1]);
              ctx.lineTo(df.pts2[j][0], df.pts2[j][1]);
            }
          }
          ctx.strokeStyle = m >= 8 ? "rgba(255, 255, 255, 0.44)" : "rgba(255, 255, 255, 0.70)";
          ctx.lineWidth = m >= 8 ? 0.75 : 0.95;
          ctx.stroke();
        }

        ctx.beginPath();
        df.pts2.forEach((p, idx) => (idx === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1])));
        ctx.closePath();
        ctx.strokeStyle = "rgba(15, 23, 42, 0.52)";
        ctx.lineWidth = 1.15;
        ctx.lineJoin = "round";
        ctx.stroke();
      }

      if (showVertices) {
        ctx.font = "600 10px 'JetBrains Mono', monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const indexed = projVerts.map((p, idx) => ({ p, idx })).sort((a, b) => a.p[2] - b.p[2]);
        for (const { p, idx } of indexed) {
          const alpha = p[2] < -0.15 ? 0.45 : 0.96;
          ctx.fillStyle = `rgba(15, 23, 42, ${alpha})`;
          ctx.beginPath();
          ctx.arc(p[0], p[1], 7.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = `rgba(255, 255, 255, ${alpha})`;
          ctx.fillText(String(idx), p[0], p[1] + 0.5);
        }
      }
    }

    function scheduleDraw() {
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        if (document.visibilityState === "hidden") return;
        if (autoSpin && !dragging) {
          rotY += 0.0045;
          draw();
          scheduleDraw();
        } else {
          draw();
        }
      });
    }

    const onPointerDown = (e) => {
      dragging = true;
      autoSpin = false;
      lastX = e.clientX;
      lastY = e.clientY;
      canvas.setPointerCapture?.(e.pointerId);
    };
    const onPointerMove = (e) => {
      if (!dragging) return;
      rotY += (e.clientX - lastX) * 0.009;
      rotX += (e.clientY - lastY) * 0.009;
      lastX = e.clientX;
      lastY = e.clientY;
      scheduleDraw();
    };
    const onPointerUp = (e) => {
      dragging = false;
      canvas.releasePointerCapture?.(e.pointerId);
    };
    const onWheel = (e) => {
      e.preventDefault();
      zoom = Math.max(0.55, Math.min(2.2, zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
      scheduleDraw();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible" && autoSpin) scheduleDraw();
    };

    canvas.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    document.addEventListener("visibilitychange", onVisibility);
    scheduleDraw();

    state.viewer3D = {
      reset() { rotX = -0.52; rotY = 0.62; zoom = 1.0; autoSpin = true; scheduleDraw(); },
      zoomBy(factor) { zoom = Math.max(0.55, Math.min(2.2, zoom * factor)); scheduleDraw(); },
      toggleSpin() { autoSpin = !autoSpin; scheduleDraw(); return autoSpin; },
      setShowDiagonals(val) { showDiagonals = Boolean(val); scheduleDraw(); },
      setShowVertices(val) { showVertices = Boolean(val); scheduleDraw(); },
      destroy() {
        autoSpin = false;
        if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
        canvas.removeEventListener("pointerdown", onPointerDown);
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
        canvas.removeEventListener("wheel", onWheel);
        document.removeEventListener("visibilitychange", onVisibility);
      },
    };
  }

  // ==========================================================================
  // EVENTOS E BOOTSTRAP
  // ==========================================================================
  function bindEvents() {
    $$("#segment-tabs .seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.segment = btn.dataset.segment;
        $$("#segment-tabs .seg-btn").forEach((b) => {
          const active = b === btn;
          b.classList.toggle("active", active);
          b.setAttribute("aria-selected", String(active));
        });
        renderCatalog();
      });
    });

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

    const onSearch = debounce((val) => { state.search = val; renderCatalog(); }, 110);
    $("#cat-search").addEventListener("input", (e) => onSearch(e.target.value));
    $("#cat-status-filter").addEventListener("change", (e) => { state.statusFilter = e.target.value; renderCatalog(); });
    $("#cat-sort").addEventListener("change", (e) => { state.sort = e.target.value; renderCatalog(); });

    $("#btn-gallery-diagonals").addEventListener("click", (e) => {
      state.galleryShowDiagonals = !state.galleryShowDiagonals;
      const active = state.galleryShowDiagonals;
      e.currentTarget.textContent = `Diagonais: ${active ? "On" : "Off"}`;
      e.currentTarget.classList.toggle("is-on", active);
      renderCatalog();
    });

    $$(".view-btn[data-view]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.view = btn.dataset.view;
        $$(".view-btn[data-view]").forEach((b) => b.classList.toggle("active", b === btn));
        renderCatalog();
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
