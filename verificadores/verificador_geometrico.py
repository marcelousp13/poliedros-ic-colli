# ==============================================================================
# PACOTE: verificadores
# CLASSE: VerificadorGeometrico
# DESCRIÇÃO: Responsável pela validação geométrica rigorosa das soluções obtidas:
#            cálculo de distâncias mútuas, ângulos diedrais entre faces adjacentes,
#            certificado matemático de convexidade poliédrica (convexo vs não-convexo),
#            detecção de colinearidade em faces e identificação de degenerações topológicas.
# ==============================================================================

import math
import numpy as np
from itertools import combinations
from collections import defaultdict

try:
    from scipy.spatial import ConvexHull
except ImportError:
    ConvexHull = None

from topologia.orientador_faces import OrientadorFaces

class VerificadorGeometrico:
    """
    Classe dedicada à conferência métrica e morfológica dos sólidos gerados.
    Executa testes de colapso de volume, sobreposição de vértices, colinearidade em faces,
    certificação rigorosa de convexidade poliédrica (convexo vs não-convexo),
    cálculo de diedrais orientados pelo método de Newell e extração de espectro de distâncias.
    """

    @staticmethod
    def calcular_distancias(vertices):
        """
        Calcula todas as distâncias euclidianas entre todos os pares de vértices do poliedro.
        Retorna um array 1D ordenado de forma ascendente.
        """
        V = np.asarray(vertices, dtype=float)
        n = len(V)
        distancias = []

        for i in range(n):
            for j in range(i + 1, n):
                distancias.append(np.linalg.norm(V[i] - V[j]))

        return np.sort(np.asarray(distancias, dtype=float))

    @staticmethod
    def normal_newell(face, vertices):
        """
        Calcula o vetor normal unitário de uma face arbitrária (3 ou mais vértices)
        utilizando o método robusto de Newell.
        """
        n = np.zeros(3, dtype=float)
        m = len(face)

        for i in range(m):
            p = np.asarray(vertices[face[i]], dtype=float)
            q = np.asarray(vertices[face[(i + 1) % m]], dtype=float)

            n[0] += (p[1] - q[1]) * (p[2] + q[2])
            n[1] += (p[2] - q[2]) * (p[0] + q[0])
            n[2] += (p[0] - q[0]) * (p[1] + q[1])

        norma = np.linalg.norm(n)
        if norma < 1e-12:
            return None

        return n / norma

    @staticmethod
    def construir_adjacencias(faces):
        """
        Mapeia cada aresta do sólido (tupla ordenada) para a lista de faces que a contêm.
        """
        arestas = defaultdict(list)
        for idx_face, face in enumerate(faces):
            m = len(face)
            for i in range(m):
                a = face[i]
                b = face[(i + 1) % m]
                aresta = tuple(sorted((a, b)))
                arestas[aresta].append(idx_face)
        return arestas

    @staticmethod
    def diedral_orientado(face1, face2, aresta, vertices):
        """
        Calcula o ângulo diedral orientado (em graus) entre duas faces adjacentes
        ao longo do eixo da aresta compartilhada.
        """
        n1 = VerificadorGeometrico.normal_newell(face1, vertices)
        n2 = VerificadorGeometrico.normal_newell(face2, vertices)

        if n1 is None or n2 is None:
            return None

        a, b = aresta
        eixo = np.asarray(vertices[b], dtype=float) - np.asarray(vertices[a], dtype=float)
        norma = np.linalg.norm(eixo)

        if norma < 1e-12:
            return None

        eixo /= norma
        seno = np.dot(eixo, np.cross(n1, n2))
        cosseno = np.dot(n1, n2)

        theta = np.degrees(np.arctan2(seno, cosseno))
        if theta < 0:
            theta += 360.0

        # Menor diedral entre as duas folhas
        if theta > 180.0:
            theta = 360.0 - theta

        return theta

    @staticmethod
    def calcular_angulos_diedrais(vertices, faces):
        """
        Calcula todos os ângulos diedrais existentes entre faces que compartilham arestas.
        Retorna um array 1D com os ângulos ordenados em graus.
        """
        adj = VerificadorGeometrico.construir_adjacencias(faces)
        angulos = []

        for aresta, lista_faces in adj.items():
            if len(lista_faces) != 2:
                continue

            f1 = faces[lista_faces[0]]
            f2 = faces[lista_faces[1]]
            theta = VerificadorGeometrico.diedral_orientado(f1, f2, aresta, vertices)

            if theta is not None:
                angulos.append(theta)

        angulos = np.asarray(angulos, dtype=float)
        angulos.sort()
        return angulos

    @staticmethod
    def pontos_colineares(p1, p2, p3, epsilon=1e-5):
        """
        Verifica se três pontos no R^3 são colineares via norma do produto vetorial:
            || (p2 - p1) x (p3 - p1) || <= epsilon
        """
        p1 = np.asarray(p1, dtype=float)
        p2 = np.asarray(p2, dtype=float)
        p3 = np.asarray(p3, dtype=float)
        prod_vet = np.cross(p2 - p1, p3 - p1)
        return np.linalg.norm(prod_vet) <= epsilon

    @staticmethod
    def possui_face_colinear(vc, faces, epsilon=1e-5):
        """
        Detecta se alguma face do poliedro possui 3 vértices colineares, o que
        indica degeneração de contorno ou perda de convexidade da face.
        """
        V = np.asarray(vc, dtype=float)
        for face in faces:
            for i, j, k in combinations(face, 3):
                if VerificadorGeometrico.pontos_colineares(V[i], V[j], V[k], epsilon):
                    print(f"Colinearidade detectada na face {face}: vértices ({i}, {j}, {k})")
                    return True
        return False

    @staticmethod
    def verificar_minimo_degenerado(vertices, faces, verbose=False):
        """
        Executa os quatro testes de integridade geométrica:
            1. Vértices colapsados (distância mínima < 1e-4)
            2. Faces de área nula (área < 1e-5)
            3. Volume poliédrico total colapsado (|V| < 1e-4)
            4. Bounding box planar ou colapsado (dimensão < 1e-3)
        Retorna True se a configuração for degenerada (inválida), False se for válida.
        """
        V = np.array(vertices, dtype=float)

        # 1. Checagem de vértices colapsados
        dist = np.linalg.norm(V[:, None, :] - V[None, :, :], axis=-1)
        np.fill_diagonal(dist, np.inf)
        min_dist = np.min(dist)
        if min_dist < 1e-4:
            if verbose:
                print(f"⚠️ Degenerado: vértices colapsados (distância mínima = {min_dist:.3e})")
            return True

        # 2. Checagem de áreas das faces
        def face_area(f):
            if len(f) < 3:
                return 0.0
            pts = V[f]
            normal = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            return 0.5 * np.linalg.norm(normal)

        areas = np.array([face_area(f) for f in faces])
        if np.sum(areas < 1e-5) > 0:
            if verbose:
                print(f"⚠️ Degenerado: faces com área ≈ 0 detectadas.")
            return True

        # 3. Volume total exato via triangulação em leque das faces
        total_volume = VerificadorGeometrico.volume_assinado(V, faces)
        if abs(total_volume) < 1e-4:
            if verbose:
                print(f"⚠️ Degenerado: volume total colapsado (|V| = {abs(total_volume):.3e})")
            return True

        # 4. Dispersão tridimensional (bounding box)
        bbox = V.max(axis=0) - V.min(axis=0)
        if np.any(bbox < 1e-3):
            if verbose:
                print(f"⚠️ Degenerado: bounding box achatado ({bbox})")
            return True

        return False

    @staticmethod
    def volume_assinado(vertices, faces):
        """
        Calcula o volume assinado exato do poliedro via triangulação em leque
        de cada face orientada.
        """
        V = np.asarray(vertices, dtype=float)
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

    @staticmethod
    def verificar_convexidade(
        vertices,
        faces_raw,
        plane_tol=1e-3,
        reflex_tol_deg=0.5,
        vol_ratio_tol=1e-3,
    ):
        """
        Certificado matemático rigoroso de convexidade poliédrica.

        Combina quatro critérios independentes sobre as faces consistentemente orientadas:
          1. Teste de plano suporte para todas as faces (todos os vértices no mesmo semiespaço).
          2. Ângulos diedrais internos orientados em [0°, 360°): aresta reflexa <=> theta_int > 180° + tol.
          3. Vértices estritamente interiores à envoltória convexa Conv(V).
          4. Razão volumétrica |V_poliedro| / V_ConvexHull (captura concavidades e autointerseções).

        Retorna dicionário contendo 'is_convex', 'classification' ('convexo' | 'nao_convexo'),
        'subpasta' ('convexos' | 'nao_convexos'), métricas geométricas, motivos e 'oriented_faces'.
        """
        V = np.asarray(vertices, dtype=float)
        if V.ndim != 2 or V.shape[1] != 3 or len(V) < 4 or not faces_raw:
            return {
                "is_convex": True,
                "classification": "indeterminado",
                "subpasta": "convexos",
                "volume": 0.0,
                "hull_volume": 0.0,
                "volume_ratio": 1.0,
                "interior_vertices": 0,
                "non_supporting_faces": 0,
                "reflex_edges": 0,
                "min_dihedral_deg": 0.0,
                "max_dihedral_deg": 0.0,
                "interior_dihedrals_deg": [],
                "reasons": [],
                "oriented_faces": faces_raw,
            }

        # 1. Orientação topológica consistente + alinhamento de normais para fora (volume positivo)
        faces = OrientadorFaces.corrigir_orientacao(faces_raw)
        signed_vol = VerificadorGeometrico.volume_assinado(V, faces)
        if signed_vol < 0:
            faces = [list(reversed(f)) for f in faces]
            signed_vol = -signed_vol

        # Escala característica (aresta média ~ 1.0) para tolerância relativa
        bbox_diag = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0)))
        scale_tol = max(plane_tol, plane_tol * max(1.0, bbox_diag * 0.1))

        # 2. Envoltória convexa (scipy.spatial.ConvexHull)
        hull_volume = signed_vol
        interior_vertices = 0
        if ConvexHull is not None:
            try:
                hull = ConvexHull(V)
                hull_volume = float(hull.volume)
                # hull.equations: cada linha [a, b, c, d] satisfaz a*x + b*y + c*z + d <= 0 em Conv(V)
                eq = hull.equations
                dists_to_hull_planes = V @ eq[:, :3].T + eq[:, 3]
                max_signed_dist = np.max(dists_to_hull_planes, axis=1)
                interior_vertices = int(np.sum(max_signed_dist < -scale_tol))
            except Exception:
                hull_volume = signed_vol

        volume_ratio = (signed_vol / hull_volume) if hull_volume > 1e-12 else 1.0

        # 3. Teste de plano suporte em todas as faces
        non_supporting_faces = 0
        face_normals = []
        for f in faces:
            n = VerificadorGeometrico.normal_newell(f, V)
            face_normals.append(n)
            if n is None:
                continue
            centroid = V[f].mean(axis=0)
            proj = (V - centroid) @ n
            pos_exc = float(np.max(proj))
            neg_exc = float(np.min(proj))
            if pos_exc > scale_tol and neg_exc < -scale_tol:
                non_supporting_faces += 1

        # 4. Ângulos diedrais internos orientados em [0°, 360°)
        directed_edges = {}
        for fi, f in enumerate(faces):
            m = len(f)
            for i in range(m):
                a, b = f[i], f[(i + 1) % m]
                directed_edges[(a, b)] = fi

        visited_undirected = set()
        interior_dihedrals = []
        reflex_edges = 0

        for (a, b), f1_idx in directed_edges.items():
            und = (a, b) if a < b else (b, a)
            if und in visited_undirected:
                continue
            if (b, a) not in directed_edges:
                continue
            visited_undirected.add(und)
            f2_idx = directed_edges[(b, a)]

            n1 = face_normals[f1_idx]
            n2 = face_normals[f2_idx]
            if n1 is None or n2 is None:
                continue

            e = V[b] - V[a]
            enorm = float(np.linalg.norm(e))
            if enorm < 1e-12:
                continue
            e = e / enorm

            # Com orientação CCW vista de fora (normal de Newell apontando para fora):
            # e . (n1 x n2) > 0 em arestas convexas; < 0 em arestas reflexas (côncavas)
            sin_turn = float(np.dot(e, np.cross(n1, n2)))
            cos_turn = float(np.clip(np.dot(n1, n2), -1.0, 1.0))
            ext_turn_deg = math.degrees(math.atan2(sin_turn, cos_turn))
            theta_int = 180.0 - ext_turn_deg
            if theta_int < 0.0:
                theta_int += 360.0
            interior_dihedrals.append(round(theta_int, 4))
            if theta_int > 180.0 + reflex_tol_deg:
                reflex_edges += 1

        interior_dihedrals.sort()
        min_d = interior_dihedrals[0] if interior_dihedrals else 0.0
        max_d = interior_dihedrals[-1] if interior_dihedrals else 0.0

        reasons = []
        if reflex_edges > 0:
            reasons.append(f"{reflex_edges} aresta(s) reflexa(s) (diedral interno máx. {max_d:.2f}°)")
        if non_supporting_faces > 0:
            reasons.append(f"{non_supporting_faces} face(s) cortam o interior do sólido")
        if interior_vertices > 0:
            reasons.append(f"{interior_vertices} vértice(s) no interior da envoltória convexa")
        if hull_volume > 1e-9 and abs(1.0 - volume_ratio) > vol_ratio_tol:
            pct = abs(1.0 - volume_ratio) * 100.0
            if volume_ratio < 1.0:
                reasons.append(f"Razão volumétrica V/V_CH = {volume_ratio:.4f} (concavidade de {pct:.2f}%)")
            else:
                reasons.append(f"Razão volumétrica anômala V/V_CH = {volume_ratio:.4f} (possível autointerseção)")

        is_convex = len(reasons) == 0

        return {
            "is_convex": is_convex,
            "classification": "convexo" if is_convex else "nao_convexo",
            "subpasta": "convexos" if is_convex else "nao_convexos",
            "volume": round(signed_vol, 6),
            "hull_volume": round(hull_volume, 6),
            "volume_ratio": round(volume_ratio, 6),
            "interior_vertices": interior_vertices,
            "non_supporting_faces": non_supporting_faces,
            "reflex_edges": reflex_edges,
            "min_dihedral_deg": round(min_d, 3),
            "max_dihedral_deg": round(max_d, 3),
            "interior_dihedrals_deg": interior_dihedrals,
            "reasons": reasons,
            "oriented_faces": faces,
        }

    @staticmethod
    def _clip_poligono_2d(subject, clip_poly):
        """Recorte de Sutherland-Hodgman para calcular sobreposição 2D entre dois triângulos coplanares."""
        def cross2(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        area_c = 0.0
        for i in range(len(clip_poly)):
            p, q = clip_poly[i], clip_poly[(i + 1) % len(clip_poly)]
            area_c += p[0] * q[1] - q[0] * p[1]
        if area_c < 0.0:
            clip_poly = list(reversed(clip_poly))

        output = list(subject)
        for i in range(len(clip_poly)):
            if not output:
                return []
            cp1 = clip_poly[i]
            cp2 = clip_poly[(i + 1) % len(clip_poly)]
            inp = output
            output = []
            s = inp[-1]
            for e in inp:
                e_in = cross2(cp1, cp2, e) >= -1e-11
                s_in = cross2(cp1, cp2, s) >= -1e-11
                if e_in:
                    if not s_in:
                        dc = (cp1[0] - cp2[0], cp1[1] - cp2[1])
                        dp = (s[0] - e[0], s[1] - e[1])
                        denom = dc[0] * dp[1] - dc[1] * dp[0]
                        if abs(denom) > 1e-14:
                            n1 = cp1[0] * cp2[1] - cp1[1] * cp2[0]
                            n2 = s[0] * e[1] - s[1] * e[0]
                            output.append((
                                (n1 * dp[0] - n2 * dc[0]) / denom,
                                (n1 * dp[1] - n2 * dc[1]) / denom,
                            ))
                    output.append(e)
                elif s_in:
                    dc = (cp1[0] - cp2[0], cp1[1] - cp2[1])
                    dp = (s[0] - e[0], s[1] - e[1])
                    denom = dc[0] * dp[1] - dc[1] * dp[0]
                    if abs(denom) > 1e-14:
                        n1 = cp1[0] * cp2[1] - cp1[1] * cp2[0]
                        n2 = s[0] * e[1] - s[1] * e[0]
                        output.append((
                            (n1 * dp[0] - n2 * dc[0]) / denom,
                            (n1 * dp[1] - n2 * dc[1]) / denom,
                        ))
                s = e
        return output

    @staticmethod
    def _area_poligono_2d(poly):
        if len(poly) < 3:
            return 0.0
        a = 0.0
        for i in range(len(poly)):
            p, q = poly[i], poly[(i + 1) % len(poly)]
            a += p[0] * q[1] - q[0] * p[1]
        return abs(a) * 0.5

    @staticmethod
    def _dist_ponto_segmento_2d(p, a, b):
        abx, aby = b[0] - a[0], b[1] - a[1]
        apx, apy = p[0] - a[0], p[1] - a[1]
        ab2 = abx * abx + aby * aby
        if ab2 < 1e-14:
            return math.hypot(apx, apy)
        t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab2))
        return math.hypot(p[0] - (a[0] + t * abx), p[1] - (a[1] + t * aby))

    @staticmethod
    def _seg_2d_intersecta_tri_2d(s0, s1, tri, eps=1e-5):
        """Verifica se o segmento 2D [s0, s1] intersecta o triângulo 2D fechado."""
        def sign(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

        def ponto_no_tri(pt):
            d1 = sign(pt, tri[0], tri[1])
            d2 = sign(pt, tri[1], tri[2])
            d3 = sign(pt, tri[2], tri[0])
            has_neg = (d1 < -eps) or (d2 < -eps) or (d3 < -eps)
            has_pos = (d1 > eps) or (d2 > eps) or (d3 > eps)
            return not (has_neg and has_pos)

        if ponto_no_tri(s0) or ponto_no_tri(s1):
            return True

        def segs_intersectam(a, b, c, d):
            def orient(p, q, r):
                return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

            o1 = orient(a, b, c)
            o2 = orient(a, b, d)
            o3 = orient(c, d, a)
            o4 = orient(c, d, b)
            if (o1 * o2 < 0.0) and (o3 * o4 < 0.0):
                return True
            if (
                VerificadorGeometrico._dist_ponto_segmento_2d(c, a, b) <= eps
                or VerificadorGeometrico._dist_ponto_segmento_2d(d, a, b) <= eps
                or VerificadorGeometrico._dist_ponto_segmento_2d(a, c, d) <= eps
                or VerificadorGeometrico._dist_ponto_segmento_2d(b, c, d) <= eps
            ):
                return True
            return False

        for i in range(3):
            if segs_intersectam(s0, s1, tri[i], tri[(i + 1) % 3]):
                return True
        return False

    @staticmethod
    def _segmento_intersecta_triangulo(p0, p1, v0, v1, v2, n_tri, eps=1e-5):
        """
        Teste exato de interseção segmento 3D [p0, p1] x triângulo fechado (v0, v1, v2)
        via algoritmo de Möller-Trumbore + caso paralelo no mesmo plano.
        """
        d = p1 - p0
        e1 = v1 - v0
        e2 = v2 - v0
        h = np.cross(d, e2)
        a = float(np.dot(e1, h))

        if abs(a) < 1e-12:
            # Segmento paralelo ao plano do triângulo: checa se está contido no plano
            if abs(float(np.dot(p0 - v0, n_tri))) <= eps and abs(float(np.dot(p1 - v0, n_tri))) <= eps:
                u_norm = float(np.linalg.norm(e1))
                if u_norm < 1e-12:
                    return False
                u_axis = e1 / u_norm
                w_axis = np.cross(n_tri, u_axis)
                tri2 = [
                    (0.0, 0.0),
                    (float(np.dot(v1 - v0, u_axis)), float(np.dot(v1 - v0, w_axis))),
                    (float(np.dot(v2 - v0, u_axis)), float(np.dot(v2 - v0, w_axis))),
                ]
                s0 = (float(np.dot(p0 - v0, u_axis)), float(np.dot(p0 - v0, w_axis)))
                s1 = (float(np.dot(p1 - v0, u_axis)), float(np.dot(p1 - v0, w_axis)))
                return VerificadorGeometrico._seg_2d_intersecta_tri_2d(s0, s1, tri2, eps=eps)
            return False

        f = 1.0 / a
        s = p0 - v0
        u = f * float(np.dot(s, h))
        if u < -eps or u > 1.0 + eps:
            return False

        q = np.cross(s, e1)
        v = f * float(np.dot(d, q))
        if v < -eps or u + v > 1.0 + eps:
            return False

        t = f * float(np.dot(e2, q))
        return -eps <= t <= 1.0 + eps

    @staticmethod
    def verificar_autointersecao_faces(vertices, faces, eps=1e-5, area_tol=1e-5, clearance_tol=0.05):
        """
        Verifica rigorosamente se existe autointerseção de faces no poliedro 3D.

        Triangula cada face em leque e testa todos os pares de triângulos considerando
        os 4 casos topológicos exatos + colisão física vértice-interior de face:
          - 3 vértices compartilhados: faces coincidentes (autointerseção).
          - 2 vértices compartilhados (aresta comum): autointerseção se coplanares
            dobradas sobre o mesmo lado (sobreposição de área > area_tol).
          - 1 vértice compartilhado: autointerseção se a aresta oposta de um triângulo
            perfura/toca o outro, ou se há sobreposição coplanar de área > area_tol.
          - 0 vértices compartilhados: autointerseção se qualquer aresta de um toca/cruza
            o outro triângulo, ou se há sobreposição/toque coplanar.
          - Colisão vértice-interior de face (vertex_face_collision): vértice não incidente
            cujo pé da perpendicular cai no interior de outra face a distância < clearance_tol.
        """
        V = np.asarray(vertices, dtype=float)
        if V.ndim != 2 or V.shape[1] != 3 or not faces:
            return {
                "has_self_intersection": False,
                "intersection_count": 0,
                "intersecting_face_pairs": [],
                "intersection_types": [],
                "subpasta_intersecao": "sem_autointersecao",
            }

        tris = []
        for fi, f in enumerate(faces):
            if len(f) < 3:
                continue
            for k in range(1, len(f) - 1):
                idx = (int(f[0]), int(f[k]), int(f[k + 1]))
                pts = V[list(idx)]
                n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
                nn = float(np.linalg.norm(n))
                if nn < 1e-12:
                    continue
                n = n / nn
                tris.append((fi, idx, pts.min(axis=0), pts.max(axis=0), n))

        intersections = []
        seen_face_pairs = set()
        n_tris = len(tris)

        for a in range(n_tris):
            fa, ia, bmin_a, bmax_a, na = tris[a]
            pa = (V[ia[0]], V[ia[1]], V[ia[2]])
            for b in range(a + 1, n_tris):
                fb, ib, bmin_b, bmax_b, nb = tris[b]
                if np.any(bmax_a + eps < bmin_b) or np.any(bmax_b + eps < bmin_a):
                    continue

                pb = (V[ib[0]], V[ib[1]], V[ib[2]])
                shared = set(ia) & set(ib)

                # Faces coincidentes (mesmos 3 vértices em faces distintas)
                if len(shared) == 3:
                    if fa != fb:
                        pair_key = (min(fa, fb), max(fa, fb), "coincident_face")
                        if pair_key not in seen_face_pairs:
                            seen_face_pairs.add(pair_key)
                            intersections.append(pair_key)
                    continue

                # Teste de coplanaridade
                cross_n = float(np.linalg.norm(np.cross(na, nb)))
                dist_plane = max(abs(float(np.dot(p - pa[0], na))) for p in pb)
                is_coplanar = (cross_n < 1e-4) and (dist_plane < 1e-4)

                if is_coplanar:
                    u_vec = pa[1] - pa[0]
                    u_norm = float(np.linalg.norm(u_vec))
                    if u_norm < 1e-12:
                        continue
                    u_axis = u_vec / u_norm
                    w_axis = np.cross(na, u_axis)
                    o = pa[0]
                    p2a = [(float(np.dot(p - o, u_axis)), float(np.dot(p - o, w_axis))) for p in pa]
                    p2b = [(float(np.dot(p - o, u_axis)), float(np.dot(p - o, w_axis))) for p in pb]
                    clipped = VerificadorGeometrico._clip_poligono_2d(p2a, p2b)
                    area_ov = VerificadorGeometrico._area_poligono_2d(clipped)
                    if area_ov > area_tol:
                        kind = "folded_face" if fa == fb else "coplanar_overlap"
                        pair_key = (min(fa, fb), max(fa, fb), kind)
                        if pair_key not in seen_face_pairs:
                            seen_face_pairs.add(pair_key)
                            intersections.append(pair_key)
                    elif len(shared) == 0 and fa != fb:
                        min_d = min(
                            min(
                                VerificadorGeometrico._dist_ponto_segmento_2d(pt, p2b[i], p2b[(i + 1) % 3])
                                for i in range(3)
                                for pt in p2a
                            ),
                            min(
                                VerificadorGeometrico._dist_ponto_segmento_2d(pt, p2a[i], p2a[(i + 1) % 3])
                                for i in range(3)
                                for pt in p2b
                            ),
                        )
                        if min_d < eps:
                            pair_key = (min(fa, fb), max(fa, fb), "coplanar_touch")
                            if pair_key not in seen_face_pairs:
                                seen_face_pairs.add(pair_key)
                                intersections.append(pair_key)
                    continue

                if fa == fb or len(shared) == 2:
                    continue

                if len(shared) == 1:
                    sv = next(iter(shared))
                    oa = [V[i] for i in ia if i != sv]
                    ob = [V[i] for i in ib if i != sv]
                    hit = (
                        VerificadorGeometrico._segmento_intersecta_triangulo(
                            oa[0], oa[1], pb[0], pb[1], pb[2], nb, eps=eps
                        )
                        or VerificadorGeometrico._segmento_intersecta_triangulo(
                            ob[0], ob[1], pa[0], pa[1], pa[2], na, eps=eps
                        )
                    )
                    if hit:
                        pair_key = (min(fa, fb), max(fa, fb), "shared_vertex_pierce")
                        if pair_key not in seen_face_pairs:
                            seen_face_pairs.add(pair_key)
                            intersections.append(pair_key)
                    continue

                # 0 vértices compartilhados e não coplanares
                hit = False
                for i in range(3):
                    if VerificadorGeometrico._segmento_intersecta_triangulo(
                        pa[i], pa[(i + 1) % 3], pb[0], pb[1], pb[2], nb, eps=eps
                    ):
                        hit = True
                        break
                if not hit:
                    for i in range(3):
                        if VerificadorGeometrico._segmento_intersecta_triangulo(
                            pb[i], pb[(i + 1) % 3], pa[0], pa[1], pa[2], na, eps=eps
                        ):
                            hit = True
                            break
                if hit:
                    pair_key = (min(fa, fb), max(fa, fb), "face_crossing")
                    if pair_key not in seen_face_pairs:
                        seen_face_pairs.add(pair_key)
                        intersections.append(pair_key)

        # Colisão física vértice-interior de face (abas dobradas contra o interior de outra face)
        if clearance_tol > 0.0:
            vertex_to_face = {}
            for fi, f in enumerate(faces):
                for vi in f:
                    vertex_to_face.setdefault(int(vi), fi)
            face_vsets = [set(int(x) for x in f) for f in faces]
            nv = len(V)
            for fa, ia, _bmin, _bmax, na in tris:
                a_pt, b_pt, c_pt = V[ia[0]], V[ia[1]], V[ia[2]]
                v0 = c_pt - a_pt
                v1 = b_pt - a_pt
                d00 = float(np.dot(v0, v0))
                d01 = float(np.dot(v0, v1))
                d11 = float(np.dot(v1, v1))
                denom = d00 * d11 - d01 * d01
                if abs(denom) < 1e-12:
                    continue
                inv_denom = 1.0 / denom
                fset = face_vsets[fa]
                for vi in range(nv):
                    if vi in fset:
                        continue
                    pt = V[vi]
                    signed_d = float(np.dot(pt - a_pt, na))
                    if abs(signed_d) >= clearance_tol:
                        continue
                    proj = pt - signed_d * na
                    v2 = proj - a_pt
                    d02 = float(np.dot(v0, v2))
                    d12 = float(np.dot(v1, v2))
                    u = (d11 * d02 - d01 * d12) * inv_denom
                    v = (d00 * d12 - d01 * d02) * inv_denom
                    if u >= -1e-4 and v >= -1e-4 and (u + v) <= 1.0 + 1e-4:
                        fb = vertex_to_face.get(vi, fa)
                        pair_key = (min(fa, fb), max(fa, fb), "vertex_face_collision")
                        if pair_key not in seen_face_pairs:
                            seen_face_pairs.add(pair_key)
                            intersections.append(pair_key)

        has_inter = len(intersections) > 0
        types_found = sorted({t for _, _, t in intersections})
        return {
            "has_self_intersection": has_inter,
            "intersection_count": len(intersections),
            "intersecting_face_pairs": [
                {"face_a": fa, "face_b": fb, "type": kind}
                for fa, fb, kind in intersections[:50]
            ],
            "intersection_types": types_found,
            "subpasta_intersecao": "com_autointersecao" if has_inter else "sem_autointersecao",
        }

    @staticmethod
    def classificar_solucao_global(vertices, faces_raw):
        """
        Executa a auditoria geométrica completa de um mínimo global:
          1. Degeneração métrica / colinearidade em faces
          2. Certificado de convexidade (convexo vs não-convexo)
          3. Certificado de autointerseção de faces (sem vs com autointerseção)
        """
        V = np.asarray(vertices, dtype=float)
        faces = OrientadorFaces.corrigir_orientacao(faces_raw)
        degenerado = VerificadorGeometrico.verificar_minimo_degenerado(V, faces)
        colinear = VerificadorGeometrico.possui_face_colinear(V, faces)
        convexidade = VerificadorGeometrico.verificar_convexidade(V, faces)
        faces_orientadas = convexidade["oriented_faces"]
        autointersecao = VerificadorGeometrico.verificar_autointersecao_faces(V, faces_orientadas)

        is_convex = bool(convexidade["is_convex"])
        has_inter = bool(autointersecao["has_self_intersection"])
        publicavel = (not degenerado) and (not colinear) and (not has_inter)
        secao_site = None
        if publicavel:
            secao_site = "resultados" if is_convex else "descobertas"

        return {
            "degenerado": degenerado,
            "colinear": colinear,
            "is_convex": is_convex,
            "has_self_intersection": has_inter,
            "subpasta_convexidade": "convexos" if is_convex else "nao_convexos",
            "subpasta_intersecao": "com_autointersecao" if has_inter else "sem_autointersecao",
            "publicavel_no_site": publicavel,
            "secao_site": secao_site,
            "convexidade": convexidade,
            "autointersecao": autointersecao,
            "oriented_faces": faces_orientadas,
        }
