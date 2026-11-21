# ==============================================================================
# PACOTE: persistencia
# CLASSE: GerenciadorSolucoes
# DESCRIÇÃO: Responsável pelo armazenamento persistente dos mínimos encontrados
#            (locais e globais), validação de duplicatas isométricas em banco binário
#            (minimos.npy) e gravação de relatórios detalhados em JSON e TXT.
# ==============================================================================

import os
import json
import numpy as np
from datetime import datetime
from verificadores.isomorfismo import resolver_isomorfismo, construir_matriz_distancias

class GerenciadorSolucoes:
    """
    Classe dedicada à persistência em disco das configurações geométricas encontradas.
    Garante o descarte de mínimos isomórficos repetidos e organiza os dados em diretórios
    padronizados por sólido:
      solidos/<NomeDoSolido>/
        ├── minimos_locais/
        └── minimos_globais/
            ├── convexos/
            │   ├── sem_autointersecao/   (vai para RESULTADOS no site)
            │   └── com_autointersecao/   (registro local, fora do site)
            └── nao_convexos/
                ├── sem_autointersecao/   (vai para DESCOBERTAS no site)
                └── com_autointersecao/   (registro local, fora do site)
    """

    PASTA_LOCAIS = "minimos_locais"
    PASTA_GLOBAIS = "minimos_globais"
    PASTA_CONVEXOS = "convexos"
    PASTA_NAO_CONVEXOS = "nao_convexos"
    PASTA_SEM_AUTOINTERSECAO = "sem_autointersecao"
    PASTA_COM_AUTOINTERSECAO = "com_autointersecao"

    def __init__(self, pasta_base=None, tol=1e-6):
        """
        Inicializa o gerenciador com a pasta base de destino dos sólidos.
        Se não fornecida, adota a pasta 'solidos' na raiz do projeto.
        """
        if pasta_base is None:
            dir_atual = os.path.dirname(os.path.abspath(__file__))
            self.pasta_base = os.path.join(os.path.dirname(dir_atual), "solidos")
        else:
            self.pasta_base = pasta_base

        self.tol = float(tol)
        os.makedirs(self.pasta_base, exist_ok=True)

    def preparar_estrutura_solido(self, nome_solido):
        """
        Garante a existência da hierarquia completa de pastas de um sólido:
          - solidos/<nome_solido>/minimos_locais/
          - solidos/<nome_solido>/minimos_globais/convexos/sem_autointersecao/
          - solidos/<nome_solido>/minimos_globais/convexos/com_autointersecao/
          - solidos/<nome_solido>/minimos_globais/nao_convexos/sem_autointersecao/
          - solidos/<nome_solido>/minimos_globais/nao_convexos/com_autointersecao/
        """
        pasta_solido = os.path.join(self.pasta_base, nome_solido)
        pasta_locais = os.path.join(pasta_solido, self.PASTA_LOCAIS)
        pasta_globais = os.path.join(pasta_solido, self.PASTA_GLOBAIS)
        pasta_convexos = os.path.join(pasta_globais, self.PASTA_CONVEXOS)
        pasta_nao_convexos = os.path.join(pasta_globais, self.PASTA_NAO_CONVEXOS)
        pasta_conv_sem = os.path.join(pasta_convexos, self.PASTA_SEM_AUTOINTERSECAO)
        pasta_conv_com = os.path.join(pasta_convexos, self.PASTA_COM_AUTOINTERSECAO)
        pasta_nconv_sem = os.path.join(pasta_nao_convexos, self.PASTA_SEM_AUTOINTERSECAO)
        pasta_nconv_com = os.path.join(pasta_nao_convexos, self.PASTA_COM_AUTOINTERSECAO)

        for d in (pasta_locais, pasta_conv_sem, pasta_conv_com, pasta_nconv_sem, pasta_nconv_com):
            os.makedirs(d, exist_ok=True)

        return {
            "solido": pasta_solido,
            "minimos_locais": pasta_locais,
            "minimos_globais": pasta_globais,
            "convexos": pasta_convexos,
            "nao_convexos": pasta_nao_convexos,
            "convexos_sem_autointersecao": pasta_conv_sem,
            "convexos_com_autointersecao": pasta_conv_com,
            "nao_convexos_sem_autointersecao": pasta_nconv_sem,
            "nao_convexos_com_autointersecao": pasta_nconv_com,
        }

    def verificar_duplicata_e_registrar(self, nome_solido, vertices, distancias, angulos, fval):
        """
        Verifica se a configuração já foi registrada previamente comparando
        o espectro de distâncias, ângulos diedrais e valor da função objetivo.
        
        Se for uma solução inédita:
            - Registra no arquivo binário 'minimos.npy'
            - Grava as coordenadas dos vértices em 'pontos.txt'
            - Retorna True
        Se for duplicada:
            - Retorna False
        """
        pasta_solido = os.path.join(self.pasta_base, nome_solido)
        os.makedirs(pasta_solido, exist_ok=True)

        banco_npy = os.path.join(pasta_solido, "minimos.npy")
        pontos_txt = os.path.join(pasta_solido, "pontos.txt")

        # Carrega o histórico de mínimos salvos para este sólido
        if os.path.exists(banco_npy):
            try:
                dados = np.load(banco_npy, allow_pickle=True).tolist()
            except Exception:
                dados = []
        else:
            dados = []

        matriz_dist = construir_matriz_distancias(vertices)

        # Compara com os registros existentes utilizando isomorfismo métrico
        for antigo in dados:
            # Pré-filtro: energias devem ser compatíveis
            if abs(antigo["fval"] - fval) <= 1e-4:
                matriz_antiga = antigo.get("matriz_distancias")
                if matriz_antiga is None and "vertices" in antigo:
                    matriz_antiga = construir_matriz_distancias(antigo["vertices"])

                if matriz_antiga is not None:
                    # Teste rigoroso de isomorfismo métrico via backtracking
                    perm = resolver_isomorfismo(matriz_dist, matriz_antiga, tol=1e-4, decimais=4)
                    if perm is not None:
                        return False  # Duplicata isométrica comprovada
                else:
                    # Fallback para registros antigos legados
                    if (
                        np.allclose(antigo["distancias"], distancias, atol=self.tol, rtol=0)
                        and np.allclose(antigo["angulos"], angulos, atol=self.tol, rtol=0)
                    ):
                        return False  # Duplicata detectada

        # Adiciona a nova solução ao banco com sua matriz de distâncias completa
        dados.append({
            "distancias": np.asarray(distancias, dtype=float),
            "angulos": np.asarray(angulos, dtype=float),
            "fval": float(fval),
            "vertices": np.asarray(vertices, dtype=float),
            "matriz_distancias": np.asarray(matriz_dist, dtype=float)
        })
        np.save(banco_npy, dados)

        # Registra no log de pontos.txt
        with open(pontos_txt, "a", encoding="utf-8") as f:
            f.write(f"Novo mínimo encontrado em {datetime.now().isoformat()}:\n")
            for i, v in enumerate(vertices):
                f.write(f"v[{i}] = [{v[0]:.6f}, {v[1]:.6f}, {v[2]:.6f}]\n")
            f.write("\n")

        return True

    def salvar_arquivos_solucao(
        self,
        nome_solucao,
        tipo,
        nome_solido,
        vc,
        distancias,
        angulos,
        autovalores,
        fval,
        convexo=None,
        tem_autointersecao=False,
        info_convexidade=None,
        info_autointersecao=None,
        timestamp=None,
        info_execucao=None,
    ):
        """
        Gera os arquivos estruturados JSON e TXT contendo todos os detalhes da solução.
        Organiza nas pastas oficiais do sólido:
          - Mínimo local -> solidos/<nome_solido>/minimos_locais/
          - Mínimo global convexo sem autointerseção     -> minimos_globais/convexos/sem_autointersecao/
          - Mínimo global convexo com autointerseção     -> minimos_globais/convexos/com_autointersecao/
          - Mínimo global não convexo sem autointerseção -> minimos_globais/nao_convexos/sem_autointersecao/
          - Mínimo global não convexo com autointerseção -> minimos_globais/nao_convexos/com_autointersecao/
        """
        pastas = self.preparar_estrutura_solido(nome_solido)

        if tipo == "global":
            if convexo is False:
                destino_dir = (
                    pastas["nao_convexos_com_autointersecao"]
                    if tem_autointersecao
                    else pastas["nao_convexos_sem_autointersecao"]
                )
            else:
                destino_dir = (
                    pastas["convexos_com_autointersecao"]
                    if tem_autointersecao
                    else pastas["convexos_sem_autointersecao"]
                )
        else:
            destino_dir = pastas["minimos_locais"]

        timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_base = f"{nome_solucao}_{timestamp}"
        json_path = os.path.join(destino_dir, f"{nome_base}.json")
        txt_path = os.path.join(destino_dir, f"{nome_base}.txt")

        classificacao = None
        if convexo is True:
            classificacao = "convexo"
        elif convexo is False:
            classificacao = "nao_convexo"

        convexidade_serializada = None
        if info_convexidade is not None:
            convexidade_serializada = {
                k: v for k, v in info_convexidade.items() if k != "oriented_faces"
            }

        # Estrutura JSON com todos os dados numéricos serializados
        dados = {
            "nome": nome_solido,
            "tipo": tipo,
            "convexo": convexo,
            "classificacao": classificacao,
            "tem_autointersecao": bool(tem_autointersecao) if tipo == "global" else None,
            "fval": float(fval),
            "vc": vc.tolist() if hasattr(vc, "tolist") else list(vc),
            "distancias": distancias.tolist() if hasattr(distancias, "tolist") else list(distancias),
            "angulos_diedrais": angulos.tolist() if hasattr(angulos, "tolist") else list(angulos),
            "autovalores": autovalores.tolist() if hasattr(autovalores, "tolist") else list(autovalores),
            "timestamp": datetime.now().isoformat()
        }
        if convexidade_serializada is not None:
            dados["convexidade"] = convexidade_serializada
        if info_autointersecao is not None:
            dados["autointersecao"] = info_autointersecao
        if info_execucao is not None:
            exec_clean = dict(info_execucao)
            if "vc_inicial" in exec_clean and hasattr(exec_clean["vc_inicial"], "tolist"):
                exec_clean["vc_inicial"] = exec_clean["vc_inicial"].tolist()
            dados["execucao"] = exec_clean

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=4, ensure_ascii=False)

        # Arquivo de texto legível para conferência analítica direta
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"Solução: {nome_solucao}\n")
            f.write(f"Tipo: {tipo}\n")
            if classificacao is not None:
                label_conv = "Convexo" if convexo else "Não convexo"
                label_inter = "Com autointerseção de faces" if tem_autointersecao else "Sem autointerseção de faces"
                f.write(f"Classificação geométrica: {label_conv} ({label_inter})\n")
            f.write(f"Valor da função objetivo (fval): {fval:.6e}\n")
            if info_execucao is not None:
                metodo_lbl = info_execucao.get("metodo_inicial") or "Não informado"
                amostra_val = info_execucao.get("tamanho_amostra")
                amostra_lbl = "Ilimitada" if amostra_val is None else str(amostra_val)
                tentativa_val = info_execucao.get("tentativa")
                iters_val = info_execucao.get("iteracoes_otimizador")
                tempo_val = info_execucao.get("tempo_segundos")
                f.write(f"Condição inicial (método): {metodo_lbl}\n")
                f.write(f"Tamanho da amostra: {amostra_lbl} | Tentativa necessária: {tentativa_val if tentativa_val is not None else '—'}\n")
                if iters_val is not None or tempo_val is not None:
                    f.write(f"Convergência: {iters_val if iters_val is not None else '—'} iterações | Tempo: {tempo_val if tempo_val is not None else '—'}s\n")
            if convexidade_serializada is not None:
                f.write(
                    f"Volume / Volume Envoltória Convexa: "
                    f"{convexidade_serializada.get('volume', 0.0):.6f} / "
                    f"{convexidade_serializada.get('hull_volume', 0.0):.6f} "
                    f"(razão = {convexidade_serializada.get('volume_ratio', 1.0):.6f})\n"
                )
                f.write(
                    f"Diedrais internos: [{convexidade_serializada.get('min_dihedral_deg', 0.0):.3f}°, "
                    f"{convexidade_serializada.get('max_dihedral_deg', 0.0):.3f}°] "
                    f"| Arestas reflexas: {convexidade_serializada.get('reflex_edges', 0)} "
                    f"| Vértices interiores: {convexidade_serializada.get('interior_vertices', 0)}\n"
                )
                if convexidade_serializada.get("reasons"):
                    f.write(f"Motivos de não convexidade: {'; '.join(convexidade_serializada['reasons'])}\n")
            if info_autointersecao is not None:
                f.write(
                    f"Autointerseção de faces: {'SIM' if info_autointersecao.get('has_self_intersection') else 'NÃO'} "
                    f"(ocorrências: {info_autointersecao.get('intersection_count', 0)}"
                    f"{', tipos: ' + ', '.join(info_autointersecao.get('intersection_types', [])) if info_autointersecao.get('intersection_types') else ''})\n"
                )
            f.write(f"Autovalores: {autovalores.tolist() if hasattr(autovalores, 'tolist') else autovalores}\n")
            f.write("\n--- Distâncias Mútuas ---\n")
            for d in (distancias.tolist() if hasattr(distancias, "tolist") else distancias):
                f.write(f"{d:.6f}\n")
            f.write("\n--- Ângulos Diedrais (graus) ---\n")
            for a in angulos:
                f.write(f"{a:.4f}\n")
            f.write("\n--- Coordenadas dos Vértices (vc) ---\n")
            for v in (vc.tolist() if hasattr(vc, "tolist") else vc):
                f.write(f"[{v[0]:.8f}, {v[1]:.8f}, {v[2]:.8f}]\n")

        print(f"Solução gravada com sucesso em:\n - {json_path}\n - {txt_path}")
        return json_path, txt_path
