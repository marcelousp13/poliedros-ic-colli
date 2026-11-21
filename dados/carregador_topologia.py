# ==============================================================================
# PACOTE: dados
# CLASSE: CarregadorTopologia
# DESCRIÇÃO: Responsável pelo carregamento, validação e consulta dos sólidos
#            geométricos a partir do arquivo estruturado faces.txt.
# ==============================================================================

import os
import ast

class CarregadorTopologia:
    """
    Classe dedicada à leitura e gerenciamento da base de dados topológica dos poliedros.
    Lê o arquivo faces.txt e extrai a lista de faces e a quantidade de vértices para cada sólido.
    """

    def __init__(self, caminho_arquivo=None):
        """
        Inicializa o carregador com o caminho do arquivo faces.txt.
        Caso não seja fornecido, busca automaticamente no diretório local ou na raiz.
        """
        if caminho_arquivo is None:
            # Diretório atual do arquivo carregador_topologia.py
            dir_atual = os.path.dirname(os.path.abspath(__file__))
            caminho_local = os.path.join(dir_atual, "faces.txt")
            caminho_raiz = os.path.join(os.path.dirname(dir_atual), "faces.txt")

            if os.path.isfile(caminho_local):
                self.caminho_arquivo = caminho_local
            elif os.path.isfile(caminho_raiz):
                self.caminho_arquivo = caminho_raiz
            else:
                self.caminho_arquivo = "faces.txt"
        else:
            self.caminho_arquivo = caminho_arquivo

        # Dicionário em memória: { 'nome_solido': (faces, num_vertices) }
        self._solidos = {}
        self.carregar()

    def carregar(self):
        """
        Lê e analisa o arquivo de faces, preenchendo o catálogo interno de poliedros.
        Retorna o dicionário com todos os sólidos carregados.
        """
        if not os.path.isfile(self.caminho_arquivo):
            raise FileNotFoundError(f"Arquivo de faces não encontrado no caminho: {self.caminho_arquivo}")

        self._solidos = {}
        with open(self.caminho_arquivo, "r", encoding="utf-8") as f:
            for num_linha, linha in enumerate(f, start=1):
                linha = linha.strip()
                if not linha or " | n=" not in linha:
                    continue

                try:
                    nome_e_faces, n_str = linha.split(" | n=")
                    if " - " not in nome_e_faces:
                        continue

                    nome, faces_raw = nome_e_faces.split(" - ")
                    nome = nome.strip()
                    n_vertices = int(n_str.strip()) if n_str.strip() else 0

                    faces = ast.literal_eval(faces_raw.strip())
                    # Ignora entradas vazias ou marcadores em branco
                    if faces and faces != [[]]:
                        self._solidos[nome] = (faces, n_vertices)
                except Exception as e:
                    # Em caso de erro de formatação em linha específica, segue com o carregamento
                    continue

        return self._solidos

    def obter_solido(self, nome):
        """
        Retorna a tupla (faces, n_vertices) para o sólido solicitado.
        Lança ValueError se o sólido não for encontrado.
        """
        if nome in self._solidos:
            return self._solidos[nome]
        raise ValueError(f"Sólido '{nome}' não encontrado no arquivo {self.caminho_arquivo}.")

    def existe_solido(self, nome):
        """
        Verifica se um determinado sólido existe na base de dados carregada.
        """
        return nome in self._solidos

    def listar_solidos(self):
        """
        Retorna a lista de nomes de todos os sólidos disponíveis na base.
        """
        return list(self._solidos.keys())

    @property
    def todos_solidos(self):
        """
        Propriedade que retorna o dicionário completo de sólidos.
        """
        return self._solidos
