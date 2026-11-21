# ==============================================================================
# WEB INTERFACE — ANALISADOR GEOMÉTRICO E CATÁLOGO CIENTÍFICO
# Módulo exclusivamente da interface web (pasta web/).
# NÃO altera nenhum arquivo oficial do projeto IC com Colli.
# ==============================================================================

import ast
import hashlib
import importlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.spatial import ConvexHull

# Garante acesso somente-leitura aos pacotes oficiais na raiz do projeto
WEB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dados.carregador_topologia import CarregadorTopologia
from topologia.orientador_faces import OrientadorFaces
from verificadores.verificador_geometrico import VerificadorGeometrico

# Estrutura oficial de pastas lidas pelo Atlas (APENAS mínimos globais SEM autointerseção):
#   solidos/<Sólido>/minimos_globais/convexos/sem_autointersecao/     -> aba RESULTADOS
#   solidos/<Sólido>/minimos_globais/nao_convexos/sem_autointersecao/ -> aba DESCOBERTAS
# As pastas com_autointersecao/ e minimos_locais/ são ignoradas pelo site.
GLOBAL_DIR_NAMES: Tuple[str, ...] = ("minimos_globais", "mínimos globais")
CONVEX_SUBDIR_NAMES: Tuple[str, ...] = ("convexos",)
NONCONVEX_SUBDIR_NAMES: Tuple[str, ...] = ("nao_convexos", "não convexos", "nao convexos")
NO_INTERSECTION_SUBDIR_NAMES: Tuple[str, ...] = ("sem_autointersecao", "sem autointerseção", "sem autointersecao")


def iter_global_category_dirs(solid_dir: Path) -> List[Tuple[Optional[str], Path]]:
    """
    Retorna EXCLUSIVAMENTE as subpastas publicáveis de mínimos globais sem autointerseção:
      - minimos_globais/convexos/sem_autointersecao/     -> 'convexos' (Resultados)
      - minimos_globais/nao_convexos/sem_autointersecao/ -> 'nao_convexos' (Descobertas)
    Nunca lê com_autointersecao/, minimos_locais/ nem locais/.
    """
    dirs: List[Tuple[Optional[str], Path]] = []
    seen = set()

    for gname in GLOBAL_DIR_NAMES:
        gdir = solid_dir / gname
        if not gdir.is_dir():
            continue

        for cname in CONVEX_SUBDIR_NAMES:
            cdir = gdir / cname
            if not cdir.is_dir():
                continue
            for sname in NO_INTERSECTION_SUBDIR_NAMES:
                sdir = cdir / sname
                if sdir.is_dir():
                    key = str(sdir.resolve())
                    if key not in seen:
                        seen.add(key)
                        dirs.append(("convexos", sdir))
            # Também inclui arquivos soltos diretamente em convexos/ (filtrados por autointerseção depois)
            if any(cdir.glob("*.json")) or any(cdir.glob("*_pythonscad.py")):
                key = str(cdir.resolve())
                if key not in seen:
                    seen.add(key)
                    dirs.append(("convexos", cdir))

        for ncname in NONCONVEX_SUBDIR_NAMES:
            ncdir = gdir / ncname
            if not ncdir.is_dir():
                continue
            for sname in NO_INTERSECTION_SUBDIR_NAMES:
                sdir = ncdir / sname
                if sdir.is_dir():
                    key = str(sdir.resolve())
                    if key not in seen:
                        seen.add(key)
                        dirs.append(("nao_convexos", sdir))
            # Também inclui arquivos soltos diretamente em nao_convexos/ (filtrados por autointerseção depois)
            if any(ncdir.glob("*.json")) or any(ncdir.glob("*_pythonscad.py")):
                key = str(ncdir.resolve())
                if key not in seen:
                    seen.add(key)
                    dirs.append(("nao_convexos", ncdir))

    return dirs


# ==============================================================================
# NOMENCLATURA CIENTÍFICA COMPLETA (PLATÔNICOS, ARQUIMEDIANOS, PRISMAS, ANTIPRISMAS, J1–J92)
# E CLASSIFICAÇÃO RIGOROSA DE POLIEDROS ELEMENTARES (ZALGALLER, 1969; JOHNSON, 1966)
# ==============================================================================
ELEMENTARY_JOHNSON_IDS = frozenset({
    1, 2, 3, 4, 5, 6,
    63, 80, 83,
    84, 85, 86, 88, 89, 90, 91, 92,
})

ELEMENTARY_NON_JOHNSON_KEYS = frozenset({
    # 2 Platônicos elementares (Cubo é prisma; Octaedro = 2×J1; Icosaedro = 2×J2 + antiprisma pentagonal)
    "tetrahedron",
    "dodecahedron",
    # 9 Arquimedianos elementares (os 5 truncados de Platônicos + 2 truncados quase-regulares + 2 torcidos/snub)
    "tetraedro truncado",
    "cubo truncado",
    "octaedro truncado",
    "dodecaedro truncado",
    "icosaedro truncado",
    "cuboctaedro truncado",
    "icosidodecaedro truncado",
    "cubo torcido",
    "cubo torcido 1",
    "cubo torcido 2",
    "dodecaedro torcido",
    "dodecaedro torcido 1",
    "dodecaedro torcido 2",
    "snub cube",
    "snub dodecahedron",
    "truncated tetrahedron",
    "truncated cube",
    "truncated octahedron",
    "truncated dodecahedron",
    "truncated icosahedron",
    "truncated cuboctahedron",
    "truncated icosidodecahedron",
})

CATALOG_SEGMENTS: List[Dict[str, str]] = [
    {
        "key": "all",
        "label": "Todos",
        "definition": "Catálogo completo da pesquisa: Sólidos de Johnson, Platônicos, Arquimedianos, Prismas e Antiprismas.",
    },
    {
        "key": "johnson",
        "label": "Johnson (todos)",
        "definition": "Os 92 poliedros estritamente convexos de faces regulares que não são platônicos, arquimedianos, prismas nem antiprismas (J1–J92).",
    },
    {
        "key": "elementares",
        "label": "Elementares",
        "definition": "Poliedros convexos de faces regulares irredutíveis por planos de corte em dois poliedros menores de faces regulares (Zalgaller, 1969).",
    },
    {
        "key": "prismas",
        "label": "Prismas",
        "definition": "Poliedros uniformes formados por duas bases poligonais regulares congruentes e paralelas unidas por faces quadradas.",
    },
    {
        "key": "antiprismas",
        "label": "Antiprismas",
        "definition": "Poliedros uniformes com duas bases poligonais regulares paralelas e rotacionadas entre si, ligadas por uma faixa alternada de triângulos equiláteros.",
    },
    {
        "key": "arquimedianos",
        "label": "Arquimedianos",
        "definition": "Poliedros convexos semirregulares vértice-transitivos compostos por dois ou mais tipos de polígonos regulares (excluindo prismas e antiprismas).",
    },
    {
        "key": "platonicos",
        "label": "Platônicos",
        "definition": "Os cinco poliedros convexos regulares com faces congruentes a um mesmo polígono regular e mesmo grau em todos os vértices.",
    },
]

SOLID_CATALOG_METADATA: Dict[str, Dict[str, str]] = {
    # Platônicos
    "Tetrahedron": {"pt": "Tetraedro Regular", "en": "Regular Tetrahedron", "family": "Platônicos", "segment": "platonicos"},
    "Cube": {"pt": "Hexaedro Regular (Cubo)", "en": "Cube", "family": "Platônicos", "segment": "platonicos"},
    "Octahedron": {"pt": "Octaedro Regular", "en": "Regular Octahedron", "family": "Platônicos", "segment": "platonicos"},
    "Dodecahedron": {"pt": "Dodecaedro Regular", "en": "Regular Dodecahedron", "family": "Platônicos", "segment": "platonicos"},
    "Icosahedron": {"pt": "Icosaedro Regular", "en": "Regular Icosahedron", "family": "Platônicos", "segment": "platonicos"},
    # Arquimedianos
    "Tetraedro_truncado": {"pt": "Tetraedro Truncado", "en": "Truncated Tetrahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Cubo_truncado": {"pt": "Cubo Truncado", "en": "Truncated Cube", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Octaedro_truncado": {"pt": "Octaedro Truncado", "en": "Truncated Octahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Icosaedro truncado": {"pt": "Icosaedro Truncado", "en": "Truncated Icosahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Dodecaedro truncado": {"pt": "Dodecaedro Truncado", "en": "Truncated Dodecahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Cuboctaedro": {"pt": "Cuboctaedro", "en": "Cuboctahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Cuboctaedro truncado": {"pt": "Cuboctaedro Truncado", "en": "Truncated Cuboctahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Cuboctaedro_truncado": {"pt": "Cuboctaedro Truncado", "en": "Truncated Cuboctahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Icosidodecaedro": {"pt": "Icosidodecaedro", "en": "Icosidodecahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Icosidodecaedro truncado": {"pt": "Icosidodecaedro Truncado", "en": "Truncated Icosidodecahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Icosidodecaedro_truncado": {"pt": "Icosidodecaedro Truncado", "en": "Truncated Icosidodecahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Rombicuboctaedro": {"pt": "Rombicuboctaedro", "en": "Rhombicuboctahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Rombicosidodecaedro": {"pt": "Rombicosidodecaedro", "en": "Rhombicosidodecahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Cubo torcido": {"pt": "Cubo Torcido (Snub Cube)", "en": "Snub Cube", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Cubo_torcido": {"pt": "Cubo Torcido (Snub Cube)", "en": "Snub Cube", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Dodecaedro torcido": {"pt": "Dodecaedro Torcido (Snub Dodecahedron)", "en": "Snub Dodecahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    "Dodecaedro_torcido": {"pt": "Dodecaedro Torcido (Snub Dodecahedron)", "en": "Snub Dodecahedron", "family": "Arquimedianos", "segment": "arquimedianos"},
    # Prismas
    "Prisma_triangular": {"pt": "Prisma Triangular", "en": "Triangular Prism", "family": "Prismas", "segment": "prismas"},
    "Prisma_pentagonal": {"pt": "Prisma Pentagonal", "en": "Pentagonal Prism", "family": "Prismas", "segment": "prismas"},
    # Antiprismas
    "Antiprisma_quadrado": {"pt": "Antiprisma Quadrado", "en": "Square Antiprism", "family": "Antiprismas", "segment": "antiprismas"},
    "Antiprisma_pentagonal": {"pt": "Antiprisma Pentagonal", "en": "Pentagonal Antiprism", "family": "Antiprismas", "segment": "antiprismas"},
}

JOHNSON_NAMES: Dict[int, Tuple[str, str]] = {
    1: ("Pirâmide quadrada", "Square pyramid"),
    2: ("Pirâmide pentagonal", "Pentagonal pyramid"),
    3: ("Cúpula triangular", "Triangular cupola"),
    4: ("Cúpula quadrada", "Square cupola"),
    5: ("Cúpula pentagonal", "Pentagonal cupola"),
    6: ("Rotunda pentagonal", "Pentagonal rotunda"),
    7: ("Pirâmide triangular alongada", "Elongated triangular pyramid"),
    8: ("Pirâmide quadrada alongada", "Elongated square pyramid"),
    9: ("Pirâmide pentagonal alongada", "Elongated pentagonal pyramid"),
    10: ("Pirâmide quadrada giroalongada", "Gyroelongated square pyramid"),
    11: ("Pirâmide pentagonal giroalongada", "Gyroelongated pentagonal pyramid"),
    12: ("Bipirâmide triangular", "Triangular bipyramid"),
    13: ("Bipirâmide pentagonal", "Pentagonal bipyramid"),
    14: ("Bipirâmide triangular alongada", "Elongated triangular bipyramid"),
    15: ("Bipirâmide quadrada alongada", "Elongated square bipyramid"),
    16: ("Bipirâmide pentagonal alongada", "Elongated pentagonal bipyramid"),
    17: ("Bipirâmide quadrada giroalongada", "Gyroelongated square bipyramid"),
    18: ("Cúpula triangular alongada", "Elongated triangular cupola"),
    19: ("Cúpula quadrada alongada", "Elongated square cupola"),
    20: ("Cúpula pentagonal alongada", "Elongated pentagonal cupola"),
    21: ("Rotunda pentagonal alongada", "Elongated pentagonal rotunda"),
    22: ("Cúpula triangular giroalongada", "Gyroelongated triangular cupola"),
    23: ("Cúpula quadrada giroalongada", "Gyroelongated square cupola"),
    24: ("Cúpula pentagonal giroalongada", "Gyroelongated pentagonal cupola"),
    25: ("Rotunda pentagonal giroalongada", "Gyroelongated pentagonal rotunda"),
    26: ("Girobifastígio", "Gyrobifastigium"),
    27: ("Ortobicúpula triangular", "Triangular orthobicupola"),
    28: ("Ortobicúpula quadrada", "Square orthobicupola"),
    29: ("Girobicúpula quadrada", "Square gyrobicupola"),
    30: ("Ortobicúpula pentagonal", "Pentagonal orthobicupola"),
    31: ("Girobicúpula pentagonal", "Pentagonal gyrobicupola"),
    32: ("Ortocupolarrotunda pentagonal", "Pentagonal orthocupolarotunda"),
    33: ("Girocupolarrotunda pentagonal", "Pentagonal gyrocupolarotunda"),
    34: ("Ortobirrotunda pentagonal", "Pentagonal orthobirotunda"),
    35: ("Ortobicúpula triangular alongada", "Elongated triangular orthobicupola"),
    36: ("Girobicúpula triangular alongada", "Elongated triangular gyrobicupola"),
    37: ("Girobicúpula quadrada alongada", "Elongated square gyrobicupola"),
    38: ("Ortobicúpula pentagonal alongada", "Elongated pentagonal orthobicupola"),
    39: ("Girobicúpula pentagonal alongada", "Elongated pentagonal gyrobicupola"),
    40: ("Ortocupolarrotunda pentagonal alongada", "Elongated pentagonal orthocupolarotunda"),
    41: ("Girocupolarrotunda pentagonal alongada", "Elongated pentagonal gyrocupolarotunda"),
    42: ("Ortobirrotunda pentagonal alongada", "Elongated pentagonal orthobirotunda"),
    43: ("Girobirrotunda pentagonal alongada", "Elongated pentagonal gyrobirotunda"),
    44: ("Bicúpula triangular giroalongada", "Gyroelongated triangular bicupola"),
    45: ("Bicúpula quadrada giroalongada", "Gyroelongated square bicupola"),
    46: ("Bicúpula pentagonal giroalongada", "Gyroelongated pentagonal bicupola"),
    47: ("Cupolarrotunda pentagonal giroalongada", "Gyroelongated pentagonal cupolarotunda"),
    48: ("Birrotunda pentagonal giroalongada", "Gyroelongated pentagonal birotunda"),
    49: ("Prisma triangular aumentado", "Augmented triangular prism"),
    50: ("Prisma triangular biaumentado", "Biaugmented triangular prism"),
    51: ("Prisma triangular triaumentado", "Triaugmented triangular prism"),
    52: ("Prisma pentagonal aumentado", "Augmented pentagonal prism"),
    53: ("Prisma pentagonal biaumentado", "Biaugmented pentagonal prism"),
    54: ("Prisma hexagonal aumentado", "Augmented hexagonal prism"),
    55: ("Prisma hexagonal parabiaumentado", "Parabiaugmented hexagonal prism"),
    56: ("Prisma hexagonal metabiaumentado", "Metabiaugmented hexagonal prism"),
    57: ("Prisma hexagonal triaumentado", "Triaugmented hexagonal prism"),
    58: ("Dodecaedro aumentado", "Augmented dodecahedron"),
    59: ("Dodecaedro parabiaumentado", "Parabiaugmented dodecahedron"),
    60: ("Dodecaedro metabiaumentado", "Metabiaugmented dodecahedron"),
    61: ("Dodecaedro triaumentado", "Triaugmented dodecahedron"),
    62: ("Icosaedro metabidiminuído", "Metabidiminished icosahedron"),
    63: ("Icosaedro tridiminuído", "Tridiminished icosahedron"),
    64: ("Icosaedro tridiminuído aumentado", "Augmented tridiminished icosahedron"),
    65: ("Tetraedro truncado aumentado", "Augmented truncated tetrahedron"),
    66: ("Cubo truncado aumentado", "Augmented truncated cube"),
    67: ("Cubo truncado biaumentado", "Biaugmented truncated cube"),
    68: ("Dodecaedro truncado aumentado", "Augmented truncated dodecahedron"),
    69: ("Dodecaedro truncado parabiaumentado", "Parabiaugmented truncated dodecahedron"),
    70: ("Dodecaedro truncado metabiaumentado", "Metabiaugmented truncated dodecahedron"),
    71: ("Dodecaedro truncado triaumentado", "Triaugmented truncated dodecahedron"),
    72: ("Rombicosidodecaedro girado", "Gyrate rhombicosidodecahedron"),
    73: ("Rombicosidodecaedro parabigirado", "Parabigyrate rhombicosidodecahedron"),
    74: ("Rombicosidodecaedro metabigirado", "Metabigyrate rhombicosidodecahedron"),
    75: ("Rombicosidodecaedro trigirado", "Trigyrate rhombicosidodecahedron"),
    76: ("Rombicosidodecaedro diminuído", "Diminished rhombicosidodecahedron"),
    77: ("Rombicosidodecaedro paragirado diminuído", "Paragyrate diminished rhombicosidodecahedron"),
    78: ("Rombicosidodecaedro metagirado diminuído", "Metagyrate diminished rhombicosidodecahedron"),
    79: ("Rombicosidodecaedro bigirado diminuído", "Bigyrate diminished rhombicosidodecahedron"),
    80: ("Rombicosidodecaedro parabidiminuído", "Parabidiminished rhombicosidodecahedron"),
    81: ("Rombicosidodecaedro metabidiminuído", "Metabidiminished rhombicosidodecahedron"),
    82: ("Rombicosidodecaedro girado bidiminuído", "Gyrate bidiminished rhombicosidodecahedron"),
    83: ("Rombicosidodecaedro tridiminuído", "Tridiminished rhombicosidodecahedron"),
    84: ("Disfenoide achatado", "Snub disphenoid"),
    85: ("Antiprisma quadrado achatado", "Snub square antiprism"),
    86: ("Esfenocorona", "Sphenocorona"),
    87: ("Esfenocorona aumentada", "Augmented sphenocorona"),
    88: ("Esfenomegacorona", "Sphenomegacorona"),
    89: ("Hebesfenomegacorona", "Hebesphenomegacorona"),
    90: ("Disfenocíngulo", "Disphenocingulum"),
    91: ("Bilunabirrotunda", "Bilunabirotunda"),
    92: ("Hebesfenorrotunda triangular", "Triangular hebesphenorotunda"),
}


def get_solid_metadata(name: str) -> Dict[str, Any]:
    """Retorna nomenclatura científica (PT/EN), família, segmento, flag elementar e ordem canônica."""
    raw_name = name.strip()
    norm_key = re.sub(r"[_\s]+", " ", raw_name).lower()

    if raw_name in SOLID_CATALOG_METADATA:
        meta = SOLID_CATALOG_METADATA[raw_name]
        order_map = {
            "Tetrahedron": 1, "Cube": 2, "Octahedron": 3, "Dodecahedron": 4, "Icosahedron": 5,
            "Tetraedro_truncado": 11, "Cubo_truncado": 12, "Octaedro_truncado": 13,
            "Icosaedro truncado": 14, "Dodecaedro truncado": 15, "Cuboctaedro": 16,
            "Cuboctaedro truncado": 17, "Cuboctaedro_truncado": 17,
            "Icosidodecaedro": 18, "Icosidodecaedro truncado": 19, "Icosidodecaedro_truncado": 19,
            "Rombicuboctaedro": 20, "Rombicosidodecaedro": 21,
            "Cubo torcido": 22, "Cubo_torcido": 22,
            "Dodecaedro torcido": 23, "Dodecaedro_torcido": 23,
            "Prisma_triangular": 31, "Prisma_pentagonal": 32,
            "Antiprisma_quadrado": 41, "Antiprisma_pentagonal": 42,
        }
        return {
            "display_code": raw_name.replace("_", " "),
            "name_pt": meta["pt"],
            "name_en": meta["en"],
            "family": meta["family"],
            "segment": meta["segment"],
            "is_elementary": norm_key in ELEMENTARY_NON_JOHNSON_KEYS,
            "sort_key": order_map.get(raw_name, 50),
        }

    m = re.match(r"^[jJ](\d+)$", raw_name)
    if m:
        idx = int(m.group(1))
        pt, en = JOHNSON_NAMES.get(idx, (f"Sólido de Johnson J{idx}", f"Johnson Solid J{idx}"))
        return {
            "display_code": f"J{idx}",
            "name_pt": pt,
            "name_en": en,
            "family": "Sólidos de Johnson",
            "segment": "johnson",
            "is_elementary": idx in ELEMENTARY_JOHNSON_IDS,
            "sort_key": 100 + idx,
        }

    if norm_key.startswith("antiprisma"):
        return {
            "display_code": raw_name.replace("_", " "),
            "name_pt": raw_name.replace("_", " ").capitalize(),
            "name_en": raw_name.replace("_", " "),
            "family": "Antiprismas",
            "segment": "antiprismas",
            "is_elementary": False,
            "sort_key": 45,
        }
    if norm_key.startswith("prisma"):
        return {
            "display_code": raw_name.replace("_", " "),
            "name_pt": raw_name.replace("_", " ").capitalize(),
            "name_en": raw_name.replace("_", " "),
            "family": "Prismas",
            "segment": "prismas",
            "is_elementary": False,
            "sort_key": 35,
        }

    return {
        "display_code": raw_name.replace("_", " "),
        "name_pt": raw_name.replace("_", " "),
        "name_en": raw_name.replace("_", " "),
        "family": "Outros Poliedros",
        "segment": "outros",
        "is_elementary": norm_key in ELEMENTARY_NON_JOHNSON_KEYS,
        "sort_key": 500,
    }


def extract_execution_metadata(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extrai e normaliza metadados técnicos da execução (condição inicial, método,
    tamanho da amostra, tentativas necessárias, iterações e tempo) a partir do JSON.
    Retorna None caso o registro seja de uma execução legada sem esses campos.
    """
    if not isinstance(data, dict):
        return None
    raw = data.get("execucao")
    src = raw if isinstance(raw, dict) else {}

    def pick(*keys):
        for k in keys:
            if k in src and src[k] is not None:
                return src[k]
            if k in data and data[k] is not None:
                return data[k]
        return None

    metodo = pick("metodo_inicial", "condicao_inicial_metodo", "metodo")
    vc_ini = pick("vc_inicial", "condicao_inicial", "initial_vertices")
    amostra = pick("tamanho_amostra", "amostra", "sample_size")
    tentativa = pick("tentativa", "tentativas", "tentativas_necessarias", "attempts")
    iters = pick("iteracoes_otimizador", "iteracoes", "iterations", "it")
    tempo = pick("tempo_segundos", "elapsed_time", "tempo")
    lado_l = pick("lado_L", "lado_l", "hipercubo_L")
    eps = pick("epsilon_perturbacao", "epsilon")
    norm_g = pick("norm_grad", "norm_g")
    autor = pick("autor", "pesquisador")
    converged = pick("converged", "convergiu")
    ocorrencias = pick("ocorrencias")

    has_any = any(
        v is not None
        for v in (metodo, vc_ini, amostra, tentativa, iters, tempo, lado_l, eps, autor, ocorrencias)
    )
    if not has_any:
        return None

    vc_ini_clean = None
    if isinstance(vc_ini, list) and vc_ini and isinstance(vc_ini[0], (list, tuple)) and len(vc_ini[0]) == 3:
        try:
            vc_ini_clean = [[float(c) for c in row] for row in vc_ini]
        except Exception:
            vc_ini_clean = None

    return {
        "metodo_inicial": str(metodo) if metodo is not None else None,
        "lado_L": float(lado_l) if lado_l is not None else None,
        "epsilon_perturbacao": float(eps) if eps is not None else None,
        "tamanho_amostra": amostra,
        "tentativa": int(tentativa) if isinstance(tentativa, (int, float)) else tentativa,
        "iteracoes_otimizador": int(iters) if isinstance(iters, (int, float)) else None,
        "tempo_segundos": float(tempo) if isinstance(tempo, (int, float)) else None,
        "norm_grad": float(norm_g) if isinstance(norm_g, (int, float)) else None,
        "converged": bool(converged) if converged is not None else None,
        "autor": str(autor) if autor else None,
        "has_vc_inicial": vc_ini_clean is not None,
        "vc_inicial": vc_ini_clean,
        "ocorrencias": ocorrencias if isinstance(ocorrencias, list) else None,
    }


def compact_execution_metadata(exec_meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Versão compacta de `execucao` para o catálogo leve (omite a matriz `vc_inicial`)."""
    if not isinstance(exec_meta, dict):
        return None
    return {
        k: v
        for k, v in exec_meta.items()
        if k != "vc_inicial" and v is not None
    }


def _newell_normal(face: List[int], V: np.ndarray) -> Optional[np.ndarray]:
    n = np.zeros(3, dtype=float)
    m = len(face)
    if m < 3:
        return None
    for i in range(m):
        p = V[face[i]]
        q = V[face[(i + 1) % m]]
        n[0] += (p[1] - q[1]) * (p[2] + q[2])
        n[1] += (p[2] - q[2]) * (p[0] + q[0])
        n[2] += (p[0] - q[0]) * (p[1] + q[1])
    norm = float(np.linalg.norm(n))
    if norm < 1e-12:
        return None
    return n / norm


def _signed_polyhedron_volume(V: np.ndarray, faces: List[List[int]]) -> float:
    """Volume assinado exato via triangulação em leque de cada face orientada."""
    vol = 0.0
    for f in faces:
        if len(f) < 3:
            continue
        v0 = V[f[0]]
        for k in range(1, len(f) - 1):
            v1 = V[f[k]]
            v2 = V[f[k + 1]]
            vol += float(np.dot(v0, np.cross(v1, v2))) / 6.0
    return vol


def analyze_polyhedron_convexity(
    vertices: List[List[float]],
    faces_raw: List[List[int]],
    plane_tol: float = 1e-3,
    reflex_tol_deg: float = 0.5,
    vol_ratio_tol: float = 1e-3,
) -> Dict[str, Any]:
    """
    Certificado matemático rigoroso de convexidade poliédrica.
    Delega integralmente ao VerificadorGeometrico oficial do projeto.
    """
    return VerificadorGeometrico.verificar_convexidade(
        vertices,
        faces_raw,
        plane_tol=plane_tol,
        reflex_tol_deg=reflex_tol_deg,
        vol_ratio_tol=vol_ratio_tol,
    )


def compute_topology_summary(faces: List[List[int]], declared_n: int = 0) -> Dict[str, Any]:
    """Calcula invariantes topológicos (V, F, E, característica de Euler e composição de faces)."""
    if not faces:
        return {
            "vertices": declared_n,
            "faces": 0,
            "edges": 0,
            "euler": None,
            "face_counts": {},
            "face_signature": "Topologia pendente",
        }

    verts = set()
    edges = set()
    counts = Counter()
    for f in faces:
        m = len(f)
        if m < 3:
            continue
        counts[m] += 1
        for i in range(m):
            a, b = f[i], f[(i + 1) % m]
            verts.add(a)
            edges.add((a, b) if a < b else (b, a))

    V = len(verts) if verts else declared_n
    F = sum(counts.values())
    E = len(edges)

    poly_symbols = {
        3: "△", 4: "□", 5: "⬠", 6: "⬡", 8: "8-gon", 10: "10-gon"
    }
    poly_labels = {
        3: "triângulos", 4: "quadrados", 5: "pentágonos",
        6: "hexágonos", 8: "octógonos", 10: "decágonos"
    }
    sig_parts = [f"{counts[k]}×{poly_symbols.get(k, f'{k}-gon')}" for k in sorted(counts)]
    desc_parts = [f"{counts[k]} {poly_labels.get(k, f'polígonos de {k} lados')}" for k in sorted(counts)]

    return {
        "vertices": V,
        "faces": F,
        "edges": E,
        "euler": V - E + F,
        "face_counts": {str(k): counts[k] for k in sorted(counts)},
        "face_signature": " · ".join(sig_parts),
        "face_description": ", ".join(desc_parts),
    }


def parse_pythonscad_file(py_path: Path) -> Optional[Tuple[List[List[float]], List[List[int]]]]:
    """Extrai pts e faces de um arquivo *_pythonscad.py de forma segura (AST, sem executar)."""
    try:
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        pts = None
        faces = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                var = node.targets[0].id
                if var == "pts":
                    pts = ast.literal_eval(node.value)
                elif var == "faces":
                    faces = ast.literal_eval(node.value)
        if pts is not None and faces is not None:
            return pts, faces
    except Exception:
        return None
    return None


class CatalogService:
    """
    Serviço dinâmico de leitura do catálogo oficial (faces.txt) e dos resultados
    gerados em solidos/, com cache inteligente em memória e disco baseado em mtime
    e hash de conteúdo para altíssima performance (sub-milissegundo em leituras repetidas).
    """

    ANALYSIS_CACHE_SCHEMA = "v3_catalog_execucao"

    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = Path(project_root)
        self.solidos_dir = self.project_root / "solidos"
        self._solution_cache: Dict[str, Tuple[Tuple[int, int, int, int], Dict[str, Any]]] = {}
        self._faces_path_cached: Optional[Path] = None
        self._solids_list_fp: Optional[Any] = None
        self._solids_list_cache: List[Dict[str, Any]] = []
        self._solids_by_id: Dict[str, Dict[str, Any]] = {}
        self._disk_cache_path = WEB_DIR / "cache" / "analysis_cache.json"
        self._disk_cache_loaded = False
        self._disk_cache_dirty = False
        self._disk_cache_data: Dict[str, Any] = {}
        self._official_fp_cache: Optional[str] = None

    def _get_faces_file_path(self) -> Path:
        if self._faces_path_cached is not None and self._faces_path_cached.exists():
            return self._faces_path_cached
        for cand in (
            self.project_root / "dados" / "faces.txt",
            self.project_root / "faces.txt",
        ):
            if cand.exists():
                self._faces_path_cached = cand
                return cand
        carregador = CarregadorTopologia()
        self._faces_path_cached = Path(carregador.caminho_arquivo)
        return self._faces_path_cached

    def _get_official_code_fingerprint(self) -> str:
        """Impressão digital dos módulos oficiais de validação; invalida cache se algum código oficial mudar."""
        parts = [self.ANALYSIS_CACHE_SCHEMA]
        for rel in (
            "verificadores/verificador_geometrico.py",
            "topologia/orientador_faces.py",
            "dados/faces.txt",
            "faces.txt",
        ):
            p = self.project_root / rel
            if p.exists():
                try:
                    st = p.stat()
                    parts.append(f"{rel}:{st.st_mtime_ns}:{st.st_size}")
                except OSError:
                    pass
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]

    def _load_disk_cache(self) -> None:
        if self._disk_cache_loaded:
            return
        self._disk_cache_loaded = True
        fp = self._get_official_code_fingerprint()
        self._official_fp_cache = fp
        if not self._disk_cache_path.exists():
            self._disk_cache_data = {"code_fp": fp, "entries": {}}
            return
        try:
            raw = json.loads(self._disk_cache_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("code_fp") == fp and isinstance(raw.get("entries"), dict):
                self._disk_cache_data = raw
            else:
                self._disk_cache_data = {"code_fp": fp, "entries": {}}
        except Exception:
            self._disk_cache_data = {"code_fp": fp, "entries": {}}

    def flush_disk_cache(self) -> None:
        if not self._disk_cache_dirty:
            return
        try:
            self._disk_cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._disk_cache_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._disk_cache_data, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(tmp, self._disk_cache_path)
            self._disk_cache_dirty = False
        except Exception:
            pass

    def get_official_files_status(self) -> Dict[str, Any]:
        """Inspeciona standbyalone2.py e faces.txt sem modificá-los para exibir integridade e versão ao vivo."""
        main_path = self.project_root / "standbyalone2.py"
        faces_path = self._get_faces_file_path()

        def file_info(p: Path) -> Dict[str, Any]:
            if not p.exists():
                return {"exists": False, "path": str(p)}
            stat = p.stat()
            digest = hashlib.sha256(p.read_bytes()).hexdigest()[:10]
            return {
                "exists": True,
                "name": p.name,
                "path": str(p),
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "hash": digest,
            }

        # Extrai parâmetros informativos de OtimizadorGradiente em standbyalone2.py (somente leitura)
        params: Dict[str, str] = {}
        prompts_detected: List[str] = []
        if main_path.exists():
            src = main_path.read_text(encoding="utf-8", errors="ignore")
            for key in ("alpha", "amortecimento", "grad_tol", "max_iter", "max_step", "epsilon_perturbacao"):
                m = re.search(rf"\b{key}\s*=\s*([0-9eE.+\-]+)", src)
                if m:
                    params[key] = m.group(1)
            for m in re.finditer(r'input\(\s*f?["\']([^"\']+)["\']\s*\)', src):
                prompts_detected.append(m.group(1).strip())

        return {
            "main_script": file_info(main_path),
            "faces_file": file_info(faces_path),
            "optimizer_params": params,
            "detected_prompts_count": len(prompts_detected),
        }

    def list_all_solids_from_faces_txt(self) -> List[Dict[str, Any]]:
        """
        Carrega TODOS os sólidos listados em faces.txt (ativos via CarregadorTopologia
        e pendentes com [[]] ou sem faces ainda), preservando o nome exato do arquivo.
        Usa cache leve baseado em mtime/size de faces.txt e subpastas de solidos/.
        """
        faces_path = self._get_faces_file_path()
        try:
            fstat = faces_path.stat()
            faces_sig = (fstat.st_mtime_ns, fstat.st_size)
        except OSError:
            faces_sig = (0, 0)

        extra_dirs: Tuple[str, ...] = ()
        if self.solidos_dir.exists():
            try:
                extra_dirs = tuple(sorted(
                    e.name for e in os.scandir(self.solidos_dir) if e.is_dir()
                ))
            except OSError:
                extra_dirs = ()

        fp = (faces_sig, extra_dirs)
        if self._solids_list_fp == fp and self._solids_list_cache:
            return self._solids_list_cache

        carregador = CarregadorTopologia()
        faces_path = Path(carregador.caminho_arquivo)
        self._faces_path_cached = faces_path
        active_map = carregador.todos_solidos  # {nome: (faces, n_vertices)}

        seen = set()
        entries: List[Dict[str, Any]] = []

        if faces_path.exists():
            for raw_line in faces_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw_line.strip()
                if not line or "-" not in line:
                    continue
                # Extrai nome antes de " -" ou "-"
                if " - " in line:
                    name = line.split(" - ", 1)[0].strip()
                elif " -|" in line:
                    name = line.split(" -|", 1)[0].strip()
                else:
                    continue
                if not name or name in seen:
                    continue
                seen.add(name)

                # Extrai n=... declarado, se houver
                declared_n = 0
                m_n = re.search(r"\|\s*n\s*=\s*(\d+)", line)
                if m_n:
                    declared_n = int(m_n.group(1))

                has_topology = name in active_map
                faces_raw = active_map[name][0] if has_topology else []
                n_info = active_map[name][1] if has_topology else declared_n

                meta = get_solid_metadata(name)
                topo = compute_topology_summary(faces_raw, declared_n=n_info)
                entries.append({
                    "id": name,
                    "display_code": meta["display_code"],
                    "name_pt": meta["name_pt"],
                    "name_en": meta["name_en"],
                    "family": meta["family"],
                    "segment": meta["segment"],
                    "is_elementary": meta["is_elementary"],
                    "sort_key": meta["sort_key"],
                    "has_topology": has_topology,
                    "topology": topo,
                    "faces_raw": faces_raw,
                })

        # Também inclui qualquer pasta extra já existente em solidos/ caso tenha sido criada manualmente
        for name in extra_dirs:
            if name not in seen:
                seen.add(name)
                meta = get_solid_metadata(name)
                entries.append({
                    "id": name,
                    "display_code": meta["display_code"],
                    "name_pt": meta["name_pt"],
                    "name_en": meta["name_en"],
                    "family": meta["family"],
                    "segment": meta["segment"],
                    "is_elementary": meta["is_elementary"],
                    "sort_key": meta["sort_key"],
                    "has_topology": name in active_map,
                    "topology": compute_topology_summary(active_map[name][0]) if name in active_map else compute_topology_summary([]),
                    "faces_raw": active_map[name][0] if name in active_map else [],
                })

        entries.sort(key=lambda e: (e["sort_key"], e["id"].lower()))
        self._solids_list_fp = fp
        self._solids_list_cache = entries
        self._solids_by_id = {e["id"]: e for e in entries}
        return entries

    def _pair_global_files(self, target_dir: Path) -> List[Dict[str, Any]]:
        """
        Emparelha cada solução global (.json, .txt e *_pythonscad.py) dentro de uma pasta
        de mínimos globais (ex: minimos_globais/convexos/ ou minimos_globais/nao_convexos/),
        lidando inclusive com diferenças de 1–2s no timestamp entre GerenciadorSolucoes e ExportadorPythonSCAD.
        """
        if not target_dir.exists():
            return []

        json_files = sorted(target_dir.glob("*.json"))
        scad_files = sorted(target_dir.glob("*_pythonscad.py"))
        used_scad = set()

        def extract_key(stem: str) -> Tuple[str, Optional[datetime]]:
            clean = stem[:-11] if stem.endswith("_pythonscad") else stem
            m = re.match(r"^(.*)_(\d{8}_\d{6})$", clean)
            if m:
                try:
                    return m.group(1), datetime.strptime(m.group(2), "%Y%m%d_%H%M%S")
                except ValueError:
                    return clean, None
            return clean, None

        records: List[Dict[str, Any]] = []
        for jf in json_files:
            stem = jf.stem
            txt_candidate = target_dir / f"{stem}.txt"
            exact_scad = target_dir / f"{stem}_pythonscad.py"

            matched_scad: Optional[Path] = None
            if exact_scad.exists():
                matched_scad = exact_scad
                used_scad.add(exact_scad)
            else:
                j_prefix, j_dt = extract_key(stem)
                best_diff = 15.0  # tolerância de até 15s entre salvar JSON e exportar SCAD
                for sf in scad_files:
                    if sf in used_scad:
                        continue
                    s_prefix, s_dt = extract_key(sf.stem)
                    if s_prefix == j_prefix and j_dt and s_dt:
                        diff = abs((s_dt - j_dt).total_seconds())
                        if diff <= best_diff:
                            best_diff = diff
                            matched_scad = sf
                if matched_scad:
                    used_scad.add(matched_scad)

            records.append({
                "id": stem,
                "json": jf,
                "txt": txt_candidate if txt_candidate.exists() else None,
                "scad": matched_scad,
                "folder_class": None,
            })

        # Inclui eventuais arquivos *_pythonscad.py órfãos (sem .json correspondente)
        for sf in scad_files:
            if sf not in used_scad:
                records.append({
                    "id": sf.stem.replace("_pythonscad", ""),
                    "json": None,
                    "txt": None,
                    "scad": sf,
                    "folder_class": None,
                })

        return records

    def _collect_global_records(self, solid_dir: Path) -> List[Dict[str, Any]]:
        """
        Coleta EXCLUSIVAMENTE as soluções dentro de solidos/<Sólido>/minimos_globais/
        (subpastas convexos/ e nao_convexos/). Nunca lê minimos_locais/.
        """
        records: List[Dict[str, Any]] = []
        used_ids = set()

        for folder_class, folder_path in iter_global_category_dirs(solid_dir):
            for rec in self._pair_global_files(folder_path):
                rec["folder_class"] = folder_class
                base_id = rec["id"]
                if base_id in used_ids and folder_class:
                    rec["id"] = f"{folder_class}__{base_id}"
                used_ids.add(rec["id"])
                records.append(rec)

        return records

    def _analyze_global_record(
        self,
        solid_id: str,
        faces_raw: List[List[int]],
        rec: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        jf = rec["json"]
        sf = rec["scad"]
        tf = rec["txt"]
        folder_class = rec.get("folder_class")  # "convexos" | "nao_convexos" | None
        ref_file = jf or sf
        if ref_file is None or not ref_file.exists():
            return None

        cache_key = f"{solid_id}::{folder_class or 'auto'}::{rec['id']}::{sf.name if sf else ''}"
        j_stat = jf.stat() if jf and jf.exists() else None
        s_stat = sf.stat() if sf and sf.exists() else None
        file_sig = (
            j_stat.st_mtime_ns if j_stat else 0,
            j_stat.st_size if j_stat else 0,
            s_stat.st_mtime_ns if s_stat else 0,
            s_stat.st_size if s_stat else 0,
        )
        mtime = max(
            j_stat.st_mtime if j_stat else 0.0,
            s_stat.st_mtime if s_stat else 0.0,
        )
        cached = self._solution_cache.get(cache_key)
        if cached and cached[0] == file_sig:
            return cached[1]

        # Verifica cache persistente em disco (evita recomputar autointerseção/convexidade ao reiniciar servidor)
        self._load_disk_cache()
        disk_entries = self._disk_cache_data.get("entries", {})
        disk_sig_str = f"{file_sig[0]}:{file_sig[1]}:{file_sig[2]}:{file_sig[3]}"
        disk_hit = disk_entries.get(cache_key)
        if isinstance(disk_hit, dict) and disk_hit.get("sig") == disk_sig_str and isinstance(disk_hit.get("result"), dict):
            res_copy = dict(disk_hit["result"])
            res_copy["scad_path"] = str(sf) if sf and sf.exists() else None
            res_copy["json_path"] = str(jf) if jf and jf.exists() else None
            res_copy["txt_path"] = str(tf) if tf and tf.exists() else None
            res_copy["has_scad"] = sf is not None and sf.exists()
            res_copy["has_json"] = jf is not None and jf.exists()
            res_copy["has_txt"] = tf is not None and tf.exists()
            self._solution_cache[cache_key] = (file_sig, res_copy)
            return res_copy

        vc: Optional[List[List[float]]] = None
        faces_for_check: List[List[int]] = faces_raw
        fval = 0.0
        timestamp = datetime.fromtimestamp(mtime).isoformat(timespec="seconds")
        distancias: List[float] = []
        angulos_salvos: List[float] = []
        autovalores: List[float] = []
        execucao: Optional[Dict[str, Any]] = None

        if jf and jf.exists():
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                vc = data.get("vc")
                fval = float(data.get("fval", 0.0))
                timestamp = str(data.get("timestamp", timestamp))
                distancias = data.get("distancias", [])
                angulos_salvos = data.get("angulos_diedrais", [])
                autovalores = data.get("autovalores", [])
                execucao = extract_execution_metadata(data)
            except Exception:
                pass

        if sf and sf.exists():
            parsed = parse_pythonscad_file(sf)
            if parsed is not None:
                scad_pts, scad_faces = parsed
                if vc is None:
                    vc = scad_pts
                if scad_faces:
                    faces_for_check = scad_faces

        if vc is None:
            return None

        convexity = analyze_polyhedron_convexity(vc, faces_for_check)
        self_inter = VerificadorGeometrico.verificar_autointersecao_faces(vc, convexity["oriented_faces"])

        # Roteamento oficial pelas subpastas sem_autointersecao/ de minimos_globais/:
        #   convexos/sem_autointersecao/     -> aba RESULTADOS (is_convex = True)
        #   nao_convexos/sem_autointersecao/ -> aba DESCOBERTAS (is_convex = False)
        if folder_class == "convexos":
            is_convex = True
            classification = "convexo"
            source_folder = "convexos"
        elif folder_class == "nao_convexos":
            is_convex = False
            classification = "nao_convexo"
            source_folder = "nao_convexos"
        else:
            is_convex = bool(convexity["is_convex"])
            classification = convexity["classification"]
            source_folder = "convexos" if is_convex else "nao_convexos"

        # Estatísticas espectrais da Hessiana (removendo os 6 modos rígidos ~0)
        hessian_summary = None
        if autovalores:
            arr = sorted(float(x) for x in autovalores)
            non_rigid = [x for x in arr if abs(x) > 1e-5]
            neg_modes = [x for x in arr if x < -1e-4]
            hessian_summary = {
                "total": len(arr),
                "min": arr[0],
                "max": arr[-1],
                "min_non_rigid": min(non_rigid) if non_rigid else 0.0,
                "negative_modes": len(neg_modes),
            }

        geom_hash = hashlib.sha1(
            json.dumps(
                {"v": [[round(float(c), 6) for c in p] for p in vc], "f": convexity["oriented_faces"]},
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:14]

        result = {
            "solution_id": rec["id"],
            "solid_id": solid_id,
            "geom_hash": geom_hash,
            "source_folder": source_folder,
            "fval": fval,
            "timestamp": timestamp,
            "is_convex": is_convex,
            "classification": classification,
            "has_self_intersection": self_inter["has_self_intersection"],
            "self_intersection": self_inter,
            "convexity": {
                k: v for k, v in convexity.items() if k != "oriented_faces"
            },
            "hessian": hessian_summary,
            "has_scad": sf is not None and sf.exists(),
            "has_json": jf is not None and jf.exists(),
            "has_txt": tf is not None and tf.exists(),
            "scad_path": str(sf) if sf and sf.exists() else None,
            "json_path": str(jf) if jf and jf.exists() else None,
            "txt_path": str(tf) if tf and tf.exists() else None,
            "vertices": vc,
            "faces": convexity["oriented_faces"],
            "distancias": distancias,
            "angulos_salvos": angulos_salvos,
            "autovalores": autovalores,
            "execucao": execucao,
        }
        self._solution_cache[cache_key] = (file_sig, result)
        disk_entries[cache_key] = {"sig": disk_sig_str, "result": result}
        self._disk_cache_dirty = True
        return result

    def get_full_catalog(self, include_geometry: bool = False) -> Dict[str, Any]:
        """
        Retorna catálogo completo para as abas do Atlas lendo APENAS minimos_globais/:
          - minimos_globais/convexos/     -> aba RESULTADOS
          - minimos_globais/nao_convexos/ -> aba DESCOBERTAS
        Nunca lê minimos_locais/.
        """
        solids_base = self.list_all_solids_from_faces_txt()

        catalog_items: List[Dict[str, Any]] = []
        total_active = 0
        solids_with_global = 0
        solids_with_convex = 0
        solids_with_nonconvex = 0
        total_global_solutions = 0
        total_convex_solutions = 0
        total_nonconvex_solutions = 0

        for entry in solids_base:
            sid = entry["id"]
            if entry["has_topology"]:
                total_active += 1

            solid_dir = self.solidos_dir / sid
            pairs = self._collect_global_records(solid_dir)
            globals_analyzed: List[Dict[str, Any]] = []
            for rec in pairs:
                analyzed = self._analyze_global_record(sid, entry["faces_raw"], rec)
                if analyzed is not None and not analyzed.get("has_self_intersection", False):
                    globals_analyzed.append(analyzed)

            # Ordena soluções: menor fval primeiro, depois mais recente
            globals_analyzed.sort(key=lambda s: (s["fval"], s["timestamp"]))

            convex_sols = [s for s in globals_analyzed if s["source_folder"] == "convexos"]
            nonconvex_sols = [s for s in globals_analyzed if s["source_folder"] == "nao_convexos"]

            if globals_analyzed:
                solids_with_global += 1
                total_global_solutions += len(globals_analyzed)
            if convex_sols:
                solids_with_convex += 1
                total_convex_solutions += len(convex_sols)
            if nonconvex_sols:
                solids_with_nonconvex += 1
                total_nonconvex_solutions += len(nonconvex_sols)

            primary_convex = convex_sols[0] if convex_sols else None
            primary_nonconvex = nonconvex_sols[0] if nonconvex_sols else None
            # Catálogo unificado: prefere convexo como miniatura principal; se só houver
            # global não convexo sem autointerseção, usa-o diretamente (nunca descarta!)
            primary_any = primary_convex or primary_nonconvex

            def compact_sol(s: Dict[str, Any]) -> Dict[str, Any]:
                out = {
                    "solution_id": s["solution_id"],
                    "geom_hash": s.get("geom_hash", ""),
                    "source_folder": s["source_folder"],
                    "fval": s["fval"],
                    "timestamp": s["timestamp"],
                    "is_convex": s["is_convex"],
                    "classification": s["classification"],
                    "has_self_intersection": s["has_self_intersection"],
                    "self_intersection": {
                        "has_self_intersection": s["self_intersection"]["has_self_intersection"],
                        "intersection_count": s["self_intersection"]["intersection_count"],
                        "intersection_types": s["self_intersection"]["intersection_types"],
                    },
                    "convexity": {
                        "volume": s["convexity"]["volume"],
                        "hull_volume": s["convexity"]["hull_volume"],
                        "volume_ratio": s["convexity"]["volume_ratio"],
                        "interior_vertices": s["convexity"]["interior_vertices"],
                        "non_supporting_faces": s["convexity"]["non_supporting_faces"],
                        "reflex_edges": s["convexity"]["reflex_edges"],
                        "min_dihedral_deg": s["convexity"]["min_dihedral_deg"],
                        "max_dihedral_deg": s["convexity"]["max_dihedral_deg"],
                        "reasons": s["convexity"]["reasons"],
                    },
                    "hessian": s["hessian"],
                    "execucao": compact_execution_metadata(s.get("execucao")),
                    "has_scad": s["has_scad"],
                    "has_json": s["has_json"],
                    "has_txt": s["has_txt"],
                }
                if include_geometry:
                    out["vertices"] = s["vertices"]
                    out["faces"] = s["faces"]
                    out["distancias"] = s["distancias"]
                    out["angulos_salvos"] = s["angulos_salvos"]
                    out["autovalores"] = s["autovalores"]
                    out["execucao"] = s.get("execucao")
                    out["convexity"]["interior_dihedrals_deg"] = s["convexity"]["interior_dihedrals_deg"]
                return out

            catalog_items.append({
                "id": sid,
                "display_code": entry["display_code"],
                "name_pt": entry["name_pt"],
                "name_en": entry["name_en"],
                "family": entry["family"],
                "segment": entry["segment"],
                "is_elementary": entry["is_elementary"],
                "sort_key": entry["sort_key"],
                "has_topology": entry["has_topology"],
                "topology": entry["topology"],
                "has_global": bool(globals_analyzed),
                "has_convex_global": bool(convex_sols),
                "has_nonconvex_global": bool(nonconvex_sols),
                "global_count": len(globals_analyzed),
                "convex_count": len(convex_sols),
                "nonconvex_count": len(nonconvex_sols),
                "primary_convex": compact_sol(primary_convex) if primary_convex else None,
                "primary_global": compact_sol(primary_any) if primary_any else None,
                "primary_nonconvex": compact_sol(primary_nonconvex) if primary_nonconvex else None,
                "convex_solutions": [compact_sol(s) for s in convex_sols],
                "nonconvex_solutions": [compact_sol(s) for s in nonconvex_sols],
                "global_solutions": [compact_sol(s) for s in globals_analyzed],
            })

        self.flush_disk_cache()
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "segments": CATALOG_SEGMENTS,
            "summary": {
                "total_solids": len(catalog_items),
                "active_topology_solids": total_active,
                "pending_topology_solids": len(catalog_items) - total_active,
                "solids_with_global": solids_with_global,
                "solids_with_convex_global": solids_with_convex,
                "solids_with_nonconvex_global": solids_with_nonconvex,
                "total_global_solutions": total_global_solutions,
                "total_convex_solutions": total_convex_solutions,
                "total_nonconvex_solutions": total_nonconvex_solutions,
            },
            "solids": catalog_items,
        }

    def get_solid_detail(self, solid_id: str) -> Optional[Dict[str, Any]]:
        """Retorna dossiê científico completo de um único sólido (todos os mínimos globais sem autointerseção)."""
        self.list_all_solids_from_faces_txt()
        target = self._solids_by_id.get(solid_id)
        if target is None:
            return None

        solid_dir = self.solidos_dir / solid_id
        pairs = self._collect_global_records(solid_dir)
        globals_analyzed = []
        for rec in pairs:
            analyzed = self._analyze_global_record(solid_id, target["faces_raw"], rec)
            if analyzed is not None and not analyzed.get("has_self_intersection", False):
                globals_analyzed.append(analyzed)

        self.flush_disk_cache()
        globals_analyzed.sort(key=lambda s: (s["source_folder"] != "convexos", s["fval"], s["timestamp"]))

        def serialize_full(s: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "solution_id": s["solution_id"],
                "geom_hash": s.get("geom_hash", ""),
                "source_folder": s["source_folder"],
                "fval": s["fval"],
                "timestamp": s["timestamp"],
                "is_convex": s["is_convex"],
                "classification": s["classification"],
                "has_self_intersection": s["has_self_intersection"],
                "self_intersection": s["self_intersection"],
                "convexity": s["convexity"],
                "hessian": s["hessian"],
                "execucao": s.get("execucao"),
                "has_scad": s["has_scad"],
                "has_json": s["has_json"],
                "has_txt": s["has_txt"],
                "vertices": s["vertices"],
                "faces": s["faces"],
                "distancias": s["distancias"],
                "angulos_salvos": s["angulos_salvos"],
                "autovalores": s["autovalores"],
            }

        all_serialized = [serialize_full(s) for s in globals_analyzed]
        return {
            "id": target["id"],
            "display_code": target["display_code"],
            "name_pt": target["name_pt"],
            "name_en": target["name_en"],
            "family": target["family"],
            "segment": target["segment"],
            "is_elementary": target["is_elementary"],
            "has_topology": target["has_topology"],
            "topology": target["topology"],
            "convex_solutions": [s for s in all_serialized if s["source_folder"] == "convexos"],
            "nonconvex_solutions": [s for s in all_serialized if s["source_folder"] == "nao_convexos"],
            "global_solutions": all_serialized,
        }

    def find_solution_files(self, solid_id: str, solution_id: str) -> Optional[Dict[str, Any]]:
        """Localiza os arquivos oficiais (.json, .txt, _pythonscad.py) em minimos_globais/ ou docs/files/."""
        solid_dir = self.solidos_dir / solid_id
        for rec in self._collect_global_records(solid_dir):
            if rec["id"] == solution_id:
                return rec

        # Fallback: arquivos estáticos já publicados no site (docs/files/<slug>/{convexos,nao_convexos}/)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", solid_id.strip()).strip("_") or "solid"
        sol_slug = re.sub(r"[^A-Za-z0-9._-]+", "_", solution_id.strip()).strip("_") or "sol"
        docs_files_base = self.project_root / "docs" / "files" / slug
        if docs_files_base.is_dir():
            for cat in ("convexos", "nao_convexos"):
                cdir = docs_files_base / cat
                if not cdir.is_dir():
                    continue
                jf = cdir / f"{sol_slug}.json"
                tf = cdir / f"{sol_slug}.txt"
                sf = cdir / f"{sol_slug}_pythonscad.py"
                if jf.exists() or sf.exists():
                    return {
                        "id": solution_id,
                        "json": jf if jf.exists() else None,
                        "txt": tf if tf.exists() else None,
                        "scad": sf if sf.exists() else None,
                        "folder_class": cat,
                    }
        return None
