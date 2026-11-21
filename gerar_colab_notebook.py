import json

cells = []

def add_md(text):
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [line + "\n" for line in text.strip().split("\n")]
    })

def add_code(text):
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [line + "\n" for line in text.strip().split("\n")]
    })

# -------------------------------------------------------------
# Célula Markdown 1: Título e Introdução
# -------------------------------------------------------------
add_md("""# Iniciação Científica - IME-USP
## Determinação de Poliedros de Faces Regulares por Otimização Não-Linear
**Autores:** Marcelo G. Reis, Thomas L. S. Dantas  
**Orientador:** Prof. Dr. Eduardo Colli  
**Instituição:** Instituto de Matemática, Estatística e Ciência da Computação – Universidade de São Paulo (IME-USP)

---

### 1. Contexto e Formulação Matemática
O objetivo deste projeto consiste em determinar numericamente as posições tridimensionais dos vértices dos **Sólidos de Johnson** e poliedros de faces regulares a partir de sua topologia combinatória.

A função de energia (distância elástica) a ser minimizada é dada por:
$$F(x) = \\frac{1}{2} \\sum_{f \\in \\text{faces}} \\sum_{i < j \\in f} \\left( \\|v_i(x) - v_j(x)\\|^2 - \\delta(i,j)^2 \\right)^2$$
onde $\\delta(i, j)$ é a distância ideal entre os vértices $i$ e $j$ em um polígono regular de aresta unitária (lado = 1).

A minimização utiliza o método do **Velocity Gradient** (dinâmica de 2ª ordem amortecida):
$$\\ddot{x} = -\\nabla F(x) - \\alpha \\dot{x}$$

---

### 2. Teorema 1: Delimitação Exata do Hipercubo de Busca (Demonstração 19-03)
**Definições:**
* $N$ é o diâmetro do grafo de arestas do poliedro (maior distância de menor caminho entre dois vértices).
* $\\Delta = \\sum_{f \\in \\text{faces}} \\sum_{i < j \\in f} \\delta(i,j)^4$ é a soma dos quartos de potências de todas as distâncias de faces.

**Teorema:**
Se existe $L > 0$ e vértices $k, l$ tais que $|x_k - x_l| \\geq L$, então $\\nabla F(x) \\neq 0$. Em particular, nenhum ponto crítico (e nenhum mínimo global ou local) pode existir fora do hipercubo $[-L, L]^3$.

**Fórmula Analítica de $L$:**
$$u = \\frac{1 + \\sqrt{1 + \\frac{\\Delta}{2}}}{2} \\implies L = N \\sqrt{\\frac{1 + \\sqrt{1 + \\frac{\\Delta}{2}}}{2}}$$

---

### 3. Tratamento da Projeção Esferográfica (Prof. Eduardo Colli)
1. **Centralização no Plano:** Subtrai-se a média $(\\bar{x}, \\bar{y})$ de todos os vértices do grafo planar (origem no $(0,0)$).
2. **Dispersão Radial:** Normaliza-se pela norma máxima e multiplica-se por 5, impedindo aglomeração no polo norte.
3. **Projeção Estereográfica Inversa em $S^2$:** Mapeamento conformal na esfera unitária.
4. **Escalonamento Unitário das Arestas:** Divide-se todas as coordenadas pela média euclidiana 3D de todas as arestas, fixando o comprimento médio em 1.
5. **Perturbação Cúbica:** A 1ª iteração roda com a projeção pura; se não atingir mínimo global, as iterações seguintes recebem perturbações uniformes em $[-\\epsilon, \\epsilon]^3$ (com $\\epsilon = 0.1$) por vértice.

---

### 4. Exportação Automática para PythonSCAD (Somente Mínimos Globais)
Quando a otimização atinge um **mínimo global** exato ($F(x) < 10^{-6}$), a classe `ExportadorPythonSCAD` gera automaticamente um arquivo `.py` compatível com PythonSCAD / OpenSCAD contendo:
* Os vértices `pts` finais com alta precisão;
* As faces `faces` orientadas;
* A chamada `polyhedron(pts, faces)`, `scale(obj, 20)` e `show(obj)` para visualização interativa instantânea com 1 clique.""")

# -------------------------------------------------------------
# Célula 2: Instalação de Dependências
# -------------------------------------------------------------
add_code("""# Instalação das dependências necessárias no ambiente do Google Colab
!pip install networkx numpy scipy matplotlib
""")

# -------------------------------------------------------------
# Célula 3: Banco de Faces Embutido
# -------------------------------------------------------------
add_code("""# Importação de módulos padrão para manipulação de arquivos e sistema
import os
import ast

# Função para carregar as faces: tenta ler de arquivo local ou utiliza base embutida
def obter_banco_faces():
    caminho = "faces.txt"
    solidos = {}
    
    # Se o arquivo faces.txt existir localmente, lê diretamente dele
    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            for linha in f:
                if " | n=" in linha:
                    bloco_faces, n_str = linha.split(" | n=")
                    nome, faces_txt = bloco_faces.split(" - ")
                    faces = ast.literal_eval(faces_txt.strip())
                    faces = [f for f in faces if len(f) >= 3]
                    solidos[nome.strip()] = (faces, int(n_str.strip()))
        return solidos

    # Caso o arquivo faces.txt não esteja presente no Colab, usa definições canônicas embutidas
    solidos_embutidos = {
        "Tetrahedron": ([[0, 1, 2], [0, 3, 1], [1, 3, 2], [0, 2, 3]], 4),
        "Cube": ([[0, 1, 2, 3], [4, 7, 6, 5], [0, 4, 5, 1], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]], 8),
        "Octahedron": ([[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1], [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4]], 6),
        "Dodecahedron": ([[0,1,2,3,4],[0,5,10,6,1],[1,6,11,7,2],[2,7,12,8,3],[3,8,13,9,4],[4,9,14,5,0],[15,10,5,14,19],[16,11,6,10,15],[17,12,7,11,16],[18,13,8,12,17],[19,14,9,13,18],[19,18,17,16,15]], 20),
        "Icosahedron": ([[0,1,2],[0,2,3],[0,3,4],[0,4,5],[0,5,1],[11,6,1],[11,7,6],[11,8,7],[11,9,8],[11,10,9],[11,1,10],[1,6,2],[2,7,3],[3,8,4],[4,9,5],[5,10,0],[10,6,2],[7,2,3],[8,3,4],[9,4,5]], 12),
        "J1": ([[0, 1, 4], [0, 3, 4], [1, 2, 4], [2, 3, 4], [0, 1, 2, 3]], 5),
        "J2": ([[0, 1, 5], [1, 2, 5], [2, 3, 5], [3, 4, 5], [0, 4, 5], [0, 1, 2, 3, 4]], 6),
        "J3": ([[0, 5, 6], [1, 2, 7], [3, 4, 8], [6, 7, 8], [0, 1, 6, 7], [2, 3, 7, 8], [4, 5, 6, 8], [0, 1, 2, 3, 4, 5]], 9),
        "J86": ([[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 5], [0, 5, 1], [1, 2, 6], [2, 3, 7], [3, 4, 8], [4, 5, 9], [5, 1, 10], [6, 7, 2], [7, 8, 3], [8, 9, 4], [9, 10, 5], [10, 6, 1]], 11)
    }
    return solidos_embutidos

banco_solidos = obter_banco_faces()
print(f"Banco de sólidos carregado com sucesso! Sólidos disponíveis: {list(banco_solidos.keys())}")
""")

# -------------------------------------------------------------
# Célula 4: Funções do Núcleo Matemático (Core)
# -------------------------------------------------------------
add_code("""# Importação de bibliotecas matemáticas e vetoriais essenciais
import numpy as np
import math
from itertools import combinations
from collections import defaultdict, deque

# Função para calcular o quadrado da distância ideal d2 entre vértices de um polígono regular de n lados
def calcular_d2(n, i, j):
    if n < 3:
        raise ValueError("O polígono precisa ter no mínimo 3 lados.")
    k = abs(i - j)
    k = min(k, n - k)
    if k == 0:
        return 0.0
    R = 1.0 / (2.0 * math.sin(math.pi / n))
    d = 2.0 * R * math.sin(k * math.pi / n)
    return d ** 2

# Função para gerar a lista de segmentos únicos com distâncias ideais ao quadrado
def gerar_segmentos(faces):
    segs = []
    for f in faces:
        m = len(f)
        for i in range(m):
            for j in range(i + 1, m):
                d2 = calcular_d2(m, i, j)
                segs.append((f[i], f[j], d2))
    return np.array(segs, dtype=float)

# Função para orientar consistentemente as faces do poliedro (normais apontando para o mesmo lado)
def corrigir_orientacao_faces(faces):
    edge_to_faces = defaultdict(list)
    for fi, face in enumerate(faces):
        m = len(face)
        for i in range(m):
            key = tuple(sorted((face[i], face[(i + 1) % m])))
            edge_to_faces[key].append(fi)

    oriented = [None] * len(faces)
    processed = [False] * len(faces)
    oriented[0] = list(faces[0])
    processed[0] = True
    queue = deque([0])

    while queue:
        fi = queue.popleft()
        ref = oriented[fi]
        for i in range(len(ref)):
            a, b = ref[i], ref[(i + 1) % len(ref)]
            key = tuple(sorted((a, b)))
            for nbr in edge_to_faces[key]:
                if not processed[nbr]:
                    f2 = list(faces[nbr])
                    for k in range(len(f2)):
                        x, y = f2[k], f2[(k + 1) % len(f2)]
                        if {x, y} == {a, b}:
                            if (x, y) == (a, b):
                                f2.reverse()
                            break
                    oriented[nbr] = f2
                    processed[nbr] = True
                    queue.append(nbr)

    for i, f in enumerate(oriented):
        if f is None:
            oriented[i] = list(faces[i])
    return oriented

# Função para calcular o gradiente analítico com amortecimento e limitação de passo
def gradiente(vc, segmentos, max_step=None):
    grad = np.zeros_like(vc)
    for seg in segmentos:
        i, j, d2 = int(seg[0]), int(seg[1]), seg[2]
        diff = vc[i] - vc[j]
        dist = np.linalg.norm(diff)
        if dist == 0:
            continue
        fator = 2.0 * (dist - math.sqrt(d2))
        delta = fator * (diff / dist)
        if max_step is not None:
            norm_delta = np.linalg.norm(delta)
            if norm_delta > max_step:
                delta = delta * (max_step / norm_delta)
        grad[i] += delta
        grad[j] -= delta
    return grad

# Função de avaliação da energia elástica total
def energia(vc, segmentos):
    diffs = []
    for (i, j, d2) in segmentos:
        vi, vj = vc[int(i)], vc[int(j)]
        diffs.append((np.linalg.norm(vi - vj) ** 2 - d2) ** 2)
    return 0.5 * sum(diffs)

# Função para calcular a matriz Hessiana via diferenças finitas para estudo de estabilidade
def hessiana(vc, segmentos, eps=1e-6):
    n = vc.size
    H = np.zeros((n, n))
    g0 = gradiente(vc, segmentos).reshape(-1)
    for k in range(n):
        vc_pert = vc.copy().reshape(-1)
        vc_pert[k] += eps
        vc_pert = vc_pert.reshape(vc.shape)
        g1 = gradiente(vc_pert, segmentos).reshape(-1)
        H[:, k] = (g1 - g0) / eps
    return H

# Função para testar colinearidade de 3 pontos
def pontos_colineares(p1, p2, p3, epsilon=1e-5):
    return np.linalg.norm(np.cross(p2 - p1, p3 - p1)) <= epsilon

# Função para testar se alguma face apresenta colinearidade
def possui_face_colinear(vc, faces, epsilon=1e-5):
    for face in faces:
        for i, j, k in combinations(face, 3):
            if pontos_colineares(vc[i], vc[j], vc[k], epsilon):
                return True
    return False

# Função para verificar se a solução colapsou em configuração degenerada
def verificar_minimo_degenerado(vertices, faces):
    V = np.array(vertices, dtype=float)
    dist = np.linalg.norm(V[:, None, :] - V[None, :, :], axis=-1)
    np.fill_diagonal(dist, np.inf)
    if np.min(dist) < 1e-4:
        return True
    bbox = V.max(axis=0) - V.min(axis=0)
    if np.any(bbox < 1e-3):
        return True
    return False

# Função para calcular o vetor ordenado de distâncias mútuas (assinatura de Cauchy)
def calcular_distancias(vertices):
    distancias = []
    n = len(vertices)
    for i in range(n):
        for j in range(i + 1, n):
            d = np.linalg.norm(np.asarray(vertices[i]) - np.asarray(vertices[j]))
            distancias.append(d)
    return np.sort(np.asarray(distancias))

# Função de Newell para cálculo do vetor normal unitário de uma face 3D
def normal_newell(face, vertices):
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

# Função para calcular todos os ângulos diedrais entre faces adjacentes
def calcular_angulos_diedrais(vertices, faces):
    arestas = defaultdict(list)
    for idx_face, face in enumerate(faces):
        m = len(face)
        for i in range(m):
            a, b = face[i], face[(i + 1) % m]
            arestas[tuple(sorted((a, b)))].append(idx_face)
    angulos = []
    for (a, b), lista_faces in arestas.items():
        if len(lista_faces) != 2:
            continue
        f1, f2 = faces[lista_faces[0]], faces[lista_faces[1]]
        n1 = normal_newell(f1, vertices)
        n2 = normal_newell(f2, vertices)
        if n1 is None or n2 is None:
            continue
        eixo = np.asarray(vertices[b], dtype=float) - np.asarray(vertices[a], dtype=float)
        norma_eixo = np.linalg.norm(eixo)
        if norma_eixo < 1e-12:
            continue
        eixo /= norma_eixo
        seno = np.dot(eixo, np.cross(n1, n2))
        cosseno = np.dot(n1, n2)
        theta = np.degrees(np.arctan2(seno, cosseno))
        if theta < 0:
            theta += 360.0
        if theta > 180.0:
            theta = 360.0 - theta
        angulos.append(theta)
    return np.sort(np.asarray(angulos))

# Certificado matemático de convexidade poliédrica (4 critérios independentes)
from scipy.spatial import ConvexHull

def volume_assinado(vertices, faces):
    V = np.asarray(vertices, dtype=float)
    vol = 0.0
    for f in faces:
        if len(f) < 3:
            continue
        v0 = V[f[0]]
        for k in range(1, len(f) - 1):
            vol += float(np.dot(v0, np.cross(V[f[k]], V[f[k + 1]]))) / 6.0
    return vol

def verificar_convexidade(vertices, faces_raw, plane_tol=1e-3, reflex_tol_deg=0.5, vol_ratio_tol=1e-3):
    V = np.asarray(vertices, dtype=float)
    faces = corrigir_orientacao_faces(faces_raw)
    signed_vol = volume_assinado(V, faces)
    if signed_vol < 0:
        faces = [list(reversed(f)) for f in faces]
        signed_vol = -signed_vol

    bbox_diag = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0)))
    scale_tol = max(plane_tol, plane_tol * max(1.0, bbox_diag * 0.1))

    hull_volume = signed_vol
    interior_vertices = 0
    try:
        hull = ConvexHull(V)
        hull_volume = float(hull.volume)
        eq = hull.equations
        dists = V @ eq[:, :3].T + eq[:, 3]
        interior_vertices = int(np.sum(np.max(dists, axis=1) < -scale_tol))
    except Exception:
        hull_volume = signed_vol

    volume_ratio = (signed_vol / hull_volume) if hull_volume > 1e-12 else 1.0

    non_supporting_faces = 0
    face_normals = []
    for f in faces:
        n = normal_newell(f, V)
        face_normals.append(n)
        if n is None:
            continue
        proj = (V - V[f].mean(axis=0)) @ n
        if float(np.max(proj)) > scale_tol and float(np.min(proj)) < -scale_tol:
            non_supporting_faces += 1

    directed_edges = {}
    for fi, f in enumerate(faces):
        m = len(f)
        for i in range(m):
            directed_edges[(f[i], f[(i + 1) % m])] = fi

    visited = set()
    interior_dihedrals = []
    reflex_edges = 0
    for (a, b), f1_idx in directed_edges.items():
        und = (a, b) if a < b else (b, a)
        if und in visited or (b, a) not in directed_edges:
            continue
        visited.add(und)
        n1 = face_normals[f1_idx]
        n2 = face_normals[directed_edges[(b, a)]]
        if n1 is None or n2 is None:
            continue
        e = V[b] - V[a]
        enorm = float(np.linalg.norm(e))
        if enorm < 1e-12:
            continue
        e = e / enorm
        sin_turn = float(np.dot(e, np.cross(n1, n2)))
        cos_turn = float(np.clip(np.dot(n1, n2), -1.0, 1.0))
        theta_int = 180.0 - math.degrees(math.atan2(sin_turn, cos_turn))
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
        reasons.append(f"Razão volumétrica V/V_CH = {volume_ratio:.4f} (desvio de {pct:.2f}%)")

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

# Verificação rigorosa de autointerseção de faces (Möller-Trumbore + recorte 2D coplanar + colisão vértice-face)
def verificar_autointersecao_faces(vertices, faces, eps=1e-5, area_tol=1e-5, clearance_tol=0.05):
    V = np.asarray(vertices, dtype=float)
    def clip_2d(subj, clip):
        def cross2(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        ac = sum(clip[i][0]*clip[(i+1)%len(clip)][1] - clip[(i+1)%len(clip)][0]*clip[i][1] for i in range(len(clip)))
        if ac < 0: clip = list(reversed(clip))
        out = list(subj)
        for i in range(len(clip)):
            if not out: return []
            c1, c2 = clip[i], clip[(i+1)%len(clip)]
            inp, out, s = out, [], out[-1]
            for e in inp:
                ei, si = cross2(c1, c2, e) >= -1e-11, cross2(c1, c2, s) >= -1e-11
                def inter_pt():
                    dc, dp = (c1[0]-c2[0], c1[1]-c2[1]), (s[0]-e[0], s[1]-e[1])
                    den = dc[0]*dp[1] - dc[1]*dp[0]
                    if abs(den) <= 1e-14: return None
                    n1, n2 = c1[0]*c2[1] - c1[1]*c2[0], s[0]*e[1] - s[1]*e[0]
                    return ((n1*dp[0]-n2*dc[0])/den, (n1*dp[1]-n2*dc[1])/den)
                if ei:
                    if not si:
                        pt = inter_pt()
                        if pt: out.append(pt)
                    out.append(e)
                elif si:
                    pt = inter_pt()
                    if pt: out.append(pt)
                s = e
        return out
    def seg_tri(p0, p1, v0, v1, v2):
        d, e1, e2 = p1 - p0, v1 - v0, v2 - v0
        h = np.cross(d, e2)
        a = float(np.dot(e1, h))
        if abs(a) < 1e-12: return False
        f = 1.0 / a
        s = p0 - v0
        u = f * float(np.dot(s, h))
        if u < -eps or u > 1.0 + eps: return False
        q = np.cross(s, e1)
        v = f * float(np.dot(d, q))
        if v < -eps or u + v > 1.0 + eps: return False
        t = f * float(np.dot(e2, q))
        return -eps <= t <= 1.0 + eps
    tris = []
    for fi, f in enumerate(faces):
        for k in range(1, len(f) - 1):
            idx = (int(f[0]), int(f[k]), int(f[k+1]))
            pts = V[list(idx)]
            n = np.cross(pts[1]-pts[0], pts[2]-pts[0])
            nn = float(np.linalg.norm(n))
            if nn >= 1e-12:
                tris.append((fi, idx, pts.min(axis=0), pts.max(axis=0), n/nn))
    count = 0
    for a in range(len(tris)):
        fa, ia, bmina, bmaxa, na = tris[a]
        pa = (V[ia[0]], V[ia[1]], V[ia[2]])
        for b in range(a + 1, len(tris)):
            fb, ib, bminb, bmaxb, nb = tris[b]
            if np.any(bmaxa + eps < bminb) or np.any(bmaxb + eps < bmina): continue
            pb = (V[ib[0]], V[ib[1]], V[ib[2]])
            sh = set(ia) & set(ib)
            if len(sh) == 3 and fa != fb:
                count += 1; continue
            if np.linalg.norm(np.cross(na, nb)) < 1e-4 and max(abs(float(np.dot(p-pa[0], na))) for p in pb) < 1e-4:
                u = (pa[1]-pa[0]) / np.linalg.norm(pa[1]-pa[0]); w = np.cross(na, u)
                p2a = [(float(np.dot(p-pa[0], u)), float(np.dot(p-pa[0], w))) for p in pa]
                p2b = [(float(np.dot(p-pa[0], u)), float(np.dot(p-pa[0], w))) for p in pb]
                cl = clip_2d(p2a, p2b)
                ov = 0.5*abs(sum(cl[i][0]*cl[(i+1)%len(cl)][1] - cl[(i+1)%len(cl)][0]*cl[i][1] for i in range(len(cl)))) if len(cl) >= 3 else 0.0
                if ov > area_tol: count += 1
                continue
            if fa == fb or len(sh) == 2: continue
            if len(sh) == 1:
                sv = next(iter(sh))
                oa = [V[i] for i in ia if i != sv]; ob = [V[i] for i in ib if i != sv]
                if seg_tri(oa[0], oa[1], pb[0], pb[1], pb[2]) or seg_tri(ob[0], ob[1], pa[0], pa[1], pa[2]): count += 1
                continue
            if any(seg_tri(pa[i], pa[(i+1)%3], pb[0], pb[1], pb[2]) for i in range(3)) or any(seg_tri(pb[i], pb[(i+1)%3], pa[0], pa[1], pa[2]) for i in range(3)):
                count += 1
    if clearance_tol > 0.0:
        fsets = [set(int(x) for x in f) for f in faces]
        for fa, ia, _bmin, _bmax, na in tris:
            a_pt, b_pt, c_pt = V[ia[0]], V[ia[1]], V[ia[2]]
            v0, v1 = c_pt - a_pt, b_pt - a_pt
            d00, d01, d11 = float(np.dot(v0, v0)), float(np.dot(v0, v1)), float(np.dot(v1, v1))
            den = d00 * d11 - d01 * d01
            if abs(den) < 1e-12: continue
            inv = 1.0 / den
            for vi in range(len(V)):
                if vi in fsets[fa]: continue
                sd = float(np.dot(V[vi] - a_pt, na))
                if abs(sd) >= clearance_tol: continue
                v2 = (V[vi] - sd * na) - a_pt
                u = (d11 * float(np.dot(v0, v2)) - d01 * float(np.dot(v1, v2))) * inv
                v = (d00 * float(np.dot(v1, v2)) - d01 * float(np.dot(v0, v2))) * inv
                if u >= -1e-4 and v >= -1e-4 and (u + v) <= 1.0 + 1e-4:
                    count += 1
    return {"has_self_intersection": count > 0, "intersection_count": count}
""")

# -------------------------------------------------------------
# Célula 5: Classe GeradorCondicoesIniciais com Teorema 1
# -------------------------------------------------------------
add_code("""# Importação da biblioteca NetworkX para construção do grafo planar e projeção esferográfica
import networkx as nx

# Classe dedicada para geração, cálculo exato de L (Teorema 1) e tratamento esferográfico
class GeradorCondicoesIniciais:
    # Construtor da classe: recebe as faces orientadas, o número de vértices e segmentos
    def __init__(self, faces, num_vertices=None, segmentos=None):
        self.faces = faces
        if num_vertices is None:
            self.num_vertices = max(max(face) for face in faces) + 1
        else:
            self.num_vertices = num_vertices
        self.segmentos = segmentos
        self.grafo = self._construir_grafo()
        self.arestas = self._extrair_arestas()
        self._posicoes_base_esferica = None

    # Constrói o grafo do poliedro conectando pares de vértices adjacentes em cada face
    def _construir_grafo(self):
        G = nx.Graph()
        G.add_nodes_from(range(self.num_vertices))
        for face in self.faces:
            m = len(face)
            for i in range(m):
                u = face[i]
                v = face[(i + 1) % m]
                G.add_edge(u, v)
        return G

    # Extrai o conjunto único de arestas sem repetições
    def _extrair_arestas(self):
        arestas_set = set()
        for face in self.faces:
            m = len(face)
            for i in range(m):
                u = face[i]
                v = face[(i + 1) % m]
                arestas_set.add(tuple(sorted((u, v))))
        return list(arestas_set)

    # ---------------------------------------------------------------------------------------------
    # CÁLCULO ANALÍTICO DE L VIA TEOREMA 1 (Demonstração Marcelo & Thomas / Orientador Colli)
    # Se |x_k - x_l| >= L, então \\nabla F \\neq 0.
    # Da dilatação radial: 8 u (u - 1) > \\Delta, onde u = (L / N)^2 e N = diâmetro do grafo.
    # ---------------------------------------------------------------------------------------------
    def calcular_lado_L_teorema(self, segmentos=None):
        if nx.is_connected(self.grafo):
            N = nx.diameter(self.grafo)
        else:
            N = self.num_vertices
            
        segs = segmentos if segmentos is not None else self.segmentos
        if segs is not None:
            Delta = float(np.sum(segs[:, 2] ** 2))
        else:
            Delta = float(len(self.arestas) * 2.0)
            
        u = (1.0 + math.sqrt(1.0 + Delta / 2.0)) / 2.0
        L = N * math.sqrt(u)
        return round(float(L), 4)

    # Método 1: Distribuição aleatória uniforme no hipercubo [-L, L]^3
    def gerar_hipercubo(self, L=None, segmentos=None):
        if L is None:
            L = self.calcular_lado_L_teorema(segmentos=segmentos)
        return np.random.uniform(-L, L, (self.num_vertices, 3))

    # Método 2: Projeção Esferográfica Tratada conforme orientações do Prof. Eduardo Colli
    def gerar_projecao_esferografica_tratada(self, escala_plano=5.0):
        is_planar, _ = nx.check_planarity(self.grafo)
        if is_planar:
            pos2d = nx.planar_layout(self.grafo)
        else:
            pos2d = nx.spring_layout(self.grafo, seed=42)
            
        coords_2d = np.array([pos2d[i] for i in range(self.num_vertices)], dtype=float)
        
        # (a) Centraliza o grafo planar subtraindo a média (x, y) de todos os vértices
        media_xy = np.mean(coords_2d, axis=0)
        coords_centralizadas = coords_2d - media_xy
        
        # (b) Normaliza pela norma máxima e multiplica por 5 para evitar acúmulo no polo norte
        normas = np.linalg.norm(coords_centralizadas, axis=1)
        norma_maxima = np.max(normas)
        if norma_maxima > 1e-12:
            coords_reescaladas = (coords_centralizadas / norma_maxima) * escala_plano
        else:
            coords_reescaladas = coords_centralizadas
            
        # (c) Projeção estereográfica inversa para a superfície da esfera unitária S^2
        posicoes_esfera = np.zeros((self.num_vertices, 3), dtype=float)
        for i in range(self.num_vertices):
            u = coords_reescaladas[i, 0]
            w = coords_reescaladas[i, 1]
            d = u * u + w * w + 1.0
            posicoes_esfera[i, 0] = 2.0 * u / d
            posicoes_esfera[i, 1] = 2.0 * w / d
            posicoes_esfera[i, 2] = (u * u + w * w - 1.0) / d
            
        # (d) Compatibilização com arestas unitárias: divide coordenadas pelo comprimento médio das arestas
        comprimentos = [np.linalg.norm(posicoes_esfera[u] - posicoes_esfera[v]) for (u, v) in self.arestas]
        media_arestas = np.mean(comprimentos)
        if media_arestas > 1e-12:
            posicoes_finais_3d = posicoes_esfera / media_arestas
        else:
            posicoes_finais_3d = posicoes_esfera
            
        self._posicoes_base_esferica = posicoes_finais_3d.copy()
        return posicoes_finais_3d

    # Aplicação de perturbação aleatória cúbica em [-epsilon, epsilon]^3 em cada vértice (Item 2.2)
    def aplicar_perturbacao_cubica(self, posicoes_base=None, epsilon=0.1):
        if posicoes_base is None:
            if self._posicoes_base_esferica is None:
                posicoes_base = self.gerar_projecao_esferografica_tratada()
            else:
                posicoes_base = self._posicoes_base_esferica
        ruido = np.random.uniform(-epsilon, epsilon, posicoes_base.shape)
        return posicoes_base + ruido
""")

# -------------------------------------------------------------
# Célula 6: Classe ExportadorPythonSCAD
# -------------------------------------------------------------
add_code("""# Importação de módulos do sistema para criação de pastas e arquivos
import os
from datetime import datetime

# Classe responsável por gerar scripts executáveis PythonSCAD (SOMENTE para mínimos globais)
class ExportadorPythonSCAD:
    # Construtor: recebe o fator de escala (padrão: 20) e pasta base de saída
    def __init__(self, fator_escala=20.0, pasta_base="solidos"):
        self.fator_escala = fator_escala
        self.pasta_base = pasta_base

    # Gera o texto do código-fonte em formato PythonSCAD
    def gerar_codigo_pythonscad(self, vertices, faces):
        linhas = []
        linhas.append("from openscad import *")
        linhas.append("")
        linhas.append("pts = [")
        for idx, v in enumerate(vertices):
            coord_str = f"    [{float(v[0]):.16f}, {float(v[1]):.16f}, {float(v[2]):.16f}]"
            if idx < len(vertices) - 1:
                coord_str += ","
            linhas.append(coord_str)
        linhas.append("]")
        linhas.append("")
        linhas.append(f"faces = {list(faces)}")
        linhas.append("")
        linhas.append("obj = polyhedron(pts, faces)")
        escala_val = int(self.fator_escala) if int(self.fator_escala) == self.fator_escala else self.fator_escala
        linhas.append(f"obj = scale(obj, {escala_val})")
        linhas.append("show(obj)")
        linhas.append("")
        return "\\n".join(linhas)

    # Exporta o script somente se a solução for um mínimo global
    def exportar_se_minimo_global(self, nome_solido, nome_solucao, tipo_solucao, vertices, faces, fval=0.0, convexo=True, tem_autointersecao=False, timestamp=None):
        # Filtro estrito: gera documento SOMENTE para mínimo global
        if tipo_solucao != "global":
            return None

        subpasta_conv = "convexos" if convexo else "nao_convexos"
        subpasta_inter = "com_autointersecao" if tem_autointersecao else "sem_autointersecao"
        destino_dir = os.path.join(self.pasta_base, nome_solido, "minimos_globais", subpasta_conv, subpasta_inter)
        os.makedirs(destino_dir, exist_ok=True)
        timestamp = timestamp or datetime.now().strftime('%Y%m%d_%H%M%S')
        nome_arquivo = f"{nome_solucao}_{timestamp}_pythonscad.py"
        caminho_completo = os.path.join(destino_dir, nome_arquivo)

        conteudo = self.gerar_codigo_pythonscad(vertices, faces)
        with open(caminho_completo, "w", encoding="utf-8") as f:
            f.write(conteudo)

        etiqueta_conv = "CONVEXO" if convexo else "NÃO CONVEXO"
        etiqueta_inter = "COM AUTOINTERSEÇÃO" if tem_autointersecao else "SEM AUTOINTERSEÇÃO"
        print(f"  [PythonSCAD] Documento gerado para MÍNIMO GLOBAL {etiqueta_conv} ({etiqueta_inter}):")
        print(f"  -> Arquivo salvo em: {caminho_completo}")
        return caminho_completo
""")

# -------------------------------------------------------------
# Célula 7: Função de Plotagem 3D (Visualização no Colab)
# -------------------------------------------------------------
add_code("""# Importação de módulos de visualização 3D do Matplotlib
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

# Função para desenhar e visualizar o poliedro convergido diretamente no notebook
def plotar_poliedro_3d(vertices, faces, titulo="Poliedro Reconstruído"):
    fig = plt.figure(figsize=(8, 8))
    ax = fig.add_subplot(111, projection='3d')
    
    poligonos = []
    for f in faces:
        poligonos.append([vertices[idx] for idx in f])
        
    colecao = Poly3DCollection(poligonos, alpha=0.75, facecolor='mediumaquamarine', edgecolor='darkslategray', linewidths=1.5)
    ax.add_collection3d(colecao)
    
    ax.scatter(vertices[:, 0], vertices[:, 1], vertices[:, 2], color='red', s=40, zorder=10)
    
    todos_pts = np.vstack(vertices)
    max_range = np.array([todos_pts[:,0].max()-todos_pts[:,0].min(),
                          todos_pts[:,1].max()-todos_pts[:,1].min(),
                          todos_pts[:,2].max()-todos_pts[:,2].min()]).max() / 2.0
    mid_x = (todos_pts[:,0].max()+todos_pts[:,0].min()) * 0.5
    mid_y = (todos_pts[:,1].max()+todos_pts[:,1].min()) * 0.5
    mid_z = (todos_pts[:,2].max()+todos_pts[:,2].min()) * 0.5
    ax.set_xlim(mid_x - max_range, mid_x + max_range)
    ax.set_ylim(mid_y - max_range, mid_y + max_range)
    ax.set_zlim(mid_z - max_range, mid_z + max_range)
    
    ax.set_title(titulo, fontsize=14, fontweight='bold')
    ax.set_xlabel('Eixo X')
    ax.set_ylabel('Eixo Y')
    ax.set_zlabel('Eixo Z')
    plt.tight_layout()
    plt.show()
""")

# -------------------------------------------------------------
# Célula 8: Loop Principal Interativo com Integração PythonSCAD
# -------------------------------------------------------------
add_code("""# Importação do módulo de medição temporal
import time

# Função executiva principal com menus interativos
def executar_otimizacao():
    print("=" * 70)
    print("SISTEMA DE OTIMIZAÇÃO NÃO-LINEAR DE POLIEDROS DE FACES REGULARES")
    print("=" * 70)
    
    nome_solido = input("Digite o nome do sólido a otimizar (ex: Tetrahedron, Cube, Octahedron, J1, J2, J86): ").strip()
    if nome_solido not in banco_solidos:
        print(f"Sólido '{nome_solido}' não encontrado. Usando 'J1' por padrão.")
        nome_solido = "J1"
        
    m_str = input("Qual o tamanho da amostra de iterações? (Enter = 5 repetições): ").strip()
    amostras = 5 if m_str == "" else int(m_str)
    
    # Menu de coordenadas iniciais (Item 2.1 solicitado)
    print("\\n" + "-" * 50)
    print("MÉTODO DE COORDENADAS INICIAIS:")
    print(" 1. Hipercubo de tamanho L (Teorema 1)")
    print(" 2. Projeção Esferográfica (Tratamento Colli)")
    print("-" * 50)
    opcao = input("Qual método de coordenadas iniciais você deseja? (1 ou 2): ").strip()
    if opcao not in ["1", "2"]:
        print("Opção inválida. Selecionando Opção 2 (Projeção Esferográfica) por padrão.")
        opcao = "2"
        
    faces_brutas, _ = banco_solidos[nome_solido]
    faces = corrigir_orientacao_faces(faces_brutas)
    segmentos = gerar_segmentos(faces)
    num_vertices = int(segmentos[:, :2].max()) + 1
    
    # Instancia o gerador de condições iniciais com os segmentos
    gerador_ci = GeradorCondicoesIniciais(faces, num_vertices=num_vertices, segmentos=segmentos)
    
    # Cria previamente a estrutura oficial de pastas do sólido
    os.makedirs(os.path.join("solidos", nome_solido, "minimos_locais"), exist_ok=True)
    os.makedirs(os.path.join("solidos", nome_solido, "minimos_globais", "convexos", "sem_autointersecao"), exist_ok=True)
    os.makedirs(os.path.join("solidos", nome_solido, "minimos_globais", "convexos", "com_autointersecao"), exist_ok=True)
    os.makedirs(os.path.join("solidos", nome_solido, "minimos_globais", "nao_convexos", "sem_autointersecao"), exist_ok=True)
    os.makedirs(os.path.join("solidos", nome_solido, "minimos_globais", "nao_convexos", "com_autointersecao"), exist_ok=True)

    # Instancia o exportador PythonSCAD
    exportador_scad = ExportadorPythonSCAD(fator_escala=20.0, pasta_base="solidos")
    
    # Lado L exato determinado analiticamente pelo Teorema 1
    L_teorema = gerador_ci.calcular_lado_L_teorema(segmentos=segmentos)
    print(f"\\nSólido '{nome_solido}': {num_vertices} vértices, {len(faces)} faces.")
    print(f"Lado L exato derivado analiticamente pelo Teorema 1: L = {L_teorema}")
    
    if opcao == "2":
        print("Gerando projeção esferográfica base com tratamento do grafo e arestas unitárias...")
        vc_base_esferica = gerador_ci.gerar_projecao_esferografica_tratada(escala_plano=5.0)
        
    # Parâmetros numéricos
    alpha = 0.01             # Força do gradiente
    grad_tol = 1e-14         # Tolerância de convergência
    max_iter = 100000        # Máximo de iterações
    max_step = 0.1           # Limite de deslocamento por passo
    amortecimento = 0.9      # Fator de amortecimento da velocidade
    epsilon_perturbacao = 0.1 # Hipercubo de perturbação por vértice (Item 2.2)
    
    melhor_solucao = None
    menor_energia = float('inf')
    contador_globais = 0
    contador_globais_convexos = 0
    contador_globais_nao_convexos = 0
    
    for rep in range(1, amostras + 1):
        print(f"\\n>>> Execução {rep}/{amostras} para '{nome_solido}' <<<")
        
        if opcao == "1":
            print(f"Sorteando vértices uniformemente no hipercubo [-{L_teorema}, {L_teorema}]^3...")
            vc = gerador_ci.gerar_hipercubo(L=L_teorema, segmentos=segmentos)
        else:
            if rep == 1:
                print("Iteração 1: Projeção esferográfica tratada pura (sem perturbação).")
                vc = vc_base_esferica.copy()
            else:
                print(f"Iteração {rep}: Aplicando perturbação aleatória em cubo eps = {epsilon_perturbacao} por vértice...")
                vc = gerador_ci.aplicar_perturbacao_cubica(posicoes_base=vc_base_esferica, epsilon=epsilon_perturbacao)
                
        vel = np.zeros_like(vc)
        t_inicio = time.time()
        convergiu = False
        
        for it in range(1, max_iter + 1):
            g = gradiente(vc, segmentos, max_step=max_step)
            norma_g = np.linalg.norm(g)
            
            if norma_g <= grad_tol:
                convergiu = True
                print(f"  Convergiu em {it} passos! ||grad|| = {norma_g:.4e}")
                break
                
            vel = vel * amortecimento - alpha * g
            vc += vel
            
        duracao = time.time() - t_inicio
        fval = energia(vc, segmentos)

        if verificar_minimo_degenerado(vc, faces) or possui_face_colinear(vc, faces):
            print(f"  Atenção: Configuração degenerada/colinear (f(x) = {fval:.6e}). Descartada.")
            continue
        
        # Classificação da solução (global convexo/não-convexo + autointerseção, ou local)
        if abs(fval) < 1e-6:
            tipo = "global"
            contador_globais += 1
            info_conv = verificar_convexidade(vc, faces)
            convexo = info_conv["is_convex"]
            faces_exp = info_conv["oriented_faces"]
            info_inter = verificar_autointersecao_faces(vc, faces_exp)
            tem_inter = info_inter["has_self_intersection"]
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if tem_inter:
                prefixo = "convexo" if convexo else "nao_convexo"
                nome_solucao = f"solucao_global_{prefixo}_intersecao_{contador_globais}"
                status = f">> MÍNIMO GLOBAL {'CONVEXO' if convexo else 'NÃO CONVEXO'} COM AUTOINTERSEÇÃO ({info_inter['intersection_count']}) <<"
            elif convexo:
                contador_globais_convexos += 1
                nome_solucao = f"solucao_global_convexo_{contador_globais_convexos}"
                status = ">> MÍNIMO GLOBAL CONVEXO SEM AUTOINTERSEÇÃO <<"
            else:
                contador_globais_nao_convexos += 1
                nome_solucao = f"solucao_global_nao_convexo_{contador_globais_nao_convexos}"
                status = ">> MÍNIMO GLOBAL NÃO CONVEXO SEM AUTOINTERSEÇÃO (DESCOBERTA) <<"
            print(f"  Resultado: {status} | Energia f(x) = {fval:.6e} | Tempo: {duracao:.2f}s")
            if not convexo:
                print(f"  Critérios: {'; '.join(info_conv['reasons'])}")
            
            # EXPORTAÇÃO AUTOMÁTICA EM PYTHONSCAD na subpasta oficial
            exportador_scad.exportar_se_minimo_global(nome_solido, nome_solucao, tipo, vc, faces_exp, fval, convexo=convexo, tem_autointersecao=tem_inter, timestamp=ts)
        else:
            tipo = "local"
            nome_solucao = f"solucao_local_{rep}"
            status = "-- MÍNIMO LOCAL --"
            print(f"  Resultado: {status} | Energia f(x) = {fval:.6e} | Tempo: {duracao:.2f}s")
        
        if fval < menor_energia:
            menor_energia = fval
            melhor_solucao = vc.copy()
            
    if melhor_solucao is not None:
        print("\\n" + "=" * 50)
        print(f"Renderizando visualização 3D da melhor configuração (f = {menor_energia:.6e})...")
        plotar_poliedro_3d(melhor_solucao, faces, titulo=f"{nome_solido} (Energia = {menor_energia:.2e})")

executar_otimizacao()
""")

notebook_data = {
    "cells": cells,
    "metadata": {
        "language_info": {
            "name": "python"
        }
    },
    "nbformat": 4,
    "nbformat_minor": 2
}

output_path = r"d:\Marcelo\Documents\IC com Colli\Otimizacao_Solidos_Johnson_Colab.ipynb"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(notebook_data, f, indent=2, ensure_ascii=False)

print(f"Notebook atualizado com PythonSCAD com sucesso em: {output_path}")
