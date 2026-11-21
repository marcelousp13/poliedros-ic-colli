# ==============================================================================
# PROJETO: Iniciação Científica - IC com Colli
# PROGRAMA: standbyalone2.py (Documento Principal / Main)
# AUTOR: Marcelo & Antigravity (Google DeepMind)
# DESCRIÇÃO: 
#   Ponto de entrada oficial do programa de determinação e otimização de 
#   poliedros regulares e sólidos de Johnson via relaxação por gradiente amortecido.
#   Este arquivo contém ESTRITAMENTE a função main() de orquestração interativa,
#   importando e delegando todas as operações para suas classes especializadas.
# ==============================================================================

import os
import sys
from datetime import datetime

# Garante que o diretório raiz do projeto esteja no sys.path para importação limpa dos módulos
diretorio_raiz = os.path.dirname(os.path.abspath(__file__))
if diretorio_raiz not in sys.path:
    sys.path.insert(0, diretorio_raiz)

# ------------------------------------------------------------------------------
# IMPORTAÇÃO DAS CLASSES OFICIAIS DO PROJETO (CADA UMA EM SUA PRÓPRIA PASTA)
# ------------------------------------------------------------------------------
# 1. Carregador de dados e leitura de faces.txt
from dados.carregador_topologia import CarregadorTopologia

# 2. Orientação e consistência topológica das faces e cálculo analítico de distâncias (d2)
from topologia.orientador_faces import OrientadorFaces

# 3. Gerador rigoroso de condições iniciais (Teorema 1 Hipercubo L, Projeção Esferográfica e Perturbação)
from condicoes_iniciais.gerador_condicoes import GeradorCondicoesIniciais

# 4. Otimizador dinâmico por Gradiente Amortecido (Velocity Gradient), Energia e Hessiana
from otimizador.otimizador_gradiente import OtimizadorGradiente

# 5. Verificador geométrico e topológico (degenerações, diedrais por Newell, colinearidade e isomorfismo)
from verificadores.verificador_geometrico import VerificadorGeometrico
from verificadores.isomorfismo import resolver_isomorfismo, verificar_isomorfismo_solidos

# 6. Gerenciador de persistência (registro binário de mínimos inéditos e salvamento JSON/TXT)
from persistencia.gerenciador_solucoes import GerenciadorSolucoes

# 7. Exportador 3D para PythonSCAD (geração automática de modelos para mínimos globais)
from exportadores.pythonscad_exportador import ExportadorPythonSCAD


# ==============================================================================
# FUNÇÃO PRINCIPAL (MAIN)
# ==============================================================================
def main():
    """
    Função principal interativa que conduz a interface com o pesquisador,
    carrega as classes especializadas e coordena as fases de:
      1. Perguntas interativas de configuração
      2. Leitura e preparação topológica do poliedro
      3. Geração das coordenadas iniciais (Hipercubo L ou Projeção Esferográfica)
      4. Otimização numérica por dinâmica de gradiente amortecido
      5. Conferência geométrica rigorosa (sem degenerações)
      6. Salvamento de soluções inéditas e exportação 3D (PythonSCAD)
    """
    print("\n" + "=" * 80)
    print("      INICIAÇÃO CIENTÍFICA COM COLLI - DETERMINAÇÃO DE POLIEDROS")
    print("              OTIMIZAÇÃO VIA SISTEMA DINÂMICO DISSIPATIVO        ")
    print("=" * 80)

    # 1. Instanciação das classes de infraestrutura
    carregador = CarregadorTopologia()
    exportador_scad = ExportadorPythonSCAD(fator_escala=20.0)
    gerenciador_solucoes = GerenciadorSolucoes()
    otimizador = OtimizadorGradiente(
        alpha=0.01,
        amortecimento=0.9,
        grad_tol=1e-14,
        max_iter=1000000,
        max_step=0.1
    )

    # 2. Interação com o usuário: quantidade de sólidos a processar
    while True:
        try:
            qtd_solidos = int(input("\nQuantos sólidos deseja rodar? "))
            if qtd_solidos > 0:
                break
            print("Por favor, digite um número inteiro positivo maior que zero.")
        except ValueError:
            print("Entrada inválida! Digite um número inteiro.")

    # 3. Interação com o usuário: tamanho da amostra (número de repetições)
    while True:
        m_input = input("Qual o tamanho da amostra de iterações? (Enter = ilimitado): ").strip()
        try:
            m = None if m_input == "" else int(m_input)
            break
        except ValueError:
            print("Entrada inválida! Digite um número inteiro.")

    # 4. Interação com o usuário: seleção dos nomes dos sólidos
    nomes_solidos = []
    for i in range(qtd_solidos):
        while True:
            nome = input(f"Digite o nome do sólido {i+1} (ex: J1, J86, Cube, Icosahedron): ").strip()
            if carregador.existe_solido(nome):
                nomes_solidos.append(nome)
                break
            print(f"Sólido '{nome}' não encontrado na base faces.txt. Tente novamente.")

    # 5. Interação com o usuário: escolha do método de coordenadas iniciais
    print("\n" + "-" * 60)
    print("MÉTODO DE COORDENADAS INICIAIS:")
    print(" 1. Hipercubo de tamanho L (Derivado pelo Teorema 1)")
    print(" 2. Projeção Esferográfica (Pura na 1ª amostra; perturbação cúbica ε=0.1 nas seguintes)")
    print("-" * 60)
    while True:
        opcao_inicializacao = input("Qual método de coordenadas iniciais você deseja? (1 ou 2): ").strip()
        if opcao_inicializacao in ["1", "2"]:
            break
        print("Opção inválida! Escolha 1 para Hipercubo ou 2 para Projeção Esferográfica.")

    # Parâmetro de perturbação cúbica para a projeção esferográfica
    epsilon_perturbacao = 0.1

    # --------------------------------------------------------------------------
    # LOOP DE PROCESSAMENTO PARA CADA SÓLIDO SELECIONADO
    # --------------------------------------------------------------------------
    for nome in nomes_solidos:
        print("\n" + "=" * 80)
        print(f"INICIANDO PROCESSAMENTO DO SÓLIDO: {nome}")
        print("=" * 80)

        # Cria previamente a estrutura oficial de pastas do sólido:
        # solidos/<nome>/minimos_locais/ e solidos/<nome>/minimos_globais/{convexos, nao_convexos}/{sem_autointersecao, com_autointersecao}/
        pastas_solido = gerenciador_solucoes.preparar_estrutura_solido(nome)
        print(f"Pastas preparadas em: {pastas_solido['solido']}")
        print(f"  - Mínimos locais                               : {pastas_solido['minimos_locais']}")
        print(f"  - Globais convexos     (sem autointerseção)    : {pastas_solido['convexos_sem_autointersecao']}")
        print(f"  - Globais convexos     (com autointerseção)    : {pastas_solido['convexos_com_autointersecao']}")
        print(f"  - Globais não convexos (sem autointerseção)    : {pastas_solido['nao_convexos_sem_autointersecao']}")
        print(f"  - Globais não convexos (com autointerseção)    : {pastas_solido['nao_convexos_com_autointersecao']}")

        # Extrai as faces brutas e o número de vértices a partir do CarregadorTopologia
        faces_brutas, n_vertices_info = carregador.obter_solido(nome)

        # Corrige a orientação topológica das faces via OrientadorFaces
        faces = OrientadorFaces.corrigir_orientacao(faces_brutas)

        # Gera os segmentos de restrição métrica (d2 ideal para arestas e diagonais)
        segmentos = OrientadorFaces.gerar_segmentos(faces)
        num_vertices = int(segmentos[:, :2].max()) + 1

        # Instancia a classe de Condições Iniciais dedicada ao sólido
        gerador_ci = GeradorCondicoesIniciais(faces, num_vertices=num_vertices, segmentos=segmentos)

        # Calcula o lado L analítico pelo Teorema 1
        L_topologico = gerador_ci.calcular_lado_L_teorema(segmentos=segmentos)
        print(f"Topologia: {num_vertices} vértices, {len(faces)} faces.")
        print(f"Lado L exato do hipercubo [-L, L]^3 (Teorema 1): L = {L_topologico:.4f}")

        # Caso a opção 2 tenha sido selecionada, gera a projeção esferográfica planar pré-calculada
        if opcao_inicializacao == "2":
            print("Calculando projeção esferográfica planar base na esfera S^2...")
            vc_base_esferica = gerador_ci.gerar_projecao_esferografica_tratada(escala_plano=5.0)

        # Contadores de métricas da execução
        rep = 0
        encontrados = 0
        contador_globais = 0
        contador_globais_convexos_limpos = 0
        contador_globais_nao_convexos_limpos = 0
        contador_globais_com_intersecao = 0
        contador_locais = 0

        try:
            while True:
                rep += 1
                if m is not None and rep > m:
                    print(f"\nAmostragem de {m} iterações concluída com êxito.")
                    break

                suffix = f"/{m}" if m is not None else ""
                print(f"\n--- Execução {rep}{suffix} para '{nome}' ---")

                # Definição das coordenadas iniciais de acordo com o método escolhido
                if opcao_inicializacao == "1":
                    # Método 1: Sorteio uniforme no Hipercubo [-L, L]^3
                    print(f"Sorteando vértices no hipercubo [-{L_topologico:.2f}, {L_topologico:.2f}]^3...")
                    vc_inicial = gerador_ci.gerar_hipercubo(L=L_topologico)
                else:
                    # Método 2: Projeção Esferográfica
                    if rep == 1:
                        # 1ª Iteração: Projeção esferográfica pura
                        print("Iteração 1: Utilizando projeção esferográfica pura (sem perturbação).")
                        vc_inicial = vc_base_esferica.copy()
                    else:
                        # Iterações subsequentes: Perturbação cúbica de lado 0.1 por vértice
                        print(f"Iteração {rep}: Aplicando perturbação aleatória em cubo de lado {epsilon_perturbacao}...")
                        vc_inicial = gerador_ci.aplicar_perturbacao_cubica(
                            posicoes_base=vc_base_esferica,
                            epsilon=epsilon_perturbacao
                        )

                # Executa a otimização dinâmica via classe OtimizadorGradiente
                resultado = otimizador.otimizar(vc_inicial, segmentos, imprimir_passos=True)
                vc = resultado["vc"]
                fval = resultado["fval"]
                converged = resultado["converged"]
                norm_g = resultado["norm_g"]
                elapsed = resultado["elapsed_time"]
                autovalores = resultado["autovalores"]

                # Verificações e cálculos métricos via classe VerificadorGeometrico
                distancias = VerificadorGeometrico.calcular_distancias(vc)
                angulos = VerificadorGeometrico.calcular_angulos_diedrais(vc, faces)

                if not converged:
                    print(f"  Aviso: Não atingiu grad_tol no limite de iterações. ||grad|| = {norm_g:.6e}")

                # Teste 1 de integridade geométrica: degeneração volumétrica / vértices colapsados
                if VerificadorGeometrico.verificar_minimo_degenerado(vc, faces):
                    print(f"  Atenção: Configuração degenerada detectada (f(x) = {fval:.6e}). Descartada.")
                    continue

                # Teste 2 de integridade geométrica: colinearidade em faces
                if VerificadorGeometrico.possui_face_colinear(vc, faces):
                    print(f"  Atenção: Face degenerada/colinear detectada (f(x) = {fval:.6e}). Descartada.")
                    continue

                # Classificação entre mínimo global (convexo vs não-convexo + autointerseção de faces) ou mínimo local
                convexo = None
                tem_autointersecao = False
                info_convexidade = None
                info_autointersecao = None
                faces_exportacao = faces

                if abs(fval) < 1e-6:
                    tipo = "global"
                    contador_globais += 1
                    auditoria = VerificadorGeometrico.classificar_solucao_global(vc, faces)
                    info_convexidade = auditoria["convexidade"]
                    info_autointersecao = auditoria["autointersecao"]
                    convexo = auditoria["is_convex"]
                    tem_autointersecao = auditoria["has_self_intersection"]
                    faces_exportacao = auditoria["oriented_faces"]

                    if tem_autointersecao:
                        contador_globais_com_intersecao += 1
                        prefixo_conv = "convexo" if convexo else "nao_convexo"
                        nome_solucao = f"solucao_global_{prefixo_conv}_intersecao_{contador_globais_com_intersecao}"
                        tipos_txt = ", ".join(info_autointersecao["intersection_types"])
                        print(
                            f"  >> MÍNIMO GLOBAL {'CONVEXO' if convexo else 'NÃO CONVEXO'} COM AUTOINTERSEÇÃO DE FACES! "
                            f"f(x) = {fval:.6e} | {info_autointersecao['intersection_count']} ocorrência(s) ({tipos_txt}) "
                            f"(Tempo: {elapsed:.2f}s)"
                        )
                        print("     Salvo em com_autointersecao/ (não publicado no site).")
                    elif convexo:
                        contador_globais_convexos_limpos += 1
                        nome_solucao = f"solucao_global_convexo_{contador_globais_convexos_limpos}"
                        print(
                            f"  >> MÍNIMO GLOBAL CONVEXO SEM AUTOINTERSEÇÃO! f(x) = {fval:.6e} "
                            f"| V/V_CH = {info_convexidade['volume_ratio']:.5f} "
                            f"| diedrais ∈ [{info_convexidade['min_dihedral_deg']:.1f}°, "
                            f"{info_convexidade['max_dihedral_deg']:.1f}°] (Tempo: {elapsed:.2f}s)"
                        )
                    else:
                        contador_globais_nao_convexos_limpos += 1
                        nome_solucao = f"solucao_global_nao_convexo_{contador_globais_nao_convexos_limpos}"
                        motivos = "; ".join(info_convexidade["reasons"])
                        print(
                            f"  >> MÍNIMO GLOBAL NÃO CONVEXO SEM AUTOINTERSEÇÃO (DESCOBERTA)! f(x) = {fval:.6e} "
                            f"(Tempo: {elapsed:.2f}s)"
                        )
                        print(f"     Critérios: {motivos}")
                else:
                    tipo = "local"
                    contador_locais += 1
                    nome_solucao = f"solucao_local_{rep}"
                    print(f"  -- Mínimo local encontrado: f(x) = {fval:.6e} (Tempo: {elapsed:.2f}s)")

                # Validação de unicidade e gravação via GerenciadorSolucoes
                vertices = [tuple(v) for v in vc]
                eh_inedito = gerenciador_solucoes.verificar_duplicata_e_registrar(
                    nome_solido=nome,
                    vertices=vertices,
                    distancias=distancias,
                    angulos=angulos,
                    fval=fval
                )

                if eh_inedito:
                    encontrados += 1
                    timestamp_solucao = datetime.now().strftime("%Y%m%d_%H%M%S")
                    gerenciador_solucoes.salvar_arquivos_solucao(
                        nome_solucao=nome_solucao,
                        tipo=tipo,
                        nome_solido=nome,
                        vc=vc,
                        distancias=distancias,
                        angulos=angulos,
                        autovalores=autovalores,
                        fval=fval,
                        convexo=convexo,
                        tem_autointersecao=tem_autointersecao,
                        info_convexidade=info_convexidade,
                        info_autointersecao=info_autointersecao,
                        timestamp=timestamp_solucao
                    )
                    print("  Configuração geométrica inédita registrada com sucesso.")

                    # Se for MÍNIMO GLOBAL, gera o código interativo em PythonSCAD na respectiva subpasta
                    exportador_scad.exportar_se_minimo_global(
                        nome_solido=nome,
                        nome_solucao=nome_solucao,
                        tipo_solucao=tipo,
                        vertices=vc,
                        faces=faces_exportacao,
                        fval=fval,
                        convexo=bool(convexo),
                        tem_autointersecao=tem_autointersecao,
                        timestamp=timestamp_solucao
                    )
                else:
                    print("  Configuração descartada por duplicidade isométrica (isomorfismo métrico detectado).")

        except KeyboardInterrupt:
            print("\nExecução interrompida pelo usuário via teclado (Ctrl+C).")

        # Resumo final da sessão para o sólido processado
        amostras_executadas = min(rep, m) if m is not None else rep
        print("\n" + "=" * 60)
        print(f"RESUMO FINAL PARA '{nome}':")
        print(f" - Método inicial: {'Hipercubo L' if opcao_inicializacao == '1' else 'Projeção Esferográfica'}")
        print(f" - Amostras executadas: {amostras_executadas}")
        print(
            f" - Mínimos globais (não degenerados): {contador_globais} "
            f"(Convexos sem autointerseção: {contador_globais_convexos_limpos} | "
            f"Não convexos sem autointerseção: {contador_globais_nao_convexos_limpos} | "
            f"Com autointerseção: {contador_globais_com_intersecao})"
        )
        print(f" - Mínimos locais (válidos): {contador_locais}")
        print(f" - Mínimos inéditos catalogados: {encontrados}")
        print("=" * 60)


# Ponto de entrada padrão
if __name__ == "__main__":
    main()
