# ==============================================================================
# WEB INTERFACE — RENDERIZADOR FOTOGRÁFICO VIA PYTHONSCAD
# Renderiza exclusivamente os documentos oficiais *_pythonscad.py gerados por
# ExportadorPythonSCAD para mínimos globais encontrados, produzindo fotos
# científicas em alta resolução sobre fundo branco puro.
# ==============================================================================

from collections import OrderedDict
import hashlib
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image

WEB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from exportadores.pythonscad_exportador import ExportadorPythonSCAD

# Presets de câmera científica (translate_x,y,z,rot_x,y,z,dist) com --autocenter --viewall
CAMERA_PRESETS: Dict[str, str] = {
    "iso": "0,0,0,60,0,34,0",
    "front": "0,0,0,82,0,12,0",
    "top": "0,0,0,22,0,45,0",
    "alt": "0,0,0,64,0,142,0",
}


def find_pythonscad_binaries() -> Tuple[Optional[Path], Optional[Path]]:
    """
    Localiza pythonscad.com (CLI silencioso) e pythonscad.exe (GUI) no sistema.
    Retorna (cli_binary, gui_binary).
    """
    candidates_cli = []
    candidates_gui = []

    env_override = os.environ.get("PYTHONSCAD_PATH")
    if env_override:
        p = Path(env_override)
        if p.exists():
            candidates_cli.append(p)
            candidates_gui.append(p)

    for exe_name in ("pythonscad.com", "pythonscad.exe", "pythonscad"):
        found = shutil.which(exe_name)
        if found:
            p = Path(found)
            if exe_name.endswith(".com"):
                candidates_cli.append(p)
            elif exe_name.endswith(".exe"):
                candidates_gui.append(p)
                com_sibling = p.with_suffix(".com")
                if com_sibling.exists():
                    candidates_cli.append(com_sibling)
            else:
                candidates_cli.append(p)
                candidates_gui.append(p)

    # Locais comuns conhecidos no Windows
    known_dirs = [
        Path(r"D:\Marcelo\Documents\PythonSCAD"),
        Path(r"C:\Program Files\PythonSCAD"),
        Path(r"C:\Program Files (x86)\PythonSCAD"),
        Path.home() / "AppData" / "Local" / "PythonSCAD",
    ]
    for d in known_dirs:
        com_p = d / "pythonscad.com"
        exe_p = d / "pythonscad.exe"
        if com_p.exists():
            candidates_cli.append(com_p)
        if exe_p.exists():
            candidates_gui.append(exe_p)
            if not com_p.exists():
                candidates_cli.append(exe_p)

    cli = candidates_cli[0] if candidates_cli else (candidates_gui[0] if candidates_gui else None)
    gui = candidates_gui[0] if candidates_gui else cli
    return cli, gui


def find_openscad_binary() -> Optional[Path]:
    """Localiza o binário padrão do OpenSCAD (usado em Linux / GitHub Actions quando PythonSCAD não está presente)."""
    for exe in ("openscad", "openscad.com", "openscad.exe"):
        found = shutil.which(exe)
        if found:
            return Path(found)
    return None


def _generate_standard_scad(vertices, faces, scale_factor: float = 20.0) -> str:
    """Converte vértices e faces para sintaxe OpenSCAD padrão (.scad) para renderização headless no Linux/CI."""
    pts_lines = ",\n".join(f"  [{float(v[0]):.16f}, {float(v[1]):.16f}, {float(v[2]):.16f}]" for v in vertices)
    faces_str = str([[int(i) for i in f] for f in faces])
    return f"pts = [\n{pts_lines}\n];\nfaces = {faces_str};\nscale({scale_factor}) polyhedron(points=pts, faces=faces);\n"


def _studio_postprocess_white(raw_png: Path, out_png: Path, target_size: int = 720, margin_ratio: float = 0.11) -> bool:
    """
    Pós-processamento editorial científico com Pillow:
      1. Identifica a cor exata do fundo renderizado pelo PythonSCAD (esquema Tomorrow ~ #f8f8f8).
      2. Verifica se o render não está vazio.
      3. Recorta perfeitamente em torno do poliedro e centraliza em um quadro 800x800
         com margens equilibradas sobre fundo branco puro (#FFFFFF), mantendo anti-aliasing suave.
    """
    with Image.open(raw_png) as raw_img:
        img = raw_img.convert("RGB")
    arr = np.asarray(img, dtype=np.int16)
    # Cor do fundo tomada a partir dos quatro cantos
    corners = np.array([arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]], dtype=np.int16)
    bg_rgb = np.median(corners, axis=0)

    # Máscara de pixels pertencentes ao sólido (diferença de cor > 6 em qualquer canal)
    diff = np.max(np.abs(arr - bg_rgb), axis=2)
    mask = diff > 6
    if not np.any(mask):
        return False

    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1

    # Pequena margem de segurança de 4px para preservar bordas anti-aliased
    h, w = arr.shape[:2]
    y0 = max(0, y0 - 4)
    y1 = min(h, y1 + 4)
    x0 = max(0, x0 - 4)
    x1 = min(w, x1 + 4)

    crop = arr[y0:y1, x0:x1].astype(np.float32)
    crop_diff = np.max(np.abs(crop - bg_rgb), axis=2)

    # Transição suave dos pixels de fundo (#f8f8f8) para branco puro (#ffffff)
    # sem criar serrilhado nas arestas
    pure_bg = crop_diff <= 4
    crop[pure_bg] = 255.0

    # Para pixels de borda muito próximos do fundo (4 < diff <= 14), interpola suavemente até branco
    near_bg = (crop_diff > 4) & (crop_diff <= 14)
    if np.any(near_bg):
        alpha = (crop_diff[near_bg] - 4.0) / 10.0  # 0..1
        alpha = alpha[:, None]
        crop[near_bg] = crop[near_bg] * alpha + 255.0 * (1.0 - alpha)

    cropped_img = Image.fromarray(np.clip(crop, 0, 255).astype(np.uint8), mode="RGB")

    # Centraliza proporcionalmente no quadro final com margens de estúdio
    inner = int(target_size * (1.0 - 2.0 * margin_ratio))
    cw, ch = cropped_img.size
    scale = min(inner / max(1, cw), inner / max(1, ch))
    new_w = max(1, int(round(cw * scale)))
    new_h = max(1, int(round(ch * scale)))

    resized = cropped_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (target_size, target_size), (255, 255, 255))
    paste_x = (target_size - new_w) // 2
    paste_y = (target_size - new_h) // 2
    canvas.paste(resized, (paste_x, paste_y))

    out_png.parent.mkdir(parents=True, exist_ok=True)
    tmp_png = out_png.with_suffix(".tmp.png")
    canvas.save(tmp_png, format="PNG", compress_level=6)
    os.replace(tmp_png, out_png)
    return True


def _safe_slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    return slug.strip("_") or "solid"


class PythonSCADRenderer:
    """
    Gerencia cache em RAM + disco endereçado por conteúdo (SHA-1) + reaproveitamento
    automático de docs/renders/ e renderização sob-demanda/background via PythonSCAD.
    """

    def __init__(self, cache_dir: Optional[Path] = None, max_concurrency: int = 2, mem_cache_max: int = 180):
        self.cache_dir = Path(cache_dir or (WEB_DIR / "cache" / "renders"))
        self.tmp_dir = WEB_DIR / "cache" / "tmp_scad"
        self.docs_renders_dir = PROJECT_ROOT / "docs" / "renders"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        self.cli_bin, self.gui_bin = find_pythonscad_binaries()
        self.openscad_bin = find_openscad_binary()
        self.xvfb_bin = shutil.which("xvfb-run") if os.name != "nt" else None
        self._sem = threading.Semaphore(max_concurrency)
        self._key_locks_guard = threading.Lock()
        self._key_locks: Dict[str, threading.Lock] = {}

        # Cache de hash de conteúdo dos scripts *_pythonscad.py: path -> (mtime_ns, size, sha1_hex)
        self._script_hash_cache: Dict[str, Tuple[int, int, str]] = {}
        self._script_hash_lock = threading.Lock()

        # Cache LRU de bytes PNG em RAM (sub-milissegundo no servidor HTTP)
        self._mem_cache_max = max(16, int(mem_cache_max))
        self._mem_png_cache: "OrderedDict[str, Tuple[bytes, str]]" = OrderedDict()
        self._mem_cache_lock = threading.Lock()

        # Fila leve de pré-aquecimento em segundo plano (baixa prioridade)
        self._prewarm_queue: "queue.Queue[Tuple[str, str, Optional[Path], str, Optional[str]]]" = queue.Queue()
        self._prewarm_seen: set = set()
        self._prewarm_lock = threading.Lock()
        self._prewarm_started = False

    def _get_script_content_hash(self, script_path: Path) -> str:
        resolved = str(script_path.resolve())
        stat = script_path.stat()
        with self._script_hash_lock:
            hit = self._script_hash_cache.get(resolved)
            if hit and hit[0] == stat.st_mtime_ns and hit[1] == stat.st_size:
                return hit[2]
        digest = hashlib.sha1(script_path.read_bytes()).hexdigest()[:20]
        with self._script_hash_lock:
            self._script_hash_cache[resolved] = (stat.st_mtime_ns, stat.st_size, digest)
        return digest

    def _get_mem_png(self, key: str) -> Optional[Tuple[bytes, str]]:
        with self._mem_cache_lock:
            hit = self._mem_png_cache.get(key)
            if hit is not None:
                self._mem_png_cache.move_to_end(key)
                return hit
        return None

    def _put_mem_png(self, key: str, raw: bytes, etag: str) -> Tuple[bytes, str]:
        with self._mem_cache_lock:
            self._mem_png_cache[key] = (raw, etag)
            self._mem_png_cache.move_to_end(key)
            while len(self._mem_png_cache) > self._mem_cache_max:
                self._mem_png_cache.popitem(last=False)
        return raw, etag

    def _find_docs_render(self, solid_id: str, preset: str, geom_hash: Optional[str]) -> Optional[Path]:
        """Reaproveita instantaneamente renders já existentes em docs/renders/ sem invocar PythonSCAD."""
        if not geom_hash or not self.docs_renders_dir.is_dir():
            return None
        cand = self.docs_renders_dir / f"{_safe_slug(solid_id)}_{geom_hash}_{preset}.png"
        if cand.is_file() and cand.stat().st_size > 1000:
            return cand
        return None

    def enqueue_prewarm(
        self,
        solid_id: str,
        solution_id: str,
        scad_path: Optional[Path],
        preset: str = "iso",
        geom_hash: Optional[str] = None,
    ) -> None:
        """Agenda pré-renderização assíncrona de baixa prioridade (nunca bloqueia HTTP)."""
        key = f"{solid_id}|{solution_id}|{preset}|{geom_hash or ''}"
        with self._prewarm_lock:
            if key in self._prewarm_seen:
                return
            self._prewarm_seen.add(key)
            if not self._prewarm_started:
                self._prewarm_started = True
                threading.Thread(target=self._prewarm_worker, daemon=True, name="scad-prewarm").start()
        self._prewarm_queue.put((solid_id, solution_id, scad_path, preset, geom_hash))

    def _prewarm_worker(self) -> None:
        while True:
            try:
                solid_id, solution_id, scad_path, preset, geom_hash = self._prewarm_queue.get()
                try:
                    self.render_solution_png(
                        solid_id=solid_id,
                        solution_id=solution_id,
                        scad_path=scad_path,
                        preset=preset,
                        geom_hash=geom_hash,
                    )
                except Exception:
                    pass
                finally:
                    self._prewarm_queue.task_done()
            except Exception:
                pass

    def get_png_bytes(
        self,
        solid_id: str,
        solution_id: str,
        scad_path: Optional[Path],
        preset: str = "iso",
        vertices=None,
        faces=None,
        geom_hash: Optional[str] = None,
        force: bool = False,
    ) -> Optional[Tuple[bytes, str]]:
        """
        Retorna (png_bytes, etag) priorizando RAM -> docs/renders/ -> web/cache/renders/ -> render sob demanda.
        """
        mem_key = f"{solid_id}|{solution_id}|{preset}|{geom_hash or ''}"
        if not force:
            hit = self._get_mem_png(mem_key)
            if hit is not None:
                return hit

            docs_png = self._find_docs_render(solid_id, preset, geom_hash)
            if docs_png is not None:
                raw = docs_png.read_bytes()
                etag = f'"{hashlib.sha1(raw).hexdigest()[:16]}"'
                return self._put_mem_png(mem_key, raw, etag)

        png_path = self.render_solution_png(
            solid_id=solid_id,
            solution_id=solution_id,
            scad_path=scad_path,
            preset=preset,
            vertices=vertices,
            faces=faces,
            geom_hash=geom_hash,
            force=force,
        )
        if not png_path or not png_path.exists():
            return None
        raw = png_path.read_bytes()
        etag = f'"{hashlib.sha1(raw).hexdigest()[:16]}"'
        return self._put_mem_png(mem_key, raw, etag)

    @property
    def available(self) -> bool:
        return (self.cli_bin is not None and self.cli_bin.exists()) or (
            self.openscad_bin is not None and self.openscad_bin.exists()
        )

    @property
    def engine_name(self) -> str:
        if self.cli_bin is not None and self.cli_bin.exists():
            return "PythonSCAD"
        if self.openscad_bin is not None and self.openscad_bin.exists():
            return "OpenSCAD"
        return "Matplotlib 3D"

    def _get_lock(self, key: str) -> threading.Lock:
        with self._key_locks_guard:
            if key not in self._key_locks:
                self._key_locks[key] = threading.Lock()
            return self._key_locks[key]

    def _ensure_scad_script(
        self,
        solid_id: str,
        solution_id: str,
        scad_path: Optional[Path],
        vertices=None,
        faces=None,
    ) -> Optional[Path]:
        """
        Utiliza preferencialmente o documento oficial *_pythonscad.py salvo em solidos/.
        Se (e somente se) uma solução global existir apenas em JSON sem o .py ao lado,
        sintetiza o código via ExportadorPythonSCAD em pasta temporária de cache sem tocar em solidos/.
        """
        if scad_path and scad_path.exists():
            return scad_path

        if vertices is not None and faces is not None:
            exp = ExportadorPythonSCAD(fator_escala=20.0)
            code = exp.gerar_codigo_pythonscad(vertices, faces)
            safe_key = hashlib.sha1(f"{solid_id}:{solution_id}".encode("utf-8")).hexdigest()[:16]
            tmp_py = self.tmp_dir / f"{safe_key}_pythonscad.py"
            tmp_py.write_text(code, encoding="utf-8")
            return tmp_py

        return None

    def render_solution_png(
        self,
        solid_id: str,
        solution_id: str,
        scad_path: Optional[Path],
        preset: str = "iso",
        vertices=None,
        faces=None,
        geom_hash: Optional[str] = None,
        force: bool = False,
    ) -> Optional[Path]:
        """Renderiza (ou recupera do cache por conteúdo / docs/renders/) a fotografia PNG do sólido via PythonSCAD."""
        camera = CAMERA_PRESETS.get(preset, CAMERA_PRESETS["iso"])

        if not force:
            docs_png = self._find_docs_render(solid_id, preset, geom_hash)
            if docs_png is not None:
                return docs_png

        script_path = self._ensure_scad_script(solid_id, solution_id, scad_path, vertices, faces)
        if script_path is None or not script_path.exists():
            return None

        # Chave baseada no CONTEÚDO do script (mover arquivos entre pastas nunca invalida o cache!)
        content_hash = self._get_script_content_hash(script_path)
        cache_sig = hashlib.sha1(f"{content_hash}|{preset}|v3".encode("utf-8")).hexdigest()[:20]
        final_png = self.cache_dir / f"{cache_sig}.png"
        raw_png = self.cache_dir / f"{cache_sig}_raw.png"

        if not force and final_png.exists() and final_png.stat().st_size > 1000:
            return final_png

        # Compatibilidade com cache legado v2 (reaproveita instantaneamente sem re-renderizar!)
        if not force:
            stat = script_path.stat()
            legacy_sig = hashlib.sha1(
                f"{script_path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{preset}|v2".encode("utf-8")
            ).hexdigest()[:20]
            legacy_png = self.cache_dir / f"{legacy_sig}.png"
            if legacy_png.exists() and legacy_png.stat().st_size > 1000:
                try:
                    shutil.copy2(legacy_png, final_png)
                    return final_png
                except OSError:
                    return legacy_png

        lock = self._get_lock(cache_sig)
        with lock:
            if not force and final_png.exists() and final_png.stat().st_size > 1000:
                return final_png

            def _safe_unlink(p: Path):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

            with self._sem:
                if self.cli_bin is not None and self.cli_bin.exists():
                    # 1ª tentativa: PythonSCAD --render (Manifold/CGAL sólido, iluminação limpa e nítida)
                    ok = self._invoke_pythonscad(script_path, raw_png, camera, use_render=True)
                    if ok and raw_png.exists():
                        if _studio_postprocess_white(raw_png, final_png):
                            _safe_unlink(raw_png)
                            return final_png

                    # 2ª tentativa (fallback para malhas não convexas com autointerseção): preview OpenCSG
                    ok = self._invoke_pythonscad(script_path, raw_png, camera, use_render=False)
                    if ok and raw_png.exists():
                        if _studio_postprocess_white(raw_png, final_png):
                            _safe_unlink(raw_png)
                            return final_png

                    _safe_unlink(raw_png)

                elif self.openscad_bin is not None and self.openscad_bin.exists():
                    # Linux / GitHub Actions: converte pts/faces para .scad padrão e renderiza via OpenSCAD
                    std_scad = self._ensure_standard_scad(solid_id, solution_id, script_path, vertices, faces)
                    if std_scad is not None:
                        for use_render in (True, False):
                            ok = self._invoke_openscad(std_scad, raw_png, camera, use_render=use_render)
                            if ok and raw_png.exists():
                                if _studio_postprocess_white(raw_png, final_png):
                                    _safe_unlink(raw_png)
                                    return final_png
                        _safe_unlink(raw_png)

                # 3ª tentativa (fallback científico otimizado via Matplotlib 3D):
                # garante foto mesmo sem PythonSCAD/OpenSCAD instalado ou em malha patológica
                if self._render_matplotlib_fallback(script_path, final_png, preset, vertices, faces):
                    return final_png
                return None

    def _ensure_standard_scad(
        self,
        solid_id: str,
        solution_id: str,
        script_path: Optional[Path],
        vertices=None,
        faces=None,
    ) -> Optional[Path]:
        if (vertices is None or faces is None) and script_path and script_path.exists():
            from geometry_analyzer import parse_pythonscad_file
            parsed = parse_pythonscad_file(script_path)
            if parsed:
                vertices, faces = parsed
        if vertices is None or faces is None:
            return None
        safe_key = hashlib.sha1(f"{solid_id}:{solution_id}:scad".encode("utf-8")).hexdigest()[:16]
        out_scad = self.tmp_dir / f"{safe_key}.scad"
        out_scad.write_text(_generate_standard_scad(vertices, faces, 20.0), encoding="utf-8")
        return out_scad

    def _invoke_openscad(self, scad_file: Path, out_png: Path, camera: str, use_render: bool) -> bool:
        assert self.openscad_bin is not None
        cmd = []
        if self.xvfb_bin and not os.environ.get("DISPLAY"):
            cmd.extend([self.xvfb_bin, "-a"])
        cmd.extend([
            str(self.openscad_bin),
            "--autocenter",
            "--viewall",
            "--imgsize=1000,1000",
            "--colorscheme=Tomorrow",
            "--view=edges",
            "--projection=p",
            f"--camera={camera}",
        ])
        if use_render:
            cmd.append("--render")
        cmd.extend(["-o", str(out_png), str(scad_file)])
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            return res.returncode == 0 and out_png.exists() and out_png.stat().st_size > 500
        except Exception:
            return False

    def _render_matplotlib_fallback(
        self,
        script_path: Optional[Path],
        out_png: Path,
        preset: str,
        vertices=None,
        faces=None,
    ) -> bool:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d.art3d import Poly3DCollection
            from geometry_analyzer import parse_pythonscad_file

            if (vertices is None or faces is None) and script_path and script_path.exists():
                parsed = parse_pythonscad_file(script_path)
                if parsed:
                    vertices, faces = parsed
            if vertices is None or faces is None:
                return False

            V = np.asarray(vertices, dtype=float)
            V = V - V.mean(axis=0)
            max_r = float(np.max(np.linalg.norm(V, axis=1))) or 1.0
            V = V / max_r

            angles = {"iso": (28, 36), "front": (8, 12), "top": (68, 45), "alt": (24, 142)}
            elev, azim = angles.get(preset, (28, 36))

            fig = plt.figure(figsize=(8, 8), dpi=100, facecolor="white")
            ax = fig.add_subplot(111, projection="3d", facecolor="white")
            ax.set_axis_off()
            ax.view_init(elev=elev, azim=azim)

            light = np.array([-0.45, 0.55, 0.70])
            light /= np.linalg.norm(light)
            base_rgb = np.array([66.0, 113.0, 174.0]) / 255.0

            polys = []
            face_colors = []
            for f in faces:
                if len(f) < 3:
                    continue
                pts = V[f]
                polys.append(pts)
                n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
                nn = float(np.linalg.norm(n)) or 1.0
                n /= nn
                shade = 0.45 + 0.55 * abs(float(np.dot(n, light)))
                rgb = np.clip(base_rgb * shade + 0.08, 0.0, 1.0)
                face_colors.append((*rgb, 1.0))

            coll = Poly3DCollection(polys, facecolors=face_colors, edgecolors=(0.12, 0.16, 0.24, 0.65), linewidths=1.1)
            ax.add_collection3d(coll)
            lim = 0.85
            ax.set_xlim(-lim, lim)
            ax.set_ylim(-lim, lim)
            ax.set_zlim(-lim, lim)
            ax.set_box_aspect([1, 1, 1])
            plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
            out_png.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(out_png, dpi=100, facecolor="white")
            plt.close(fig)
            return out_png.exists() and out_png.stat().st_size > 1000
        except Exception:
            return False

    def _invoke_pythonscad(self, script_path: Path, out_png: Path, camera: str, use_render: bool) -> bool:
        assert self.cli_bin is not None
        cmd = [
            str(self.cli_bin),
            "--trust-python",
            "--autocenter",
            "--viewall",
            "--imgsize=800,800",
            "--colorscheme=Tomorrow",
            "--view=edges",
            "--projection=p",
            f"--camera={camera}",
        ]
        if use_render:
            cmd.append("--render")
        cmd.extend(["-o", str(out_png), str(script_path)])

        # CREATE_NO_WINDOW (0x08000000) | BELOW_NORMAL_PRIORITY_CLASS (0x00004000)
        # Mantém navegador e Spyder 100% responsivos durante renderização
        creationflags = (0x08000000 | 0x00004000) if os.name == "nt" else 0
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=25,
                creationflags=creationflags,
            )
            return res.returncode == 0 and out_png.exists() and out_png.stat().st_size > 500
        except Exception:
            return False

    def open_in_desktop_gui(self, scad_path: Path) -> Tuple[bool, str]:
        """Abre o documento *_pythonscad.py diretamente no aplicativo PythonSCAD local."""
        if not self.gui_bin or not self.gui_bin.exists():
            return False, "Executável do PythonSCAD não encontrado no sistema."
        if not scad_path.exists():
            return False, "Arquivo PythonSCAD não encontrado."
        try:
            subprocess.Popen([str(self.gui_bin), str(scad_path)])
            return True, f"Aberto no PythonSCAD: {scad_path.name}"
        except Exception as e:
            return False, str(e)
