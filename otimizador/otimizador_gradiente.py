# ==============================================================================
# PACOTE: otimizador
# CLASSE: OtimizadorGradiente
# DESCRIÇÃO: Implementação rigorosa do método de otimização por Gradiente com
#            Amortecimento de Velocidade (Velocity Gradient / Sistema Dinâmico Dissipativo)
#            e cálculo das propriedades energéticas e espectrais (Hessiana / Autovalores).
# ==============================================================================

import time
import math
import numpy as np

class OtimizadorGradiente:
    """
    Classe responsável pelo processo de relaxação e convergência geométrica dos sólidos.
    Modela o poliedro como uma rede de molas não-lineares sujeitas a um potencial elástico
    e integra as equações do movimento sob atrito numérico (amortecimento) até o equilíbrio mecânico.
    """

    def __init__(self, alpha=0.01, amortecimento=0.9, grad_tol=1e-14, max_iter=1000000, max_step=0.1):
        """
        Inicializa o otimizador com os parâmetros numéricos padrão da pesquisa:
            alpha (float): Passo de integração / taxa de aprendizado do gradiente (0.01)
            amortecimento (float): Coeficiente de persistência da velocidade (0.9)
            grad_tol (float): Norma mínima do gradiente para critério de parada (1e-14)
            max_iter (int): Número máximo de iterações permitidas (1.000.000)
            max_step (float): Deslocamento máximo por passo em cada aresta (0.1)
        """
        self.alpha = float(alpha)
        self.amortecimento = float(amortecimento)
        self.grad_tol = float(grad_tol)
        self.max_iter = int(max_iter)
        self.max_step = float(max_step)

    @staticmethod
    def calcular_energia(vc, segmentos):
        """
        Calcula o valor da função objetivo de energia elástica potencial do sólido:
            E(V) = 0.5 * sum [ ( ||v_i - v_j||^2 - d_{ij}^2 )^2 ]
        """
        diffs = []
        for (i, j, d2) in segmentos:
            vi, vj = vc[int(i)], vc[int(j)]
            diffs.append((np.linalg.norm(vi - vj) ** 2 - d2) ** 2)
        return 0.5 * sum(diffs)

    @staticmethod
    def calcular_gradiente(vc, segmentos, max_step=None):
        """
        Calcula a força restauradora (vetor gradiente analítico) atuando em cada vértice:
            grad[i] += 2 * ( ||v_i - v_j|| - d_{ij} ) * ( (v_i - v_j) / ||v_i - v_j|| )
        """
        grad = np.zeros_like(vc)
        for seg in segmentos:
            i, j, d2 = int(seg[0]), int(seg[1]), seg[2]
            diff = vc[i] - vc[j]
            dist = np.linalg.norm(diff)
            if dist == 0.0:
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

    def calcular_hessiana(self, vc, segmentos, eps=1e-6):
        """
        Calcula a matriz Hessiana (n x n, onde n = 3 * num_vertices) via diferenças finitas:
            H[:, k] = (grad(vc + eps * e_k) - grad(vc)) / eps
        """
        n = vc.size
        H = np.zeros((n, n))
        g0 = self.calcular_gradiente(vc, segmentos).reshape(-1)

        for k in range(n):
            vc_pert = vc.copy().reshape(-1)
            vc_pert[k] += eps
            vc_pert = vc_pert.reshape(vc.shape)

            g1 = self.calcular_gradiente(vc_pert, segmentos).reshape(-1)
            H[:, k] = (g1 - g0) / eps

        return H

    def otimizar(self, vc_inicial, segmentos, imprimir_passos=True, intervalo_impressao=10000):
        """
        Executa a integração temporal do gradiente com velocidade amortecida:
            v_{t+1} = beta * v_t - alpha * grad(x_t)
            x_{t+1} = x_t + v_{t+1}
        
        Retorna um dicionário contendo os resultados completos da otimização:
            - vc: matriz final de coordenadas (N, 3)
            - converged: booleano indicando convergência estrita (||grad|| <= tol)
            - norm_g: norma euclidiana final do gradiente
            - it: número de passos executados
            - elapsed_time: tempo de execução em segundos
            - fval: energia residual final
            - autovalores: autovalores da matriz Hessiana
        """
        vc = np.array(vc_inicial, dtype=float, copy=True)
        vel = np.zeros_like(vc)
        converged = False
        norm_g = 0.0
        start_time = time.time()

        for it in range(1, self.max_iter + 1):
            g = self.calcular_gradiente(vc, segmentos, max_step=self.max_step)
            norm_g = float(np.linalg.norm(g))

            if imprimir_passos and it % intervalo_impressao == 0:
                print(f"  Passo {it:6d} | ||grad|| = {norm_g:.6e}")

            if norm_g <= self.grad_tol:
                converged = True
                if imprimir_passos:
                    print(f"  Convergiu em {it} iterações! ||grad|| = {norm_g:.6e}")
                break

            vel = vel * self.amortecimento - self.alpha * g
            vc += vel

        elapsed_time = time.time() - start_time
        fval = self.calcular_energia(vc, segmentos)
        H = self.calcular_hessiana(vc, segmentos)
        autovalores = np.linalg.eigvalsh(H)

        return {
            "vc": vc,
            "converged": converged,
            "norm_g": norm_g,
            "it": it,
            "elapsed_time": elapsed_time,
            "fval": fval,
            "autovalores": autovalores
        }
