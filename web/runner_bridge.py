# ==============================================================================
# WEB INTERFACE — PONTE DE EXECUÇÃO EM TEMPO REAL PARA standbyalone2.py
# Executa o código oficial standbyalone2.py SEM MODIFICAR NENHUM ARQUIVO OFICIAL,
# capturando prompts de input(), saída padrão em tempo real e interrupções
# controladas (KeyboardInterrupt) via protocolo JSON em linha.
# ==============================================================================

import builtins
import io
import json
import os
import queue
import runpy
import sys
import threading
import traceback
import _thread
from pathlib import Path


def main():
    # Garante DLLs BLAS/LAPACK de ambientes Conda/Spyder no Windows (ex: np.linalg.eigvalsh)
    if os.name == "nt":
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

    web_dir = Path(__file__).resolve().parent
    project_root = web_dir.parent
    main_script = project_root / "standbyalone2.py"

    # Garante UTF-8 nos canais reais de comunicação com o servidor web
    orig_stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    orig_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    write_lock = threading.Lock()

    def emit(event: dict):
        line = json.dumps(event, ensure_ascii=False)
        with write_lock:
            orig_stdout.write(line + "\n")
            orig_stdout.flush()

    class StreamCapture(io.TextIOBase):
        def __init__(self, channel: str):
            self.channel = channel
            self._buf = ""
            self._lock = threading.Lock()

        def write(self, s: str) -> int:
            if not s:
                return 0
            with self._lock:
                self._buf += s
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    emit({"type": self.channel, "text": line.rstrip("\r")})
            return len(s)

        def flush(self):
            with self._lock:
                if self._buf:
                    emit({"type": self.channel, "text": self._buf.rstrip("\r")})
                    self._buf = ""

        def isatty(self) -> bool:
            return False

    cap_out = StreamCapture("stdout")
    cap_err = StreamCapture("stderr")
    answer_queue: "queue.Queue[object]" = queue.Queue()
    stop_sentinel = object()

    def stdin_listener():
        buf = b""
        fd = sys.stdin.fileno()
        try:
            while True:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw_line, buf = buf.split(b"\n", 1)
                    raw = raw_line.decode("utf-8", errors="replace").strip()
                    if not raw:
                        continue
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    mtype = msg.get("type")
                    if mtype == "answer":
                        answer_queue.put(str(msg.get("value", "")))
                    elif mtype == "interrupt":
                        emit({"type": "status", "message": "Interrupção controlada (Ctrl+C) enviada ao algoritmo..."})
                        _thread.interrupt_main()
                    elif mtype == "eof":
                        answer_queue.put(stop_sentinel)
                        return
        except Exception:
            pass
        finally:
            answer_queue.put(stop_sentinel)

    listener = threading.Thread(target=stdin_listener, daemon=True)
    listener.start()

    def web_input(prompt: str = "") -> str:
        cap_out.flush()
        cap_err.flush()
        prompt_str = str(prompt) if prompt is not None else ""
        # Limpa quebras de linha iniciais para exibição elegante, preservando texto fiel
        emit({"type": "prompt", "prompt": prompt_str})
        val = answer_queue.get()
        if val is stop_sentinel:
            raise EOFError("Sessão encerrada pelo servidor.")
        return str(val)

    # Prepara ambiente idêntico à execução direta `python standbyalone2.py`
    os.chdir(str(project_root))
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    sys.stdout = cap_out
    sys.stderr = cap_err
    builtins.input = web_input

    emit({
        "type": "started",
        "script": str(main_script),
        "pid": os.getpid(),
    })

    exit_code = 0
    try:
        if not main_script.exists():
            raise FileNotFoundError(f"Arquivo oficial não encontrado: {main_script}")
        runpy.run_path(str(main_script), run_name="__main__")
    except (EOFError, SystemExit) as e:
        if isinstance(e, SystemExit) and isinstance(e.code, int):
            exit_code = e.code
    except KeyboardInterrupt:
        cap_out.flush()
        emit({"type": "stdout", "text": "Sessão interrompida pelo pesquisador (KeyboardInterrupt)."})
    except Exception:
        exit_code = 1
        cap_out.flush()
        cap_err.flush()
        emit({"type": "error", "traceback": traceback.format_exc()})
    finally:
        cap_out.flush()
        cap_err.flush()
        emit({"type": "finished", "exit_code": exit_code})
        try:
            orig_stdout.flush()
        except Exception:
            pass
        os._exit(exit_code)


if __name__ == "__main__":
    main()
