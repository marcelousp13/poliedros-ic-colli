# ==============================================================================
# WEB INTERFACE — CONSTRUTOR DO ATLAS ESTÁTICO (GITHUB PAGES & CI/CD)
# Executa validação matemática oficial + deduplicação por isomorfismo métrico
# + certificado de convexidade + renderização fotográfica (PythonSCAD / OpenSCAD
# / Matplotlib 3D) e gera um site 100% estático em docs/ pronto para GitHub Pages.
# NÃO modifica nenhum arquivo oficial do projeto.
# ==============================================================================

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


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
STATIC_DIR = WEB_DIR / "static"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from PIL import Image

from geometry_analyzer import (
    CATALOG_SEGMENTS,
    CatalogService,
    compact_execution_metadata,
)
from scad_renderer import CAMERA_PRESETS, PythonSCADRenderer
from validador_cientifico import ValidadorCientifico
from verificadores.isomorfismo import construir_matriz_distancias


def _save_webp_from_image(src_path: Path, dst_webp: Path, max_size: int = 720, quality: int = 88) -> bool:
    """Converte PNG/WebP para WebP otimizado (reduz ~5x a ~17x o peso do site sem perda perceptível)."""
    try:
        with Image.open(src_path) as im:
            rgb = im.convert("RGB")
            if max(rgb.size) > max_size:
                rgb = rgb.resize((max_size, max_size), Image.Resampling.LANCZOS)
            dst_webp.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst_webp.with_suffix(".tmp.webp")
            rgb.save(tmp, format="WEBP", quality=quality, method=6)
            os.replace(tmp, dst_webp)
        return dst_webp.exists() and dst_webp.stat().st_size > 300
    except Exception:
        return False


def safe_slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    return slug.strip("_") or "solid"


def _compute_geom_hash(vertices: List[List[float]], faces: List[List[int]]) -> str:
    return hashlib.sha1(
        json.dumps(
            {"v": [[round(float(c), 6) for c in p] for p in vertices], "f": faces},
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:14]


def _load_existing_site_solutions(
    solids_data_dir: Path,
    validador: ValidadorCientifico,
    skip_verify: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Carrega os mínimos que JÁ existem no site (em docs/data/solids/*.json),
    servindo como base oficial para a verificação incremental de 4 passos:
      1. Novo mínimo na pasta
      2. Já existe mínimo para esse sólido no site
      3. Verifica se é igual (isomorfismo métrico)
      4. Se for igual, descarta; se for novo e cumprir todas as exigências, adiciona no site.
    """
    existing_by_solid: Dict[str, List[Dict[str, Any]]] = {}
    if not solids_data_dir.is_dir():
        return existing_by_solid

    for jf in sorted(solids_data_dir.glob("*.json")):
        try:
            payload = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        sid = payload.get("id")
        if not sid:
            continue

        raw_sols = payload.get("global_solutions") or (
            (payload.get("convex_solutions") or []) + (payload.get("nonconvex_solutions") or [])
        )
        kept_for_solid: List[Dict[str, Any]] = []
        for sol in raw_sols:
            verts = sol.get("vertices")
            faces = sol.get("faces") or []
            if not verts:
                continue

            if not skip_verify:
                check = validador.validar_solucao_global(sid, verts, faces)
                if not check["valid"]:
                    continue
                faces = check["faces_oriented"]
                sol["fval"] = float(check["fval_recomputed"])
                sol["is_convex"] = bool(check["is_convex"])
                sol["classification"] = check["classification"]
                sol["source_folder"] = check["source_folder"]
                sol["convexity"] = {
                    k: v for k, v in check["convexity"].items() if k != "oriented_faces"
                }
                sol["self_intersection"] = check["self_intersection"]
                sol["has_self_intersection"] = False
                sol["faces"] = faces
                sol["verified_official"] = True

            # Evita duplicatas internas caso o json antigo tivesse alguma
            iso = validador.verificar_igualdade_isometrica(verts, kept_for_solid)
            if iso["is_equal"]:
                continue

            sol_copy = dict(sol)
            sol_copy["geom_hash"] = sol_copy.get("geom_hash") or _compute_geom_hash(verts, faces)
            sol_copy["already_on_site"] = True
            sol_copy["_dist_matrix"] = construir_matriz_distancias(verts)
            kept_for_solid.append(sol_copy)

        if kept_for_solid:
            existing_by_solid[sid] = kept_for_solid

    return existing_by_solid


def build_static_atlas(
    output_dir: Path,
    presets: List[str],
    skip_verify: bool = False,
    extra_source_dirs: List[Path] | None = None,
    reset_site: bool = False,
    force_renders: bool = False,
) -> Dict[str, Any]:
    output_dir = Path(output_dir).resolve()
    data_dir = output_dir / "data"
    solids_data_dir = data_dir / "solids"
    renders_dir = output_dir / "renders"
    files_dir = output_dir / "files"

    catalog_svc = CatalogService(PROJECT_ROOT)
    validador = ValidadorCientifico()
    renderer = PythonSCADRenderer(max_concurrency=4)
    render_jobs = []  # (solid_id, sol_id, scad_path, preset, vertices, faces, target_png, render_map)

    # 0. Carrega mínimos que JÁ existem no site antes de atualizar data/
    existing_site_map: Dict[str, List[Dict[str, Any]]] = {}
    if not reset_site and solids_data_dir.is_dir():
        existing_site_map = _load_existing_site_solutions(solids_data_dir, validador, skip_verify=skip_verify)

    if reset_site:
        if data_dir.exists():
            shutil.rmtree(data_dir)
        if files_dir.exists():
            shutil.rmtree(files_dir)

    solids_data_dir.mkdir(parents=True, exist_ok=True)
    renders_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)

    solids_base = catalog_svc.list_all_solids_from_faces_txt()
    used_render_names = set()
    active_detail_slugs = set()

    # Mapeia pastas extras (ex: pasta de Colli ou Thomas) por nome canônico do sólido
    canonical_map = {e["id"].lower(): e["id"] for e in solids_base}
    extra_dirs_by_solid: Dict[str, List[Path]] = {}
    for src in (extra_source_dirs or []):
        src_p = Path(src).resolve()
        if not src_p.exists():
            continue
        if any((src_p / d).is_dir() for d in ("minimos_globais", "globais", "minimos_locais", "locais")):
            sid_key = canonical_map.get(src_p.name.lower(), src_p.name)
            extra_dirs_by_solid.setdefault(sid_key, []).append(src_p)
        else:
            for child in sorted(src_p.iterdir()):
                if child.is_dir():
                    sid_key = canonical_map.get(child.name.lower(), child.name)
                    extra_dirs_by_solid.setdefault(sid_key, []).append(child)

    stats = {
        "total_solids": len(solids_base),
        "elementary_solids": sum(1 for e in solids_base if e.get("is_elementary")),
        "active_topology_solids": 0,
        "pending_topology_solids": 0,
        "solids_with_global": 0,
        "solids_with_convex_global": 0,
        "solids_with_nonconvex_global": 0,
        "total_global_solutions": 0,
        "total_convex_solutions": 0,
        "total_nonconvex_solutions": 0,
        "existing_kept": 0,
        "new_solutions_added": 0,
        "duplicates_removed": 0,
        "rejected_invalid": 0,
        "renders_generated": 0,
        "renders_reused": 0,
        "render_engine": renderer.engine_name,
    }

    catalog_items: List[Dict[str, Any]] = []
    detail_payloads: List[Any] = []

    print(f"[Atlas] Construindo/atualizando site estático em: {output_dir}")
    print(f"[Atlas] Motor de renderização detectado: {renderer.engine_name}")
    print("[Atlas] Verificação incremental de 4 passos ativa (puxa apenas NOVOS mínimos válidos)")

    for entry in solids_base:
        sid = entry["id"]
        slug = safe_slug(sid)
        if entry["has_topology"]:
            stats["active_topology_solids"] += 1
        else:
            stats["pending_topology_solids"] += 1

        # Base existente no site para este sólido (Passo 2)
        site_solutions: List[Dict[str, Any]] = list(existing_site_map.get(sid, []))
        stats["existing_kept"] += len(site_solutions)
        existing_by_id: Dict[str, Dict[str, Any]] = {s["solution_id"]: s for s in site_solutions}

        # Coleta candidatos na pasta local solidos/<sid> e em pastas extras (ex: pasta de Colli)
        candidate_dirs = [PROJECT_ROOT / "solidos" / sid] + extra_dirs_by_solid.get(sid, [])
        seen_json_paths = set()
        pairs = []
        for sdir in candidate_dirs:
            for rec in catalog_svc._collect_global_records(sdir):
                ref_p = rec.get("json") or rec.get("scad")
                if ref_p:
                    rp = str(Path(ref_p).resolve())
                    if rp in seen_json_paths:
                        continue
                    seen_json_paths.add(rp)
                pairs.append(rec)

        for rec in pairs:
            analyzed = catalog_svc._analyze_global_record(sid, entry["faces_raw"], rec)
            if analyzed is None:
                continue

            sol_id = analyzed["solution_id"]
            cand_hash = analyzed.get("geom_hash") or _compute_geom_hash(analyzed["vertices"], analyzed["faces"])

            # Se for exatamente o mesmo registro já indexado no site (mesmo ID e mesmo geom_hash),
            # vincula os caminhos locais e absorve metadados técnicos de execução (se agora disponíveis)
            if sol_id in existing_by_id and existing_by_id[sol_id].get("geom_hash") == cand_hash:
                ex = existing_by_id[sol_id]
                for k in ("scad_path", "json_path", "txt_path"):
                    if analyzed.get(k):
                        ex[k] = analyzed[k]
                if analyzed.get("execucao") and not ex.get("execucao"):
                    ex["execucao"] = analyzed["execucao"]
                continue

            # ==================================================================
            # PROTOCOLO DE 4 PASSOS DO SITE:
            #   1. Novo mínimo detectado na pasta
            #   2. Verifica se já existe mínimo para esse sólido no site
            #   3. Verifica se é igual (isomorfismo métrico)
            #   4. Se for igual, descarta; se for novo e cumprir todas as exigências, adiciona
            # ==================================================================
            if not skip_verify:
                if not entry["has_topology"]:
                    stats["rejected_invalid"] += 1
                    print(f"  [1-4 · REJEITADO] {sid}/{sol_id}: sólido sem topologia ativa em faces.txt.")
                    continue

                avaliacao = validador.avaliar_novo_minimo_4_passos(sid, analyzed, site_solutions)
                if not avaliacao["accepted"]:
                    if avaliacao["status"] == "descartado_igual":
                        stats["duplicates_removed"] += 1
                        print(
                            f"  [1-4 · DESCARTADO (IGUAL AO SITE)] {sid}/{sol_id}: "
                            f"já existe mínimo isométrico igual no site ({avaliacao['matched_solution_id']})."
                        )
                    else:
                        stats["rejected_invalid"] += 1
                        print(f"  [1-4 · REJEITADO (EXIGÊNCIAS)] {sid}/{sol_id}: {avaliacao['reason']}")
                    continue

                analyzed["fval"] = float(avaliacao["fval_recomputed"])
                analyzed["is_convex"] = bool(avaliacao["is_convex"])
                analyzed["classification"] = avaliacao["classification"]
                analyzed["source_folder"] = avaliacao["source_folder"]
                analyzed["convexity"] = {
                    k: v for k, v in avaliacao["convexity"].items() if k != "oriented_faces"
                }
                analyzed["self_intersection"] = avaliacao["self_intersection"]
                analyzed["has_self_intersection"] = False
                analyzed["faces"] = avaliacao["faces_oriented"]
                analyzed["verified_official"] = True
                analyzed["geom_hash"] = _compute_geom_hash(analyzed["vertices"], analyzed["faces"])
            else:
                iso = validador.verificar_igualdade_isometrica(analyzed["vertices"], site_solutions)
                if iso["is_equal"]:
                    stats["duplicates_removed"] += 1
                    continue
                analyzed["verified_official"] = False
                analyzed["geom_hash"] = cand_hash

            # Se o solution_id colidir com outro mínimo distinto já existente no site, desambigua com o geom_hash
            if analyzed["solution_id"] in existing_by_id:
                analyzed["solution_id"] = f"{analyzed['solution_id']}_{analyzed['geom_hash'][:6]}"

            analyzed["already_on_site"] = True
            analyzed["_dist_matrix"] = construir_matriz_distancias(analyzed["vertices"])
            site_solutions.append(analyzed)
            existing_by_id[analyzed["solution_id"]] = analyzed
            stats["new_solutions_added"] += 1
            aba_destino = "Resultados" if analyzed["source_folder"] == "convexos" else "Descobertas"
            print(
                f"  [1-4 · NOVO MÍNIMO ADICIONADO AO SITE] {sid}/{analyzed['solution_id']} "
                f"-> aba {aba_destino} (F(x) = {analyzed['fval']:.2e})"
            )

        unique_convex = [s for s in site_solutions if s["source_folder"] == "convexos"]
        unique_nonconvex = [s for s in site_solutions if s["source_folder"] != "convexos"]
        unique_convex.sort(key=lambda s: (s["fval"], s["timestamp"]))
        unique_nonconvex.sort(key=lambda s: (s["fval"], s["timestamp"]))
        unique_globals = unique_convex + unique_nonconvex

        # Renderiza fotos e copia arquivos oficiais para download
        sol_out_list: List[Dict[str, Any]] = []
        for sol in unique_globals:
            sol_id = sol["solution_id"]
            sol_slug = safe_slug(sol_id)
            cat_folder = sol["source_folder"]  # "convexos" | "nao_convexos"
            scad_path = Path(sol["scad_path"]) if sol.get("scad_path") else None
            json_path = Path(sol["json_path"]) if sol.get("json_path") else None
            txt_path = Path(sol["txt_path"]) if sol.get("txt_path") else None

            geom_hash = sol.get("geom_hash") or _compute_geom_hash(sol["vertices"], sol["faces"])

            render_map: Dict[str, str] = {}
            render_clean_map: Dict[str, str] = {}
            thumb_rel: Optional[str] = None
            thumb_clean_rel: Optional[str] = None
            has_face_diags = any(len(f) >= 4 for f in sol["faces"])

            def _schedule_or_reuse_webp(preset_key: str, include_diags: bool, target_map: Dict[str, str]) -> Optional[str]:
                suffix = "" if include_diags else "_clean"
                webp_name = f"{slug}_{geom_hash}_{preset_key}{suffix}.webp"
                target_webp = renders_dir / webp_name
                legacy_png = renders_dir / f"{slug}_{geom_hash}_{preset_key}{suffix}.png"
                used_render_names.add(webp_name)
                target_map[preset_key] = f"./renders/{webp_name}"

                make_thumb = preset_key == "iso"
                thumb_name = f"{slug}_{geom_hash}_{preset_key}{suffix}_thumb.webp" if make_thumb else None
                target_thumb = (renders_dir / thumb_name) if thumb_name else None
                if thumb_name:
                    used_render_names.add(thumb_name)

                if not force_renders and target_webp.exists() and target_webp.stat().st_size > 400:
                    stats["renders_reused"] += 1
                    if target_thumb and (not target_thumb.exists() or target_thumb.stat().st_size <= 300):
                        _save_webp_from_image(target_webp, target_thumb, max_size=360, quality=84)
                elif not force_renders and legacy_png.exists() and legacy_png.stat().st_size > 1000:
                    if _save_webp_from_image(legacy_png, target_webp, max_size=720, quality=88):
                        stats["renders_reused"] += 1
                        if target_thumb:
                            _save_webp_from_image(legacy_png, target_thumb, max_size=360, quality=84)
                    else:
                        render_jobs.append((
                            sid, sol_id, scad_path, preset_key,
                            sol["vertices"], sol["faces"], target_webp, target_thumb, target_map, include_diags,
                        ))
                else:
                    render_jobs.append((
                        sid, sol_id, scad_path, preset_key,
                        sol["vertices"], sol["faces"], target_webp, target_thumb, target_map, include_diags,
                    ))

                return f"./renders/{thumb_name}" if thumb_name else None

            for preset in presets:
                t_rel = _schedule_or_reuse_webp(preset, True, render_map)
                if preset == "iso":
                    thumb_rel = t_rel

                if has_face_diags:
                    tc_rel = _schedule_or_reuse_webp(preset, False, render_clean_map)
                    if preset == "iso":
                        thumb_clean_rel = tc_rel
                else:
                    render_clean_map[preset] = render_map[preset]
                    if preset == "iso":
                        thumb_clean_rel = thumb_rel

            # Copia arquivos oficiais para downloads estáticos (ou preserva os já existentes em docs/files/)
            sol_files_dir = files_dir / slug / cat_folder
            dl_map: Dict[str, str] = dict(sol.get("downloads") or {})

            dst_scad = sol_files_dir / f"{sol_slug}_pythonscad.py"
            if scad_path and scad_path.exists():
                sol_files_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(scad_path, dst_scad)
                dl_map["scad"] = f"./files/{slug}/{cat_folder}/{dst_scad.name}"
            elif dst_scad.exists():
                dl_map["scad"] = f"./files/{slug}/{cat_folder}/{dst_scad.name}"

            dst_json = sol_files_dir / f"{sol_slug}.json"
            if json_path and json_path.exists():
                sol_files_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(json_path, dst_json)
                dl_map["json"] = f"./files/{slug}/{cat_folder}/{dst_json.name}"
            elif dst_json.exists():
                dl_map["json"] = f"./files/{slug}/{cat_folder}/{dst_json.name}"

            dst_txt = sol_files_dir / f"{sol_slug}.txt"
            if txt_path and txt_path.exists():
                sol_files_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(txt_path, dst_txt)
                dl_map["txt"] = f"./files/{slug}/{cat_folder}/{dst_txt.name}"
            elif dst_txt.exists():
                dl_map["txt"] = f"./files/{slug}/{cat_folder}/{dst_txt.name}"

            sol_out = {
                "solution_id": sol_id,
                "geom_hash": geom_hash,
                "source_folder": cat_folder,
                "fval": sol["fval"],
                "timestamp": sol["timestamp"],
                "is_convex": sol["is_convex"],
                "classification": sol["classification"],
                "has_self_intersection": sol.get("has_self_intersection", False),
                "self_intersection": sol.get("self_intersection"),
                "verified_official": sol.get("verified_official", True),
                "convexity": sol["convexity"],
                "hessian": sol.get("hessian"),
                "execucao": sol.get("execucao"),
                "has_scad": "scad" in dl_map,
                "has_json": "json" in dl_map,
                "has_txt": "txt" in dl_map,
                "thumb": thumb_rel or render_map.get("iso"),
                "thumb_clean": thumb_clean_rel or render_clean_map.get("iso"),
                "renders": render_map,
                "renders_clean": render_clean_map,
                "downloads": dl_map,
                "vertices": sol["vertices"],
                "faces": sol["faces"],
                "distancias": sol.get("distancias", []),
                "angulos_salvos": sol.get("angulos_salvos", []),
                "autovalores": sol.get("autovalores", []),
            }
            sol_out_list.append(sol_out)

        convex_sols = [s for s in sol_out_list if s["source_folder"] == "convexos"]
        nonconvex_sols = [s for s in sol_out_list if s["source_folder"] == "nao_convexos"]

        if sol_out_list:
            stats["solids_with_global"] += 1
            stats["total_global_solutions"] += len(sol_out_list)
            active_detail_slugs.add(f"{slug}.json")
            detail_payload = {
                "id": sid,
                "slug": slug,
                "display_code": entry["display_code"],
                "name_pt": entry["name_pt"],
                "name_en": entry["name_en"],
                "family": entry["family"],
                "segment": entry["segment"],
                "is_elementary": entry["is_elementary"],
                "has_topology": entry["has_topology"],
                "topology": entry["topology"],
                "convex_solutions": convex_sols,
                "nonconvex_solutions": nonconvex_sols,
                "global_solutions": sol_out_list,
            }
            detail_payloads.append((slug, detail_payload))

        if convex_sols:
            stats["solids_with_convex_global"] += 1
            stats["total_convex_solutions"] += len(convex_sols)
        if nonconvex_sols:
            stats["solids_with_nonconvex_global"] += 1
            stats["total_nonconvex_solutions"] += len(nonconvex_sols)

        primary_convex = convex_sols[0] if convex_sols else None
        primary_nonconvex = nonconvex_sols[0] if nonconvex_sols else None
        # Catálogo unificado: prefere convexo na capa; se houver apenas global não convexo
        # sem autointerseção, exibe-o normalmente sem nunca descartá-lo!
        primary_any = primary_convex or primary_nonconvex

        def compact_brief(s: Dict[str, Any]) -> Dict[str, Any]:
            c = s.get("convexity") or {}
            out = {
                "solution_id": s["solution_id"],
                "geom_hash": s.get("geom_hash", ""),
                "fval": s["fval"],
                "is_convex": s["is_convex"],
                "thumb": s.get("thumb") or (s.get("renders") or {}).get("iso"),
                "thumb_clean": s.get("thumb_clean") or (s.get("renders_clean") or {}).get("iso"),
                "max_dihedral_deg": c.get("max_dihedral_deg"),
                "volume_ratio": c.get("volume_ratio"),
            }
            ex = compact_execution_metadata(s.get("execucao"))
            if ex:
                out["execucao"] = ex
            return out

        catalog_items.append({
            "id": sid,
            "slug": slug,
            "detail_url": f"./data/solids/{slug}.json" if sol_out_list else None,
            "display_code": entry["display_code"],
            "name_pt": entry["name_pt"],
            "name_en": entry["name_en"],
            "family": entry["family"],
            "segment": entry["segment"],
            "is_elementary": entry["is_elementary"],
            "sort_key": entry["sort_key"],
            "has_topology": entry["has_topology"],
            "topology": entry["topology"],
            "has_global": bool(sol_out_list),
            "has_convex_global": bool(convex_sols),
            "has_nonconvex_global": bool(nonconvex_sols),
            "global_count": len(sol_out_list),
            "convex_count": len(convex_sols),
            "nonconvex_count": len(nonconvex_sols),
            "primary_global": compact_brief(primary_any) if primary_any else None,
            "global_solutions": [compact_brief(s) for s in sol_out_list],
        })

    # Executa todas as renderizações pendentes em paralelo (4 workers PythonSCAD/OpenSCAD -> WebP otimizado)
    if render_jobs:
        print(f"[Atlas] Renderizando {len(render_jobs)} fotografia(s) via {renderer.engine_name} em paralelo...")

        def _run_job(job):
            sid, sol_id, scad_path, preset, verts, faces, target_webp, target_thumb, render_map, include_diags = job
            rendered = renderer.render_solution_png(
                solid_id=sid,
                solution_id=sol_id,
                scad_path=scad_path,
                preset=preset,
                vertices=verts,
                faces=faces,
                force=force_renders,
                include_diagonals=include_diags,
            )
            if rendered and rendered.exists():
                ok_full = _save_webp_from_image(rendered, target_webp, max_size=720, quality=88)
                if ok_full and target_thumb is not None:
                    _save_webp_from_image(rendered, target_thumb, max_size=360, quality=84)
                if ok_full:
                    return True
            render_map.pop(preset, None)
            return False

        with ThreadPoolExecutor(max_workers=4) as pool:
            for ok in pool.map(_run_job, render_jobs):
                if ok:
                    stats["renders_generated"] += 1

    # Grava os dossiês individuais após concluir as renderizações (JSON compacto sem espaços extras)
    for slug, detail_payload in detail_payloads:
        (solids_data_dir / f"{slug}.json").write_text(
            json.dumps(detail_payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    for existing_json in solids_data_dir.glob("*.json"):
        if existing_json.name not in active_detail_slugs:
            existing_json.unlink(missing_ok=True)

    # Remove imagens órfãs/antigas (PNGs legados e WebPs não usados) de renders_dir
    for existing_img in renders_dir.iterdir():
        if existing_img.is_file() and existing_img.suffix.lower() in (".png", ".webp"):
            if existing_img.name not in used_render_names:
                existing_img.unlink(missing_ok=True)

    # Grava catálogo estático principal (compacto para carregamento instantâneo)
    catalog_payload = {
        "mode": "static",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "render_engine": renderer.engine_name,
        "segments": CATALOG_SEGMENTS,
        "summary": stats,
        "solids": catalog_items,
    }
    (data_dir / "catalog.json").write_text(
        json.dumps(catalog_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    # Copia assets institucionais (logotipo IME-USP, emblema Arquimedes, favicon)
    assets_src = STATIC_DIR / "assets"
    assets_dst = output_dir / "assets"
    if assets_src.is_dir():
        assets_dst.mkdir(parents=True, exist_ok=True)
        valid_asset_names = set()
        for af in assets_src.iterdir():
            if af.is_file():
                shutil.copy2(af, assets_dst / af.name)
                valid_asset_names.add(af.name)
        for old_af in assets_dst.iterdir():
            if old_af.is_file() and old_af.name not in valid_asset_names:
                old_af.unlink(missing_ok=True)

    # Copia frontend (ajustando rotas de /static/ para relativas ./ + cache-busting por hash)
    css_bytes = (STATIC_DIR / "styles.css").read_bytes()
    js_bytes = (STATIC_DIR / "app.js").read_bytes()
    css_ver = hashlib.sha1(css_bytes).hexdigest()[:8]
    js_ver = hashlib.sha1(js_bytes).hexdigest()[:8]

    html_src = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html_static = (
        html_src
        .replace("<body>", '<body data-atlas-mode="static">', 1)
        .replace('href="/static/styles.css"', f'href="./styles.css?v={css_ver}"')
        .replace('src="/static/app.js"', f'src="./app.js?v={js_ver}"')
        .replace('href="/static/', 'href="./')
        .replace('src="/static/', 'src="./')
    )
    (output_dir / "index.html").write_text(html_static, encoding="utf-8")
    (output_dir / "styles.css").write_bytes(css_bytes)
    (output_dir / "app.js").write_bytes(js_bytes)
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")

    print("-" * 68)
    print(f"  Sólidos catalogados       : {stats['total_solids']} ({stats['elementary_solids']} elementares · {stats['active_topology_solids']} ativos)")
    print(f"  Globais convexos          : {stats['total_convex_solutions']} (em {stats['solids_with_convex_global']} sólidos)")
    print(f"  Globais não convexos      : {stats['total_nonconvex_solutions']} (em {stats['solids_with_nonconvex_global']} sólidos)")
    print(f"  Mínimos já no site        : {stats['existing_kept']} mantidos")
    print(f"  NOVOS mínimos adicionados : {stats['new_solutions_added']} adicionados")
    print(f"  Duplicatas isométricas    : {stats['duplicates_removed']} descartadas")
    print(f"  Soluções rejeitadas       : {stats['rejected_invalid']}")
    print(f"  Fotos WebP geradas/cache  : {stats['renders_generated']} novas / {stats['renders_reused']} reutilizadas")
    print("-" * 68)
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera o Atlas Científico Estático em docs/ para GitHub Pages")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "docs"), help="Pasta de saída estática (padrão: docs/)")
    parser.add_argument("--presets", nargs="+", default=list(CAMERA_PRESETS.keys()), help="Ângulos a renderizar")
    parser.add_argument("--fontes", nargs="*", default=[], help="Pastas adicionais de mínimos (ex.: pasta de Colli ou Thomas)")
    parser.add_argument("--reset-site", action="store_true", help="Reconstrói do zero ignorando base anterior de docs/data/")
    parser.add_argument("--regerar-fotos", action="store_true", help="Força regeração de todas as fotografias PNG em docs/renders/")
    parser.add_argument("--skip-verify", action="store_true", help="Pula re-validação oficial (não recomendado)")
    args = parser.parse_args()
    build_static_atlas(
        Path(args.output),
        presets=args.presets,
        skip_verify=args.skip_verify,
        extra_source_dirs=[Path(p) for p in args.fontes],
        reset_site=args.reset_site,
        force_renders=args.regerar_fotos,
    )
