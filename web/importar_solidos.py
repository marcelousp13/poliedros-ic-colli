# ==============================================================================
# WEB INTERFACE — IMPORTADOR E VERIFICADOR CIENTÍFICO DE 4 PASSOS
# Aponta diretamente para qualquer pasta local no computador do pesquisador
# (Marcelo, Thomas ou Prof. Eduardo Colli), ex.:
#   python web/importar_solidos.py "C:\caminho\para\pasta_do_colli" --aplicar
#
# Executa rigorosamente o protocolo de 4 passos:
#   1. Detecta novo mínimo na pasta informada
#   2. Verifica se já existe mínimo para esse sólido no site
#   3. Verifica se é igual (isomorfismo métrico via backtracking do Prof. Colli)
#   4. Se for igual, descarta. Se for novo, valida todas as exigências científicas
#      (topologia ativa em faces.txt, energia |F(x)| < 1e-6, não degenerado,
#      sem colinearidade e SEM autointerseção de faces) e adiciona ao site!
# NUNCA modifica os arquivos da pasta de origem externa nem nenhum código oficial.
# ==============================================================================

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


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

from construir_site_estatico import _compute_geom_hash, _load_existing_site_solutions, build_static_atlas
from dados.carregador_topologia import CarregadorTopologia
from exportadores.pythonscad_exportador import ExportadorPythonSCAD
from geometry_analyzer import CatalogService, parse_pythonscad_file
from github_sync import load_github_config, sync_global_solutions_to_github
from persistencia.gerenciador_solucoes import GerenciadorSolucoes
from scad_renderer import CAMERA_PRESETS
from topologia.orientador_faces import OrientadorFaces
from validador_cientifico import ValidadorCientifico
from verificadores.isomorfismo import construir_matriz_distancias
from verificadores.verificador_geometrico import VerificadorGeometrico


IGNORED_WALK_DIRS = {
    ".git",
    "__pycache__",
    "docs",
    "cache",
    "minimos_locais",
    "mínimos locais",
    "locais",
}


def _extract_stem_and_ts(stem: str) -> Tuple[str, Optional[str]]:
    clean = stem[:-11] if stem.endswith("_pythonscad") else stem
    m = re.match(r"^(.*)_(\d{8}_\d{6})$", clean)
    if m:
        return m.group(1), m.group(2)
    return clean, None


def _all_global_json_files(solid_dir: Path) -> List[Path]:
    found: List[Path] = []
    candidates = [
        solid_dir / "globais",
        solid_dir / "minimos_globais" / "convexos",
        solid_dir / "minimos_globais" / "convexos" / "sem_autointersecao",
        solid_dir / "minimos_globais" / "convexos" / "com_autointersecao",
        solid_dir / "minimos_globais" / "nao_convexos",
        solid_dir / "minimos_globais" / "nao_convexos" / "sem_autointersecao",
        solid_dir / "minimos_globais" / "nao_convexos" / "com_autointersecao",
    ]
    seen = set()
    for d in candidates:
        if not d.is_dir():
            continue
        for jf in sorted(d.glob("*.json")):
            rp = str(jf.resolve())
            if rp not in seen:
                seen.add(rp)
                found.append(jf)
    return found


def _discover_candidates_in_sources(
    source_dirs: List[Path],
    canonical_map: Dict[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Varre recursivamente qualquer pasta local informada (ex.: pasta do Prof. Colli,
    pasta do Thomas, subpastas `solidos/`, `globais/`, `minimos_globais/` ou arquivos
    JSON/PythonSCAD em qualquer nível de profundidade) e agrupa os candidatos por sólido.
    """
    candidates_by_solid: Dict[str, List[Dict[str, Any]]] = {}
    seen_files: Set[str] = set()

    for src in source_dirs:
        src_path = Path(src).resolve()
        if not src_path.exists():
            print(f"  [Aviso] Caminho não encontrado: {src_path}")
            continue

        # Caso o usuário aponte diretamente para um arquivo .json ou *_pythonscad.py
        if src_path.is_file():
            files_to_inspect = [src_path]
        else:
            files_to_inspect = []
            for root, dirs, filenames in os.walk(src_path):
                dirs[:] = [d for d in dirs if d not in IGNORED_WALK_DIRS and d.lower() not in IGNORED_WALK_DIRS]
                root_p = Path(root)
                for fn in sorted(filenames):
                    if fn.lower().endswith(".json") or fn.lower().endswith("_pythonscad.py"):
                        files_to_inspect.append(root_p / fn)

        # Primeiro processa todos os arquivos .json
        scad_covered: Set[str] = set()
        for fp in files_to_inspect:
            if not fp.name.lower().endswith(".json"):
                continue
            rp = str(fp.resolve())
            if rp in seen_files:
                continue

            # Ignora arquivos de configuração/catálogo que não são soluções de sólidos
            if fp.name in ("catalog.json", "analysis_cache.json", "enviados_github.json", "config_github.json", "config_github.example.json"):
                continue

            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue

            # Ignora mínimos declarados explicitamente como locais
            if str(data.get("tipo", "global")).lower() == "local":
                continue

            vc = data.get("vc") or data.get("vertices")
            if not vc or not isinstance(vc, list):
                continue

            # Identifica o sólido pelo campo "nome" no JSON ou pelo nome de alguma pasta ancestral
            raw_name = str(data.get("nome") or data.get("id") or "").strip()
            solid_id = canonical_map.get(raw_name.lower()) if raw_name else None
            if not solid_id:
                for part in reversed(fp.parent.parts):
                    if part.lower() in canonical_map:
                        solid_id = canonical_map[part.lower()]
                        break
            if not solid_id:
                continue

            seen_files.add(rp)
            companion_scad = fp.parent / f"{fp.stem}_pythonscad.py"
            if companion_scad.exists():
                scad_covered.add(str(companion_scad.resolve()))

            candidates_by_solid.setdefault(solid_id, []).append({
                "file_path": fp,
                "solution_id": fp.stem,
                "vc": vc,
                "fval": float(data.get("fval", 0.0)),
                "timestamp": str(data.get("timestamp", "")),
                "distancias": data.get("distancias"),
                "angulos_diedrais": data.get("angulos_diedrais"),
                "autovalores": data.get("autovalores"),
                "execucao": data.get("execucao"),
            })

        # Também suporta pastas que tenham scripts *_pythonscad.py órfãos (sem .json ao lado)
        for fp in files_to_inspect:
            if not fp.name.lower().endswith("_pythonscad.py"):
                continue
            rp = str(fp.resolve())
            if rp in seen_files or rp in scad_covered:
                continue
            companion_json = fp.parent / f"{fp.stem[:-11]}.json"
            if companion_json.exists():
                continue

            solid_id = None
            for part in reversed(fp.parent.parts):
                if part.lower() in canonical_map:
                    solid_id = canonical_map[part.lower()]
                    break
            if not solid_id:
                continue

            parsed = parse_pythonscad_file(fp)
            if not parsed:
                continue
            pts, _ = parsed
            seen_files.add(rp)
            candidates_by_solid.setdefault(solid_id, []).append({
                "file_path": fp,
                "solution_id": fp.stem[:-11],
                "vc": pts,
                "fval": 0.0,
                "timestamp": "",
                "distancias": None,
                "angulos_diedrais": None,
                "autovalores": None,
                "execucao": None,
            })

    return candidates_by_solid


def importar_pasta(
    source_dirs: List[Path],
    apply_copy: bool = False,
    include_locals: bool = True,
    clean_loose_files: bool = False,
    update_site: bool = True,
    sync_github: bool = True,
) -> Dict[str, int]:
    carregador = CarregadorTopologia()
    validador = ValidadorCientifico()
    catalog_svc = CatalogService(PROJECT_ROOT)
    gerenciador = GerenciadorSolucoes(pasta_base=str(PROJECT_ROOT / "solidos"))
    exportador = ExportadorPythonSCAD(fator_escala=20.0, pasta_base=str(PROJECT_ROOT / "solidos"))

    # Carrega os mínimos que JÁ existem no site (docs/data/solids/*.json)
    solids_data_dir = PROJECT_ROOT / "docs" / "data" / "solids"
    existing_site_map = _load_existing_site_solutions(solids_data_dir, validador) if not clean_loose_files else {}

    canonical_map: Dict[str, str] = {k.lower(): k for k in carregador.listar_solidos()}
    candidates_by_solid = _discover_candidates_in_sources(source_dirs, canonical_map)

    print("=" * 92)
    print("  VERIFICAÇÃO CIENTÍFICA DE 4 PASSOS DO SITE (PUXA APENAS NOVOS MÍNIMOS VÁLIDOS)")
    print(f"  Pasta(s) monitorada(s): {', '.join(str(Path(p).resolve()) for p in source_dirs)}")
    print(f"  Modo: {'APLICANDO E ATUALIZANDO O SITE' if apply_copy else 'SIMULAÇÃO (DRY-RUN — use --aplicar para gravar)'}")
    print("=" * 92)

    cnt_existing_site = 0
    cnt_new_conv_sem = 0
    cnt_new_nconv_sem = 0
    cnt_with_inter = 0
    total_dups = 0
    total_rejected = 0

    for solid_id in sorted(candidates_by_solid.keys(), key=lambda s: s.lower()):
        if not carregador.existe_solido(solid_id):
            continue

        faces_raw, _ = carregador.obter_solido(solid_id)
        faces_oriented = OrientadorFaces.corrigir_orientacao(faces_raw)
        dest_solid = PROJECT_ROOT / "solidos" / solid_id

        # Passo 2: Base de mínimos que JÁ existem no site para este sólido (preservando recorrências)
        site_solutions = list(existing_site_map.get(solid_id, []))
        seen_exact_keys: Set[Tuple[str, str]] = {
            (str(s.get("solution_id", "")), str(s.get("geom_hash") or _compute_geom_hash(s.get("vertices") or [])))
            for s in site_solutions
        }
        if not clean_loose_files and dest_solid.is_dir():
            for rec in catalog_svc._collect_global_records(dest_solid):
                analyzed = catalog_svc._analyze_global_record(solid_id, faces_raw, rec)
                if analyzed is None:
                    continue
                check = validador.validar_solucao_global(solid_id, analyzed["vertices"], faces_oriented)
                if not check["valid"]:
                    continue
                gh = _compute_geom_hash(analyzed["vertices"])
                ex_key = (str(analyzed.get("solution_id", "")), gh)
                if ex_key not in seen_exact_keys:
                    seen_exact_keys.add(ex_key)
                    analyzed["already_on_site"] = True
                    analyzed["geom_hash"] = gh
                    analyzed["_dist_matrix"] = construir_matriz_distancias(analyzed["vertices"])
                    site_solutions.append(analyzed)

        cnt_existing_site += len(site_solutions)

        # Conjunto de arquivos já gravados na pasta oficial sem_autointersecao/ deste sólido
        official_published_files: Set[str] = set()
        if not clean_loose_files and dest_solid.is_dir():
            for sub in ("convexos", "nao_convexos"):
                sdir = dest_solid / "minimos_globais" / sub / "sem_autointersecao"
                if sdir.is_dir():
                    for f_ex in sdir.iterdir():
                        if f_ex.is_file():
                            official_published_files.add(str(f_ex.resolve()))

        new_for_site = []
        new_with_intersection = []
        dups_here = 0
        rejected_here = 0

        for cand in candidates_by_solid[solid_id]:
            fp: Path = cand["file_path"]
            # Se este arquivo exato já está dentro da pasta oficial sem_autointersecao/ do site, pula
            if not clean_loose_files and str(fp.resolve()) in official_published_files:
                continue

            vc = cand["vc"]
            sol_id = cand["solution_id"]
            gh_cand = _compute_geom_hash(vc)
            if not clean_loose_files and (sol_id, gh_cand) in seen_exact_keys:
                dups_here += 1
                continue

            # ==================================================================
            # PROTOCOLO CIENTÍFICO (TODOS OS GLOBAIS SEM AUTOINTERSEÇÃO):
            #   1. Novo mínimo na pasta informada (ex.: pasta de Colli ou Thomas)
            #   2. Valida todas as exigências científicas (global, sem autointerseção)
            #   3. Classifica isometria em relação aos já catalogados
            #   4. Adiciona TODOS os mínimos globais limpos (inéditos ou recorrências)
            # ==================================================================
            avaliacao = validador.avaliar_novo_minimo_4_passos(
                solid_id,
                {"solution_id": sol_id, "vertices": vc, "faces": faces_oriented},
                site_solutions,
                permitir_isometricos=True,
            )

            if not avaliacao["accepted"]:
                if avaliacao["status"] == "descartado_igual":
                    dups_here += 1
                    continue

                v_info = avaliacao.get("validation") or {}
                si_info = v_info.get("self_intersection")
                if clean_loose_files and si_info and si_info.get("has_self_intersection"):
                    conv = VerificadorGeometrico.verificar_convexidade(vc, faces_oriented)
                    new_with_intersection.append({
                        "solution_id": sol_id,
                        "fval": float(v_info.get("fval_recomputed", 0.0)),
                        "timestamp": cand["timestamp"],
                        "vertices": vc,
                        "faces": conv["oriented_faces"],
                        "is_convex": bool(conv["is_convex"]),
                        "has_self_intersection": True,
                        "convexity": conv,
                        "self_intersection": si_info,
                        "distancias": cand["distancias"] or VerificadorGeometrico.calcular_distancias(vc).tolist(),
                        "angulos_diedrais": cand["angulos_diedrais"] or VerificadorGeometrico.calcular_angulos_diedrais(vc, faces_oriented).tolist(),
                        "autovalores": cand["autovalores"] or [],
                        "execucao": cand.get("execucao"),
                    })
                    cnt_with_inter += 1
                else:
                    rejected_here += 1
                    print(f"  [1-4 · REJEITADO (EXIGÊNCIAS)] {solid_id}/{sol_id}: {avaliacao['reason']}")
                continue

            conv = avaliacao["convexity"]
            si = avaliacao["self_intersection"]
            cand_obj = {
                "solution_id": sol_id,
                "fval": float(avaliacao["fval_recomputed"]),
                "timestamp": cand["timestamp"],
                "vertices": vc,
                "faces": avaliacao["faces_oriented"],
                "is_convex": bool(avaliacao["is_convex"]),
                "has_self_intersection": False,
                "convexity": conv,
                "self_intersection": si,
                "distancias": cand["distancias"] or VerificadorGeometrico.calcular_distancias(vc).tolist(),
                "angulos_diedrais": cand["angulos_diedrais"] or VerificadorGeometrico.calcular_angulos_diedrais(vc, faces_oriented).tolist(),
                "autovalores": cand["autovalores"] or [],
                "execucao": cand.get("execucao"),
                "already_on_site": True,
                "geom_hash": gh_cand,
                "_dist_matrix": construir_matriz_distancias(vc),
            }
            seen_exact_keys.add((sol_id, gh_cand))
            site_solutions.append(cand_obj)
            new_for_site.append(cand_obj)
            tag_rec = " (recorrência isométrica)" if avaliacao.get("is_isometric_repeat") else ""
            print(
                f"  [1-4 · MÍNIMO APROVADO{tag_rec}] {solid_id}/{sol_id} -> aba {avaliacao['target_tab']} "
                f"(F(x) = {cand_obj['fval']:.2e})"
            )

        total_dups += dups_here
        total_rejected += rejected_here

        cs = sum(1 for s in new_for_site if s["is_convex"])
        ns = sum(1 for s in new_for_site if not s["is_convex"])
        cnt_new_conv_sem += cs
        cnt_new_nconv_sem += ns

        if new_for_site or dups_here or rejected_here:
            print(
                f"  {solid_id:22s} | já no site={len(site_solutions) - len(new_for_site)} "
                f"| NOVOS(conv={cs}, desc={ns}) | descartados_iguais={dups_here:2d} | rejeitados={rejected_here:2d}"
            )

        to_write = new_for_site + new_with_intersection
        if apply_copy and to_write:
            if clean_loose_files:
                mg = dest_solid / "minimos_globais"
                if mg.is_dir():
                    shutil.rmtree(mg, ignore_errors=True)
                for leg in ("globais", "locais"):
                    lp = dest_solid / leg
                    if lp.is_dir():
                        shutil.rmtree(lp, ignore_errors=True)

            for s in to_write:
                nome_sol, ts = _extract_stem_and_ts(s["solution_id"])
                gerenciador.inspecionar_ou_registrar_isometria(
                    nome_solido=solid_id,
                    vertices=s["vertices"],
                    distancias=s["distancias"],
                    angulos=s["angulos_diedrais"],
                    fval=s["fval"],
                )
                gerenciador.salvar_arquivos_solucao(
                    nome_solucao=nome_sol,
                    tipo="global",
                    nome_solido=solid_id,
                    vc=s["vertices"],
                    distancias=s["distancias"],
                    angulos=s["angulos_diedrais"],
                    autovalores=s["autovalores"],
                    fval=s["fval"],
                    convexo=s["is_convex"],
                    tem_autointersecao=s["has_self_intersection"],
                    info_convexidade=s["convexity"],
                    info_autointersecao=s["self_intersection"],
                    timestamp=ts,
                    info_execucao=s.get("execucao"),
                )
                exportador.exportar_se_minimo_global(
                    nome_solido=solid_id,
                    nome_solucao=nome_sol,
                    tipo_solucao="global",
                    vertices=s["vertices"],
                    faces=s["faces"],
                    fval=s["fval"],
                    convexo=s["is_convex"],
                    tem_autointersecao=s["has_self_intersection"],
                    timestamp=ts,
                    nome_base_exato=gerenciador.ultimo_nome_base,
                )

    total_new = cnt_new_conv_sem + cnt_new_nconv_sem
    if apply_copy and update_site and (total_new > 0 or clean_loose_files):
        build_static_atlas(PROJECT_ROOT / "docs", presets=list(CAMERA_PRESETS.keys()), reset_site=clean_loose_files)
        if sync_github and load_github_config() is not None:
            ok_gh, msg_gh, sent_cnt = sync_global_solutions_to_github()
            print(f"  [GitHub Sync] {'✓' if ok_gh else '✗'} {msg_gh} ({sent_cnt} arquivo(s))")

    print("=" * 92)
    print(f"  Mínimos já existentes no site preservados     : {cnt_existing_site}")
    print(f"  NOVOS RESULTADOS adicionados (convexos)       : {cnt_new_conv_sem}")
    print(f"  NOVAS DESCOBERTAS adicionadas (não convexos)  : {cnt_new_nconv_sem}")
    print(f"  Duplicatas iguais ao site descartadas         : {total_dups} | Rejeitados: {total_rejected}")
    print("=" * 92)
    return {
        "existing_site": cnt_existing_site,
        "new_convex": cnt_new_conv_sem,
        "new_nonconvex": cnt_new_nconv_sem,
        "duplicates_discarded": total_dups,
        "rejected_invalid": total_rejected,
    }


def _snapshot_sources(source_dirs: List[Path]) -> Dict[str, Tuple[int, int]]:
    snap: Dict[str, Tuple[int, int]] = {}
    for src in source_dirs:
        p = Path(src)
        if not p.exists():
            continue
        if p.is_file():
            try:
                st = p.stat()
                snap[str(p.resolve())] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
            continue
        for root, dirs, filenames in os.walk(p):
            dirs[:] = [d for d in dirs if d not in IGNORED_WALK_DIRS]
            for fn in filenames:
                if fn.lower().endswith((".json", "_pythonscad.py")):
                    fp = Path(root) / fn
                    try:
                        st = fp.stat()
                        snap[str(fp.resolve())] = (st.st_mtime_ns, st.st_size)
                    except OSError:
                        pass
    return snap


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Varre pasta(s) local(is) do pesquisador, aplica os 4 passos e adiciona ao site apenas NOVOS mínimos válidos"
    )
    parser.add_argument(
        "sources",
        nargs="*",
        default=[str(PROJECT_ROOT / "solidos")],
        help="Caminho(s) da(s) pasta(s) local(is) no computador (ex.: 'C:\\caminho\\para\\pasta_do_colli')",
    )
    parser.add_argument("--aplicar", action="store_true", help="Grava os novos mínimos aprovados e atualiza o site (docs/)")
    parser.add_argument("--vigiar", action="store_true", help="Fica monitorando a pasta continuamente em tempo real")
    parser.add_argument("--limpar-legado", action="store_true", help="Reorganiza minimos_globais/ do zero")
    parser.add_argument("--sem-locais", action="store_true", help="Não copiar mínimos locais")
    parser.add_argument("--sem-github", action="store_true", help="Não sincronizar com o GitHub após atualizar o site local")
    args = parser.parse_args()

    src_paths = [Path(p) for p in args.sources]
    importar_pasta(
        src_paths,
        apply_copy=args.aplicar,
        include_locals=not args.sem_locais,
        clean_loose_files=args.limpar_legado,
        sync_github=not args.sem_github,
    )

    if args.vigiar:
        print(f"\n[Vigia de Pasta] Monitorando {', '.join(str(p.resolve()) for p in src_paths)} em tempo real (Ctrl+C para sair)...")
        last_snap = _snapshot_sources(src_paths)
        try:
            while True:
                time.sleep(3.0)
                cur_snap = _snapshot_sources(src_paths)
                if cur_snap != last_snap:
                    last_snap = cur_snap
                    print("\n[Vigia de Pasta] Alteração detectada na pasta! Executando protocolo de 4 passos...")
                    importar_pasta(
                        src_paths,
                        apply_copy=True,
                        include_locals=not args.sem_locais,
                        clean_loose_files=False,
                        sync_github=not args.sem_github,
                    )
        except KeyboardInterrupt:
            print("\n[Vigia de Pasta] Monitoramento encerrado.")
