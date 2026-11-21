# ==============================================================================
# PROJETO: Iniciação Científica - IC com Colli (IME-USP)
# PACOTE: verificadores
# MÓDULO: isomorfismo.py
# AUTOR: Marcelo & Orientação Prof. Eduardo Colli
# DESCRIÇÃO: 
#   Algoritmo para resolução de isomorfismo e congruência isométrica entre
#   poliedros via backtracking guiado por assinaturas locais de distâncias
#   (invariantes métricos locais) com tolerância numérica configurável.
# ==============================================================================

import numpy as np


def mapeamento_valido(A, B, p, i, j, tol=1e-4):
    """
    Verifica se mapear a linha 'i' de A para a linha 'j' de B
    mantém a consistência com os elementos já mapeados anteriormente.
    
    Parâmetros:
        A: Matriz de adjacência ou de distâncias mútuas do poliedro A.
        B: Matriz de adjacência ou de distâncias mútuas do poliedro B.
        p: Dicionário com os mapeamentos já consolidados {k: p[k]}.
        i: Índice do vértice candidato em A.
        j: Índice do vértice candidato em B.
        tol: Tolerância numérica para igualdade em ponto flutuante.
    """
    for k in p:
        # Se o vizinho k já foi mapeado para p[k]
        # O peso/conexão entre i e k em A deve ser igual ao de j e p[k] em B
        if abs(A[i][k] - B[j][p[k]]) > tol:
            return False
    return True


def resolver_isomorfismo(A, B, tol=1e-4, decimais=4):
    """
    Determina se duas matrizes A e B (por exemplo, de distâncias mútuas)
    são isomorfas, encontrando a permutação p que mapeia o vértice i de A
    no vértice p[i] de B.
    
    Parâmetros:
        A: Matriz n x n do sólido A.
        B: Matriz n x n do sólido B.
        tol: Tolerância absoluta para verificação de consistência métrica.
        decimais: Casas decimais para discretização das assinaturas locais.
                  Se None, utiliza o valor exato.
                  
    Retorna:
        list: Permutação p onde p[i] é o vértice em B correspondente a i em A.
        None: Se as configurações não forem isomorfas.
    """
    n = len(A)
    if len(B) != n:
        return None

    # 1. Gerar assinaturas das linhas (ordenando os elementos de cada linha)
    if decimais is not None:
        assinaturas_A = {i: tuple(sorted(round(float(val), decimais) for val in A[i])) for i in range(n)}
        assinaturas_B = {j: tuple(sorted(round(float(val), decimais) for val in B[j])) for j in range(n)}
    else:
        assinaturas_A = {i: tuple(sorted(A[i])) for i in range(n)}
        assinaturas_B = {j: tuple(sorted(B[j])) for j in range(n)}

    # Verificar se o conjunto total de assinaturas bate (invariante global)
    if sorted(assinaturas_A.values()) != sorted(assinaturas_B.values()):
        return None  # Invariante global falhou

    # 2. Mapeamento de busca (Backtracking)
    p = {}           # Guarda o mapeamento: i de A -> j de B
    usados_B = set() # Guarda as linhas de B que já foram escolhidas

    def backtrack(i):
        if i == n:
            return True  # Todos os elementos foram mapeados com sucesso

        sig_A = assinaturas_A[i]

        # Tenta mapear a linha 'i' de A para alguma linha 'j' de B
        for j in range(n):
            if j not in usados_B and assinaturas_B[j] == sig_A:
                # Verifica se a consistência da matriz é mantida com o que já foi mapeado
                if mapeamento_valido(A, B, p, i, j, tol=tol):
                    p[i] = j
                    usados_B.add(j)

                    if backtrack(i + 1):
                        return True

                    # Desfaz a escolha (Backtrack)
                    del p[i]
                    usados_B.remove(j)
        return False

    if backtrack(0):
        # Retorna a permutação como uma lista onde o índice é 'i' e o valor é 'p(i)'
        return [p[i] for i in range(n)]
    return None


def construir_matriz_distancias(vertices):
    """
    Calcula a matriz de distâncias euclidianas mútuas D (n x n)
    a partir das coordenadas 3D dos vértices.
    """
    V = np.asarray(vertices, dtype=float)
    diff = V[:, np.newaxis, :] - V[np.newaxis, :, :]
    return np.linalg.norm(diff, axis=-1)


def verificar_isomorfismo_solidos(vertices_A, vertices_B, tol=1e-4, decimais=4):
    """
    Recebe as coordenadas dos vértices de dois sólidos no R^3 (vertices_A e vertices_B)
    e testa se representam poliedros isometricamente idênticos.
    
    Retorna:
        list: Permutação [p[0], p[1], ..., p[n-1]] se forem congruentes/isométricos.
        None: Se os sólidos forem geometricamente distintos.
    """
    if len(vertices_A) != len(vertices_B):
        return None
    A = construir_matriz_distancias(vertices_A)
    B = construir_matriz_distancias(vertices_B)
    return resolver_isomorfismo(A, B, tol=tol, decimais=decimais)
