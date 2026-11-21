# Importação de módulos do sistema operacional para gerenciamento de caminhos e diretórios
import os
# Importação do módulo de medição de tempo para medir duração da otimização
import time
# Importação da biblioteca NumPy para manipulação de matrizes e álgebra linear
import numpy as np
# Importação do módulo json para gravação dos resultados em formato estruturado
import json
# Importação de ferramentas de combinação para testes de geometria
from itertools import combinations
# Importação do módulo datetime para timestamp dos arquivos salvos
from datetime import datetime

# Importação dos módulos do núcleo existente (pasta gerador_solidos_extracted/gerador_solidos/core)
# Garantimos a adição do diretório ao sys.path para importação limpa
import sys
# Obtém o diretório do script atual
script_dir = os.path.dirname(os.path.abspath(__file__))
# Adiciona a pasta do gerador_solidos ao sys.path caso esteja na pasta extraída
caminho_core_pkg = os.path.join(script_dir, "gerador_solidos_extracted", "gerador_solidos")
if caminho_core_pkg not in sys.path:
    sys.path.insert(0, caminho_core_pkg)

# Importação das funções matemáticas e topológicas do módulo core
from core.loader import carregar_solidos
from core.orientacao import corrigir_orientacao_faces
from core.geometria import gradiente, gerar_segmentos
from core.distancias import calcular_distancias, salvar_solido
from core.conferindo import verificar_minimo_degenerado
from core.diedrais import calcular_angulos_diedrais

# Importação da nova classe criada para o gerenciamento de condições iniciais
from condicoes_iniciais.gerador_condicoes import GeradorCondicoesIniciais

# Importação da classe de exportação para PythonSCAD (mínimos globais)
from exportadores.pythonscad_exportador import ExportadorPythonSCAD

# Definição da função de energia elástica (função objetivo teórica do problema)
def energia(vc, segmentos):
    # Lista para acumular as diferenças quadráticas de cada segmento
    diffs = []
    # Itera sobre cada segmento (vértice i, vértice j, distância ideal ao quadrado d2)
    for (i, j, d2) in segmentos:
        # Obtém as coordenadas 3D dos vértices i e j
        vi, vj = vc[int(i)], vc[int(j)]
        # Calcula o erro quadrático da mola: (||vi - vj||^2 - d_ij^2)^2
        diffs.append((np.linalg.norm(vi - vj) ** 2 - d2) ** 2)
    # Retorna o valor de energia multiplicado pelo fator 0.5
    return 0.5 * sum(diffs)

# Definição do cálculo da matriz Hessiana via diferenças finitas centrais do gradiente
def hessiana(vc, segmentos, eps=1e-6):
    # Número total de variáveis escalares (3 * número de vértices)
    n = vc.size
    # Inicialização da matriz quadrada Hessiana de dimensões (n, n)
    H = np.zeros((n, n))
    # Calcula o gradiente nas posições atuais e achata para vetor 1D
    g0 = gradiente(vc, segmentos).reshape(-1)
    # Percorre cada uma das n coordenadas
    for k in range(n):
        # Cria uma cópia do vetor de vértices achatado
        vc_pert = vc.copy().reshape(-1)
        # Adiciona a perturbação infinitesimal eps na k-ésima coordenada
        vc_pert[k] += eps
        # Redimensiona de volta para a matriz (N, 3)
        vc_pert = vc_pert.reshape(vc.shape)
        # Calcula o novo gradiente perturbado
        g1 = gradiente(vc_pert, segmentos).reshape(-1)
        # Diferença finita dividida por eps preenche a k-ésima coluna da Hessiana
        H[:, k] = (g1 - g0) / eps
    # Retorna a matriz Hessiana calculada
    return H

# Função para verificar se 3 pontos no espaço 3D são colineares via produto vetorial
def pontos_colineares(p1, p2, p3, epsilon=1e-5):
    # Calcula o produto vetorial entre os vetores (p2 - p1) e (p3 - p1)
    produto_vetorial = np.cross(p2 - p1, p3 - p1)
    # Se a norma for menor ou igual a epsilon, os pontos estão sobre a mesma reta
    return np.linalg.norm(produto_vetorial) <= epsilon

# Função para testar se alguma face possui 3 vértices colineares (indicativo de degeneração)
def possui_face_colinear(vc, faces, epsilon=1e-5):
    # Percorre cada face do poliedro
    for face in faces:
        # Testa todas as combinações de 3 vértices pertencentes à mesma face
        for i, j, k in combinations(face, 3):
            # Se encontrar colinearidade, reporta e retorna True
            if pontos_colineares(vc[i], vc[j], vc[k], epsilon):
                print(f"Colinearidade detectada na face {face}: vértices ({i}, {j}, {k})")
                return True
    # Se nenhuma combinação for colinear, retorna False
    return False

# Função para salvar a solução numérica encontrada em disco (.json e .txt)
def salvar_solucao(nome_solucao, tipo, nome_solido, vc, distancias, angulos, autovalores, fval):
    # Determina a subpasta ("globais" ou "locais")
    base = "globais" if tipo == "global" else "locais"
    # Diretório base de saída dentro da pasta "solidos"
    solido_dir = os.path.join(script_dir, "solidos", nome_solido, base)
    # Cria os diretórios necessários recursivamente
    os.makedirs(solido_dir, exist_ok=True)
    # Gera timestamp formatado para nome único de arquivo
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    # Nome base do arquivo de saída
    filename = f"{nome_solucao}_{timestamp}"
    # Caminho completo do arquivo JSON
    json_path = os.path.join(solido_dir, filename + ".json")
    # Caminho completo do arquivo TXT
    txt_path = os.path.join(solido_dir, filename + ".txt")

    # Dicionário contendo todos os dados calculados da configuração
    dados = {
        "nome": nome_solido,
        "tipo": tipo,
        "fval": fval,
        "vc": vc.tolist(),
        "distancias": distancias.tolist() if hasattr(distancias, "tolist") else list(distancias),
        "angulos_diedrais": angulos.tolist() if hasattr(angulos, "tolist") else list(angulos),
        "autovalores": autovalores.tolist() if hasattr(autovalores, "tolist") else list(autovalores),
        "timestamp": datetime.now().isoformat()
    }

    # Gravação do arquivo JSON formatado
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)

    # Gravação do arquivo TXT detalhado para conferência visual
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"Solução: {nome_solucao}\n")
        f.write(f"Tipo: {tipo}\n")
        f.write(f"Valor da função (fval): {fval:.6e}\n")
        f.write(f"Autovalores: {autovalores.tolist() if hasattr(autovalores, 'tolist') else autovalores}\n")
        f.write("\n--- Distâncias Mútuas ---\n")
        for d in (distancias.tolist() if hasattr(distancias, "tolist") else distancias):
            f.write(str(d) + "\n")
        f.write("\n--- Ângulos Diedrais ---\n")
        for a in angulos:
            f.write(f"{a}\n")
        f.write("\n--- Coordenadas dos Vértices (vc) ---\n")
        for v in (vc.tolist() if hasattr(vc, "tolist") else vc):
            f.write(str(v) + "\n")

    # Imprime mensagem de confirmação do salvamento
    print(f"Solução gravada em:\n - {json_path}\n - {txt_path}")

# Função principal de execução interativa com comandos de escolha do usuário
def main():
    # Caminho do arquivo contendo as definições combinatórias das faces
    faces_path = os.path.join(script_dir, 'faces.txt')
    # Carrega o dicionário de sólidos disponíveis
    solidos = carregar_solidos(faces_path)

    # Solicita a quantidade de sólidos a serem processados na sessão
    while True:
        try:
            qtd_solidos = int(input("\nQuantos sólidos deseja rodar? "))
            if qtd_solidos > 0:
                break
            print("Digite um número inteiro positivo maior que zero.")
        except ValueError:
            print("Entrada inválida! Digite um número inteiro.")

    # Solicita a quantidade de repetições/amostras para cada sólido
    while True:
        m_input = input("Qual o tamanho da amostra de iterações? (Enter = ilimitado): ").strip()
        try:
            m = None if m_input == "" else int(m_input)
            break
        except ValueError:
            print("Entrada inválida! Digite um número inteiro.")

    # Lê os nomes dos sólidos escolhidos pelo usuário
    nomes_solidos = []
    for i in range(qtd_solidos):
        while True:
            nome = input(f"Digite o nome do sólido {i+1} (ex: J1, J86, Cube, Icosahedron): ").strip()
            if nome in solidos:
                nomes_solidos.append(nome)
                break
            print(f"Sólido '{nome}' não encontrado em faces.txt. Tente novamente.")

    # -------------------------------------------------------------------------------------------------
    # Menu interativo para escolha do método de coordenadas iniciais (Item 2.1 solicitado)
    # -------------------------------------------------------------------------------------------------
    print("\n" + "-" * 60)
    print("MÉTODO DE COORDENADAS INICIAIS:")
    print(" 1. Hipercubo de tamanho L")
    print(" 2. Projeção Esferográfica")
    print("-" * 60)
    while True:
        opcao_inicializacao = input("Qual método de coordenadas iniciais você deseja? (1 ou 2): ").strip()
        if opcao_inicializacao in ["1", "2"]:
            break
        print("Opção inválida! Escolha 1 para Hipercubo ou 2 para Projeção Esferográfica.")

    # Parâmetros numéricos do otimizador Velocity Gradient
    alpha = 0.01             # Taxa de aprendizado / força do gradiente
    grad_tol = 1e-14         # Tolerância da norma do gradiente para convergência
    max_iter = 1000000       # Número máximo de iterações do gradiente
    max_step = 0.1           # Limite máximo de deslocamento por passo para evitar explosões
    amortecimento = 0.9      # Fator de amortecimento da velocidade (atrito numérico)
    epsilon_perturbacao = 0.1 # Tamanho L do cubo de perturbação para projeção esferográfica (Item 2.2)

    # Instancia o exportador de PythonSCAD para geração de arquivos 3D dos mínimos globais
    exportador_scad = ExportadorPythonSCAD(fator_escala=20.0, pasta_base=os.path.join(script_dir, "solidos"))

    # Processa sequencialmente cada sólido da lista
    for nome in nomes_solidos:
        print("\n" + "=" * 75)
        print(f"INICIANDO PROCESSAMENTO DO SÓLIDO: {nome}")
        print("=" * 75)

        # Extrai as faces brutas e o número de vértices do arquivo
        faces_brutas, n_vertices_info = solidos[nome]
        # Aplica a correção de orientação topológica das normais das faces
        faces = corrigir_orientacao_faces(faces_brutas)
        # Gera a lista de segmentos com distâncias ideais ao quadrado
        segmentos = gerar_segmentos(faces)
        # Calcula o número total de vértices
        num_vertices = int(segmentos[:, :2].max()) + 1

        # Instancia a classe de Condições Iniciais dedicada
        gerador_ci = GeradorCondicoesIniciais(faces, num_vertices=num_vertices, segmentos=segmentos)
        
        # Calcula o valor exato de L para o hipercubo topológico via Teorema 1 (demonstração do LaTeX)
        L_topologico = gerador_ci.calcular_lado_L_teorema(segmentos=segmentos)
        print(f"Informações topológicas: {num_vertices} vértices, {len(faces)} faces.")
        print(f"Lado L exato derivado pelo Teorema 1 para hipercubo [-L, L]: L = {L_topologico}")

        # Se a opção escolhida for 2 (Projeção Esferográfica), gera a configuração base tratada
        if opcao_inicializacao == "2":
            print("Gerando projeção esferográfica base com tratamento do grafo e arestas unitárias...")
            vc_base_esferica = gerador_ci.gerar_projecao_esferografica_tratada(escala_plano=5.0)

        # Contadores de controle estatístico
        rep = 0
        encontrados = 0
        contador_globais = 0
        encontrou_global_na_primeira = False

        try:
            # Loop de execuções / amostras
            while True:
                rep += 1
                # Verifica condição de parada por número de amostras
                if m is not None and rep > m:
                    print(f"Amostragem de {m} iterações finalizada com sucesso.")
                    break

                suffix = f"/{m}" if m is not None else ""
                print(f"\n--- Execução {rep}{suffix} para '{nome}' ---")

                # -----------------------------------------------------------------------------------------
                # Definição das coordenadas iniciais de acordo com a opção escolhida
                # -----------------------------------------------------------------------------------------
                if opcao_inicializacao == "1":
                    # Opção 1: Hipercubo de lado L. Sorteia aleatoriamente a cada amostra
                    print(f"Sorteando vértices uniformemente dentro do hipercubo [-{L_topologico}, {L_topologico}]^3...")
                    vc = gerador_ci.gerar_hipercubo(L=L_topologico)
                else:
                    # Opção 2: Projeção Esferográfica
                    if rep == 1:
                        # Na 1ª iteração, usa EXCLUSIVAMENTE a projeção esferográfica pura (Item 2.2)
                        print("Iteração 1: Utilizando projeção esferográfica tratada pura (sem perturbação).")
                        vc = vc_base_esferica.copy()
                    else:
                        # Nas iterações seguintes (caso a 1ª não tenha sido global), aplica perturbação cúbica de lado 0.1
                        print(f"Iteração {rep}: Aplicando perturbação aleatória em cubo de lado {epsilon_perturbacao} por vértice...")
                        vc = gerador_ci.aplicar_perturbacao_cubica(posicoes_base=vc_base_esferica, epsilon=epsilon_perturbacao)

                # Inicializa as velocidades dos vértices com zero
                vel = np.zeros_like(vc)
                converged = False
                start_time = time.time()

                # Loop de integração da equação do gradiente com amortecimento
                for it in range(1, max_iter + 1):
                    # Calcula o gradiente do potencial nas posições atuais
                    g = gradiente(vc, segmentos, max_step=max_step)
                    # Calcula a norma euclidiana do gradiente
                    norm_g = np.linalg.norm(g)

                    # Exibe progresso a cada 10.000 iterações
                    if it % 10000 == 0:
                        print(f"  Passo {it:6d} | ||grad|| = {norm_g:.6e}")

                    # Critério de parada: gradiente menor que a tolerância
                    if norm_g <= grad_tol:
                        converged = True
                        print(f"  Convergiu em {it} iterações! ||grad|| = {norm_g:.6e}")
                        break

                    # Atualização de velocidade com amortecimento: v = v * atrito - alpha * grad
                    vel = vel * amortecimento - alpha * g
                    # Atualização das posições: x = x + v
                    vc += vel

                # Tempo total de processamento da otimização
                elapsed = time.time() - start_time
                # Avaliação da energia final da configuração
                fval = energia(vc, segmentos)
                # Cálculo de todas as distâncias mútuas entre vértices
                distancias = calcular_distancias([tuple(v) for v in vc])
                # Cálculo dos ângulos diedrais entre faces adjacentes
                angulos = calcular_angulos_diedrais(vc, faces)
                # Cálculo da Hessiana para análise de estabilidade e autovalores
                H = hessiana(vc, segmentos)
                # Extração dos autovalores da matriz Hessiana
                autovalores = np.linalg.eigvalsh(H)

                # Classificação em mínimo global ou local
                if abs(fval) < 1e-6:
                    tipo = "global"
                    contador_globais += 1
                    nome_solucao = f"solucao_global_{contador_globais}"
                    print(f"  >> MÍNIMO GLOBAL ENCONTRADO! f(x) = {fval:.6e} (Tempo: {elapsed:.2f}s)")
                    if rep == 1:
                        encontrou_global_na_primeira = True
                else:
                    tipo = "local"
                    nome_solucao = f"solucao_local_{rep}"
                    print(f"  -- Mínimo local encontrado: f(x) = {fval:.6e} (Tempo: {elapsed:.2f}s)")

                # Aviso caso não tenha convergido no limite de iterações
                if not converged:
                    print(f"  Aviso: Não atingiu grad_tol em {max_iter} iterações. ||grad|| = {norm_g:.6e}")

                # Verificação de degenerações geométricas (colapso de volume/área)
                if verificar_minimo_degenerado(vc, faces):
                    print("  Atenção: Mínimo degenerado detectado (vértices colapsados ou volume nulo). Descartado.")
                    continue

                # Verificação de colinearidade de vértices em faces
                if possui_face_colinear(vc, faces):
                    print("  Atenção: Face não convexa detectada (3 vértices colineares). Descartado.")
                    continue

                # Salva o sólido no registro evitando duplicatas dentro da tolerância
                vertices = [tuple(v) for v in vc]
                saved = salvar_solido(nome, vertices, distancias, angulos, fval, tol=1e-6)
                if saved:
                    encontrados += 1
                    salvar_solucao(nome_solucao, tipo, nome, vc, distancias, angulos, autovalores, fval)
                    print("  Configuração geométrica inédita salva com sucesso.")
                    # Exporta documento PythonSCAD SOMENTE SE for um mínimo global
                    exportador_scad.exportar_se_minimo_global(nome, nome_solucao, tipo, vc, faces, fval)
                else:
                    print("  Configuração geométrica descartada por duplicidade isométrica.")

        except KeyboardInterrupt:
            print("\nExecução interrompida pelo usuário via teclado (Ctrl+C).")

        # Resumo final da execução para o sólido atual
        print("\n" + "=" * 50)
        print(f"RESUMO FINAL PARA '{nome}':")
        print(f" - Método inicial utilizado: {'Hipercubo L' if opcao_inicializacao == '1' else 'Projeção Esferográfica'}")
        print(f" - Total de execuções realizadas: {rep}")
        print(f" - Mínimos globais obtidos: {contador_globais}")
        print(f" - Mínimos inéditos catalogados: {encontrados}")
        print("=" * 50)

# Ponto de entrada padrão para execução via terminal
if __name__ == "__main__":
    main()
