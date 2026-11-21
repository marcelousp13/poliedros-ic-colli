// ==============================================================================
// CLOUDFLARE WORKER — PONTE SEGURA PARA O ATLAS IC COM COLLI
// Recebe mínimos globais validados de standbyalone2.py (Marcelo, Thomas, Colli),
// valida a chave da equipe (TEAM_KEY) e grava apenas em solidos/... no GitHub
// usando commit atômico com retry automático para envios simultâneos.
//
// Variáveis de ambiente / Secrets no Cloudflare:
//   - GITHUB_TOKEN (Secret): Fine-grained PAT com Contents: Read and write
//   - TEAM_KEY     (Secret): Senha simples compartilhada entre a equipe
//   - GITHUB_OWNER (Var)   : "marcelousp13"
//   - GITHUB_REPO  (Var)   : "poliedros-ic-colli"
//   - GITHUB_BRANCH(Var)   : "main"
// ==============================================================================

const ALLOWED_PATH_REGEX =
  /^solidos\/[^\/\\]+\/minimos_globais\/(convexos|nao_convexos)\/sem_autointersecao\/[^\/\\]+\.(json|txt|py)$/;

const MAX_FILES_PER_REQUEST = 30;
const MAX_BASE64_LENGTH = 3 * 1024 * 1024; // ~2.2 MB por arquivo

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, X-Team-Key",
    },
  });
}

function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const enc = new TextEncoder();
  const ab = enc.encode(a);
  const bb = enc.encode(b);
  if (ab.length !== bb.length) return false;
  let diff = 0;
  for (let i = 0; i < ab.length; i++) {
    diff |= ab[i] ^ bb[i];
  }
  return diff === 0;
}

async function ghRequest(method, url, token, payload = null) {
  const headers = {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "User-Agent": "IC-com-Colli-Cloudflare-Worker/1.0",
    "X-GitHub-Api-Version": "2022-11-28",
  };
  const init = { method, headers };
  if (payload !== null) {
    headers["Content-Type"] = "application/json; charset=utf-8";
    init.body = JSON.stringify(payload);
  }
  const resp = await fetch(url, init);
  const text = await resp.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { message: text };
  }
  return { status: resp.status, data };
}

async function pushFilesAtomicGitHub(env, files, commitMessage, maxRetries = 4) {
  const owner = (env.GITHUB_OWNER || "marcelousp13").trim();
  const repo = (env.GITHUB_REPO || "poliedros-ic-colli").trim();
  const branch = (env.GITHUB_BRANCH || "main").trim();
  const token = (env.GITHUB_TOKEN || "").trim();

  if (!token) {
    return { ok: false, status: 500, message: "GITHUB_TOKEN não configurado nos Secrets do Worker." };
  }

  const apiBase = `https://api.github.com/repos/${owner}/${repo}`;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    // 1. Ler HEAD atual do branch
    const refRes = await ghRequest("GET", `${apiBase}/git/ref/heads/${branch}`, token);
    if (refRes.status !== 200) {
      return {
        ok: false,
        status: 502,
        message: `Erro ao ler branch '${branch}' (${refRes.status}): ${refRes.data?.message || ""}`,
      };
    }

    const headSha = refRes.data.object.sha;
    const commitRes = await ghRequest("GET", `${apiBase}/git/commits/${headSha}`, token);
    if (commitRes.status !== 200) {
      return {
        ok: false,
        status: 502,
        message: `Erro ao ler commit ${headSha.slice(0, 7)} (${commitRes.status}).`,
      };
    }
    const baseTreeSha = commitRes.data.tree.sha;

    // 2. Criar blobs em paralelo
    const treeEntries = [];
    for (const f of files) {
      const blobRes = await ghRequest("POST", `${apiBase}/git/blobs`, token, {
        content: f.content_base64,
        encoding: "base64",
      });
      if (blobRes.status !== 200 && blobRes.status !== 201) {
        return {
          ok: false,
          status: 502,
          message: `Erro ao criar blob '${f.path}' (${blobRes.status}): ${blobRes.data?.message || ""}`,
        };
      }
      treeEntries.push({
        path: f.path,
        mode: "100644",
        type: "blob",
        sha: blobRes.data.sha,
      });
    }

    // 3. Criar nova tree
    const treeRes = await ghRequest("POST", `${apiBase}/git/trees`, token, {
      base_tree: baseTreeSha,
      tree: treeEntries,
    });
    if (treeRes.status !== 200 && treeRes.status !== 201) {
      return {
        ok: false,
        status: 502,
        message: `Erro ao montar árvore (${treeRes.status}): ${treeRes.data?.message || ""}`,
      };
    }

    // 4. Criar commit
    const newCommitRes = await ghRequest("POST", `${apiBase}/git/commits`, token, {
      message: commitMessage,
      tree: treeRes.data.sha,
      parents: [headSha],
    });
    if (newCommitRes.status !== 200 && newCommitRes.status !== 201) {
      return {
        ok: false,
        status: 502,
        message: `Erro ao criar commit (${newCommitRes.status}): ${newCommitRes.data?.message || ""}`,
      };
    }

    // 5. Atualizar referência do branch (com retry em caso de push simultâneo)
    const patchRes = await ghRequest("PATCH", `${apiBase}/git/refs/heads/${branch}`, token, {
      sha: newCommitRes.data.sha,
      force: false,
    });
    if (patchRes.status === 200) {
      const shortSha = newCommitRes.data.sha.slice(0, 7);
      return {
        ok: true,
        status: 200,
        commit: shortSha,
        message: `Enviado via Worker para ${owner}/${repo}@${branch} (${shortSha}).`,
      };
    }

    if (patchRes.status === 422 && attempt < maxRetries) {
      await new Promise((r) => setTimeout(r, 800 * attempt));
      continue;
    }

    return {
      ok: false,
      status: 502,
      message: `Erro ao atualizar branch (${patchRes.status}): ${patchRes.data?.message || ""}`,
    };
  }

  return { ok: false, status: 409, message: "Conflito concorrente após múltiplas tentativas." };
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return jsonResponse({ ok: true }, 200);
    }

    const url = new URL(request.url);
    const owner = (env.GITHUB_OWNER || "marcelousp13").trim();
    const repo = (env.GITHUB_REPO || "poliedros-ic-colli").trim();
    const branch = (env.GITHUB_BRANCH || "main").trim();

    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return jsonResponse({
        ok: true,
        service: "poliedros-ic-colli-sync",
        repo: `${owner}/${repo}`,
        branch,
        configured: Boolean(env.GITHUB_TOKEN && env.TEAM_KEY),
      });
    }

    if (request.method === "POST" && url.pathname === "/submit") {
      // 1. Autenticação pela chave da equipe
      const expectedKey = (env.TEAM_KEY || "").trim();
      if (!expectedKey) {
        return jsonResponse({ ok: false, message: "TEAM_KEY não configurada no Worker." }, 500);
      }
      const providedKey = (request.headers.get("X-Team-Key") || "").trim();
      if (!timingSafeEqual(providedKey, expectedKey)) {
        return jsonResponse({ ok: false, message: "Chave da equipe inválida." }, 401);
      }

      // 2. Ler e validar payload
      let body;
      try {
        body = await request.json();
      } catch {
        return jsonResponse({ ok: false, message: "JSON inválido." }, 400);
      }

      const files = Array.isArray(body?.files) ? body.files : [];
      if (files.length === 0) {
        return jsonResponse({ ok: false, message: "Nenhum arquivo informado." }, 400);
      }
      if (files.length > MAX_FILES_PER_REQUEST) {
        return jsonResponse(
          { ok: false, message: `Máximo de ${MAX_FILES_PER_REQUEST} arquivos por envio.` },
          400
        );
      }

      const validatedFiles = [];
      for (const item of files) {
        const relPath = String(item?.path || "").trim();
        const b64 = String(item?.content_base64 || "").trim();
        if (!relPath || relPath.includes("..") || !ALLOWED_PATH_REGEX.test(relPath)) {
          return jsonResponse(
            {
              ok: false,
              message: `Caminho não permitido pelo Worker: '${relPath}'. Apenas solidos/<Sólido>/minimos_globais/(convexos|nao_convexos)/sem_autointersecao/*.{json,txt,py}.`,
            },
            403
          );
        }
        if (!b64 || b64.length > MAX_BASE64_LENGTH) {
          return jsonResponse(
            { ok: false, message: `Conteúdo inválido ou grande demais em '${relPath}'.` },
            400
          );
        }
        validatedFiles.push({ path: relPath, content_base64: b64 });
      }

      const autor = String(body?.autor || "Pesquisador").trim().slice(0, 40);
      const rawMsg = String(body?.commit_message || "").trim().slice(0, 180);
      const commitMessage = rawMsg || `resultado: novo(s) mínimo(s) global(is) [${autor}]`;

      const res = await pushFilesAtomicGitHub(env, validatedFiles, commitMessage);
      return jsonResponse(
        {
          ok: res.ok,
          commit: res.commit || null,
          files_count: res.ok ? validatedFiles.length : 0,
          message: res.message,
        },
        res.status
      );
    }

    return jsonResponse({ ok: false, message: "Rota não encontrada." }, 404);
  },
};
