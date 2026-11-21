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
from typing import Dict, List, Optional, Tuple

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


FACE_COLOR_RGB = (0.2588, 0.4431, 0.6824)       # Azul Tomorrow (#4271ae)
EDGE_COLOR_RGB = (0.87, 0.92, 0.98)             # Arestas reais de contorno
DIAG_COLOR_STD_RGB = (0.82, 0.89, 0.98)         # Diagonais reais (m = 4, 5, 6)
DIAG_COLOR_DENSE_RGB = (0.74, 0.84, 0.96)       # Diagonais reais (m >= 8, mais sutis)
RENDER_CACHE_VERSION = "v4_real_diags"


def _segment_transform_matrix(p1, p2) -> Tuple[float, Optional[List[List[float]]]]:
    """Calcula comprimento L e matriz 4x4 que alinha o eixo +Z de um cilindro ao segmento p1 -> p2."""
    a = np.asarray(p1, dtype=float)
    b = np.asarray(p2, dtype=float)
    v = b - a
    length = float(np.linalg.norm(v))
    if length < 1e-12:
        return 0.0, None
    z = v / length
    ref = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = np.cross(ref, z)
    x_norm = float(np.linalg.norm(x))
    if x_norm < 1e-12:
        return 0.0, None
    x /= x_norm
    y = np.cross(z, x)
    mat = [
        [round(float(x[0]), 8), round(float(y[0]), 8), round(float(z[0]), 8), round(float(a[0]), 8)],
        [round(float(x[1]), 8), round(float(y[1]), 8), round(float(z[1]), 8), round(float(a[1]), 8)],
        [round(float(x[2]), 8), round(float(y[2]), 8), round(float(z[2]), 8), round(float(a[2]), 8)],
        [0.0, 0.0, 0.0, 1.0],
    ]
    return length, mat


def _extract_real_edges_and_diagonals(faces) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int, int]]]:
    """
    Extrai separadamente todas as arestas reais de contorno (k = 1) e todas as
    diagonais reais internas de cada face poligonal (k >= 2, m >= 4).
    """
    edges = set()
    for f in faces:
        m = len(f)
        if m < 3:
            continue
        for i in range(m):
            a, b = int(f[i]), int(f[(i + 1) % m])
            if a != b:
                edges.add((min(a, b), max(a, b)))

    diags: Dict[Tuple[int, int], int] = {}
    for f in faces:
        m = len(f)
        if m < 4:
            continue
        for i in range(m):
            for j in range(i + 2, m):
                if i == 0 and j == m - 1:
                    continue
                a, b = int(f[i]), int(f[j])
                if a == b:
                    continue
                key = (min(a, b), max(a, b))
                if key not in edges:
                    diags[key] = max(diags.get(key, 0), m)

    return sorted(edges), [(a, b, m) for (a, b), m in sorted(diags.items())]


def _compute_wireframe_radii(vertices) -> Tuple[float, float, float]:
    """Escala o raio dos cilindros proporcionalmente ao raio envolvente do sólido."""
    V = np.asarray(vertices, dtype=float)
    centroid = V.mean(axis=0)
    max_r = float(np.max(np.linalg.norm(V - centroid, axis=1))) or 1.0
    r_edge = round(max(0.0060, 0.0085 * max_r), 6)
    r_diag_std = round(max(0.0036, 0.0049 * max_r), 6)
    r_diag_dense = round(max(0.0026, 0.0034 * max_r), 6)
    return r_edge, r_diag_std, r_diag_dense


def _generate_pythonscad_render_scene(
    vertices,
    faces,
    scale_factor: float = 20.0,
    include_diagonals: bool = True,
) -> str:
    """
    Gera cena temporária PythonSCAD com o poliedro sólido + todas as arestas reais
    de contorno + (opcionalmente) todas as diagonais reais de cada face (via cilindros
    com multmatrix, eliminando as linhas falsas de triangulação do --view=edges).
    """
    edges, diags = _extract_real_edges_and_diagonals(faces)
    r_edge, r_diag_std, r_diag_dense = _compute_wireframe_radii(vertices)

    pts_clean = [[round(float(v[0]), 12), round(float(v[1]), 12), round(float(v[2]), 12)] for v in vertices]
    faces_clean = [[int(idx) for idx in f] for f in faces]

    lines = [
        "from openscad import *",
        f"pts = {pts_clean}",
        f"faces = {faces_clean}",
        f"parts = [color(polyhedron(pts, faces), {list(FACE_COLOR_RGB)})]",
    ]
    edge_col = list(EDGE_COLOR_RGB)
    for p in pts_clean:
        lines.append(
            f"parts.append(color(translate(sphere(r={r_edge:.6f}, fn=10), [{p[0]:.8f}, {p[1]:.8f}, {p[2]:.8f}]), {edge_col}))"
        )
    for a, b in edges:
        length, mat = _segment_transform_matrix(pts_clean[a], pts_clean[b])
        if mat is None:
            continue
        lines.append(
            f"parts.append(color(multmatrix(cylinder(h={length:.8f}, r={r_edge:.6f}, fn=10), {mat}), {edge_col}))"
        )
    if include_diagonals:
        diag_std_col = list(DIAG_COLOR_STD_RGB)
        diag_dense_col = list(DIAG_COLOR_DENSE_RGB)
        for a, b, m in diags:
            length, mat = _segment_transform_matrix(pts_clean[a], pts_clean[b])
            if mat is None:
                continue
            r_d = r_diag_dense if m >= 8 else r_diag_std
            col = diag_dense_col if m >= 8 else diag_std_col
            lines.append(
                f"parts.append(color(multmatrix(cylinder(h={length:.8f}, r={r_d:.6f}, fn=10), {mat}), {col}))"
            )
    lines.append(f"obj = scale(union(*parts), {scale_factor})")
    lines.append("show(obj)")
    return "\n".join(lines) + "\n"


def _generate_standard_scad(
    vertices,
    faces,
    scale_factor: float = 20.0,
    include_diagonals: bool = True,
) -> str:
    """
    Converte vértices e faces para sintaxe OpenSCAD padrão (.scad) com arestas reais
    e (opcionalmente) todas as diagonais reais de cada face (para renderização headless no Linux/CI).
    """
    edges, diags = _extract_real_edges_and_diagonals(faces)
    r_edge, r_diag_std, r_diag_dense = _compute_wireframe_radii(vertices)

    pts_lines = ",\n".join(f"  [{float(v[0]):.12f}, {float(v[1]):.12f}, {float(v[2]):.12f}]" for v in vertices)
    faces_str = str([[int(i) for i in f] for f in faces])

    lines = [
        f"pts = [\n{pts_lines}\n];",
        f"faces = {faces_str};",
        f"scale({scale_factor}) {{",
        f"  color({list(FACE_COLOR_RGB)}) polyhedron(points=pts, faces=faces);",
        f"  color({list(EDGE_COLOR_RGB)}) {{",
    ]
    for v in vertices:
        lines.append(f"    translate([{float(v[0]):.8f}, {float(v[1]):.8f}, {float(v[2]):.8f}]) sphere(r={r_edge:.6f}, $fn=10);")
    for a, b in edges:
        length, mat = _segment_transform_matrix(vertices[a], vertices[b])
        if mat is None:
            continue
        lines.append(f"    multmatrix({mat}) cylinder(h={length:.8f}, r={r_edge:.6f}, $fn=10);")
    lines.append("  }")

    if include_diagonals:
        diags_std = [(a, b) for a, b, m in diags if m < 8]
        diags_dense = [(a, b) for a, b, m in diags if m >= 8]
        if diags_std:
            lines.append(f"  color({list(DIAG_COLOR_STD_RGB)}) {{")
            for a, b in diags_std:
                length, mat = _segment_transform_matrix(vertices[a], vertices[b])
                if mat is None:
                    continue
                lines.append(f"    multmatrix({mat}) cylinder(h={length:.8f}, r={r_diag_std:.6f}, $fn=10);")
            lines.append("  }")
        if diags_dense:
            lines.append(f"  color({list(DIAG_COLOR_DENSE_RGB)}) {{")
            for a, b in diags_dense:
                length, mat = _segment_transform_matrix(vertices[a], vertices[b])
                if mat is None:
                    continue
                lines.append(f"    multmatrix({mat}) cylinder(h={length:.8f}, r={r_diag_dense:.6f}, $fn=10);")
            lines.append("  }")

    lines.append("}")
    return "\n".join(lines) + "\n"


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

    def _find_docs_render(
        self,
        solid_id: str,
        preset: str,
        geom_hash: Optional[str],
        include_diagonals: bool = True,
        thumb: bool = False,
    ) -> Optional[Path]:
        """Reaproveita instantaneamente renders (WebP ou PNG) já existentes em docs/renders/ sem invocar PythonSCAD."""
        if not geom_hash or not self.docs_renders_dir.is_dir():
            return None
        suffix = "" if include_diagonals else "_clean"
        slug = _safe_slug(solid_id)
        candidates = []
        if thumb:
            candidates.append(self.docs_renders_dir / f"{slug}_{geom_hash}_{preset}{suffix}_thumb.webp")
        candidates.append(self.docs_renders_dir / f"{slug}_{geom_hash}_{preset}{suffix}.webp")
        candidates.append(self.docs_renders_dir / f"{slug}_{geom_hash}_{preset}{suffix}.png")
        for cand in candidates:
            if cand.is_file() and cand.stat().st_size > 400:
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

    def get_image_bytes(
        self,
        solid_id: str,
        solution_id: str,
        scad_path: Optional[Path],
        preset: str = "iso",
        vertices=None,
        faces=None,
        geom_hash: Optional[str] = None,
        force: bool = False,
        include_diagonals: bool = True,
        thumb: bool = False,
        as_png: bool = False,
    ) -> Optional[Tuple[bytes, str, str]]:
        """
        Retorna (img_bytes, content_type, etag) priorizando RAM -> docs/renders/ (WebP/PNG)
        -> web/cache/renders/ -> render sob demanda. Se `as_png=True`, garante saída PNG.
        """
        import io
        dtag = f"{'d1' if include_diagonals else 'd0'}_{'t1' if thumb else 't0'}_{'png' if as_png else 'auto'}"
        mem_key = f"{solid_id}|{solution_id}|{preset}|{geom_hash or ''}|{dtag}"
        if not force:
            hit = self._get_mem_png(mem_key)
            if hit is not None:
                raw_b, etag = hit
                ctype = "image/webp" if raw_b[:4] == b"RIFF" and raw_b[8:12] == b"WEBP" else "image/png"
                return raw_b, ctype, etag

            docs_img = self._find_docs_render(
                solid_id, preset, geom_hash, include_diagonals=include_diagonals, thumb=thumb
            )
            if docs_img is not None:
                raw = docs_img.read_bytes()
                is_webp = docs_img.suffix.lower() == ".webp"
                if as_png and is_webp:
                    buf = io.BytesIO()
                    with Image.open(io.BytesIO(raw)) as im:
                        im.save(buf, format="PNG", compress_level=6)
                    raw = buf.getvalue()
                    ctype = "image/png"
                else:
                    ctype = "image/webp" if is_webp else "image/png"
                etag = f'"{hashlib.sha1(raw).hexdigest()[:16]}"'
                self._put_mem_png(mem_key, raw, etag)
                return raw, ctype, etag

        png_path = self.render_solution_png(
            solid_id=solid_id,
            solution_id=solution_id,
            scad_path=scad_path,
            preset=preset,
            vertices=vertices,
            faces=faces,
            geom_hash=geom_hash,
            force=force,
            include_diagonals=include_diagonals,
        )
        if not png_path or not png_path.exists():
            return None
        raw = png_path.read_bytes()
        is_webp = png_path.suffix.lower() == ".webp"
        if as_png and is_webp:
            buf = io.BytesIO()
            with Image.open(io.BytesIO(raw)) as im:
                im.save(buf, format="PNG", compress_level=6)
            raw = buf.getvalue()
            ctype = "image/png"
        elif thumb and not is_webp:
            buf = io.BytesIO()
            with Image.open(io.BytesIO(raw)) as im:
                im.resize((360, 360), Image.Resampling.LANCZOS).save(buf, format="WEBP", quality=84, method=6)
            raw = buf.getvalue()
            ctype = "image/webp"
        else:
            ctype = "image/webp" if is_webp else "image/png"
        etag = f'"{hashlib.sha1(raw).hexdigest()[:16]}"'
        self._put_mem_png(mem_key, raw, etag)
        return raw, ctype, etag

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
        include_diagonals: bool = True,
    ) -> Optional[Tuple[bytes, str]]:
        """Compatibilidade: retorna (png_bytes, etag) sempre em formato PNG."""
        res = self.get_image_bytes(
            solid_id=solid_id,
            solution_id=solution_id,
            scad_path=scad_path,
            preset=preset,
            vertices=vertices,
            faces=faces,
            geom_hash=geom_hash,
            force=force,
            include_diagonals=include_diagonals,
            thumb=False,
            as_png=True,
        )
        if res is None:
            return None
        return res[0], res[2]

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
        include_diagonals: bool = True,
    ) -> Optional[Path]:
        """Renderiza (ou recupera do cache por conteúdo / docs/renders/) a fotografia PNG do sólido via PythonSCAD."""
        camera = CAMERA_PRESETS.get(preset, CAMERA_PRESETS["iso"])

        if not force:
            docs_png = self._find_docs_render(solid_id, preset, geom_hash, include_diagonals=include_diagonals)
            if docs_png is not None:
                return docs_png

        script_path = self._ensure_scad_script(solid_id, solution_id, scad_path, vertices, faces)
        if script_path is None or not script_path.exists():
            return None

        # Para sólidos puramente triangulares (sem faces m >= 4), com/sem diagonais são idênticos
        effective_diags = bool(include_diagonals)
        if not effective_diags:
            rv, rf = self._resolve_geometry(script_path, vertices, faces)
            if rf is not None and not any(len(f) >= 4 for f in rf):
                effective_diags = True
                if not force:
                    docs_png = self._find_docs_render(solid_id, preset, geom_hash, include_diagonals=True)
                    if docs_png is not None:
                        return docs_png

        variant_tag = RENDER_CACHE_VERSION if effective_diags else f"{RENDER_CACHE_VERSION}_clean"

        # Chave baseada no CONTEÚDO do script (mover arquivos entre pastas nunca invalida o cache!)
        content_hash = self._get_script_content_hash(script_path)
        cache_sig = hashlib.sha1(f"{content_hash}|{preset}|{variant_tag}".encode("utf-8")).hexdigest()[:20]
        final_png = self.cache_dir / f"{cache_sig}.png"
        raw_png = self.cache_dir / f"{cache_sig}_raw.png"

        if not force and final_png.exists() and final_png.stat().st_size > 1000:
            return final_png

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
                    # Cena temporária com arestas reais (+ diagonais reais se effective_diags=True)
                    render_py = self._ensure_render_pythonscad(
                        content_hash, script_path, vertices, faces, include_diagonals=effective_diags
                    ) or script_path

                    # 1ª tentativa: preview OpenGL (preserva cores exatas de faces, arestas e diagonais)
                    ok = self._invoke_pythonscad(render_py, raw_png, camera, use_render=False)
                    if ok and raw_png.exists():
                        if _studio_postprocess_white(raw_png, final_png):
                            _safe_unlink(raw_png)
                            return final_png

                    # 2ª tentativa (fallback): --render Manifold/CGAL
                    ok = self._invoke_pythonscad(render_py, raw_png, camera, use_render=True)
                    if ok and raw_png.exists():
                        if _studio_postprocess_white(raw_png, final_png):
                            _safe_unlink(raw_png)
                            return final_png

                    _safe_unlink(raw_png)

                elif self.openscad_bin is not None and self.openscad_bin.exists():
                    # Linux / GitHub Actions: converte pts/faces para .scad com arestas (e diagonais se ativo)
                    std_scad = self._ensure_standard_scad(
                        content_hash, script_path, vertices, faces, include_diagonals=effective_diags
                    )
                    if std_scad is not None:
                        for use_render in (False, True):
                            ok = self._invoke_openscad(std_scad, raw_png, camera, use_render=use_render)
                            if ok and raw_png.exists():
                                if _studio_postprocess_white(raw_png, final_png):
                                    _safe_unlink(raw_png)
                                    return final_png
                        _safe_unlink(raw_png)

                # 3ª tentativa (fallback científico otimizado via Matplotlib 3D):
                # garante foto mesmo sem PythonSCAD/OpenSCAD instalado ou em malha patológica
                if self._render_matplotlib_fallback(
                    script_path, final_png, preset, vertices, faces, include_diagonals=effective_diags
                ):
                    return final_png
                return None

    def _resolve_geometry(self, script_path: Optional[Path], vertices=None, faces=None):
        if (vertices is None or faces is None) and script_path and script_path.exists():
            from geometry_analyzer import parse_pythonscad_file
            parsed = parse_pythonscad_file(script_path)
            if parsed:
                vertices, faces = parsed
        if vertices is None or faces is None:
            return None, None
        return vertices, faces

    def _ensure_render_pythonscad(
        self,
        content_hash: str,
        script_path: Optional[Path],
        vertices=None,
        faces=None,
        include_diagonals: bool = True,
    ) -> Optional[Path]:
        vertices, faces = self._resolve_geometry(script_path, vertices, faces)
        if vertices is None or faces is None:
            return None
        tag = RENDER_CACHE_VERSION if include_diagonals else f"{RENDER_CACHE_VERSION}_clean"
        out_py = self.tmp_dir / f"{content_hash}_{tag}.py"
        if out_py.exists() and out_py.stat().st_size > 100:
            return out_py
        scene_lock = self._get_lock(f"scene_py:{content_hash}:{tag}")
        with scene_lock:
            if out_py.exists() and out_py.stat().st_size > 100:
                return out_py
            tmp_out = self.tmp_dir / f"{content_hash}_{tag}_{threading.get_ident()}.tmp.py"
            tmp_out.write_text(
                _generate_pythonscad_render_scene(vertices, faces, 20.0, include_diagonals=include_diagonals),
                encoding="utf-8",
            )
            os.replace(tmp_out, out_py)
        return out_py

    def _ensure_standard_scad(
        self,
        content_hash: str,
        script_path: Optional[Path],
        vertices=None,
        faces=None,
        include_diagonals: bool = True,
    ) -> Optional[Path]:
        vertices, faces = self._resolve_geometry(script_path, vertices, faces)
        if vertices is None or faces is None:
            return None
        tag = RENDER_CACHE_VERSION if include_diagonals else f"{RENDER_CACHE_VERSION}_clean"
        out_scad = self.tmp_dir / f"{content_hash}_{tag}.scad"
        if out_scad.exists() and out_scad.stat().st_size > 100:
            return out_scad
        scene_lock = self._get_lock(f"scene_scad:{content_hash}:{tag}")
        with scene_lock:
            if out_scad.exists() and out_scad.stat().st_size > 100:
                return out_scad
            tmp_out = self.tmp_dir / f"{content_hash}_{tag}_{threading.get_ident()}.tmp.scad"
            tmp_out.write_text(
                _generate_standard_scad(vertices, faces, 20.0, include_diagonals=include_diagonals),
                encoding="utf-8",
            )
            os.replace(tmp_out, out_scad)
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
            "--imgsize=1200,1200",
            "--colorscheme=Tomorrow",
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
        include_diagonals: bool = True,
    ) -> bool:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection
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

            coll = Poly3DCollection(polys, facecolors=face_colors, edgecolors=(0.93, 0.96, 1.0, 0.9), linewidths=1.2)
            ax.add_collection3d(coll)

            if include_diagonals:
                _, diags = _extract_real_edges_and_diagonals(faces)
                if diags:
                    diag_segs = [[V[a], V[b]] for a, b, _ in diags]
                    diag_coll = Line3DCollection(diag_segs, colors=(0.84, 0.91, 1.0, 0.72), linewidths=0.75)
                    ax.add_collection3d(diag_coll)
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
            "--imgsize=1200,1200",
            "--colorscheme=Tomorrow",
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
                timeout=45,
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
