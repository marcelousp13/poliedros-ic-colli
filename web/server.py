# ==============================================================================
# WEB INTERFACE — SERVIDOR LOCAL DO ATLAS VIVO DE RESULTADOS (IC COM COLLI)
# Observa solidos/ e faces.txt em tempo real (absorção automática via SSE),
# valida soluções com os módulos oficiais, deduplica por isomorfismo métrico,
# renderiza fotos via PythonSCAD (cache RAM + disco + docs/renders/) e serve
# a interface em http://127.0.0.1:8765 com latência sub-milissegundo.
# ==============================================================================

import argparse
import gzip
import hashlib
import json
import mimetypes
mimetypes.add_type("image/webp", ".webp")
import os
import queue
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


def _ensure_conda_dll_paths():
    if os.name != "nt":
        return
    prefix = Path(sys.prefix)
    extra_dirs = [prefix / "Library" / "bin", prefix / "DLLs", prefix]
    current_path = os.environ.get("PATH", "")
    prepend = []
    for d in extra_dirs:
        if d.is_dir():
            ds = str(d)
            if ds.lower() not in current_path.lower():
                prepend.append(ds)
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(ds)
                except Exception:
                    pass
    if prepend:
        os.environ["PATH"] = os.pathsep.join(prepend) + os.pathsep + current_path


_ensure_conda_dll_paths()

WEB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_DIR.parent
STATIC_DIR = WEB_DIR / "static"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from geometry_analyzer import (
    CATALOG_SEGMENTS,
    GLOBAL_DIR_NAMES,
    NO_INTERSECTION_SUBDIR_NAMES,
    CatalogService,
    compact_execution_metadata,
    iter_global_category_dirs,
)
from github_sync import (
    _fetch_pages_json_file,
    has_remote_publish_credentials,
    load_github_config,
    pull_new_minima_from_github,
    sync_global_solutions_to_github,
)
from scad_renderer import CAMERA_PRESETS, PythonSCADRenderer
from validador_cientifico import ValidadorCientifico
from verificadores.isomorfismo import construir_matriz_distancias


def _safe_slug(text: str) -> str:
    import re
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    return slug.strip("_") or "solid"


class VerifiedCatalogService:
    """
    Envolve CatalogService aplicando o protocolo oficial de 4 passos:
      1. Novo mínimo detectado em solidos/
      2. Verifica se já existe mínimo para esse sólido no site (docs/data/solids/)
      3. Verifica se é igual (isomorfismo métrico)
      4. Se for igual, descarta; se for novo e cumprir todas as exigências, adiciona no site.
    Mantém snapshot pré-serializado (JSON + gzip + ETag) em memória para respostas < 1 ms.
    """

    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = Path(project_root)
        self.base = CatalogService(project_root)
        self.validador = ValidadorCientifico()
        self._lock = threading.RLock()
        self._version: int = 0
        self._catalog_obj: Optional[Dict[str, Any]] = None
        self._catalog_payload: Optional[Tuple[bytes, bytes, str]] = None  # (raw, gz, etag)
        self._detail_obj_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._detail_payload_cache: Dict[str, Tuple[bytes, bytes, str]] = {}
        self._geom_hash_index: Dict[Tuple[str, str], str] = {}

    def _load_site_baseline_for_solid(self, solid_id: str) -> List[Dict[str, Any]]:
        """Carrega os mínimos que JÁ existem no site (docs/data/solids/<slug>.json) para `solid_id`."""
        slug = _safe_slug(solid_id)
        site_json = self.project_root / "docs" / "data" / "solids" / f"{slug}.json"
        if not site_json.is_file():
            return []
        try:
            payload = json.loads(site_json.read_text(encoding="utf-8"))
        except Exception:
            return []
        raw_sols = payload.get("global_solutions") or (
            (payload.get("convex_solutions") or []) + (payload.get("nonconvex_solutions") or [])
        )
        baseline: List[Dict[str, Any]] = []
        for s in raw_sols:
            verts = s.get("vertices")
            if not verts:
                continue
            sc = dict(s)
            sc["already_on_site"] = True
            sc["_dist_matrix"] = construir_matriz_distancias(verts)
            baseline.append(sc)
        return baseline

    def invalidate(self) -> None:
        with self._lock:
            self._version += 1
            self._catalog_obj = None
            self._catalog_payload = None
            self._detail_obj_cache.clear()
            self._detail_payload_cache.clear()

    def get_geom_hash(self, solid_id: str, sol_id: str) -> Optional[str]:
        with self._lock:
            hit = self._geom_hash_index.get((solid_id, sol_id))
            if hit:
                return hit
        self.get_catalog()
        with self._lock:
            return self._geom_hash_index.get((solid_id, sol_id))

    def get_catalog(self) -> Dict[str, Any]:
        with self._lock:
            if self._catalog_obj is not None:
                return self._catalog_obj

        built = self._build_catalog()
        raw = json.dumps(built, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        gz = gzip.compress(raw, compresslevel=5)
        etag = f'"{hashlib.sha1(raw).hexdigest()[:16]}"'

        with self._lock:
            self._catalog_obj = built
            self._catalog_payload = (raw, gz, etag)
            return built

    def get_catalog_payload(self) -> Tuple[bytes, bytes, str]:
        with self._lock:
            if self._catalog_payload is not None:
                return self._catalog_payload
        self.get_catalog()
        with self._lock:
            assert self._catalog_payload is not None
            return self._catalog_payload

    def _build_catalog(self) -> Dict[str, Any]:
        raw = self.base.get_full_catalog(include_geometry=False)
        solids_with_global = 0
        solids_with_convex = 0
        solids_with_nonconvex = 0
        total_globals = 0
        total_convex = 0
        total_nonconvex = 0
        new_geom_index: Dict[Tuple[str, str], str] = {}

        def _compact_from_detail(s: Dict[str, Any]) -> Dict[str, Any]:
            conv = s.get("convexity") or {}
            out = {
                "solution_id": s["solution_id"],
                "geom_hash": s.get("geom_hash", ""),
                "source_folder": s["source_folder"],
                "fval": s["fval"],
                "timestamp": s["timestamp"],
                "is_convex": s["is_convex"],
                "classification": s["classification"],
                "max_dihedral_deg": conv.get("max_dihedral_deg"),
                "volume_ratio": conv.get("volume_ratio"),
            }
            ex = compact_execution_metadata(s.get("execucao"))
            if ex:
                out["execucao"] = ex
            return out

        for item in raw["solids"]:
            sid = item["id"]
            slug = _safe_slug(sid)
            has_site_baseline = (self.project_root / "docs" / "data" / "solids" / f"{slug}.json").is_file()
            if item["global_count"] > 0 or has_site_baseline:
                detail = self.get_solid_detail(sid)
                if detail:
                    conv_list = [_compact_from_detail(s) for s in detail["convex_solutions"]]
                    nconv_list = [_compact_from_detail(s) for s in detail["nonconvex_solutions"]]
                    all_list = conv_list + nconv_list
                    primary_any = conv_list[0] if conv_list else (nconv_list[0] if nconv_list else None)

                    item["convex_solutions"] = conv_list
                    item["nonconvex_solutions"] = nconv_list
                    item["global_solutions"] = all_list
                    item["convex_count"] = len(conv_list)
                    item["nonconvex_count"] = len(nconv_list)
                    item["global_count"] = len(all_list)
                    item["has_convex_global"] = bool(conv_list)
                    item["has_nonconvex_global"] = bool(nconv_list)
                    item["has_global"] = bool(all_list)
                    item["primary_convex"] = conv_list[0] if conv_list else None
                    item["primary_global"] = primary_any
                    item["primary_nonconvex"] = nconv_list[0] if nconv_list else None

                for s in item["global_solutions"]:
                    gh = s.get("geom_hash")
                    if gh:
                        new_geom_index[(sid, s["solution_id"])] = gh

            total_globals += item["global_count"]
            total_convex += item["convex_count"]
            total_nonconvex += item["nonconvex_count"]
            if item["has_global"]:
                solids_with_global += 1
            if item["has_convex_global"]:
                solids_with_convex += 1
            if item["has_nonconvex_global"]:
                solids_with_nonconvex += 1

        raw["segments"] = CATALOG_SEGMENTS
        raw["summary"]["elementary_solids"] = sum(1 for s in raw["solids"] if s.get("is_elementary"))
        raw["summary"]["solids_with_global"] = solids_with_global
        raw["summary"]["solids_with_convex_global"] = solids_with_convex
        raw["summary"]["solids_with_nonconvex_global"] = solids_with_nonconvex
        raw["summary"]["total_global_solutions"] = total_globals
        raw["summary"]["total_convex_solutions"] = total_convex
        raw["summary"]["total_nonconvex_solutions"] = total_nonconvex
        raw["mode"] = "local"
        with self._lock:
            self._geom_hash_index.update(new_geom_index)
        return raw

    def get_solid_detail(self, solid_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if solid_id in self._detail_obj_cache:
                return self._detail_obj_cache[solid_id]

        detail = self.base.get_solid_detail(solid_id)
        if detail is None:
            with self._lock:
                self._detail_obj_cache[solid_id] = None
            return None

        # 0. Carrega os mínimos que JÁ existem no site (docs/data/solids/<slug>.json)
        site_solutions: List[Dict[str, Any]] = self._load_site_baseline_for_solid(solid_id)
        existing_ids = {s["solution_id"]: s for s in site_solutions}

        # 1–4. Avalia candidatos encontrados em solidos/<solid_id>/minimos_globais/
        candidates = detail.get("global_solutions", [])
        for cand in candidates:
            sol_id = cand["solution_id"]
            gh = cand.get("geom_hash", "")
            if sol_id in existing_ids and existing_ids[sol_id].get("geom_hash") == gh:
                if cand.get("execucao") and not existing_ids[sol_id].get("execucao"):
                    existing_ids[sol_id]["execucao"] = cand["execucao"]
                continue

            if not detail.get("has_topology"):
                continue

            avaliacao = self.validador.avaliar_novo_minimo_4_passos(solid_id, cand, site_solutions)
            if not avaliacao["accepted"]:
                continue

            cand_copy = dict(cand)
            cand_copy["fval"] = float(avaliacao["fval_recomputed"])
            cand_copy["is_convex"] = bool(avaliacao["is_convex"])
            cand_copy["classification"] = avaliacao["classification"]
            cand_copy["source_folder"] = avaliacao["source_folder"]
            cand_copy["convexity"] = {
                k: v for k, v in avaliacao["convexity"].items() if k != "oriented_faces"
            }
            cand_copy["self_intersection"] = avaliacao["self_intersection"]
            cand_copy["has_self_intersection"] = False
            cand_copy["faces"] = avaliacao["faces_oriented"]
            if cand_copy["solution_id"] in existing_ids:
                cand_copy["solution_id"] = f"{cand_copy['solution_id']}_{gh[:6]}"
            cand_copy["already_on_site"] = True
            cand_copy["_dist_matrix"] = construir_matriz_distancias(cand_copy["vertices"])
            site_solutions.append(cand_copy)
            existing_ids[cand_copy["solution_id"]] = cand_copy

        def _strip_internal(s: Dict[str, Any]) -> Dict[str, Any]:
            return {k: v for k, v in s.items() if k not in ("_dist_matrix", "already_on_site")}

        conv = [_strip_internal(s) for s in site_solutions if s.get("source_folder") == "convexos"]
        nconv = [_strip_internal(s) for s in site_solutions if s.get("source_folder") != "convexos"]
        conv.sort(key=lambda s: (s["fval"], s["timestamp"]))
        nconv.sort(key=lambda s: (s["fval"], s["timestamp"]))
        detail["convex_solutions"] = conv
        detail["nonconvex_solutions"] = nconv
        detail["global_solutions"] = conv + nconv

        with self._lock:
            self._detail_obj_cache[solid_id] = detail
            for s in detail["global_solutions"]:
                gh = s.get("geom_hash")
                if gh:
                    self._geom_hash_index[(solid_id, s["solution_id"])] = gh
        return detail

    def get_solid_detail_payload(self, solid_id: str) -> Optional[Tuple[bytes, bytes, str]]:
        with self._lock:
            hit = self._detail_payload_cache.get(solid_id)
            if hit is not None:
                return hit

        detail = self.get_solid_detail(solid_id)
        if detail is None:
            return None
        raw = json.dumps(detail, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        gz = gzip.compress(raw, compresslevel=5)
        etag = f'"{hashlib.sha1(raw).hexdigest()[:16]}"'
        payload = (raw, gz, etag)
        with self._lock:
            self._detail_payload_cache[solid_id] = payload
        return payload

    def warm_startup_async(self, renderer: PythonSCADRenderer) -> None:
        """Pré-aquece o catálogo em RAM e agenda pré-renderização de eventuais fotos faltantes."""
        def _worker():
            try:
                cat = self.get_catalog()
                for item in cat.get("solids", []):
                    if not item.get("has_global"):
                        continue
                    sid = item["id"]
                    for sol in item.get("global_solutions", []):
                        sol_id = sol["solution_id"]
                        gh = sol.get("geom_hash")
                        if renderer._find_docs_render(sid, "iso", gh) is not None:
                            # Carrega os bytes PNG do ângulo principal em RAM (~60 KB cada) para entrega <1ms
                            renderer.get_png_bytes(sid, sol_id, None, preset="iso", geom_hash=gh)
                        else:
                            files = self.base.find_solution_files(sid, sol_id)
                            if files and files.get("scad"):
                                renderer.enqueue_prewarm(sid, sol_id, files["scad"], preset="iso", geom_hash=gh)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True, name="atlas-warmup").start()


class SolidosLiveWatcher:
    """
    Observa EXCLUSIVAMENTE solidos/*/minimos_globais/ e faces.txt em segundo plano
    com custo de CPU próximo de zero (os.scandir, sem re-instanciar CarregadorTopologia).
    """

    def __init__(
        self,
        catalog: VerifiedCatalogService,
        renderer: PythonSCADRenderer,
        poll_interval: float = 3.0,
    ):
        self.catalog = catalog
        self.renderer = renderer
        self.poll_interval = float(poll_interval)
        self._lock = threading.RLock()
        self._subscribers: List["queue.Queue[Dict[str, Any]]"] = []
        self._stop = threading.Event()
        self._faces_path = self.catalog.base._get_faces_file_path()
        self._last_snapshot = self._take_snapshot()

    def _take_snapshot(self) -> Dict[str, Tuple[int, int]]:
        snap: Dict[str, Tuple[int, int]] = {}
        try:
            st = self._faces_path.stat()
            snap[str(self._faces_path)] = (st.st_mtime_ns, st.st_size)
        except OSError:
            pass

        solidos_dir = PROJECT_ROOT / "solidos"
        if not solidos_dir.is_dir():
            return snap

        try:
            with os.scandir(solidos_dir) as it:
                for entry in it:
                    if not entry.is_dir():
                        continue
                    sdir = Path(entry.path)
                    for _, cat_dir in iter_global_category_dirs(sdir):
                        try:
                            with os.scandir(cat_dir) as fit:
                                for fe in fit:
                                    if fe.is_file() and fe.name.lower().endswith((".json", ".py")):
                                        try:
                                            fst = fe.stat()
                                            snap[fe.path] = (fst.st_mtime_ns, fst.st_size)
                                        except OSError:
                                            pass
                        except OSError:
                            pass
        except OSError:
            pass
        return snap

    def subscribe(self) -> "queue.Queue[Dict[str, Any]]":
        q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[Dict[str, Any]]"):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def broadcast(self, event: str, data: Dict[str, Any]):
        msg = {"event": event, "data": data}
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="solidos-watcher").start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        solidos_dir = (PROJECT_ROOT / "solidos").resolve()
        while not self._stop.wait(self.poll_interval):
            try:
                cur = self._take_snapshot()
                if cur != self._last_snapshot:
                    added = [p for p in cur if p not in self._last_snapshot]
                    self._last_snapshot = cur

                    # Contagem anterior de soluções aceitas por sólido para distinguir
                    # novos mínimos inéditos de duplicatas isométricas descartadas
                    prev_counts: Dict[str, int] = {}
                    try:
                        prev_cat = self.catalog.get_catalog()
                        prev_counts = {
                            item["id"]: int(item.get("global_count", 0))
                            for item in prev_cat.get("solids", [])
                        }
                    except Exception:
                        prev_counts = {}

                    # Invalida cache em RAM imediatamente para refletir a alteração
                    self.catalog.invalidate()

                    touched_solids = set()
                    for p_str in added:
                        p = Path(p_str).resolve()
                        try:
                            rel = p.relative_to(solidos_dir)
                        except ValueError:
                            continue
                        if len(rel.parts) >= 4 and rel.parts[1] in GLOBAL_DIR_NAMES and "com_autointersecao" not in rel.parts:
                            sid = rel.parts[0]
                            touched_solids.add(sid)
                            if p.name.endswith("_pythonscad.py") and (len(rel.parts) == 4 or rel.parts[3] in NO_INTERSECTION_SUBDIR_NAMES):
                                sol_id = p.stem.replace("_pythonscad", "")
                                self.renderer.enqueue_prewarm(sid, sol_id, p, preset="iso")

                    accepted_new_solids: List[str] = []
                    discarded_solids: List[str] = []
                    try:
                        new_cat = self.catalog.get_catalog()
                        new_counts = {
                            item["id"]: int(item.get("global_count", 0))
                            for item in new_cat.get("solids", [])
                        }
                        for sid in sorted(touched_solids):
                            if new_counts.get(sid, 0) > prev_counts.get(sid, 0):
                                accepted_new_solids.append(sid)
                            else:
                                discarded_solids.append(sid)
                    except Exception:
                        accepted_new_solids = sorted(touched_solids)

                    self.broadcast("catalog_updated", {
                        "solids": accepted_new_solids,
                        "discarded_solids": discarded_solids,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    })
            except Exception:
                pass


class RemoteAtlasPoller:
    """
    Verifica periodicamente o Atlas público (GitHub Pages) para trazer automaticamente
    novos mínimos globais descobertos por outros membros da equipe (em outras máquinas)
    para o servidor local em tempo real (sem exigir ação manual).
    """

    def __init__(self, poll_interval: float = 45.0):
        self.poll_interval = float(poll_interval)
        self._stop = threading.Event()
        self._last_remote_sig: Optional[str] = None

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="remote-atlas-poller").start()

    def stop(self):
        self._stop.set()

    def _check_once(self) -> int:
        cfg = load_github_config()
        if not cfg or not cfg.get("owner") or not cfg.get("repo"):
            return 0
        remote_cat = _fetch_pages_json_file(cfg, "data/catalog.json")
        if not isinstance(remote_cat, dict):
            return 0
        summary = remote_cat.get("summary") or {}
        sig = f"{remote_cat.get('generated_at', '')}|{summary.get('total_global_solutions', 0)}"
        if sig == self._last_remote_sig:
            return 0
        self._last_remote_sig = sig
        ok, msg, added = pull_new_minima_from_github(rebuild_docs=False)
        if ok and added > 0:
            print(f"[Atlas Remoto -> Local] ✓ {msg}", flush=True)
        return added

    def _loop(self):
        # Primeira verificação suave 4s após subir o servidor
        if self._stop.wait(4.0):
            return
        while not self._stop.is_set():
            try:
                self._check_once()
            except Exception:
                pass
            if self._stop.wait(self.poll_interval):
                break


class StaticFileCache:
    """Cache leve em memória (com gzip e ETag) para arquivos em web/static/."""

    def __init__(self, static_dir: Path):
        self.static_dir = static_dir.resolve()
        self._lock = threading.Lock()
        self._entries: Dict[str, Tuple[int, int, bytes, bytes, str, str]] = {}

    def get(self, rel_path: str) -> Optional[Tuple[bytes, bytes, str, str]]:
        safe = (self.static_dir / rel_path).resolve()
        if not str(safe).startswith(str(self.static_dir)) or not safe.is_file():
            return None
        st = safe.stat()
        key = str(safe)
        with self._lock:
            hit = self._entries.get(key)
            if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
                return hit[2], hit[3], hit[4], hit[5]

        raw = safe.read_bytes()
        ctype, _ = mimetypes.guess_type(key)
        if not ctype:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        gz = gzip.compress(raw, compresslevel=5) if len(raw) > 512 else raw
        etag = f'"{hashlib.sha1(raw).hexdigest()[:16]}"'
        with self._lock:
            self._entries[key] = (st.st_mtime_ns, st.st_size, raw, gz, ctype, etag)
        return raw, gz, ctype, etag


class AtlasHTTPServer(ThreadingHTTPServer):
    # No Windows, SO_REUSEADDR permite que dois processos escutem a mesma porta silenciosamente!
    allow_reuse_address = os.name != "nt"
    daemon_threads = True
    request_queue_size = 64

    def __init__(
        self,
        server_address,
        handler_cls,
        catalog: VerifiedCatalogService,
        renderer: PythonSCADRenderer,
        watcher: SolidosLiveWatcher,
    ):
        self.catalog = catalog
        self.renderer = renderer
        self.watcher = watcher
        self.static_cache = StaticFileCache(STATIC_DIR)
        super().__init__(server_address, handler_cls)

    def handle_error(self, request, client_address):
        _, exc_val, _ = sys.exc_info()
        if isinstance(exc_val, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class AtlasRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 10  # evita threads/sockets keep-alive presos indefinidamente

    def log_message(self, format: str, *args):
        if os.environ.get("IC_WEB_DEBUG") == "1":
            super().log_message(format, *args)

    @property
    def srv(self) -> AtlasHTTPServer:
        return self.server  # type: ignore[return-value]

    def _accepts_gzip(self) -> bool:
        return "gzip" in (self.headers.get("Accept-Encoding") or "").lower()

    def _check_not_modified(self, etag: Optional[str], cache_control: str) -> bool:
        if etag and self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache_control)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        return False

    def _send_cached_payload(
        self,
        raw: bytes,
        gz: bytes,
        content_type: str,
        etag: str,
        cache_control: str = "no-cache",
    ):
        if self._check_not_modified(etag, cache_control):
            return
        use_gz = self._accepts_gzip() and gz is not raw and len(gz) < len(raw)
        body = gz if use_gz else raw
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("ETag", etag)
        if use_gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj: Any, status: int = HTTPStatus.OK):
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        use_gz = self._accepts_gzip() and len(raw) > 512
        body = gzip.compress(raw, compresslevel=5) if use_gz else raw
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if use_gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        data: bytes,
        content_type: str,
        cache_control: str = "no-cache",
        filename: Optional[str] = None,
        etag: Optional[str] = None,
    ):
        if etag and self._check_not_modified(etag, cache_control):
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        if etag:
            self.send_header("ETag", etag)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if path in ("/", "/index.html"):
                self._serve_static("index.html")
                return
            if path.startswith("/static/"):
                self._serve_static(path[len("/static/"):])
                return

            if path == "/api/system/status":
                gh = load_github_config()
                self._send_json({
                    "mode": "local",
                    "python_version": sys.version.split()[0],
                    "render_engine": self.srv.renderer.engine_name,
                    "pythonscad_available": self.srv.renderer.available,
                    "github_configured": has_remote_publish_credentials(gh),
                    "github_repo": f"{gh['owner']}/{gh['repo']}" if gh else None,
                    "official_files": self.srv.catalog.base.get_official_files_status(),
                    "camera_presets": list(CAMERA_PRESETS.keys()),
                })
                return

            if path == "/api/catalog":
                raw, gz, etag = self.srv.catalog.get_catalog_payload()
                self._send_cached_payload(raw, gz, "application/json; charset=utf-8", etag, cache_control="no-cache")
                return

            if path.startswith("/api/solid/"):
                solid_id = urllib.parse.unquote(path[len("/api/solid/"):])
                payload = self.srv.catalog.get_solid_detail_payload(solid_id)
                if payload is None:
                    self._send_json({"error": f"Sólido '{solid_id}' não encontrado."}, HTTPStatus.NOT_FOUND)
                    return
                raw, gz, etag = payload
                self._send_cached_payload(raw, gz, "application/json; charset=utf-8", etag, cache_control="no-cache")
                return

            if path.startswith("/api/render/"):
                rest = path[len("/api/render/"):]
                parts = rest.split("/", 1)
                if len(parts) != 2 or not (parts[1].endswith(".png") or parts[1].endswith(".webp")):
                    self._send_json({"error": "Rota inválida."}, HTTPStatus.BAD_REQUEST)
                    return
                solid_id = urllib.parse.unquote(parts[0])
                sol_part = parts[1][:-5] if parts[1].endswith(".webp") else parts[1][:-4]
                sol_id = urllib.parse.unquote(sol_part)
                preset = (qs.get("preset", ["iso"])[0] or "iso").lower()
                include_diags = qs.get("diagonals", ["1"])[0] != "0"
                thumb = qs.get("thumb", ["0"])[0] == "1"
                force = qs.get("force", ["0"])[0] == "1"
                version_tag = (qs.get("v", [""])[0] or "").strip()
                geom_hash = self.srv.catalog.get_geom_hash(solid_id, sol_id) or (version_tag if len(version_tag) == 14 else None)
                dtag = f"{'d1' if include_diags else 'd0'}_{'t1' if thumb else 't0'}_auto"

                # Caminho ultra-rápido: RAM ou docs/renders/ (WebP/PNG) sem precisar listar pastas de solidos/
                img_res = None
                if not force:
                    img_res = self.srv.renderer.get_image_bytes(
                        solid_id=solid_id,
                        solution_id=sol_id,
                        scad_path=None,
                        preset=preset,
                        geom_hash=geom_hash,
                        force=False,
                        include_diagonals=include_diags,
                        thumb=thumb,
                        as_png=False,
                    ) if (
                        self.srv.renderer._get_mem_png(f"{solid_id}|{sol_id}|{preset}|{geom_hash or ''}|{dtag}") is not None
                        or self.srv.renderer._find_docs_render(solid_id, preset, geom_hash, include_diagonals=include_diags, thumb=thumb) is not None
                    ) else None

                if img_res is None:
                    files = self.srv.catalog.base.find_solution_files(solid_id, sol_id)
                    if files is None:
                        self._send_json({"error": "Solução global não encontrada."}, HTTPStatus.NOT_FOUND)
                        return

                    scad_path = files.get("scad")
                    vertices = faces = None
                    if scad_path is None:
                        detail = self.srv.catalog.get_solid_detail(solid_id)
                        if detail:
                            sol = next((s for s in detail["global_solutions"] if s["solution_id"] == sol_id), None)
                            if sol:
                                vertices, faces = sol["vertices"], sol["faces"]

                    img_res = self.srv.renderer.get_image_bytes(
                        solid_id=solid_id,
                        solution_id=sol_id,
                        scad_path=scad_path,
                        preset=preset,
                        vertices=vertices,
                        faces=faces,
                        geom_hash=geom_hash,
                        force=force,
                        include_diagonals=include_diags,
                        thumb=thumb,
                        as_png=False,
                    )

                if img_res is None:
                    self._send_json({"error": "Render indisponível."}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return

                img_bytes, img_ctype, etag = img_res
                cc = "public, max-age=31536000, immutable" if (version_tag and not force) else "public, max-age=3600"
                self._send_bytes(img_bytes, img_ctype, cache_control=cc, etag=etag)
                return

            if path.startswith("/api/download/"):
                parts = path[len("/api/download/"):].split("/")
                if len(parts) != 3:
                    self._send_json({"error": "Parâmetros inválidos."}, HTTPStatus.BAD_REQUEST)
                    return
                solid_id = urllib.parse.unquote(parts[0])
                sol_id = urllib.parse.unquote(parts[1])
                kind = parts[2].lower()
                files = self.srv.catalog.base.find_solution_files(solid_id, sol_id)
                if not files:
                    self._send_json({"error": "Solução não encontrada."}, HTTPStatus.NOT_FOUND)
                    return
                if kind == "png":
                    preset = (qs.get("preset", ["iso"])[0] or "iso").lower()
                    include_diags = qs.get("diagonals", ["1"])[0] != "0"
                    geom_hash = self.srv.catalog.get_geom_hash(solid_id, sol_id)
                    png_res = self.srv.renderer.get_png_bytes(
                        solid_id,
                        sol_id,
                        files.get("scad"),
                        preset=preset,
                        geom_hash=geom_hash,
                        include_diagonals=include_diags,
                    )
                    if not png_res:
                        self._send_json({"error": "Render indisponível."}, HTTPStatus.NOT_FOUND)
                        return
                    suffix = "" if include_diags else "_sem_diagonais"
                    self._send_bytes(png_res[0], "image/png", filename=f"{solid_id}_{sol_id}{suffix}.png")
                    return
                target = files.get(kind)
                if not target or not target.exists():
                    self._send_json({"error": "Arquivo não encontrado."}, HTTPStatus.NOT_FOUND)
                    return
                ctype = "application/json; charset=utf-8" if kind == "json" else "text/plain; charset=utf-8"
                self._send_bytes(target.read_bytes(), ctype, filename=target.name)
                return

            if path == "/api/events":
                self._handle_sse()
                return

            self._send_json({"error": "Não encontrado."}, HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            pass
        except Exception as e:
            try:
                self._send_json({"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            except Exception:
                pass

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._read_json_body()
        try:
            if path == "/api/open-pythonscad":
                solid_id = str(body.get("solid_id", ""))
                sol_id = str(body.get("solution_id", ""))
                files = self.srv.catalog.base.find_solution_files(solid_id, sol_id)
                if not files or not files.get("scad"):
                    self._send_json({"ok": False, "error": "Arquivo PythonSCAD não encontrado."}, HTTPStatus.NOT_FOUND)
                    return
                ok, msg = self.srv.renderer.open_in_desktop_gui(files["scad"])  # type: ignore[arg-type]
                self._send_json({"ok": ok, "message": msg}, HTTPStatus.OK if ok else HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            if path == "/api/sync-github":
                ok, msg, count = sync_global_solutions_to_github()
                self._send_json({"ok": ok, "message": msg, "count": count}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
                return

            if path == "/api/pull-github":
                ok, msg, count = pull_new_minima_from_github(rebuild_docs=False)
                if count > 0:
                    self.srv.catalog.invalidate()
                    self.srv.watcher.broadcast("catalog_updated", {
                        "solids": [],
                        "pulled_count": count,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    })
                self._send_json({"ok": ok, "message": msg, "count": count}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
                return

            self._send_json({"error": "Não encontrado."}, HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            pass
        except Exception as e:
            self._send_json({"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _serve_static(self, rel_path: str):
        hit = self.srv.static_cache.get(rel_path)
        if hit is None:
            self._send_json({"error": "Recurso não encontrado."}, HTTPStatus.NOT_FOUND)
            return
        raw, gz, ctype, etag = hit
        self._send_cached_payload(raw, gz, ctype, etag, cache_control="no-cache")

    def _handle_sse(self):
        # SSE precisa de socket sem timeout curto; encerra limpo ao desconectar cliente
        try:
            self.request.settimeout(None)
        except Exception:
            pass
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        sub = self.srv.watcher.subscribe()
        try:
            self._write_sse("connected", {"mode": "local"})
            while True:
                try:
                    msg = sub.get(timeout=25.0)
                    self._write_sse(msg["event"], msg["data"])
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.srv.watcher.unsubscribe(sub)

    def _write_sse(self, event: str, data: Any):
        chunk = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
        self.wfile.write(chunk)
        self.wfile.flush()


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False):
    catalog = VerifiedCatalogService(PROJECT_ROOT)
    renderer = PythonSCADRenderer()
    watcher = SolidosLiveWatcher(catalog, renderer, poll_interval=3.0)
    remote_poller = RemoteAtlasPoller(poll_interval=45.0)
    watcher.start()
    if os.environ.get("ATLAS_NO_REMOTE_POLL") != "1":
        remote_poller.start()
    catalog.warm_startup_async(renderer)

    httpd = AtlasHTTPServer((host, port), AtlasRequestHandler, catalog, renderer, watcher)
    url = f"http://{host}:{port}"

    print("=" * 72)
    print("  ATLAS VIVO DE POLIEDROS — IC COM COLLI (IME-USP)")
    print("=" * 72)
    print(f"  Local          : {url}")
    print(f"  Renderização   : {renderer.engine_name} (cache RAM + docs/renders + conteúdo)")
    print(f"  Observando     : {PROJECT_ROOT / 'solidos'}/*/minimos_globais (sem_autointersecao)")
    print("=" * 72, flush=True)

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        remote_poller.stop()
        watcher.stop()
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Servidor local do Atlas de Poliedros — IC com Colli")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, open_browser=args.open)
