import ast
from collections import defaultdict, deque


def edges(face):
    """Retorna as arestas orientadas da face"""
    e = []
    for i in range(len(face)):
        a = face[i]
        b = face[(i+1) % len(face)]
        e.append((a, b))
    return e


def shared_edge(f1, f2):
    """Retorna aresta compartilhada se existir"""
    e1 = edges(f1)
    e2 = edges(f2)

    for a, b in e1:
        if (a, b) in e2:
            return (a, b, True)
        if (b, a) in e2:
            return (a, b, False)
    return None


def corrigir_orientacao(faces, base=0):

    n = len(faces)
    visitado = [False]*n
    visitado[base] = True

    fila = deque([base])

    while fila:

        f = fila.popleft()

        for i in range(n):

            if visitado[i] or i == f:
                continue

            info = shared_edge(faces[f], faces[i])

            if info is None:
                continue

            a, b, mesma_orientacao = info

            if mesma_orientacao:
                print(f"Face {i} invertida (aresta {a}-{b})")
                faces[i] = list(reversed(faces[i]))

            visitado[i] = True
            fila.append(i)

    return faces


# =============================
# INTERFACE TERMINAL
# =============================

print("\nCole a lista de faces:")
texto = input("> ")

fim = texto.rfind("]]")
if fim != -1:
    texto = texto[:fim+2]

faces = ast.literal_eval(texto)

faces = ast.literal_eval(texto)

print("\nFaces lidas:")
for i,f in enumerate(faces):
    print(i, f)

print("\nEscolha o índice da face que está correta:")
base = int(input("> "))

faces_corrigidas = corrigir_orientacao(faces, base)

print("\nFaces corrigidas:\n")
print(faces_corrigidas)