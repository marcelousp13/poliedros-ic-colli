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
        self._banco_cache = {}
        self.ultimo_nome_base = None
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

    def inspecionar_ou_registrar_isometria(
        self,
        nome_solido,
        vertices,
        distancias,
        angulos,
        fval,
        registrar_se_inedito=True,
    ):
        """
        Compara `vertices` com o histórico de formas distintas em `minimos.npy` via
        isomorfismo métrico (backtracking).
        Retorna dict com:
          - eh_inedito (bool): True se for uma nova forma geométrica
          - indice_classe (int): índice 1-based da forma geométrica correspondente em `minimos.npy`
        Mantém cache em RAM por sólido para evitar leituras repetidas em amostras grandes.
        """
        pasta_solido = os.path.join(self.pasta_base, nome_solido)
        os.makedirs(pasta_solido, exist_ok=True)

        banco_npy = os.path.join(pasta_solido, "minimos.npy")
        pontos_txt = os.path.join(pasta_solido, "pontos.txt")

        if nome_solido in self._banco_cache:
            dados = self._banco_cache[nome_solido]
        elif os.path.exists(banco_npy):
            try:
                dados = np.load(banco_npy, allow_pickle=True).tolist()
            except Exception:
                dados = []
            self._banco_cache[nome_solido] = dados
        else:
            dados = []
            self._banco_cache[nome_solido] = dados

        matriz_dist = construir_matriz_distancias(vertices)

        # Compara com os registros existentes utilizando isomorfismo métrico
        for idx, antigo in enumerate(dados):
            if abs(antigo["fval"] - fval) <= 1e-4:
                matriz_antiga = antigo.get("matriz_distancias")
                if matriz_antiga is None and "vertices" in antigo:
                    matriz_antiga = construir_matriz_distancias(antigo["vertices"])
                    antigo["matriz_distancias"] = matriz_antiga

                if matriz_antiga is not None:
                    perm = resolver_isomorfismo(matriz_dist, matriz_antiga, tol=1e-4, decimais=4)
                    if perm is not None:
                        return {"eh_inedito": False, "indice_classe": idx + 1}
                else:
                    if (
                        np.allclose(antigo["distancias"], distancias, atol=self.tol, rtol=0)
                        and np.allclose(antigo["angulos"], angulos, atol=self.tol, rtol=0)
                    ):
                        return {"eh_inedito": False, "indice_classe": idx + 1}

        novo_indice = len(dados) + 1
        if registrar_se_inedito:
            dados.append({
                "distancias": np.asarray(distancias, dtype=float),
                "angulos": np.asarray(angulos, dtype=float),
                "fval": float(fval),
                "vertices": np.asarray(vertices, dtype=float),
                "matriz_distancias": np.asarray(matriz_dist, dtype=float),
            })
            np.save(banco_npy, dados)

            with open(pontos_txt, "a", encoding="utf-8") as f:
                f.write(f"Novo mínimo encontrado em {datetime.now().isoformat()} (Classe #{novo_indice}):\n")
                for i, v in enumerate(vertices):
                    f.write(f"v[{i}] = [{v[0]:.6f}, {v[1]:.6f}, {v[2]:.6f}]\n")
                f.write("\n")

        return {"eh_inedito": True, "indice_classe": novo_indice}

    def verificar_duplicata_e_registrar(self, nome_solido, vertices, distancias, angulos, fval):
        """
        Compatibilidade: verifica se a configuração é inédita por isomorfismo métrico,
        registrando-a em `minimos.npy` e `pontos.txt` se for inédita.
        """
        res = self.inspecionar_ou_registrar_isometria(
            nome_solido=nome_solido,
            vertices=vertices,
            distancias=distancias,
            angulos=angulos,
            fval=fval,
            registrar_se_inedito=True,
        )
        return bool(res["eh_inedito"])

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
        nome_base_candidato = f"{nome_solucao}_{timestamp}"
        nome_base = nome_base_candidato
        sufixo_colisao = 2
        while os.path.exists(os.path.join(destino_dir, f"{nome_base}.json")):
            nome_base = f"{nome_base_candidato}_{sufixo_colisao}"
            sufixo_colisao += 1
        self.ultimo_nome_base = nome_base
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
            json.dump(dados, f, indent=2, ensure_ascii=False)

        # Arquivo de texto legível para conferência analítica direta
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"Solução: {nome_base}\n")
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
                amostra_atual = info_execucao.get("amostra_atual", info_execucao.get("tentativa"))
                tent_desde = info_execucao.get("tentativas_desde_ultimo_global")
                iters_val = info_execucao.get("iteracoes_otimizador")
                tempo_val = info_execucao.get("tempo_segundos")
                norm_g_val = info_execucao.get("norm_grad")
                e_ini = info_execucao.get("energia_inicial")
                autor_lbl = info_execucao.get("autor")
                sessao_lbl = info_execucao.get("sessao_id")
                classe_iso = info_execucao.get("classe_isometria_local")
                eh_ined = info_execucao.get("eh_inedito_isometrico")
                if autor_lbl or sessao_lbl:
                    f.write(f"Pesquisador / Sessão: {autor_lbl or '—'} | Sessão: {sessao_lbl or '—'}\n")
                f.write(f"Condição inicial (método): {metodo_lbl}\n")
                f.write(
                    f"Amostragem: amostra atual #{amostra_atual if amostra_atual is not None else '—'} "
                    f"/ tamanho da amostra = {amostra_lbl}"
                    f"{f' (tentativas desde o global anterior: {tent_desde})' if tent_desde is not None else ''}\n"
                )
                if e_ini is not None:
                    f.write(f"Energia inicial F(x0): {float(e_ini):.6e}\n")
                if iters_val is not None or tempo_val is not None or norm_g_val is not None:
                    ng_str = f" | ||grad|| = {float(norm_g_val):.3e}" if norm_g_val is not None else ""
                    f.write(
                        f"Convergência: {iters_val if iters_val is not None else '—'} iterações "
                        f"| Tempo: {tempo_val if tempo_val is not None else '—'}s{ng_str}\n"
                    )
                if classe_iso is not None or eh_ined is not None:
                    iso_lbl = "Inédito" if eh_ined else "Recorrência isométrica"
                    f.write(f"Isometria local: Classe #{classe_iso if classe_iso is not None else '—'} ({iso_lbl})\n")
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
            if info_execucao is not None and info_execucao.get("vc_inicial") is not None:
                vc_ini = info_execucao["vc_inicial"]
                vc_ini_list = vc_ini.tolist() if hasattr(vc_ini, "tolist") else list(vc_ini)
                f.write("\n--- Condição Inicial dos Vértices (x0 / vc_inicial) ---\n")
                for v in vc_ini_list:
                    f.write(f"[{float(v[0]):.8f}, {float(v[1]):.8f}, {float(v[2]):.8f}]\n")

        print(f"Solução gravada com sucesso em:\n - {json_path}\n - {txt_path}")
        return json_path, txt_path
