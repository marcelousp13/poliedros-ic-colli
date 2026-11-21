# ==============================================================================
# WEB INTERFACE — VIGIA AUTOMÁTICO DE RESULTADOS (MODO 100% AUTOMÁTICO)
# Observa a pasta solidos/ em segundo plano enquanto standbyalone2.py executa
# (sem alterar UMA ÚNICA LINHA dos códigos oficiais).
# Assim que qualquer mínimo global novo é salvo em solidos/<Sólido>/globais/,
# valida matematicamente e sincroniza automaticamente com o GitHub — disparando
# o GitHub Actions que atualiza o site público em ~1 minuto!
# ==============================================================================

import argparse
import os
import runpy
import sys
import threading
import time
from pathlib import Path
from typing import Dict


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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from geometry_analyzer import iter_global_category_dirs
from github_sync import (
    has_worker_credentials,
    load_github_config,
    sync_global_solutions_to_github,
)


def _snapshot_global_files(solidos_dir: Path) -> Dict[str, float]:
    """Observa EXCLUSIVAMENTE solidos/<Sólido>/minimos_globais/ (convexos e nao_convexos)."""
    snap: Dict[str, float] = {}
    if not solidos_dir.exists():
        return snap
    for solid_dir in solidos_dir.iterdir():
        if not solid_dir.is_dir():
            continue
        for _, cat_dir in iter_global_category_dirs(solid_dir):
            for f in cat_dir.iterdir():
                if f.is_file() and f.suffix.lower() in (".json", ".txt", ".py"):
                    try:
                        snap[str(f)] = f.stat().st_mtime
                    except OSError:
                        pass
    return snap


class AutomaticResultWatcher:
    """Thread leve que monitora solidos/*/globais/ e envia descobertas ao GitHub com debounce."""

    def __init__(
        self,
        poll_seconds: float = 2.0,
        debounce_seconds: float = 4.0,
        only_solidos: bool = True,
    ):
        self.solidos_dir = PROJECT_ROOT / "solidos"
        self.poll_seconds = poll_seconds
        self.debounce_seconds = debounce_seconds
        self.only_solidos = only_solidos
        self._stop_evt = threading.Event()
        self._sync_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop_and_flush(self):
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=30.0)
        # Sincronização final garantida antes de encerrar (sem corrida com _loop)
        with self._sync_lock:
            ok, msg, count = sync_global_solutions_to_github(only_solidos=self.only_solidos)
            if count > 0:
                prefix = "✓" if ok else "✗"
                print(f"\n[Atlas Auto-Sync] {prefix} {count} arquivo(s) processado(s) — {msg}", flush=True)

    def _loop(self):
        last_snap = _snapshot_global_files(self.solidos_dir)
        pending_since: float | None = None

        while not self._stop_evt.is_set():
            time.sleep(self.poll_seconds)
            cur_snap = _snapshot_global_files(self.solidos_dir)
            if cur_snap != last_snap:
                last_snap = cur_snap
                pending_since = time.time()

            if pending_since is not None and (time.time() - pending_since) >= self.debounce_seconds:
                pending_since = None
                try:
                    with self._sync_lock:
                        ok, msg, count = sync_global_solutions_to_github(only_solidos=self.only_solidos)
                    if count > 0:
                        prefix = "✓" if ok else "✗"
                        print(f"\n[Atlas Auto-Sync] {prefix} {msg} ({count} arq.)", flush=True)
                except Exception as e:
                    print(f"\n[Atlas Auto-Sync] Aviso: {e}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Vigia automático de resultados para o Atlas no GitHub")
    parser.add_argument("--executar-main", action="store_true", help="Roda standbyalone2.py com envio automático em segundo plano")
    parser.add_argument("--agora", action="store_true", help="Apenas sincroniza todos os mínimos globais novos atuais e encerra")
    parser.add_argument("--pasta", nargs="*", default=[], help="Importa novos mínimos de pasta(s) externa(s) (ex.: pasta de Colli ou Thomas) aplicando os 4 passos")
    args = parser.parse_args()

    cfg = load_github_config()
    if cfg:
        print(f"[Atlas Auto-Sync] Conectado a {cfg['owner']}/{cfg['repo']}@{cfg['branch']} (autor: {cfg['autor']})")
    else:
        print("[Atlas Auto-Sync] Modo local ativo (para sincronizar com GitHub remoto, execute web\\configurar_github.bat).")

    if args.pasta:
        from importar_solidos import importar_pasta
        importar_pasta([Path(p) for p in args.pasta], apply_copy=True, update_site=True)

    if args.agora or args.pasta:
        ok, msg, count = sync_global_solutions_to_github()
        print(f"[Atlas Auto-Sync] {'✓' if ok else '✗'} {msg} ({count} arquivo(s))")
        sys.exit(0 if ok else 1)

    watcher = AutomaticResultWatcher()
    watcher.start()

    if args.executar_main:
        main_script = PROJECT_ROOT / "standbyalone2.py"
        os.chdir(str(PROJECT_ROOT))
        os.environ["ATLAS_WATCHER_ACTIVE"] = "1"
        try:
            runpy.run_path(str(main_script), run_name="__main__")
        except KeyboardInterrupt:
            pass
        finally:
            os.environ.pop("ATLAS_WATCHER_ACTIVE", None)
            watcher.stop_and_flush()
    else:
        print("[Atlas Auto-Sync] Observando solidos/ em segundo plano... (Ctrl+C para encerrar)")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            watcher.stop_and_flush()


if __name__ == "__main__":
    main()
