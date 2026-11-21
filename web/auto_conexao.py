# ==============================================================================
# WEB INTERFACE — CONEXÃO AUTOMÁTICA EMBUTIDA NO CÓDIGO PRINCIPAL
# Permite que Marcelo, Thomas e Prof. Colli rodem APENAS standbyalone2.py
# (no Spyder, VS Code ou terminal) e tenham envio automático em segundo plano
# via Cloudflare Worker (ou GitHub API) para o site do Atlas.
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

    # Só pula o prompt se ATLAS_NON_INTERACTIVE=1 (em Spyder/VS Code/PyCharm/IDLE input() funciona)
    if os.environ.get("ATLAS_NON_INTERACTIVE") == "1":
        return cfg

    print("\n" + "-" * 72)
    print("  [Atlas Online] Primeira execução nesta máquina!")
    print("  Todos os mínimos globais (sem autointerseção) podem ser enviados automaticamente para:")
    print(f"  https://{cfg['owner']}.github.io/{cfg['repo']}/")
    print("-" * 72)

    try:
        resp = input("  Ativar envio automático para o site do Atlas? [S/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return cfg

    if resp in ("n", "nao", "não"):
        print("  [Atlas] Continuando em modo local nesta execução.\n")
        return cfg

    autor_padrao = cfg.get("autor") or os.environ.get("USERNAME") or "Pesquisador"
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
            print("  [Atlas] Chave não informada; continuando em modo local.\n")
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
            print(f"  [Atlas] ✓ Conectado! {msg} (autor: {autor})\n")
            return novo_cfg

        if "TEAM_KEY" in msg or "401" in msg:
            print(f"  [Atlas] ✗ {msg} (tentativa {tentativa}/3)")
            if tentativa < 3:
                continue
            print("  [Atlas] Chave inválida; continuando em modo local nesta execução.\n")
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
        print(f"  [Atlas] Aviso ao testar Worker: {msg}")
        print("  [Atlas] A chave foi salva em web/config_github.json e o envio será tentado automaticamente.\n")
        return novo_cfg

    return cfg


def iniciar_sincronizacao_automatica():
    """
    Inicia o vigia automático em segundo plano (thread daemon) a partir do standbyalone2.py.
    Nunca interrompe nem atrasa o código principal em caso de falta de internet ou erro.
    """
    if os.environ.get("ATLAS_NO_SYNC") == "1":
        return None
    if os.environ.get("ATLAS_WATCHER_ACTIVE") == "1":
        return None

    try:
        from github_sync import (
            has_remote_publish_credentials,
            has_worker_credentials,
            load_github_config,
        )
        from vigia_resultados import AutomaticResultWatcher

        cfg = load_github_config()

        # Se a URL do Worker já está no repo, mas falta a chave local nesta máquina, pede 1 única vez
        if cfg and cfg.get("worker_url") and not has_remote_publish_credentials(cfg):
            cfg = _configurar_primeira_vez_worker(cfg)

        if not has_remote_publish_credentials(cfg):
            if cfg and not cfg.get("worker_url"):
                print(
                    "[Atlas] Modo local ativo (para envio automático em equipe, "
                    "preencha worker_url em web/config_worker.json)."
                )
            else:
                print("[Atlas] Modo local ativo nesta execução.")
            return None

        modo = "Cloudflare Worker" if has_worker_credentials(cfg) else "GitHub API"
        print(
            f"[Atlas Auto-Sync] ✓ Ativo via {modo} "
            f"({cfg['owner']}/{cfg['repo']}@{cfg['branch']} · autor: {cfg['autor']})"
        )
        print(
            f"[Atlas Auto-Sync]   Novos mínimos globais (sem autointerseção) serão verificados e enviados "
            f"automaticamente para https://{cfg['owner']}.github.io/{cfg['repo']}/"
        )

        os.environ["ATLAS_WATCHER_ACTIVE"] = "1"
        watcher = AutomaticResultWatcher(poll_seconds=2.0, debounce_seconds=4.0, only_solidos=True)
        watcher.start()
        return watcher
    except Exception as e:
        print(f"[Atlas] Aviso: sincronização automática indisponível ({e}). Seguindo em modo local.")
        return None


def encerrar_sincronizacao_automatica(watcher) -> None:
    """Garante o envio do último mínimo descoberto antes de encerrar standbyalone2.py."""
    if watcher is None or getattr(watcher, "_atlas_closed", False):
        return
    watcher._atlas_closed = True
    try:
        watcher.stop_and_flush()
    except Exception as e:
        print(f"[Atlas Auto-Sync] Aviso ao finalizar envio: {e}")
    finally:
        os.environ.pop("ATLAS_WATCHER_ACTIVE", None)
