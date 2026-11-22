# ==============================================================================
# WEB INTERFACE — CONEXÃO AUTOMÁTICA EMBUTIDA NO CÓDIGO PRINCIPAL
# Permite que Marcelo, Thomas e Prof. Colli rodem APENAS standbyalone2.py
# (no Spyder, VS Code, PyCharm, IDLE ou terminal) e tenham envio automático
# em lote ao final de cada sólido via Cloudflare Worker (ou GitHub API)
# para o catálogo público no GitHub Pages.
# ==============================================================================

import json
import os
import sys
from pathlib import Path
from typing import Optional

WEB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))


def _configurar_primeira_vez_worker(cfg: dict) -> Optional[dict]:
    """
    Se a URL do Cloudflare Worker já estiver em web/config_worker.json, mas esta
    máquina ainda não tiver salvo autor + chave da equipe em web/config_github.json,
    faz uma pergunta rápida na 1ª execução e nunca mais pede.
    """
    from github_sync import CONFIG_PATH, load_github_config, test_worker_connection

    if os.environ.get("ATLAS_NON_INTERACTIVE") == "1":
        return cfg

    print("\n" + "-" * 72)
    print("  [Catálogo Online] Primeira execução nesta máquina!")
    print("  Ao final de cada sólido, os mínimos globais (sem autointerseção)")
    print("  podem ser enviados automaticamente para o catálogo da pesquisa:")
    print(f"  https://{cfg['owner']}.github.io/{cfg['repo']}/")
    print("-" * 72)

    try:
        resp = input("  Ativar envio automático para o site? [S/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return cfg

    if resp in ("n", "nao", "não"):
        print("  [Catálogo] Continuando em modo local nesta execução.\n")
        return cfg

    autor_padrao = cfg.get("autor") or os.environ.get("USERNAME") or os.environ.get("USER") or "Pesquisador"
    try:
        autor = input(f"  Seu nome [{autor_padrao}]: ").strip() or autor_padrao
    except (EOFError, KeyboardInterrupt):
        return cfg

    for tentativa in range(1, 4):
        try:
            team_key = input("  Cole a chave da equipe (TEAM_KEY): ").strip()
        except (EOFError, KeyboardInterrupt):
            return cfg

        if not team_key:
            print("  [Catálogo] Chave não informada; continuando em modo local.\n")
            return cfg

        candidato = dict(cfg)
        candidato["autor"] = autor
        candidato["team_key"] = team_key
        ok, msg = test_worker_connection(candidato)
        if ok:
            existente = {}
            if CONFIG_PATH.exists():
                try:
                    existente = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                except Exception:
                    existente = {}
            existente["autor"] = autor
            existente["team_key"] = team_key
            CONFIG_PATH.write_text(json.dumps(existente, indent=2, ensure_ascii=False), encoding="utf-8")
            novo_cfg = load_github_config() or candidato
            print(f"  [Catálogo] ✓ Conectado! {msg} (autor: {autor})\n")
            return novo_cfg

        if "TEAM_KEY" in msg or "401" in msg:
            print(f"  [Catálogo] ✗ {msg} (tentativa {tentativa}/3)")
            if tentativa < 3:
                continue
            print("  [Catálogo] Chave inválida; continuando em modo local nesta execução.\n")
            return cfg

        # Caso sem internet no momento, salva localmente para tentar quando voltar online
        existente = {}
        if CONFIG_PATH.exists():
            try:
                existente = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                existente = {}
        existente["autor"] = autor
        existente["team_key"] = team_key
        CONFIG_PATH.write_text(json.dumps(existente, indent=2, ensure_ascii=False), encoding="utf-8")
        novo_cfg = load_github_config() or candidato
        print(f"  [Catálogo] Aviso ao testar Worker: {msg}")
        print("  [Catálogo] A chave foi salva em web/config_github.json e o envio será tentado ao final do sólido.\n")
        return novo_cfg

    return cfg


def preparar_sincronizacao_automatica() -> bool:
    """
    Prepara a conexão remota no início de standbyalone2.py (sem thread em segundo plano).
    Na 1ª execução em uma máquina nova, pede nome + TEAM_KEY uma única vez.
    Retorna True se o envio automático ao final de cada sólido está ativo.
    """
    if os.environ.get("ATLAS_NO_SYNC") == "1":
        return False

    try:
        from github_sync import (
            has_remote_publish_credentials,
            has_worker_credentials,
            load_github_config,
        )

        cfg = load_github_config()

        if cfg and cfg.get("worker_url") and not has_remote_publish_credentials(cfg):
            cfg = _configurar_primeira_vez_worker(cfg)

        if not has_remote_publish_credentials(cfg):
            if cfg and not cfg.get("worker_url"):
                print(
                    "[Catálogo] Modo local ativo (para envio automático em equipe, "
                    "preencha worker_url em web/config_worker.json)."
                )
            else:
                print("[Catálogo] Modo local ativo nesta execução.")
            return False

        modo = "Cloudflare Worker" if has_worker_credentials(cfg) else "GitHub API"
        print(
            f"[Catálogo Sync] ✓ Ativo via {modo} "
            f"({cfg['owner']}/{cfg['repo']}@{cfg['branch']} · autor: {cfg['autor']})"
        )
        print(
            f"[Catálogo Sync]   Ao final de cada sólido, todos os mínimos globais (sem autointerseção) "
            f"serão enviados em lote para https://{cfg['owner']}.github.io/{cfg['repo']}/"
        )
        return True
    except Exception as e:
        print(f"[Catálogo] Aviso: sincronização indisponível ({e}). Seguindo em modo local.")
        return False


def sincronizar_solido_ao_final(nome_solido: str) -> None:
    """
    Envia em um único lote ao GitHub todos os novos mínimos globais (sem autointerseção)
    encontrados para `nome_solido` assim que o sólido termina (ou é interrompido por Ctrl+C).
    """
    if os.environ.get("ATLAS_NO_SYNC") == "1":
        return
    try:
        from github_sync import (
            has_remote_publish_credentials,
            load_github_config,
            sync_global_solutions_to_github,
        )

        cfg = load_github_config()
        if not has_remote_publish_credentials(cfg):
            return

        print(f"\n[Catálogo Sync] Sincronizando resultados globais de '{nome_solido}' com o site...", flush=True)
        ok, msg, count = sync_global_solutions_to_github(solid_filter=nome_solido, only_solidos=True)
        if count > 0:
            if ok:
                print(f"[Catálogo Sync] ✓ {count} arquivo(s) enviado(s) — {msg}", flush=True)
                print(
                    f"[Catálogo Sync]   O catálogo online será atualizado em ~1 minuto: "
                    f"https://{cfg['owner']}.github.io/{cfg['repo']}/",
                    flush=True,
                )
            else:
                print(
                    f"[Catálogo Sync] ✗ Falha ao enviar '{nome_solido}': {msg} "
                    f"(os arquivos continuam salvos localmente e serão reenviados na próxima execução).",
                    flush=True,
                )
        else:
            print(f"[Catálogo Sync] {msg}", flush=True)
    except Exception as e:
        print(f"[Catálogo Sync] Aviso ao sincronizar '{nome_solido}': {e}", flush=True)


def finalizar_sincronizacao_automatica() -> None:
    """
    Ao encerrar standbyalone2.py, verifica se restou algum mínimo global pendente de
    execuções anteriores (ex.: quando ficou sem internet) e envia em lote.
    """
    if os.environ.get("ATLAS_NO_SYNC") == "1":
        return
    try:
        from github_sync import (
            has_remote_publish_credentials,
            load_github_config,
            sync_global_solutions_to_github,
        )

        cfg = load_github_config()
        if not has_remote_publish_credentials(cfg):
            return

        ok, msg, count = sync_global_solutions_to_github(only_solidos=True)
        if count > 0:
            prefix = "✓" if ok else "✗"
            print(f"\n[Catálogo Sync] {prefix} Pendências anteriores: {count} arquivo(s) — {msg}", flush=True)
    except Exception as e:
        print(f"\n[Catálogo Sync] Aviso ao finalizar sincronização: {e}", flush=True)


# Compatibilidade com chamadas antigas
def iniciar_sincronizacao_automatica():
    return preparar_sincronizacao_automatica()


def encerrar_sincronizacao_automatica(_watcher=None) -> None:
    finalizar_sincronizacao_automatica()
