# ==============================================================================
# WEB INTERFACE — VALIDADOR CIENTÍFICO E DEDUPLICAÇÃO POR ISOMORFISMO MÉTRICO
# Re-verifica soluções globais usando EXCLUSIVAMENTE as classes oficiais do
# projeto (sem modificá-las) e remove duplicatas isométricas entre colaboradores
# via verificadores/isomorfismo.py (Prof. Eduardo Colli).
# ==============================================================================

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

WEB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dados.carregador_topologia import CarregadorTopologia
from otimizador.otimizador_gradiente import OtimizadorGradiente
from topologia.orientador_faces import OrientadorFaces
from verificadores.isomorfismo import construir_matriz_distancias, resolver_isomorfismo
from verificadores.verificador_geometrico import VerificadorGeometrico


class ValidadorCientifico:
    """
    Aplica o protocolo oficial de validação sobre soluções globais submetidas
    ou armazenadas em solidos/:
      1. Verifica existência da topologia em faces.txt (CarregadorTopologia)
      2. Recomputa energia elástica F(x) oficial e exige |F(x)| < 1e-6
      3. Verifica não-degeneração (VerificadorGeometrico.verificar_minimo_degenerado)
      4. Verifica ausência de colinearidade em faces (VerificadorGeometrico.possui_face_colinear)
      5. Deduplica configurações isométricas via backtracking (resolver_isomorfismo)
    """

    def __init__(self, energy_tol: float = 1e-6, iso_tol: float = 1e-4):
        self.energy_tol = float(energy_tol)
        self.iso_tol = float(iso_tol)
        self.carregador = CarregadorTopologia()
        self._topo_cache: Dict[str, Tuple[List[List[int]], np.ndarray]] = {}

    def _get_topology(self, solid_id: str) -> Optional[Tuple[List[List[int]], np.ndarray]]:
        if solid_id in self._topo_cache:
            return self._topo_cache[solid_id]
        if not self.carregador.existe_solido(solid_id):
            return None
        faces_raw, _ = self.carregador.obter_solido(solid_id)
        faces = OrientadorFaces.corrigir_orientacao(faces_raw)
        segmentos = OrientadorFaces.gerar_segmentos(faces)
        self._topo_cache[solid_id] = (faces, segmentos)
        return faces, segmentos

    def validar_solucao_global(
        self,
        solid_id: str,
        vertices: List[List[float]],
        faces_override: Optional[List[List[int]]] = None,
    ) -> Dict[str, Any]:
        """
        Valida matematicamente uma solução candidata usando os módulos oficiais.
        Retorna dict com `valid`, `fval_recomputed`, `reason` e `faces_oriented`.
        """
        topo = self._get_topology(solid_id)
        if topo is None:
            return {
                "valid": False,
                "reason": f"Sólido '{solid_id}' não possui topologia ativa em faces.txt.",
                "fval_recomputed": None,
                "faces_oriented": faces_override or [],
            }

        faces_topo, segmentos = topo
        V = np.asarray(vertices, dtype=float)
        if V.ndim != 2 or V.shape[1] != 3:
            return {
                "valid": False,
                "reason": "Matriz de vértices inválida (esperado shape N×3).",
                "fval_recomputed": None,
                "faces_oriented": faces_topo,
            }

        expected_v = int(segmentos[:, :2].max()) + 1
        if len(V) < expected_v:
            return {
                "valid": False,
                "reason": f"Número de vértices insuficiente ({len(V)} < {expected_v}).",
                "fval_recomputed": None,
                "faces_oriented": faces_topo,
            }

        if not np.all(np.isfinite(V)):
            return {
                "valid": False,
                "reason": "Coordenadas contêm NaN ou infinito.",
                "fval_recomputed": None,
                "faces_oriented": faces_topo,
            }

        # 1. Energia elástica oficial recomputada independentemente
        fval = float(OtimizadorGradiente.calcular_energia(V, segmentos))
        if abs(fval) >= self.energy_tol:
            return {
                "valid": False,
                "reason": f"Energia F(x) = {fval:.3e} excede tolerância global ({self.energy_tol:.0e}).",
                "fval_recomputed": fval,
                "faces_oriented": faces_topo,
            }

        # 2. Integridade geométrica oficial (colapso de vértices, área, volume, bbox)
        if VerificadorGeometrico.verificar_minimo_degenerado(V, faces_topo):
            return {
                "valid": False,
                "reason": "Configuração geométrica degenerada (rejeitada pelo VerificadorGeometrico).",
                "fval_recomputed": fval,
                "faces_oriented": faces_topo,
            }

        # 3. Colinearidade em faces
        if VerificadorGeometrico.possui_face_colinear(V, faces_topo):
            return {
                "valid": False,
                "reason": "Face com vértices colineares detectada.",
                "fval_recomputed": fval,
                "faces_oriented": faces_topo,
            }

        # 4. Ausência de autointerseção de faces (regra oficial do site)
        inter = VerificadorGeometrico.verificar_autointersecao_faces(V, faces_topo)
        if inter["has_self_intersection"]:
            tipos = ", ".join(inter["intersection_types"])
            return {
                "valid": False,
                "reason": f"Autointerseção de faces detectada ({inter['intersection_count']} ocorrência(s): {tipos}).",
                "fval_recomputed": fval,
                "faces_oriented": faces_topo,
                "self_intersection": inter,
            }

        # 5. Certificado oficial de convexidade (Resultados vs Descobertas)
        conv = VerificadorGeometrico.verificar_convexidade(V, faces_topo)
        is_convex = bool(conv["is_convex"])
        source_folder = "convexos" if is_convex else "nao_convexos"

        return {
            "valid": True,
            "reason": "Verificado matematicamente pelos módulos oficiais (sem degeneração e sem autointerseção).",
            "fval_recomputed": fval,
            "faces_oriented": conv["oriented_faces"],
            "is_convex": is_convex,
            "classification": conv["classification"],
            "source_folder": source_folder,
            "convexity": conv,
            "self_intersection": inter,
        }

    def verificar_igualdade_isometrica(
        self,
        vertices_novo: List[List[float]],
        solucoes_existentes_no_site: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Verifica (Passo 3) se uma configuração candidata `vertices_novo` é
        isometricamente igual a qualquer mínimo já existente para esse sólido no site.
        """
        if not solucoes_existentes_no_site:
            return {"is_equal": False, "matched_solution_id": None, "permutation": None}

        try:
            V_new = np.asarray(vertices_novo, dtype=float)
            if V_new.ndim != 2 or V_new.shape[1] != 3 or not np.all(np.isfinite(V_new)):
                return {"is_equal": False, "matched_solution_id": None, "permutation": None}
            mat_new = construir_matriz_distancias(V_new)
        except Exception:
            return {"is_equal": False, "matched_solution_id": None, "permutation": None}

        for existing in solucoes_existentes_no_site:
            verts_ex = existing.get("vertices")
            if not verts_ex:
                continue
            mat_ex = existing.get("_dist_matrix")
            if mat_ex is None:
                mat_ex = construir_matriz_distancias(verts_ex)
            if len(mat_ex) != len(mat_new):
                continue
            perm = resolver_isomorfismo(mat_new, mat_ex, tol=self.iso_tol, decimais=4)
            if perm is not None:
                return {
                    "is_equal": True,
                    "matched_solution_id": existing.get("solution_id", "minimo_existente"),
                    "permutation": perm,
                }

        return {"is_equal": False, "matched_solution_id": None, "permutation": None}

    def classificar_classes_isometricas(
        self,
        solutions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Agrupa uma lista de mínimos globais válidos (sem autointerseção) em classes
        de isometria métrica SEM descartar nenhum registro.
        Anota cada solução in-place com:
          - isometry_class (int, 1-based)
          - is_canonical_in_class (bool)
          - isometric_to (solution_id do representante canônico quando recorrente, ou None)
        Retorna a lista resumida das classes distintas (com contagem e representante).
        """
        classes: List[Dict[str, Any]] = []

        for sol in solutions:
            verts = sol.get("vertices")
            if not verts:
                sol["isometry_class"] = 1
                sol["is_canonical_in_class"] = True
                sol["isometric_to"] = None
                continue

            mat = sol.get("_dist_matrix")
            if mat is None:
                mat = construir_matriz_distancias(verts)

            matched_cls = None
            for cls in classes:
                if bool(cls["is_convex"]) != bool(sol.get("is_convex")):
                    continue
                if len(cls["_mat"]) != len(mat):
                    continue
                perm = resolver_isomorfismo(mat, cls["_mat"], tol=self.iso_tol, decimais=4)
                if perm is not None:
                    matched_cls = cls
                    break

            if matched_cls is None:
                cid = len(classes) + 1
                cls_obj = {
                    "class_id": cid,
                    "is_convex": bool(sol.get("is_convex")),
                    "representative_id": sol.get("solution_id"),
                    "representative_geom_hash": sol.get("geom_hash", ""),
                    "count": 1,
                    "_mat": mat,
                }
                classes.append(cls_obj)
                sol["isometry_class"] = cid
                sol["is_canonical_in_class"] = True
                sol["isometric_to"] = None
            else:
                matched_cls["count"] += 1
                sol["isometry_class"] = matched_cls["class_id"]
                sol["is_canonical_in_class"] = False
                sol["isometric_to"] = matched_cls["representative_id"]

        return [
            {k: v for k, v in cls.items() if k != "_mat"}
            for cls in classes
        ]

    def avaliar_novo_minimo_4_passos(
        self,
        solid_id: str,
        candidato: Dict[str, Any],
        solucoes_existentes_no_site: List[Dict[str, Any]],
        permitir_isometricos: bool = True,
    ) -> Dict[str, Any]:
        """
        Avalia um mínimo global candidato para o catálogo:
          1. Exige cumprimento rigoroso de todas as exigências científicas:
             - Topologia ativa em faces.txt
             - |F(x)| < 1e-6 (mínimo global)
             - Sem degeneração e sem faces colineares
             - Sem autointerseção de faces (convexo ou não convexo)
          2. Verifica isomorfismo métrico contra os registros já presentes no catálogo.
          3. Regra oficial atualizada (`permitir_isometricos=True`):
             - Mínimos globais sem autointerseção (convexos ou não convexos) são SEMPRE
               aceitos e preservados com sua condição inicial e metadados da amostra,
               mesmo quando isométricos a outro mínimo já registrado (recebendo anotação
               de recorrência isométrica).
             - Apenas registros estritamente idênticos (mesmo arquivo/solution_id + geom_hash)
               são tratados externamente como já indexados.
        """
        verts = candidato.get("vertices") or candidato.get("vc")
        faces = candidato.get("faces")
        ja_existe_no_site = len(solucoes_existentes_no_site) > 0

        # 1. Validação científica obrigatória (rejeita locais, degenerados e autointerseção)
        check = self.validar_solucao_global(solid_id, verts if verts is not None else [], faces)
        if not check["valid"]:
            return {
                "accepted": False,
                "status": "descartado_exigencias",
                "step_1_new_in_folder": True,
                "step_2_exists_on_site": ja_existe_no_site,
                "step_3_is_equal": False,
                "step_4_decision": "descartar_invalido",
                "matched_solution_id": None,
                "permutation": None,
                "is_isometric_repeat": False,
                "validation": check,
                "reason": f"Rejeitado (exigências científicas): {check['reason']}",
            }

        # 2. Classificação isométrica contra mínimos existentes no site
        iso_res = {"is_equal": False, "matched_solution_id": None, "permutation": None}
        if ja_existe_no_site and verts is not None:
            iso_res = self.verificar_igualdade_isometrica(verts, solucoes_existentes_no_site)
            if iso_res["is_equal"] and not permitir_isometricos:
                return {
                    "accepted": False,
                    "status": "descartado_igual",
                    "step_1_new_in_folder": True,
                    "step_2_exists_on_site": True,
                    "step_3_is_equal": True,
                    "step_4_decision": "descartar",
                    "matched_solution_id": iso_res["matched_solution_id"],
                    "permutation": iso_res["permutation"],
                    "is_isometric_repeat": True,
                    "validation": check,
                    "reason": (
                        f"Descartado: já existe mínimo isométrico igual para '{solid_id}' "
                        f"({iso_res['matched_solution_id']})."
                    ),
                }

        target_tab = "Convexo" if check["is_convex"] else "Não Convexo"
        is_repeat = bool(iso_res["is_equal"])
        return {
            "accepted": True,
            "status": "adicionado_recorrencia" if is_repeat else "adicionado_novo",
            "step_1_new_in_folder": True,
            "step_2_exists_on_site": ja_existe_no_site,
            "step_3_is_equal": is_repeat,
            "step_4_decision": "adicionar_no_site",
            "matched_solution_id": iso_res["matched_solution_id"],
            "permutation": iso_res["permutation"],
            "is_isometric_repeat": is_repeat,
            "validation": check,
            "fval_recomputed": check["fval_recomputed"],
            "is_convex": check["is_convex"],
            "classification": check["classification"],
            "source_folder": check["source_folder"],
            "target_tab": target_tab,
            "convexity": check["convexity"],
            "self_intersection": check["self_intersection"],
            "faces_oriented": check["faces_oriented"],
            "reason": (
                f"Adicionado ao catálogo: mínimo global ({target_tab}, sem autointerseção)"
                + (f" — recorrência isométrica de {iso_res['matched_solution_id']}." if is_repeat else " — nova forma geométrica.")
            ),
        }

    def deduplicar_por_isomorfismo(
        self,
        solutions: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Recebe lista de soluções globais válidas de um mesmo sólido (cada item contendo
        `vertices` e `fval`) e retorna (unicas, qtd_duplicatas_removidas).
        Preserva prioritariamente mínimos que JÁ existem no site (`already_on_site=True`),
        seguidos pelos mais antigos/menor energia, descartando duplicatas posteriores.
        """
        ordered = sorted(
            solutions,
            key=lambda s: (
                0 if s.get("already_on_site") else 1,
                str(s.get("timestamp", "")),
                float(s.get("fval", 0.0)),
                str(s.get("solution_id", "")),
            ),
        )
        kept: List[Dict[str, Any]] = []
        kept_matrices: List[np.ndarray] = []
        removed = 0

        for sol in ordered:
            verts = sol.get("vertices")
            if not verts:
                continue
            mat = construir_matriz_distancias(verts)

            is_dup = False
            for existing_mat in kept_matrices:
                if len(existing_mat) != len(mat):
                    continue
                perm = resolver_isomorfismo(mat, existing_mat, tol=self.iso_tol, decimais=4)
                if perm is not None:
                    is_dup = True
                    break

            if is_dup:
                removed += 1
            else:
                kept.append(sol)
                kept_matrices.append(mat)

        return kept, removed
