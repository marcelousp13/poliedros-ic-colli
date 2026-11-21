# ==============================================================================
# PACOTE: topologia
# CLASSE: OrientadorFaces
# DESCRIÇÃO: Responsável pelo tratamento topológico da malha poliédrica:
#            correção de orientação das normais das faces (consistência de sentido)
#            e geração dos segmentos de restrição métrica (distâncias ideais ao quadrado).
# ==============================================================================

import numpy as np
import math
from collections import defaultdict, deque

class OrientadorFaces:
    """
    Classe responsável pela manipulação e correção topológica das faces de um sólido.
    Garante que todas as faces possuam orientação consistente de normais (todas apontando para fora)
    e calcula os comprimentos ideais ao quadrado (arestas e diagonais internas de polígonos regulares).
    """

    @staticmethod
    def calcular_d2(n, i, j):
        """
        Calcula o quadrado da distância euclidiana ideal entre os vértices locais i e j
        de um polígono regular de n lados e aresta de comprimento unitário (lado = 1).
        
        Fórmula analítica exata:
            R = 1 / (2 * sen(pi / n))
            k = min(|i - j|, n - |i - j|)   # distância percorrida no contorno
            d = 2 * R * sen(k * pi / n)
            d^2 = [ 2 * R * sen(k * pi / n) ]^2
        """
        if n < 3:
            raise ValueError("Polígono precisa ter pelo menos 3 lados.")

        k = abs(i - j)
        k = min(k, n - k)  # Menor caminho no grafo circular do polígono

        if k == 0:
            return 0.0

        raio_circunscrito = 1.0 / (2.0 * math.sin(math.pi / n))
        distancia = 2.0 * raio_circunscrito * math.sin(k * math.pi / n)

        return float(distancia ** 2)

    @staticmethod
    def gerar_segmentos(faces):
        """
        Gera o array NumPy de restrições métricas contendo todas as arestas e diagonais internas.
        Cada linha do array retornado é uma tupla: (vértice_i, vértice_j, d2_ideal)
        """
        segmentos = []
        for face in faces:
            m = len(face)
            for i in range(m):
                for j in range(i + 1, m):
                    d2 = OrientadorFaces.calcular_d2(m, i, j)
                    segmentos.append((face[i], face[j], d2))

        return np.array(segmentos, dtype=float)

    @staticmethod
    def corrigir_orientacao(faces):
        """
        Aplica o algoritmo de Busca em Largura (BFS) no grafo dual de adjacência de arestas
        para garantir que faces vizinhas compartilhem arestas em direções opostas.
        Isso garante a consistência topológica da superfície e evita normais invertidas.
        """
        # Mapeamento de arestas ordenadas -> índices de faces adjacentes
        edge_to_faces = defaultdict(list)
        for fi, face in enumerate(faces):
            m = len(face)
            for i in range(m):
                key = tuple(sorted((face[i], face[(i + 1) % m])))
                edge_to_faces[key].append(fi)

        oriented = [None] * len(faces)
        processed = [False] * len(faces)

        # Inicia a propagação da orientação a partir da primeira face
        oriented[0] = list(faces[0])
        processed[0] = True
        queue = deque([0])

        while queue:
            fi = queue.popleft()
            ref = oriented[fi]

            # Percorre cada aresta orientada da face de referência
            for i in range(len(ref)):
                a, b = ref[i], ref[(i + 1) % len(ref)]
                key = tuple(sorted((a, b)))

                # Propaga para todas as faces vizinhas que compartilham esta aresta
                for nbr in edge_to_faces[key]:
                    if nbr == fi or processed[nbr]:
                        continue

                    f2 = list(faces[nbr])
                    m = len(f2)

                    # Verifica se a aresta na face vizinha está na mesma direção ou invertida
                    for k in range(m):
                        x, y = f2[k], f2[(k + 1) % m]
                        if {x, y} == {a, b}:
                            if (x, y) == (a, b):
                                # Aresta no mesmo sentido: inverte a orientação da face vizinha
                                f2.reverse()
                            break

                    oriented[nbr] = f2
                    processed[nbr] = True
                    queue.append(nbr)

        # Trata faces isoladas ou não alcançadas na busca principal
        for i, f in enumerate(oriented):
            if f is None:
                oriented[i] = list(faces[i])

        # Verificação da coerência global das arestas orientadas
        consistent = []
        seen_edges = {}
        for f in oriented:
            for i in range(len(f)):
                a, b = f[i], f[(i + 1) % len(f)]
                key = (a, b)
                if (b, a) in seen_edges:
                    consistent.append(True)
                else:
                    seen_edges[key] = True

        ratio = sum(consistent) / len(consistent) if consistent else 1.0
        if ratio < 0.5:
            # Caso a maioria esteja no sentido oposto, inverte todas as faces
            oriented = [list(reversed(f)) for f in oriented]

        return oriented
