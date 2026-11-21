# ==============================================================================
# HELPER PARA GOOGLE COLAB — ENVIO AUTOMÁTICO DE MÍNIMOS GLOBAIS PARA O ATLAS
# Exemplo de uso na última célula do Colab:
#   import os
#   os.environ["GITHUB_REPO"] = "seu-usuario/poliedros-ic-colli"
#   os.environ["GITHUB_TOKEN"] = "github_pat_..."
#   os.environ["ATLAS_AUTOR"] = "Marcelo (Colab)"
#   from web.colab_enviar_atlas import enviar_solidos_colab
#   enviar_solidos_colab("solidos")
# ==============================================================================

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Tuple

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl._create_unverified_context()
_SSL_UNVERIFIED = ssl._create_unverified_context()


def _req(method: str, url: str, token: str, payload=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "IC-com-Colli-Colab-Sync/1.0",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    for ctx in (_SSL_CTX, _SSL_UNVERIFIED):
        r = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=45, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            if ctx is _SSL_CTX:
                continue
            return 0, str(e)
    return 0, "SSL error"


def enviar_solidos_colab(pasta_solidos: str = "solidos", branch: str = "main"):
    """
    Envia EXCLUSIVAMENTE os NOVOS mínimos globais SEM autointerseção em:
      solidos/*/minimos_globais/{convexos, nao_convexos}/sem_autointersecao/
    diretamente ao GitHub do Atlas, aplicando o protocolo de 4 passos:
      1. Novo mínimo na pasta
      2. Verifica se já existe mínimo para esse sólido no site (GitHub)
      3. Verifica se é igual (isomorfismo métrico)
      4. Se for igual, descarta; se for novo e cumprir todas as exigências, adiciona.
    """
    repo_full = os.environ.get("GITHUB_REPO", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    autor = os.environ.get("ATLAS_AUTOR", "Colab").strip()

    if "/" not in repo_full or not token:
        print("[Atlas Colab] Defina GITHUB_REPO ('usuario/repo') e GITHUB_TOKEN antes de chamar enviar_solidos_colab().")
        return False

    base_dir = Path(pasta_solidos)
    if not base_dir.exists():
        print(f"[Atlas Colab] Pasta '{pasta_solidos}' não encontrada.")
        return False

    validador = None
    construir_matriz_distancias = None
    try:
        from web.validador_cientifico import ValidadorCientifico
        from verificadores.isomorfismo import construir_matriz_distancias as _cmd
        validador = ValidadorCientifico()
        construir_matriz_distancias = _cmd
    except Exception:
        pass

    api = f"https://api.github.com/repos/{repo_full}"
    files: List[Tuple[str, bytes]] = []
    solids = set()

    for solid_dir in sorted(base_dir.iterdir()):
        if not solid_dir.is_dir():
            continue
        sid = solid_dir.name
        gdir = solid_dir / "minimos_globais"
        if not gdir.is_dir():
            continue

        # Carrega mínimos já existentes no site (GitHub) para este sólido
        site_solutions = []
        if validador is not None and construir_matriz_distancias is not None:
            st_rem, rem_data = _req("GET", f"{api}/contents/docs/data/solids/{sid}.json?ref={branch}", token)
            if st_rem == 200 and isinstance(rem_data, dict) and rem_data.get("content"):
                try:
                    rem_payload = json.loads(base64.b64decode(rem_data["content"]).decode("utf-8"))
                    for rsol in (rem_payload.get("global_solutions") or []):
                        if rsol.get("vertices"):
                            rc = dict(rsol)
                            rc["already_on_site"] = True
                            rc["_dist_matrix"] = construir_matriz_distancias(rc["vertices"])
                            site_solutions.append(rc)
                except Exception:
                    pass

        for sub_name in ("convexos", "nao_convexos"):
            sdir = gdir / sub_name / "sem_autointersecao"
            if not sdir.is_dir():
                continue
            for jf in sorted(sdir.glob("*.json")):
                stem = jf.stem
                if validador is not None and construir_matriz_distancias is not None:
                    try:
                        jdata = json.loads(jf.read_text(encoding="utf-8"))
                        vc = jdata.get("vc") or []
                    except Exception:
                        continue
                    avaliacao = validador.avaliar_novo_minimo_4_passos(
                        sid,
                        {"solution_id": stem, "vertices": vc},
                        site_solutions,
                    )
                    if not avaliacao["accepted"]:
                        print(f"  [Atlas Colab] {sid}/{stem}: {avaliacao['reason']}")
                        continue
                    site_solutions.append({
                        "solution_id": stem,
                        "vertices": vc,
                        "already_on_site": True,
                        "_dist_matrix": construir_matriz_distancias(vc),
                    })

                for cand_f in (jf, sdir / f"{stem}.txt", sdir / f"{stem}_pythonscad.py"):
                    if cand_f.is_file():
                        files.append(
                            (
                                f"solidos/{sid}/minimos_globais/{sub_name}/sem_autointersecao/{cand_f.name}",
                                cand_f.read_bytes(),
                            )
                        )
                solids.add(sid)

    if not files:
        print("[Atlas Colab] Nenhum mínimo global encontrado para enviar.")
        return True

    api = f"https://api.github.com/repos/{repo_full}"
    for _ in range(3):
        st, ref = _req("GET", f"{api}/git/ref/heads/{branch}", token)
        if st != 200:
            print(f"[Atlas Colab] Erro ao acessar branch '{branch}': {ref}")
            return False
        head_sha = ref["object"]["sha"]
        st, commit = _req("GET", f"{api}/git/commits/{head_sha}", token)
        base_tree = commit["tree"]["sha"]

        entries = []
        for path_posix, raw in files:
            st_b, blob = _req("POST", f"{api}/git/blobs", token, {
                "content": base64.b64encode(raw).decode("ascii"),
                "encoding": "base64",
            })
            if st_b not in (200, 201):
                print(f"[Atlas Colab] Falha ao enviar {path_posix}: {blob}")
                return False
            entries.append({"path": path_posix, "mode": "100644", "type": "blob", "sha": blob["sha"]})

        st_t, tree = _req("POST", f"{api}/git/trees", token, {"base_tree": base_tree, "tree": entries})
        msg = f"resultado({', '.join(sorted(solids)[:5])}): envio automático Colab [{autor}]"
        st_c, new_c = _req("POST", f"{api}/git/commits", token, {"message": msg, "tree": tree["sha"], "parents": [head_sha]})
        st_p, _ = _req("PATCH", f"{api}/git/refs/heads/{branch}", token, {"sha": new_c["sha"], "force": False})
        if st_p == 200:
            print(f"[Atlas Colab] ✓ {len(files)} arquivo(s) enviados para {repo_full}! O site será atualizado em ~1 min.")
            return True
        time.sleep(1.0)
    return False
