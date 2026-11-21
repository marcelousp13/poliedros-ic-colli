# Importação de módulos do sistema operacional para gerenciamento de diretórios e arquivos
import os
# Importação do módulo datetime para timestamp e identificação única dos arquivos gerados
from datetime import datetime

# Classe responsável por gerar scripts PythonSCAD para visualização interativa 3D de mínimos globais
class ExportadorPythonSCAD:
    # Construtor da classe: define o fator de escala padrão (ex: 20x) e a pasta base de saída
    def __init__(self, fator_escala=20.0, pasta_base=None):
        # Armazena o fator de escala que será aplicado ao objeto polyhedron (padrão: 20)
        self.fator_escala = fator_escala
        
        # Se nenhuma pasta base foi informada, utiliza a pasta do script atual
        if pasta_base is None:
            # Obtém o diretório deste arquivo
            script_dir = os.path.dirname(os.path.abspath(__file__))
            # Define o diretório de sólidos no nível superior
            self.pasta_base = os.path.join(os.path.dirname(script_dir), "solidos")
        else:
            # Utiliza a pasta base customizada informada pelo usuário
            self.pasta_base = pasta_base

    # Método para gerar o conteúdo textual do script no formato PythonSCAD
    def gerar_codigo_pythonscad(self, vertices, faces):
        # Lista de linhas de texto que comporão o arquivo final
        linhas = []
        
        # Importação do pacote openscad / pythonscad
        linhas.append("from openscad import *")
        linhas.append("")
        
        # Abertura da lista de pontos 3D
        linhas.append("pts = [")
        # Itera sobre cada vértice na matriz de coordenadas (N, 3)
        for idx, v in enumerate(vertices):
            # Formata as coordenadas x, y, z em float com alta precisão (16 casas decimais)
            coord_str = f"    [{float(v[0]):.16f}, {float(v[1]):.16f}, {float(v[2]):.16f}]"
            # Adiciona vírgula se não for o último elemento
            if idx < len(vertices) - 1:
                coord_str += ","
            # Adiciona a linha de coordenadas
            linhas.append(coord_str)
        # Fechamento da lista de pontos
        linhas.append("]")
        linhas.append("")
        
        # Linha contendo a lista de faces com índices inteiros dos vértices
        linhas.append(f"faces = {list(faces)}")
        linhas.append("")
        
        # Criação do objeto geométrico polyhedron
        linhas.append("obj = polyhedron(pts, faces)")
        
        # Aplicação do fator de escala ao objeto
        escala_val = int(self.fator_escala) if int(self.fator_escala) == self.fator_escala else self.fator_escala
        linhas.append(f"obj = scale(obj, {escala_val})")
        
        # Chamada da função show para renderizar e visualizar o sólido interativamente
        linhas.append("show(obj)")
        linhas.append("")
        
        # Junta todas as linhas separadas por quebra de linha
        return "\n".join(linhas)

    # Método principal para salvar o arquivo PythonSCAD somente quando a solução for um mínimo global
    def exportar_se_minimo_global(
        self,
        nome_solido,
        nome_solucao,
        tipo_solucao,
        vertices,
        faces,
        fval=0.0,
        convexo=True,
        tem_autointersecao=False,
        timestamp=None,
    ):
        # Verificação rigorosa: somente exporta se o tipo de solução for 'global'
        if tipo_solucao != "global":
            # Se não for mínimo global, encerra o método retornando None
            return None

        # Determina a subpasta dentro de minimos_globais/:
        # {convexos | nao_convexos}/{sem_autointersecao | com_autointersecao}
        subpasta_conv = "convexos" if convexo else "nao_convexos"
        subpasta_inter = "com_autointersecao" if tem_autointersecao else "sem_autointersecao"
        destino_dir = os.path.join(self.pasta_base, nome_solido, "minimos_globais", subpasta_conv, subpasta_inter)
        # Cria o diretório recursivamente caso não exista
        os.makedirs(destino_dir, exist_ok=True)

        # Gera timestamp formatado no padrão YYYYMMDD_HHMMSS (ou reutiliza o mesmo do JSON/TXT)
        timestamp = timestamp or datetime.now().strftime('%Y%m%d_%H%M%S')

        # Define o nome do arquivo com a extensão .py (executável PythonSCAD)
        nome_arquivo = f"{nome_solucao}_{timestamp}_pythonscad.py"
        # Caminho completo do arquivo no sistema de arquivos
        caminho_completo = os.path.join(destino_dir, nome_arquivo)

        # Gera o código-fonte em formato de texto
        conteudo_codigo = self.gerar_codigo_pythonscad(vertices, faces)

        # Grava o arquivo em disco com codificação UTF-8
        with open(caminho_completo, "w", encoding="utf-8") as f:
            f.write(conteudo_codigo)

        # Imprime mensagem de confirmação no console
        etiqueta_conv = "CONVEXO" if convexo else "NÃO CONVEXO"
        etiqueta_inter = "COM AUTOINTERSEÇÃO" if tem_autointersecao else "SEM AUTOINTERSEÇÃO"
        print(f"  [PythonSCAD] Documento gerado para MÍNIMO GLOBAL {etiqueta_conv} ({etiqueta_inter}):")
        print(f"  -> {caminho_completo}")

        # Retorna o caminho do arquivo gerado
        return caminho_completo
