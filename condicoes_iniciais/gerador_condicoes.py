# Importação da biblioteca NumPy para operações numéricas e vetoriais
import numpy as np

# Importação da biblioteca NetworkX para criação e manipulação da estrutura de grafos
import networkx as nx

# Importação de funções matemáticas nativas
import math

# Importação do módulo de combinações para iteração sobre pares de vértices
from itertools import combinations

# Definição da classe responsável por gerar e gerenciar as condições iniciais dos vértices
class GeradorCondicoesIniciais:
    # Construtor da classe: recebe as faces orientadas do poliedro e o número total de vértices
    def __init__(self, faces, num_vertices=None, segmentos=None):
        # Armazena a lista de faces do poliedro (cada face é uma lista de índices de vértices)
        self.faces = faces
        
        # Se o número de vértices não foi informado explicitamente, calcula o índice máximo presente nas faces + 1
        if num_vertices is None:
            # Obtém o maior índice de vértice em todas as faces e soma 1
            self.num_vertices = max(max(face) for face in faces) + 1
        else:
            # Atribui o número de vértices passado como parâmetro
            self.num_vertices = num_vertices
            
        # Segmentos contendo (i, j, d2_ideal) se já pré-calculados
        self.segmentos = segmentos

        # Constrói o grafo NetworkX a partir das arestas extraídas das faces
        self.grafo = self._construir_grafo()
        
        # Extrai o conjunto único de todas as arestas do poliedro (pares não ordenados)
        self.arestas = self._extrair_arestas()
        
        # Inicializa a variável para armazenar a configuração base da projeção esferográfica
        self._posicoes_base_esferografica = None

    # Método interno para construir um grafo planar da topologia do sólido
    def _construir_grafo(self):
        # Cria uma instância de grafo não-direcionado do NetworkX
        G = nx.Graph()
        
        # Adiciona todos os vértices de 0 até num_vertices - 1 ao grafo
        G.add_nodes_from(range(self.num_vertices))
        
        # Itera sobre cada face do sólido para extrair suas arestas de contorno
        for face in self.faces:
            # Determina a quantidade de vértices da face
            m = len(face)
            # Percorre os vértices da face conectando cada vértice ao próximo
            for i in range(m):
                # Vértice de origem da aresta
                u = face[i]
                # Vértice de destino da aresta (com operador módulo para fechar o ciclo)
                v = face[(i + 1) % m]
                # Adiciona a aresta entre os vértices u e v ao grafo
                G.add_edge(u, v)
                
        # Retorna o grafo NetworkX construído
        return G

    # Método interno para extrair a lista de arestas únicas (sem repetição de sentido)
    def _extrair_arestas(self):
        # Cria um conjunto para armazenar arestas únicas ordenadas
        arestas_set = set()
        # Percorre cada face da lista de faces
        for face in self.faces:
            # Obtém o número de vértices da face
            m = len(face)
            # Itera pelos vértices da face
            for i in range(m):
                # Vértice atual
                u = face[i]
                # Próximo vértice adjacente
                v = face[(i + 1) % m]
                # Insere a tupla ordenada no conjunto para garantir unicidade
                arestas_set.add(tuple(sorted((u, v))))
        # Converte o conjunto em uma lista de tuplas de arestas
        return list(arestas_set)

    # -------------------------------------------------------------------------------------------------
    # CÁLCULO ANALÍTICO EXATO DO LADO L DO HIPERCUBO VIA TEOREMA 1 (Demonstração Marcelo & Thomas / Colli):
    # Teorema: Se |x_k - x_l| >= L para algum par de vértices, então \nabla F \neq 0.
    # Da dilatação radial \Gamma(t) = F((1+t)x):
    #   \dot{\Gamma}(0) = \sum 4 d_ij^2 (d_ij^2 - \delta_ij^2).
    # O valor mais negativo possível de cada termo 4 W^2(W^2 - \delta^2) ocorre em W = \delta / \sqrt{2},
    # resultando no mínimo - \delta^4.
    # Definindo \Delta = \sum_{faces} \sum_{i,j} \delta(i,j)^4.
    # Pela desigualdade triangular, no caminho de tamanho no máximo N (diâmetro do grafo),
    # existe pelo menos uma aresta com d_ij >= L / N.
    # Como essa aresta pertence a 2 faces, sua contribuição positiva na derivada radial é:
    #   2 * 4 * (L/N)^2 * ((L/N)^2 - 1) = 8 u (u - 1), onde u = (L/N)^2.
    # Para garantir \dot{\Gamma}(0) > 0, impõe-se: 8 u (u - 1) > \Delta.
    # Resolvendo a equação do 2º grau: 8 u^2 - 8 u - \Delta = 0:
    #   u = (1 + \sqrt{1 + \Delta / 2}) / 2
    # Logo: L = N * \sqrt{u}
    # -------------------------------------------------------------------------------------------------
    def calcular_lado_L_teorema(self, segmentos=None):
        # Obtém o diâmetro N do grafo (maior distância de menor caminho entre dois vértices)
        if nx.is_connected(self.grafo):
            N = nx.diameter(self.grafo)
        else:
            N = self.num_vertices
            
        # Usa segmentos passados por parâmetro ou os armazenados na instância
        segs = segmentos if segmentos is not None else self.segmentos
        
        # Se os segmentos estão disponíveis, calcula Delta = soma dos \delta(i, j)^4
        if segs is not None:
            # Como cada segmento tem d2_valor = \delta^2, temos \delta^4 = (d2_valor)^2
            delta_quarta = np.sum(segs[:, 2] ** 2)
        else:
            # Caso não tenha segmentos, estima pela quantidade de arestas (cada aresta regular tem delta = 1)
            # Cada aresta pertence a 2 faces, logo contribui com 2 * 1^4 = 2
            delta_quarta = len(self.arestas) * 2.0
            
        # Delta total da soma de todas as faces
        Delta = float(delta_quarta)
        
        # Raiz da equação 8 u^2 - 8 u - Delta = 0 => u^2 - u - Delta/8 = 0
        # u = (1 + sqrt(1 + 4 * (Delta / 8))) / 2 = (1 + sqrt(1 + Delta / 2)) / 2
        u = (1.0 + math.sqrt(1.0 + Delta / 2.0)) / 2.0
        
        # Como u = (L / N)^2, temos L = N * sqrt(u)
        L = N * math.sqrt(u)
        
        # Retorna o valor de L com 4 casas decimais
        return round(float(L), 4)

    # Método 1: Distribuição aleatória uniforme dos vértices dentro de um hipercubo [-L, L]^3
    def gerar_hipercubo(self, L=None, segmentos=None):
        # Se L não foi fornecido pelo usuário, calcula via Teorema 1
        if L is None:
            L = self.calcular_lado_L_teorema(segmentos=segmentos)
            
        # Sorteia coordenadas aleatórias uniformemente no intervalo [-L, L] para cada vértice em R^3
        coordenadas = np.random.uniform(-L, L, (self.num_vertices, 3))
        
        # Retorna o array NumPy de dimensões (num_vertices, 3)
        return coordenadas

    # Método 2: Projeção Esferográfica com tratamento completo proposto pelo Prof. Eduardo Colli
    def gerar_projecao_esferografica_tratada(self, escala_plano=5.0):
        # Verifica se o grafo do poliedro é planar antes de calcular o layout
        is_planar, _ = nx.check_planarity(self.grafo)
        
        # Se o grafo for planar, calcula o embedding planar
        if is_planar:
            # Obtém coordenadas 2D dos vértices no plano via planar_layout
            pos2d = nx.planar_layout(self.grafo)
        else:
            # Caso não seja estritamente planar, usa layout force-directed (spring_layout) como fallback
            pos2d = nx.spring_layout(self.grafo, seed=42)
            
        # Converte as coordenadas 2D do dicionário para um array NumPy ordenado pelos índices dos vértices
        coords_2d = np.array([pos2d[i] for i in range(self.num_vertices)], dtype=float)
        
        # -------------------------------------------------------------------------------------------------
        # Tratamento sugerido pelo Prof. Eduardo Colli (Item 2.3 do projeto):
        # (a) Calcular a média (x, y) das coordenadas dos vértices do grafo planar e subtrair de todas (centralizar)
        # -------------------------------------------------------------------------------------------------
        media_xy = np.mean(coords_2d, axis=0)
        # Subtrai o vetor médio para centralizar a distribuição na origem (0, 0)
        coords_centralizadas = coords_2d - media_xy
        
        # -------------------------------------------------------------------------------------------------
        # (b) Achar o vértice mais distante, calcular sua norma, dividir todos por essa norma e multiplicar por 5
        # Isso faz com que os pontos fiquem bem espalhados e não se acumulem excessivamente no polo norte da esfera
        # -------------------------------------------------------------------------------------------------
        normas_vertices = np.linalg.norm(coords_centralizadas, axis=1)
        # Encontra a norma máxima (distância do vértice mais distante ao centro)
        norma_maxima = np.max(normas_vertices)
        
        # Evita divisão por zero caso todos os pontos estejam na origem
        if norma_maxima > 1e-12:
            # Normaliza e reescala pelo fator especificado (padrão 5.0)
            coords_reescaladas_2d = (coords_centralizadas / norma_maxima) * escala_plano
        else:
            # Mantém as coordenadas caso a norma seja nula
            coords_reescaladas_2d = coords_centralizadas
            
        # -------------------------------------------------------------------------------------------------
        # (c) Fazer a projeção estereográfica inversa para a superfície da esfera unitária S^2
        # Fórmula: x = 2u/(u^2 + w^2 + 1), y = 2w/(u^2 + w^2 + 1), z = (u^2 + w^2 - 1)/(u^2 + w^2 + 1)
        # -------------------------------------------------------------------------------------------------
        # Array para armazenar as posições 3D na esfera unitária
        posicoes_esfera = np.zeros((self.num_vertices, 3), dtype=float)
        
        # Percorre cada vértice calculando suas coordenadas na esfera unitária
        for i in range(self.num_vertices):
            # Coordenada horizontal u
            u = coords_reescaladas_2d[i, 0]
            # Coordenada vertical w
            w = coords_reescaladas_2d[i, 1]
            # Denominador d = u^2 + w^2 + 1
            d = u * u + w * w + 1.0
            
            # Coordenada X na esfera
            posicoes_esfera[i, 0] = 2.0 * u / d
            # Coordenada Y na esfera
            posicoes_esfera[i, 1] = 2.0 * w / d
            # Coordenada Z na esfera
            posicoes_esfera[i, 2] = (u * u + w * w - 1.0) / d
            
        # -------------------------------------------------------------------------------------------------
        # (d) Reescalonamento para compatibilizar o tamanho das arestas com aresta de tamanho 1:
        # Calcula as distâncias euclidianas 3D de todas as arestas e obtém a média.
        # Divide todas as coordenadas de todos os vértices por essa média para que a aresta média seja 1.
        # -------------------------------------------------------------------------------------------------
        comprimentos_arestas = []
        # Itera sobre todas as arestas únicas do poliedro
        for (u_idx, v_idx) in self.arestas:
            # Calcula a distância euclidiana 3D entre os vértices da aresta
            dist_aresta = np.linalg.norm(posicoes_esfera[u_idx] - posicoes_esfera[v_idx])
            # Armazena na lista de comprimentos
            comprimentos_arestas.append(dist_aresta)
            
        # Calcula o comprimento médio das arestas
        comprimento_medio = np.mean(comprimentos_arestas)
        
        # Divide todas as posições 3D pelo comprimento médio das arestas
        if comprimento_medio > 1e-12:
            posicoes_finais_3d = posicoes_esfera / comprimento_medio
        else:
            posicoes_finais_3d = posicoes_esfera
            
        # Armazena internamente a configuração base esferográfica tratada
        self._posicoes_base_esferografica = posicoes_finais_3d.copy()
        
        # Retorna a matriz de vértices (num_vertices, 3)
        return posicoes_finais_3d

    # Método de Perturbação Cúbica Local: aplica perturbação uniforme em [-epsilon, epsilon]^3 em cada vértice
    def aplicar_perturbacao_cubica(self, posicoes_base=None, epsilon=0.1):
        # Se nenhuma posição base foi fornecida, utiliza a base esferográfica gerada previamente
        if posicoes_base is None:
            if self._posicoes_base_esferografica is None:
                # Se ainda não foi gerada, gera agora
                posicoes_base = self.gerar_projecao_esferografica_tratada()
            else:
                posicoes_base = self._posicoes_base_esferografica
                
        # Sorteia uma perturbação aleatória independente em [-epsilon, epsilon] para cada coordenada de cada vértice
        perturbacao = np.random.uniform(-epsilon, epsilon, posicoes_base.shape)
        
        # Soma a perturbação às posições base: vk = vk + (e_x, e_y, e_z)
        posicoes_perturbadas = posicoes_base + perturbacao
        
        # Retorna as novas coordenadas perturbadas
        return posicoes_perturbadas
