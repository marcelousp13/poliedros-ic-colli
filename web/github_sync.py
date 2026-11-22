# ==============================================================================
# WEB INTERFACE — SINCRONIZADOR AUTOMÁTICO COM GITHUB (SEM EXIGIR GIT INSTALADO)
# Envia novos mínimos globais validados de solidos/ diretamente para o GitHub
# via API oficial (commits atômicos) ou via git CLI (se instalado).
# Também possui modo --configurar e --publicar-projeto para setup inicial em 1 passo.
# ==============================================================================

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _build_ssl_context() -> ssl.SSLContext:
    """Cria contexto SSL compatível com Conda/Spyder no Windows (usa certifi se disponível)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception:
            return ssl._create_unverified_context()


_SSL_CTX = _build_ssl_context()
_SSL_UNVERIFIED_CTX = ssl._create_unverified_context()


def _ensure_conda_dll_paths():
    if os.name != "nt":
        return
    prefix = Path(sys.prefix)
    for d in (prefix / "Library" / "bin", prefix / "DLLs", prefix):
        if d.is_dir():
            if str(d).lower() not in os.environ.get("PATH", "").lower():
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(d))
                except Exception:
                    pass


_ensure_conda_dll_paths()

WEB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_DIR.parent
CONFIG_PATH = WEB_DIR / "config_github.json"
WORKER_CONFIG_PATH = WEB_DIR / "config_worker.json"
SENT_STATE_PATH = WEB_DIR / "cache" / "enviados_github.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

# Pastas e arquivos incluídos no bootstrap inicial do repositório (--publicar-projeto)
# Obs: docs/ é incluído para que o site estático e as fotos PythonSCAD já subam prontos!
IGNORED_TOP_DIRS = {
    ".git",
    "__pycache__",
}
IGNORED_EXTENSIONS = {".pyc", ".pyo", ".rar", ".zip", ".blend", ".blend1", ".log"}
IGNORED_REL_PATHS = {
    "web/config_github.json",
}


def load_github_config() -> Optional[Dict[str, str]]:
    """
    Carrega configuração combinando:
      1. web/config_worker.json (público no repo: worker_url, owner, repo, branch)
      2. web/config_github.json (local, ignorado no Git: autor, team_key e/ou token)
      3. Variáveis de ambiente (ATLAS_WORKER_URL, ATLAS_TEAM_KEY, ATLAS_AUTOR, GITHUB_TOKEN, etc.)
    """
    cfg: Dict[str, str] = {}
    if WORKER_CONFIG_PATH.exists():
        try:
            w_cfg = json.loads(WORKER_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(w_cfg, dict):
                cfg.update(w_cfg)
        except Exception:
            pass

    if CONFIG_PATH.exists():
        try:
            l_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(l_cfg, dict):
                for k, v in l_cfg.items():
                    if v is not None and str(v).strip() != "":
                        cfg[k] = v
        except Exception:
            pass

    if os.environ.get("GITHUB_REPO") and "/" in os.environ["GITHUB_REPO"]:
        owner, repo = os.environ["GITHUB_REPO"].split("/", 1)
        cfg.setdefault("owner", owner.strip())
        cfg.setdefault("repo", repo.strip())
    if os.environ.get("GITHUB_TOKEN"):
        cfg["token"] = os.environ["GITHUB_TOKEN"].strip()
    if os.environ.get("GITHUB_BRANCH"):
        cfg["branch"] = os.environ["GITHUB_BRANCH"].strip()
    if os.environ.get("ATLAS_AUTOR"):
        cfg["autor"] = os.environ["ATLAS_AUTOR"].strip()
    if os.environ.get("ATLAS_WORKER_URL"):
        cfg["worker_url"] = os.environ["ATLAS_WORKER_URL"].strip()
    if os.environ.get("ATLAS_TEAM_KEY"):
        cfg["team_key"] = os.environ["ATLAS_TEAM_KEY"].strip()

    owner = (cfg.get("owner") or "").strip()
    repo = (cfg.get("repo") or "").strip()
    token = (cfg.get("token") or "").strip()
    if token == "COLE_SEU_TOKEN_GITHUB_AQUI":
        token = ""
    worker_url = (cfg.get("worker_url") or "").strip().rstrip("/")
    team_key = (cfg.get("team_key") or "").strip()

    if not owner or not repo or owner == "SEU_USUARIO_GITHUB":
        return None
    return {
        "owner": owner,
        "repo": repo,
        "branch": (cfg.get("branch") or "main").strip(),
        "token": token,
        "worker_url": worker_url,
        "team_key": team_key,
        "autor": (cfg.get("autor") or os.environ.get("USERNAME") or "Pesquisador").strip(),
    }


def has_worker_credentials(cfg: Optional[Dict[str, str]]) -> bool:
    return bool(cfg and cfg.get("worker_url") and cfg.get("team_key"))


def has_remote_publish_credentials(cfg: Optional[Dict[str, str]]) -> bool:
    return bool(cfg and (has_worker_credentials(cfg) or cfg.get("token")))


def _http_json_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 45,
) -> Tuple[int, Any]:
    req_headers = dict(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json; charset=utf-8")

    for ctx in (_SSL_CTX, _SSL_UNVERIFIED_CTX):
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else {"message": str(e)}
            except Exception:
                body = {"message": raw or str(e)}
            return e.code, body
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLError) and ctx is _SSL_CTX:
                continue
            return 0, {"message": f"Falha de rede/SSL: {e}"}
        except Exception as e:
            return 0, {"message": str(e)}
    return 0, {"message": "Falha de conexão HTTP."}


def test_worker_connection(cfg: Dict[str, str]) -> Tuple[bool, str]:
    worker_url = (cfg.get("worker_url") or "").strip().rstrip("/")
    if not worker_url:
        return False, "URL do Cloudflare Worker não configurada em web/config_worker.json."
    status, data = _http_json_request(
        "GET",
        f"{worker_url}/health",
        headers={"User-Agent": "IC-com-Colli-Atlas-Sync/1.0"},
        timeout=15,
    )
    if not (status == 200 and isinstance(data, dict) and data.get("ok")):
        msg = data.get("message", str(data)) if isinstance(data, dict) else str(data)
        return False, f"Worker inacessível ({status}): {msg}"
    if not data.get("configured", True):
        return False, "Worker online, mas faltam os Secrets GITHUB_TOKEN ou TEAM_KEY no Cloudflare."

    repo_lbl = data.get("repo", cfg["owner"] + "/" + cfg["repo"])
    team_key = (cfg.get("team_key") or "").strip()
    if team_key:
        # Valida a chave da equipe sem gravar nada no GitHub:
        # /submit verifica X-Team-Key (401 se inválida) antes de exigir files (400 se chave válida).
        st_k, data_k = _http_json_request(
            "POST",
            f"{worker_url}/submit",
            headers={
                "X-Team-Key": team_key,
                "User-Agent": "IC-com-Colli-Atlas-Sync/1.0",
            },
            payload={"files": []},
            timeout=15,
        )
        if st_k == 401:
            return False, "Chave da equipe (TEAM_KEY) inválida! Confira a senha com a equipe."
        if st_k == 400:
            return True, f"Worker online e chave da equipe validada ({repo_lbl})."
        msg_k = data_k.get("message", str(data_k)) if isinstance(data_k, dict) else str(data_k)
        return False, f"Falha ao validar chave no Worker ({st_k}): {msg_k}"

    return True, f"Worker online ({repo_lbl})."


def push_files_via_worker(
    cfg: Dict[str, str],
    files: List[Tuple[str, bytes]],
    commit_message: str,
) -> Tuple[bool, str]:
    """
    Envia mínimos globais validados através do Cloudflare Worker da equipe.
    Não exige token do GitHub na máquina do pesquisador — usa apenas a chave da equipe.
    """
    if not files:
        return True, "Nenhum arquivo para enviar."
    worker_url = (cfg.get("worker_url") or "").strip().rstrip("/")
    team_key = (cfg.get("team_key") or "").strip()
    if not worker_url or not team_key:
        return False, "Cloudflare Worker ou chave da equipe não configurados."

    # Envia em lotes de até 15 arquivos (5 soluções completas × 3 arquivos):
    # mantém 5 + 15 = 20 subrequests no Worker (< 50 mesmo se houver retry concorrente 422)
    batch_size = 15
    total_batches = (len(files) + batch_size - 1) // batch_size
    last_msg = "Enviado via Cloudflare Worker."
    for b_idx in range(total_batches):
        chunk = files[b_idx * batch_size : (b_idx + 1) * batch_size]
        batch_msg = commit_message if total_batches == 1 else f"{commit_message} [lote {b_idx + 1}/{total_batches}]"
        payload = {
            "autor": cfg.get("autor") or "Pesquisador",
            "commit_message": batch_msg,
            "files": [
                {
                    "path": rel_posix,
                    "content_base64": base64.b64encode(raw_bytes).decode("ascii"),
                }
                for rel_posix, raw_bytes in chunk
            ],
        }
        status, data = _http_json_request(
            "POST",
            f"{worker_url}/submit",
            headers={
                "X-Team-Key": team_key,
                "User-Agent": "IC-com-Colli-Atlas-Sync/1.0",
            },
            payload=payload,
            timeout=60,
        )
        if status == 200 and isinstance(data, dict) and data.get("ok"):
            last_msg = data.get("message") or last_msg
        else:
            msg = data.get("message", str(data)) if isinstance(data, dict) else str(data)
            return False, f"Erro Worker ({status}, lote {b_idx + 1}/{total_batches}): {msg}"
    return True, last_msg


def _gh_request(method: str, url: str, token: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "IC-com-Colli-Atlas-Sync/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    for ctx in (_SSL_CTX, _SSL_UNVERIFIED_CTX):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else {"message": str(e)}
            except Exception:
                body = {"message": raw or str(e)}
            return e.code, body
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLError) and ctx is _SSL_CTX:
                continue
            return 0, {"message": f"Falha de rede/SSL: {e}"}
        except Exception as e:
            return 0, {"message": str(e)}
    return 0, {"message": "Falha de conexão com a API do GitHub."}


def test_github_connection(cfg: Dict[str, str]) -> Tuple[bool, str]:
    if not cfg.get("token"):
        return False, "Token do GitHub não informado (necessário para enviar arquivos ao repositório)."
    url = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}"
    status, data = _gh_request("GET", url, cfg["token"])
    if status == 200 and isinstance(data, dict):
        perms = data.get("permissions", {})
        if perms and not perms.get("push", False):
            return False, "Este token não possui permissão de escrita (repo / Contents: Read and write) neste repositório."
        # Verifica também se o token realmente está autenticado
        st_u, u_data = _gh_request("GET", "https://api.github.com/user", cfg["token"])
        if st_u != 200:
            return False, f"Token inválido ou expirado ({st_u}): {u_data.get('message', '')}"
        return True, f"Autenticado como '{u_data.get('login')}' em {data.get('full_name')} (branch: {data.get('default_branch', 'main')})."
    return False, f"Erro GitHub ({status}): {data.get('message', 'verifique owner/repo/token') if isinstance(data, dict) else data}"


def push_files_atomic_api(
    cfg: Dict[str, str],
    files: List[Tuple[str, bytes]],
    commit_message: str,
    max_retries: int = 3,
) -> Tuple[bool, str]:
    """
    Publica múltiplos arquivos em UM único commit atômico no GitHub via Git Data API.
    Funciona sem git instalado e lida automaticamente com repositório recém-criado (vazio)
    ou push concorrente de outro membro da equipe (retry automático).
    """
    if not files:
        return True, "Nenhum arquivo para enviar."
    if not cfg.get("token"):
        return False, "Token GitHub não configurado em web/config_github.json."

    api_base = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}"
    branch = cfg["branch"]
    token = cfg["token"]

    for attempt in range(1, max_retries + 1):
        # 1. Busca ref atual do branch
        st_ref, ref_data = _gh_request("GET", f"{api_base}/git/ref/heads/{branch}", token)

        # Caso especial: repositório completamente vazio (409 / 404)
        if st_ref in (404, 409):
            # Cria o primeiro arquivo via Contents API para inicializar o branch
            first_path, first_bytes = files[0]
            first_path_enc = urllib.parse.quote(first_path, safe="/")
            st_init, init_data = _gh_request(
                "PUT",
                f"{api_base}/contents/{first_path_enc}",
                token,
                {
                    "message": commit_message,
                    "content": base64.b64encode(first_bytes).decode("ascii"),
                    "branch": branch,
                },
            )
            if st_init not in (200, 201):
                return False, f"Falha ao inicializar repositório ({st_init}): {init_data.get('message')}"
            if len(files) == 1:
                return True, f"Commit inicial criado em {cfg['owner']}/{cfg['repo']}@{branch}."
            files = files[1:]
            time.sleep(0.8)
            continue

        if st_ref != 200:
            return False, f"Erro ao ler branch '{branch}' ({st_ref}): {ref_data.get('message')}"

        head_sha = ref_data["object"]["sha"]
        st_commit, commit_data = _gh_request("GET", f"{api_base}/git/commits/{head_sha}", token)
        if st_commit != 200:
            return False, f"Erro ao ler commit {head_sha[:7]} ({st_commit})."
        base_tree_sha = commit_data["tree"]["sha"]

        # 2. Cria blobs em base64 (em paralelo para alta velocidade)
        tree_entries = []
        total_f = len(files)

        def _upload_one_blob(item: Tuple[str, bytes]) -> Tuple[str, int, Any]:
            rel_p, raw_b = item
            b64_str = base64.b64encode(raw_b).decode("ascii")
            last_st, last_data = 0, {}
            for retry in range(4):
                st_b, b_data = _gh_request(
                    "POST",
                    f"{api_base}/git/blobs",
                    token,
                    {"content": b64_str, "encoding": "base64"},
                )
                if st_b in (200, 201):
                    return rel_p, st_b, b_data
                last_st, last_data = st_b, b_data
                time.sleep(0.8 * (retry + 1))
            return rel_p, last_st, last_data

        if total_f <= 4:
            for rel_posix, raw_bytes in files:
                _, st_blob, blob_data = _upload_one_blob((rel_posix, raw_bytes))
                if st_blob not in (200, 201):
                    return False, f"Erro ao enviar blob '{rel_posix}' ({st_blob}): {blob_data.get('message')}"
                tree_entries.append({
                    "path": rel_posix,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_data["sha"],
                })
        else:
            done_cnt = 0
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(_upload_one_blob, f_item): f_item[0] for f_item in files}
                for fut in as_completed(futures):
                    rel_posix, st_blob, blob_data = fut.result()
                    if st_blob not in (200, 201):
                        return False, f"Erro ao enviar blob '{rel_posix}' ({st_blob}): {blob_data.get('message')}"
                    tree_entries.append({
                        "path": rel_posix,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_data["sha"],
                    })
                    done_cnt += 1
                    if done_cnt % 50 == 0 or done_cnt == total_f:
                        print(f"    [GitHub Upload] {done_cnt}/{total_f} arquivos processados...", flush=True)
            tree_entries.sort(key=lambda e: e["path"])

        # 3. Cria árvore combinada
        st_tree, tree_data = _gh_request(
            "POST",
            f"{api_base}/git/trees",
            token,
            {"base_tree": base_tree_sha, "tree": tree_entries},
        )
        if st_tree not in (200, 201):
            return False, f"Erro ao montar árvore ({st_tree}): {tree_data.get('message')}"

        # 4. Cria commit
        st_new_commit, new_commit_data = _gh_request(
            "POST",
            f"{api_base}/git/commits",
            token,
            {
                "message": commit_message,
                "tree": tree_data["sha"],
                "parents": [head_sha],
            },
        )
        if st_new_commit not in (200, 201):
            return False, f"Erro ao criar commit ({st_new_commit}): {new_commit_data.get('message')}"

        # 5. Atualiza ponteiro do branch
        st_patch, patch_data = _gh_request(
            "PATCH",
            f"{api_base}/git/refs/heads/{branch}",
            token,
            {"sha": new_commit_data["sha"], "force": False},
        )
        if st_patch == 200:
            short = new_commit_data["sha"][:7]
            return True, f"Enviado para GitHub ({cfg['owner']}/{cfg['repo']}@{branch} · {short})."

        if st_patch == 422 and attempt < max_retries:
            # Outro membro enviou um commit no mesmo instante: tenta novamente sobre o novo HEAD
            time.sleep(1.2)
            continue

        return False, f"Erro ao atualizar branch ({st_patch}): {patch_data.get('message')}"

    return False, "Falha após múltiplas tentativas concorrentes."


def push_via_git_cli(rel_paths: List[str], commit_message: str) -> Tuple[bool, str]:
    """Fallback/alternativa nativa caso git esteja instalado e configurado na máquina."""
    git_bin = shutil.which("git")
    if not git_bin or not (PROJECT_ROOT / ".git").exists():
        return False, "Git CLI não disponível neste diretório."

    def run_git(*args: str):
        return subprocess.run(
            [git_bin, *args],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    run_git("pull", "--rebase", "--autostash")
    add_res = run_git("add", "--", *rel_paths)
    if add_res.returncode != 0:
        return False, add_res.stderr.strip()

    status = run_git("diff", "--cached", "--name-only")
    if not status.stdout.strip():
        return True, "Nenhuma alteração nova para enviar."

    c_res = run_git("commit", "-m", commit_message)
    if c_res.returncode != 0:
        return False, c_res.stderr.strip() or c_res.stdout.strip()

    p_res = run_git("push")
    if p_res.returncode != 0:
        return False, p_res.stderr.strip() or p_res.stdout.strip()
    return True, "Sincronizado via git push."


def load_sent_registry() -> Dict[str, str]:
    if SENT_STATE_PATH.exists():
        try:
            return json.loads(SENT_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_sent_registry(reg: Dict[str, str]):
    SENT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SENT_STATE_PATH.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")


def _fetch_pages_json_file(cfg: Dict[str, str], rel_posix: str) -> Optional[Any]:
    """
    Busca um arquivo JSON diretamente do site público publicado no GitHub Pages
    (https://<owner>.github.io/<repo>/<rel_posix>), que é sempre a versão mais
    recente construída pelo GitHub Actions — sem exigir token e sem consumir
    rate limit da API do GitHub.
    """
    if not cfg or not cfg.get("owner") or not cfg.get("repo"):
        return None
    rel_enc = urllib.parse.quote(rel_posix.lstrip("/"), safe="/")
    pages_url = f"https://{cfg['owner']}.github.io/{cfg['repo']}/{rel_enc}?t={int(time.time())}"
    st, data = _http_json_request(
        "GET",
        pages_url,
        headers={
            "User-Agent": "IC-com-Colli-Atlas-Sync/1.0",
            "Cache-Control": "no-cache",
        },
        timeout=20,
    )
    if st == 200:
        return data
    return None


def _fetch_remote_json_file(cfg: Dict[str, str], rel_posix: str) -> Optional[Any]:
    """
    Busca e decodifica um arquivo JSON do repositório GitHub remoto (se existir).
    Quando não há token GitHub local (modo Cloudflare Worker), lê via raw.githubusercontent.com
    para evitar o limite de 60 req/hora da API não autenticada do GitHub.
    """
    if not cfg or not cfg.get("owner") or not cfg.get("repo"):
        return None
    rel_enc = urllib.parse.quote(rel_posix.lstrip("/"), safe="/")
    if not cfg.get("token"):
        raw_url = (
            f"https://raw.githubusercontent.com/{cfg['owner']}/{cfg['repo']}/"
            f"{cfg['branch']}/{rel_enc}?t={int(time.time())}"
        )
        st, data = _http_json_request(
            "GET",
            raw_url,
            headers={"User-Agent": "IC-com-Colli-Atlas-Sync/1.0"},
            timeout=20,
        )
        if st == 200:
            return data
        return None

    url = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}/contents/{rel_enc}?ref={cfg['branch']}"
    status, data = _gh_request("GET", url, cfg.get("token", ""))
    if status != 200 or not isinstance(data, dict):
        return None
    b64 = data.get("content")
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64).decode("utf-8")
        return json.loads(raw)
    except Exception:
        return None


def _get_existing_site_solutions_for_solid(
    cfg: Optional[Dict[str, str]],
    solid_id: str,
    validador: Any,
) -> List[Dict[str, Any]]:
    """
    Carrega os mínimos que JÁ existem no site para `solid_id`, combinando:
      1. Base local do site em docs/data/solids/<slug>.json
      2. Site público ao vivo no GitHub Pages (https://<owner>.github.io/<repo>/data/solids/<slug>.json)
      3. Base estática do repositório em docs/data/solids/<slug>.json (fallback)
      4. JSONs recém-enviados em solidos/<solid_id>/minimos_globais/.../sem_autointersecao/ no GitHub
         (funciona TANTO com token quanto em modo Cloudflare Worker, para que uma máquina enxergue
         imediatamente mínimos enviados segundos atrás por outra máquina antes mesmo do deploy!)
    """
    from geometry_analyzer import compute_geom_hash, find_exact_same_vertices_match, safe_slug
    from verificadores.isomorfismo import construir_matriz_distancias

    slug = safe_slug(solid_id)
    site_solutions: List[Dict[str, Any]] = []

    def _absorb_solution_list(sol_list: List[Dict[str, Any]]):
        for s in sol_list:
            verts = s.get("vertices") or s.get("vc")
            if not verts:
                continue
            check = validador.validar_solucao_global(solid_id, verts, s.get("faces"))
            if not check["valid"]:
                continue
            faces = check["faces_oriented"]
            gh = s.get("geom_hash") or compute_geom_hash(verts, faces)
            sid_item = s.get("solution_id") or s.get("nome") or f"site_{gh[:8]}"
            if find_exact_same_vertices_match(verts, site_solutions) is not None:
                continue
            site_solutions.append({
                "solution_id": sid_item,
                "geom_hash": gh,
                "vertices": verts,
                "faces": faces,
                "fval": float(check["fval_recomputed"]),
                "is_convex": bool(check["is_convex"]),
                "source_folder": check["source_folder"],
                "already_on_site": True,
                "_dist_matrix": construir_matriz_distancias(verts),
            })

    # 1. Site local (docs/data/solids/<slug>.json)
    local_site_json = PROJECT_ROOT / "docs" / "data" / "solids" / f"{slug}.json"
    if local_site_json.is_file():
        try:
            payload = json.loads(local_site_json.read_text(encoding="utf-8"))
            raw_sols = payload.get("global_solutions") or (
                (payload.get("convex_solutions") or []) + (payload.get("nonconvex_solutions") or [])
            )
            _absorb_solution_list(raw_sols)
        except Exception:
            pass

    # 2. Site público ao vivo (GitHub Pages) + fallback no repo + solidos/ recém-enviados no GitHub
    if cfg and cfg.get("owner") and cfg.get("repo"):
        # 2a. GitHub Pages ao vivo (sempre atualizado após o GitHub Actions!)
        pages_payload = _fetch_pages_json_file(cfg, f"data/solids/{slug}.json")
        if isinstance(pages_payload, dict):
            raw_pages = pages_payload.get("global_solutions") or (
                (pages_payload.get("convex_solutions") or []) + (pages_payload.get("nonconvex_solutions") or [])
            )
            _absorb_solution_list(raw_pages)

        # 2b. Fallback: docs/data/solids/<slug>.json no branch principal do repositório
        remote_payload = _fetch_remote_json_file(cfg, f"docs/data/solids/{slug}.json")
        if isinstance(remote_payload, dict):
            raw_remote = remote_payload.get("global_solutions") or (
                (remote_payload.get("convex_solutions") or []) + (remote_payload.get("nonconvex_solutions") or [])
            )
            _absorb_solution_list(raw_remote)

        # 2c. Consulta JSONs em solidos/<solid_id>/minimos_globais/{convexos,nao_convexos}/sem_autointersecao/
        # no GitHub (enxerga commits enviados segundos atrás por outra máquina antes do GitHub Actions terminar!)
        seen_solution_ids = {s.get("solution_id") for s in site_solutions if s.get("solution_id")}
        sid_enc = urllib.parse.quote(solid_id, safe="")
        tok = cfg.get("token", "")
        for cat_sub in ("convexos", "nao_convexos"):
            dir_url = (
                f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}/contents/"
                f"solidos/{sid_enc}/minimos_globais/{cat_sub}/sem_autointersecao?ref={cfg['branch']}"
            )
            st, items = _gh_request("GET", dir_url, tok)
            if st == 200 and isinstance(items, list):
                for item in items:
                    if not (isinstance(item, dict) and str(item.get("name", "")).endswith(".json")):
                        continue
                    stem_name = Path(item["name"]).stem
                    if stem_name in seen_solution_ids:
                        continue
                    r_sol = None
                    dl_url = item.get("download_url")
                    if dl_url and not tok:
                        st_dl, d_dl = _http_json_request(
                            "GET",
                            f"{dl_url}?t={int(time.time())}",
                            headers={"User-Agent": "IC-com-Colli-Atlas-Sync/1.0"},
                            timeout=20,
                        )
                        if st_dl == 200 and isinstance(d_dl, dict):
                            r_sol = d_dl
                    else:
                        r_sol = _fetch_remote_json_file(cfg, item["path"])
                    if isinstance(r_sol, dict) and r_sol.get("vc"):
                        r_sol["solution_id"] = stem_name
                        _absorb_solution_list([r_sol])
                        seen_solution_ids.add(stem_name)

    return site_solutions


def sync_global_solutions_to_github(
    solid_filter: Optional[str] = None,
    force_all: bool = False,
    only_solidos: Optional[bool] = None,
) -> Tuple[bool, str, int]:
    """
    Executa a verificação científica de 4 passos sobre os mínimos da pasta solidos/:
      1. Novo mínimo detectado na pasta local (de Colli, Thomas ou Marcelo)
      2. Verifica se já existe um mínimo para esse sólido no site (local + GitHub)
      3. Verifica se é igual (isomorfismo métrico via backtracking)
      4. Se for igual, descarta; se for novo e cumprir todas as exigências científicas,
         envia ao GitHub (via Cloudflare Worker ou API) para o GitHub Actions atualizar o site.

    Quando `only_solidos=True` (padrão no modo Cloudflare Worker e no vigia automático),
    envia apenas os arquivos de solidos/<Sólido>/minimos_globais/.../sem_autointersecao/
    e deixa o GitHub Actions reconstruir docs/ sem conflitos entre múltiplos pesquisadores.
    """
    from geometry_analyzer import CatalogService, compute_geom_hash, find_exact_same_vertices_match, safe_slug
    from validador_cientifico import ValidadorCientifico
    from verificadores.isomorfismo import construir_matriz_distancias

    cfg = load_github_config()
    use_worker = has_worker_credentials(cfg)
    has_git = bool(shutil.which("git") and (PROJECT_ROOT / ".git").exists())
    if only_solidos is None:
        only_solidos = use_worker

    # Se GitHub estiver configurado no modo completo (não leve), puxa antes eventuais mínimos novos
    if not only_solidos and cfg and cfg.get("token"):
        try:
            pull_new_minima_from_github()
        except Exception:
            pass

    catalog = CatalogService(PROJECT_ROOT)
    solids_meta_map = {e["id"]: e for e in catalog.list_all_solids_from_faces_txt()}
    validador = ValidadorCientifico()
    sent_reg = {} if force_all else load_sent_registry()
    reg_dirty = False

    solidos_dir = PROJECT_ROOT / "solidos"
    if not solidos_dir.exists():
        return True, "Pasta solidos/ ainda vazia.", 0

    files_to_send: List[Tuple[str, bytes, str]] = []  # (rel_posix, content, sig)
    solids_touched = set()
    discarded_equal_count = 0
    rejected_invalid_count = 0

    for solid_dir in sorted(solidos_dir.iterdir()):
        if not solid_dir.is_dir():
            continue
        sid = solid_dir.name
        if solid_filter and sid != solid_filter:
            continue

        records = catalog._collect_global_records(solid_dir)
        if not records:
            continue

        # Verifica primeiro se há algum arquivo pendente neste sólido
        pending_records = []
        for rec in records:
            paths = [p for p in (rec.get("json"), rec.get("txt"), rec.get("scad")) if p and p.exists()]
            if not paths:
                continue
            pending_paths = []
            for p in paths:
                rel_posix = p.relative_to(PROJECT_ROOT).as_posix()
                sig = f"{p.stat().st_size}:{int(p.stat().st_mtime)}"
                prev_val = sent_reg.get(rel_posix, "")
                if prev_val not in (sig, f"discarded_equal:{sig}", f"discarded_invalid:{sig}"):
                    pending_paths.append((rel_posix, p, sig))
            if pending_paths:
                pending_records.append((rec, pending_paths))

        if not pending_records:
            continue

        # Passo 2: Carrega os mínimos que JÁ existem no site (local + GitHub Pages + GitHub solidos/)
        site_solutions = _get_existing_site_solutions_for_solid(cfg, sid, validador)
        faces_raw = (solids_meta_map.get(sid) or {}).get("faces_raw") or []

        for rec, pending_paths in pending_records:
            analyzed = catalog._analyze_global_record(sid, faces_raw, rec)
            if analyzed is None:
                continue

            sol_id = analyzed["solution_id"]
            matched = find_exact_same_vertices_match(analyzed["vertices"], site_solutions)

            # Regra oficial: somente pula se já existirem EXATAMENTE os mesmos vértices no site
            if not force_all and matched is not None:
                if matched.get("solution_id") != sol_id:
                    discarded_equal_count += 1
                    print(
                        f"  [JÁ NO SITE · MESMOS VÉRTICES] {sid}/{sol_id} == {matched.get('solution_id')}"
                    )
                for rel_posix, _, sig in pending_paths:
                    sent_reg[rel_posix] = sig
                    reg_dirty = True
                continue

            if force_all and matched is not None:
                check = validador.validar_solucao_global(sid, analyzed["vertices"], analyzed["faces"])
                if not check["valid"]:
                    rejected_invalid_count += 1
                    continue
            else:
                avaliacao = validador.avaliar_novo_minimo_4_passos(
                    sid, analyzed, site_solutions, permitir_isometricos=True
                )
                if not avaliacao["accepted"]:
                    rejected_invalid_count += 1
                    print(f"  [REJEITADO (EXIGÊNCIAS)] {sid}/{sol_id}: {avaliacao['reason']}")
                    for rel_posix, _, sig in pending_paths:
                        sent_reg[rel_posix] = f"discarded_invalid:{sig}"
                        reg_dirty = True
                    continue

                tag_iso = " [recorrência isométrica]" if avaliacao.get("is_isometric_repeat") else " [nova forma]"
                print(
                    f"  [APROVADO] {sid}/{sol_id} -> {avaliacao['target_tab']}{tag_iso} "
                    f"(F(x) = {avaliacao['fval_recomputed']:.2e})"
                )
                analyzed["already_on_site"] = True
                analyzed["_dist_matrix"] = construir_matriz_distancias(analyzed["vertices"])
                site_solutions.append(analyzed)

            solids_touched.add(sid)
            for rel_posix, p, sig in pending_paths:
                files_to_send.append((rel_posix, p.read_bytes(), sig))

    if reg_dirty:
        save_sent_registry(sent_reg)

    if not files_to_send:
        extra_info = ""
        if discarded_equal_count > 0 or rejected_invalid_count > 0:
            extra_info = f" ({discarded_equal_count} com mesmos vértices já no site, {rejected_invalid_count} inválido(s))"
        if solid_filter:
            return True, f"Nenhum mínimo global novo de '{solid_filter}' para enviar{extra_info}.", 0
        return True, f"Nenhum mínimo global novo para enviar{extra_info}.", 0

    # Atualiza o site estático local (docs/) apenas quando NÃO estamos em modo somente-solidos
    # (no modo Worker / multi-máquina, o GitHub Actions reconstrói docs/ sem conflitos entre a equipe)
    solids_label = ", ".join(sorted(solids_touched)[:5])
    if len(solids_touched) > 5:
        solids_label += f" (+{len(solids_touched) - 5})"

    if not only_solidos:
        try:
            from construir_site_estatico import build_static_atlas
            from scad_renderer import CAMERA_PRESETS
            build_static_atlas(PROJECT_ROOT / "docs", presets=list(CAMERA_PRESETS.keys()))
            docs_dir = PROJECT_ROOT / "docs"
            already_queued = {r for r, _, _ in files_to_send}
            # Inclui catalog.json e os arquivos docs/ dos sólidos novos adicionados
            cat_file = docs_dir / "data" / "catalog.json"
            if cat_file.is_file():
                rel_c = cat_file.relative_to(PROJECT_ROOT).as_posix()
                if rel_c not in already_queued:
                    files_to_send.append((rel_c, cat_file.read_bytes(), f"{cat_file.stat().st_size}:{int(cat_file.stat().st_mtime)}"))
                    already_queued.add(rel_c)
            for sid in sorted(solids_touched):
                slug = safe_slug(sid)
                s_json = docs_dir / "data" / "solids" / f"{slug}.json"
                if s_json.is_file():
                    rel_s = s_json.relative_to(PROJECT_ROOT).as_posix()
                    if rel_s not in already_queued:
                        files_to_send.append((rel_s, s_json.read_bytes(), f"{s_json.stat().st_size}:{int(s_json.stat().st_mtime)}"))
                        already_queued.add(rel_s)
                for img_f in list((docs_dir / "renders").glob(f"{slug}_*.webp")) + list((docs_dir / "renders").glob(f"{slug}_*.png")):
                    rel_p = img_f.relative_to(PROJECT_ROOT).as_posix()
                    if rel_p not in already_queued:
                        files_to_send.append((rel_p, img_f.read_bytes(), f"{img_f.stat().st_size}:{int(img_f.stat().st_mtime)}"))
                        already_queued.add(rel_p)
                s_files_dir = docs_dir / "files" / slug
                if s_files_dir.is_dir():
                    for df in s_files_dir.rglob("*"):
                        if df.is_file():
                            rel_d = df.relative_to(PROJECT_ROOT).as_posix()
                            if rel_d not in already_queued:
                                files_to_send.append((rel_d, df.read_bytes(), f"{df.stat().st_size}:{int(df.stat().st_mtime)}"))
                                already_queued.add(rel_d)
        except Exception as e:
            print(f"  [Aviso] Não foi possível atualizar docs/ localmente antes do envio: {e}")

    if not has_remote_publish_credentials(cfg) and not has_git:
        return (
            True,
            f"Novo(s) mínimo(s) de {solids_label} validado(s) localmente. "
            "Configure o Worker (web/config_worker.json + chave da equipe) ou web\\configurar_github.bat para enviar ao site.",
            len(files_to_send),
        )

    autor = cfg["autor"] if cfg else (os.environ.get("USERNAME") or "Pesquisador")
    msg = f"resultado({solids_label}): novo(s) mínimo(s) global(is) [{autor}]"

    if use_worker:
        ok, info = push_files_via_worker(cfg, [(r, b) for r, b, _ in files_to_send], msg)
    elif cfg and cfg.get("token"):
        ok, info = push_files_atomic_api(cfg, [(r, b) for r, b, _ in files_to_send], msg)
    else:
        ok, info = push_via_git_cli([r for r, _, _ in files_to_send], msg)

    if ok:
        for rel_posix, _, sig in files_to_send:
            sent_reg[rel_posix] = sig
        save_sent_registry(sent_reg)
        return True, info, len(files_to_send)
    return False, info, 0


def pull_new_minima_from_github(rebuild_docs: bool = True) -> Tuple[bool, str, int]:
    """
    Puxa do site público publicado (GitHub Pages) / repositório GitHub apenas os NOVOS
    mínimos encontrados pelos outros membros da equipe (Marcelo, Thomas ou Prof. Colli),
    aplicando o protocolo de 4 passos:
      1. Novo mínimo detectado no Atlas remoto
      2. Verifica se já existe mínimo para esse sólido localmente (docs/ + solidos/)
      3. Verifica se é igual (isomorfismo métrico)
      4. Se for igual, descarta; se for novo e cumprir todas as exigências, adiciona localmente.
    """
    import re
    from exportadores.pythonscad_exportador import ExportadorPythonSCAD
    from geometry_analyzer import CatalogService, find_exact_same_vertices_match
    from persistencia.gerenciador_solucoes import GerenciadorSolucoes
    from validador_cientifico import ValidadorCientifico
    from verificadores.isomorfismo import construir_matriz_distancias
    from verificadores.verificador_geometrico import VerificadorGeometrico

    cfg = load_github_config()
    if not cfg or not cfg.get("owner") or not cfg.get("repo"):
        return False, "GitHub ainda não configurado (execute web\\configurar_github.bat).", 0

    validador = ValidadorCientifico()
    catalog_svc = CatalogService(PROJECT_ROOT)
    solids_meta_map = {e["id"]: e for e in catalog_svc.list_all_solids_from_faces_txt()}
    gerenciador = GerenciadorSolucoes(pasta_base=str(PROJECT_ROOT / "solidos"))
    exportador = ExportadorPythonSCAD(fator_escala=20.0, pasta_base=str(PROJECT_ROOT / "solidos"))

    # Prioriza o site público ao vivo (GitHub Pages), com fallback para docs/ no branch
    remote_catalog = _fetch_pages_json_file(cfg, "data/catalog.json")
    from_pages = isinstance(remote_catalog, dict) and isinstance(remote_catalog.get("solids"), list)
    if not from_pages:
        remote_catalog = _fetch_remote_json_file(cfg, "docs/data/catalog.json")
    if not isinstance(remote_catalog, dict) or not isinstance(remote_catalog.get("solids"), list):
        return False, "Não foi possível ler data/catalog.json do Atlas remoto.", 0

    local_site_map: Dict[str, List[Dict[str, Any]]] = {}
    if (PROJECT_ROOT / "docs" / "data" / "solids").is_dir():
        try:
            from construir_site_estatico import _load_existing_site_solutions
            local_site_map = _load_existing_site_solutions(PROJECT_ROOT / "docs" / "data" / "solids", validador)
        except Exception:
            local_site_map = {}
    sent_reg = load_sent_registry()
    reg_dirty = False
    added_count = 0

    for item in remote_catalog["solids"]:
        if not isinstance(item, dict) or not item.get("has_global"):
            continue
        sid = item.get("id")
        slug = item.get("slug") or sid
        if not sid:
            continue

        # Base local combinada: docs/data/solids/ + solidos/<sid>/minimos_globais/
        site_solutions = list(local_site_map.get(sid, []))
        local_sdir = PROJECT_ROOT / "solidos" / sid
        if local_sdir.is_dir():
            faces_raw = (solids_meta_map.get(sid) or {}).get("faces_raw") or []
            for rec in catalog_svc._collect_global_records(local_sdir):
                analyzed = catalog_svc._analyze_global_record(sid, faces_raw, rec)
                if analyzed is None or not analyzed.get("vertices"):
                    continue
                if find_exact_same_vertices_match(analyzed["vertices"], site_solutions) is None:
                    analyzed["already_on_site"] = True
                    analyzed["_dist_matrix"] = construir_matriz_distancias(analyzed["vertices"])
                    site_solutions.append(analyzed)

        # Atalho rápido: evita baixar o dossiê se a contagem remota não exceder a local e o principal já existir
        remote_count = int(item.get("global_count") or 0)
        remote_primary_hash = (item.get("primary_global") or {}).get("geom_hash")
        local_hashes = {s.get("geom_hash") for s in site_solutions if s.get("geom_hash")}
        if remote_count <= len(site_solutions) and (not remote_primary_hash or remote_primary_hash in local_hashes):
            continue

        remote_detail = (
            _fetch_pages_json_file(cfg, f"data/solids/{slug}.json")
            if from_pages
            else None
        ) or _fetch_remote_json_file(cfg, f"docs/data/solids/{slug}.json")
        if not isinstance(remote_detail, dict):
            continue

        remote_sols = remote_detail.get("global_solutions") or (
            (remote_detail.get("convex_solutions") or []) + (remote_detail.get("nonconvex_solutions") or [])
        )

        for rsol in remote_sols:
            verts = rsol.get("vertices")
            if not verts:
                continue
            r_sid = str(rsol.get("solution_id") or "solucao_global_github")
            if find_exact_same_vertices_match(verts, site_solutions) is not None:
                continue
            avaliacao = validador.avaliar_novo_minimo_4_passos(
                sid, rsol, site_solutions, permitir_isometricos=True
            )
            if not avaliacao["accepted"]:
                continue

            # Novo registro global válido vindo do Atlas remoto! Salva em solidos/<sid>/minimos_globais/...
            fval = float(avaliacao["fval_recomputed"])
            is_conv = bool(avaliacao["is_convex"])
            faces_or = avaliacao["faces_oriented"]
            dists = rsol.get("distancias") or VerificadorGeometrico.calcular_distancias(verts).tolist()
            angs = rsol.get("angulos_salvos") or VerificadorGeometrico.calcular_angulos_diedrais(verts, faces_or).tolist()
            autovals = rsol.get("autovalores") or []
            sol_id = r_sid
            m_ts = re.match(r"^(.*)_(\d{8}_\d{6})$", sol_id)
            nome_base = m_ts.group(1) if m_ts else sol_id
            ts_val = m_ts.group(2) if m_ts else None

            gerenciador.inspecionar_ou_registrar_isometria(sid, verts, dists, angs, fval, registrar_se_inedito=True)
            j_path, t_path = gerenciador.salvar_arquivos_solucao(
                nome_solucao=nome_base,
                tipo="global",
                nome_solido=sid,
                vc=verts,
                distancias=dists,
                angulos=angs,
                autovalores=autovals,
                fval=fval,
                convexo=is_conv,
                tem_autointersecao=False,
                info_convexidade=avaliacao["convexity"],
                info_autointersecao=avaliacao["self_intersection"],
                timestamp=ts_val,
                info_execucao=rsol.get("execucao"),
            )
            nome_base_usado = gerenciador.ultimo_nome_base or Path(j_path).stem
            s_path = exportador.exportar_se_minimo_global(
                nome_solido=sid,
                nome_solucao=nome_base,
                tipo_solucao="global",
                vertices=verts,
                faces=faces_or,
                fval=fval,
                convexo=is_conv,
                tem_autointersecao=False,
                timestamp=ts_val,
                nome_base_exato=nome_base_usado,
            )
            # Marca arquivos puxados como já presentes no remoto para o vigia não reenviar
            for fp_str in (j_path, t_path, s_path):
                if fp_str and Path(fp_str).is_file():
                    fp = Path(fp_str)
                    rel_posix = fp.relative_to(PROJECT_ROOT).as_posix()
                    sent_reg[rel_posix] = f"{fp.stat().st_size}:{int(fp.stat().st_mtime)}"
                    reg_dirty = True

            rsol_copy = dict(rsol)
            rsol_copy["already_on_site"] = True
            rsol_copy["_dist_matrix"] = construir_matriz_distancias(verts)
            site_solutions.append(rsol_copy)
            added_count += 1
            print(f"  [Atlas Pull · REGISTRO GLOBAL] {sid}/{sol_id} sincronizado localmente (-> {avaliacao['target_tab']}).")

    if reg_dirty:
        save_sent_registry(sent_reg)

    if added_count > 0:
        if rebuild_docs:
            from construir_site_estatico import build_static_atlas
            from scad_renderer import CAMERA_PRESETS
            build_static_atlas(PROJECT_ROOT / "docs", presets=list(CAMERA_PRESETS.keys()))
        return True, f"{added_count} novo(s) mínimo(s) sincronizado(s) do Atlas remoto.", added_count
    return True, "Base local já contém todos os mínimos publicados no Atlas.", 0


def collect_project_files_for_bootstrap() -> List[Tuple[str, bytes]]:
    """Coleta os arquivos do projeto (respeitando exclusões de segurança e arquivos pesados) para publicação inicial."""
    collected: List[Tuple[str, bytes]] = []
    for root, dirs, filenames in os.walk(PROJECT_ROOT):
        root_path = Path(root)
        rel_root = root_path.relative_to(PROJECT_ROOT)

        # Filtra diretórios ignorados (minimos_locais/ e com_autointersecao/ nunca vão ao site)
        dirs[:] = [
            d for d in dirs
            if d not in IGNORED_TOP_DIRS
            and d != "__pycache__"
            and d not in ("minimos_locais", "mínimos locais", "locais", "com_autointersecao")
            and not (rel_root == Path("web") and d == "cache")
        ]

        for fn in filenames:
            fp = root_path / fn
            if fp.suffix.lower() in IGNORED_EXTENSIONS:
                continue
            rel_posix = fp.relative_to(PROJECT_ROOT).as_posix()
            if rel_posix in IGNORED_REL_PATHS:
                continue
            # Evita subir arquivos muito grandes (> 5 MB)
            if fp.stat().st_size > 5 * 1024 * 1024:
                continue
            collected.append((rel_posix, fp.read_bytes()))

    collected.sort(key=lambda x: x[0])
    return collected


def enable_github_pages_api(cfg: Dict[str, str]) -> Tuple[bool, str]:
    """
    Ativa automaticamente o GitHub Pages do repositório apontando para a pasta /docs
    do branch principal (main), para que o site fique no ar sem configuração manual.
    """
    api_base = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}"
    branch = cfg["branch"]
    token = cfg["token"]
    pages_url = f"https://{cfg['owner']}.github.io/{cfg['repo']}/"

    # Verifica se já está ativo
    st_get, data_get = _gh_request("GET", f"{api_base}/pages", token)
    if st_get == 200 and isinstance(data_get, dict):
        # Garante que aponte para branch main /docs
        _gh_request(
            "PUT",
            f"{api_base}/pages",
            token,
            {"source": {"branch": branch, "path": "/docs"}},
        )
        return True, f"GitHub Pages ativo em: {data_get.get('html_url') or pages_url}"

    # Ativa GitHub Pages a partir de main /docs
    st_post, data_post = _gh_request(
        "POST",
        f"{api_base}/pages",
        token,
        {"source": {"branch": branch, "path": "/docs"}},
    )
    if st_post in (200, 201, 409):
        return True, f"GitHub Pages ativado automaticamente! Link: {pages_url}"
    return False, f"Aviso ao ativar Pages via API ({st_post}): {data_post.get('message', '')}. Ative em Settings -> Pages -> Branch: main /docs."


def publish_entire_project() -> Tuple[bool, str]:
    """Envia toda a estrutura do projeto (códigos oficiais + docs/ + web/ + solidos/) e ativa o GitHub Pages."""
    cfg = load_github_config()
    if not cfg or not cfg.get("token"):
        return False, "Token do GitHub não configurado. Execute web\\configurar_github.bat e cole seu token."

    ok_conn, conn_msg = test_github_connection(cfg)
    if not ok_conn:
        return False, conn_msg
    print(f"[GitHub] ✓ {conn_msg}")

    all_files = collect_project_files_for_bootstrap()
    # Separa arquivos de workflow (.github/workflows/) para que funcionem mesmo se o token não tiver escopo 'workflow'
    core_files = [item for item in all_files if not item[0].startswith(".github/workflows/")]
    wf_files = [item for item in all_files if item[0].startswith(".github/workflows/")]

    print(f"[GitHub] Enviando {len(core_files)} arquivos do projeto e do site estático (docs/) em paralelo...")
    ok, msg = push_files_atomic_api(
        cfg,
        core_files,
        "atlas: publicar projeto IC com Colli e site estático completo (docs/)",
    )
    if not ok:
        return False, msg
    print(f"  ✓ {msg}")

    if wf_files:
        ok_wf, msg_wf = push_files_atomic_api(cfg, wf_files, "ci: adicionar workflow automático do GitHub Pages")
        if ok_wf:
            print(f"  ✓ Workflow GitHub Actions enviado ({msg_wf})")

    # Ativa automaticamente o GitHub Pages (branch main -> pasta /docs)
    ok_pg, msg_pg = enable_github_pages_api(cfg)
    print(f"  {'✓' if ok_pg else '!'} {msg_pg}")

    pages_url = f"https://{cfg['owner']}.github.io/{cfg['repo']}/"
    return True, (
        f"SITE PUBLICADO COM SUCESSO!\n"
        f"  • Repositório : https://github.com/{cfg['owner']}/{cfg['repo']}\n"
        f"  • Link do Site: {pages_url}\n"
        f"  (O GitHub leva ~40 a 60 segundos após o primeiro envio para colocar o link no ar)."
    )


def interactive_setup():
    print("\n" + "=" * 76)
    print("  PUBLICAÇÃO AUTOMÁTICA DO SITE NO GITHUB (IC COM COLLI · IME-USP)")
    print("=" * 76)

    existing = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    owner = (existing.get("owner") or "marcelousp13").strip()
    if owner == "SEU_USUARIO_GITHUB" or not owner:
        owner = "marcelousp13"
    repo = (existing.get("repo") or "poliedros-ic-colli").strip()
    branch = (existing.get("branch") or "main").strip()
    autor = (existing.get("autor") or "Marcelo").strip()
    token = (existing.get("token") or "").strip()
    if token == "COLE_SEU_TOKEN_GITHUB_AQUI":
        token = ""

    print(f"  Repositório alvo : https://github.com/{owner}/{repo} (branch: {branch})")
    print(f"  Link do site     : https://{owner}.github.io/{repo}/")
    print("-" * 76)

    # Verifica se já tem um token válido
    cfg = {"owner": owner, "repo": repo, "branch": branch, "token": token, "autor": autor}
    ok, msg = test_github_connection(cfg) if token else (False, "Token ainda não informado.")

    if not ok:
        token_url = "https://github.com/settings/tokens/new?description=Atlas+Poliedros+IC+Colli&scopes=repo,workflow"
        print("  Para o script enviar os arquivos ao seu GitHub, é necessário um Token de Acesso.")
        print("  Vou abrir no seu navegador a página do GitHub já com as permissões marcadas:")
        print(f"  -> {token_url}")
        print("\n  PASSO A PASSO NO NAVEGADOR:")
        print("    1. Role a página do GitHub até o final e clique no botão verde 'Generate token'.")
        print("    2. Copie o código gerado (ele começa com 'ghp_' ou 'github_pat_').")
        print("    3. Cole o código abaixo (botão direito do mouse ou Ctrl+V) e aperte ENTER.\n")
        try:
            webbrowser.open(token_url)
        except Exception:
            pass

        while True:
            novo_token = input("  Cole aqui o seu Token do GitHub: ").strip()
            if not novo_token:
                print("  [!] O token não pode ficar vazio. Gere o token na página aberta e cole aqui.")
                continue
            cfg["token"] = novo_token
            ok_t, msg_t = test_github_connection(cfg)
            if ok_t:
                print(f"  ✓ {msg_t}")
                break
            print(f"  [✗] {msg_t}\n  Tente colar o token novamente:")

    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[GitHub] Configuração salva localmente em {CONFIG_PATH}")

    print("\n[GitHub] Iniciando publicação completa do projeto e ativação do site...")
    ok_p, msg_p = publish_entire_project()
    print(f"\n{'✓' if ok_p else '✗'} {msg_p}")
    if ok_p:
        pages_url = f"https://{cfg['owner']}.github.io/{cfg['repo']}/"
        try:
            webbrowser.open(f"https://github.com/{cfg['owner']}/{cfg['repo']}")
        except Exception:
            pass
        print(f"\n  Acesse o site em ~1 minuto: {pages_url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sincronizador automático com GitHub — IC com Colli")
    parser.add_argument("--configurar", action="store_true", help="Assistente interativo de configuração do GitHub")
    parser.add_argument("--publicar-projeto", action="store_true", help="Publica o projeto inteiro no repositório GitHub")
    parser.add_argument("--sincronizar-solidos", action="store_true", help="Sincroniza mínimos globais novos de solidos/")
    parser.add_argument("--puxar", action="store_true", help="Puxa novos mínimos inéditos do GitHub para o site local")
    parser.add_argument("--forcar", action="store_true", help="Reenvia todos os mínimos globais válidos")
    args = parser.parse_args()

    if args.configurar:
        interactive_setup()
    elif args.publicar_projeto:
        ok, msg = publish_entire_project()
        print(msg)
        sys.exit(0 if ok else 1)
    elif args.puxar:
        ok, msg, count = pull_new_minima_from_github()
        print(f"[Pull] {msg} ({count} novo(s))")
        sys.exit(0 if ok else 1)
    else:
        ok, msg, count = sync_global_solutions_to_github(force_all=args.forcar)
        print(f"[Sync] {msg} ({count} arquivo(s))")
        sys.exit(0 if ok else 1)
