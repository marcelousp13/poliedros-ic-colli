# Otimização Não Linear: Determinação de Poliedros de Faces Regulares
## Iniciação Científica - IC com Colli

Implementação computacional desenvolvida em Iniciação Científica no Instituto de Matemática e Estatística da Universidade de São Paulo (IME-USP), voltada à determinação de poliedros de faces regulares via métodos numéricos e otimização não linear.

## Contexto Acadêmico e Autoria
* **Instituição:** IME-USP (2025–2026)
* **Orientação:** Prof. Eduardo Colli
* **Desenvolvimento:** Projeto desenvolvido em parceria por **Marcelo Germano Reis** e **Thomas Louzada Santesso**
* **Marcelo Germano Reis** — Graduando em Matemática Aplicada (IME-USP)
* **E-mail:** mgermanoreis@usp.br
* **Currículo Lattes:** [lattes.cnpq.br/5656546908715977](http://lattes.cnpq.br/5656546908715977)

---

## 📁 Estrutura Oficial do Projeto

O projeto foi organizado de forma estritamente modular, em que **cada classe possui sua própria pasta (pacote dedicado)**, separando claramente as responsabilidades de carregamento de dados, topologia, inicialização, otimização, validação geométrica, persistência e exportação 3D.

```text
D:\Marcelo\Documents\IC com Colli\
│
├── standbyalone2.py              # Ponto de entrada oficial (Main pura: perguntas interativas e orquestração)
├── standalone2.py                # Atalho / alias direto para standbyalone2.py
├── faces.txt                     # Base de dados combinatória completa de poliedros (111 sólidos)
├── README.md                     # Este documento explicativo da arquitetura
│
├── dados/                        # [PASTA 1] Carregamento e leitura de dados
│   ├── __init__.py
│   ├── carregador_topologia.py   # Classe CarregadorTopologia (leitura e validação de faces.txt)
│   └── faces.txt                 # Cópia local de dados topológicos
│
├── topologia/                    # [PASTA 2] Análise topológica da malha
│   ├── __init__.py
│   └── orientador_faces.py       # Classe OrientadorFaces (correção BFS de normais e restrições d2)
│
├── condicoes_iniciais/           # [PASTA 3] Geração de coordenadas iniciais
│   ├── __init__.py
│   └── gerador_condicoes.py      # Classe GeradorCondicoesIniciais (Teorema 1 Hipercubo L, Projeção Esferográfica e Perturbação)
│
├── otimizador/                   # [PASTA 4] Otimização numérica dissipativa
│   ├── __init__.py
│   └── otimizador_gradiente.py   # Classe OtimizadorGradiente (Velocity Gradient, Energia Elástica e Hessiana)
│
├── verificadores/                # [PASTA 5] Validação e conferência métrica
│   ├── __init__.py
│   ├── verificador_geometrico.py # Classe VerificadorGeometrico (degenerações, diedrais de Newell e colinearidade)
│   └── isomorfismo.py            # Resolução de Isomorfismo e Isometria métrica via Backtracking (Prof. Colli)
│
├── persistencia/                 # [PASTA 6] Registro e armazenamento de resultados
│   ├── __init__.py
│   └── gerenciador_solucoes.py   # Classe GerenciadorSolucoes (validação de unicidade e gravação JSON/TXT)
│
├── exportadores/                 # [PASTA 7] Visualização 3D e exportação
│   ├── __init__.py
│   └── pythonscad_exportador.py  # Classe ExportadorPythonSCAD (scripts PythonSCAD interativos de mínimos globais)
│
├── ferramentas/                  # Ferramentas auxiliares e scripts Blender
│   ├── blender_addon.py          # Add-on oficial para Blender
│   ├── solido_automatizado.py    # Script de animação e gravação de vídeo via câmera no Blender
│   ├── generalcode.blend         # Cena configurada no Blender (iluminação, câmeras e materiais)
│   ├── calculo_diagonais.py      # Cálculo analítico simbólico (SymPy) de polígonos regulares (5 a 10 lados)
│   ├── verificacao_normal.py     # Script independente para checagem de normais
│   ├── codigo_geral_blender.py   # Script geral para visualização em Blender
│   └── corrigir_faces_separado.py# Utilitário para correção isolada de faces
│
├── notebooks/                    # Ambientes Google Colab e Jupyter
│   ├── gerar_colab_notebook.py   # Gerador automático de notebook completo para o Colab
│   └── Otimizacao_Solidos_Johnson_Colab.ipynb # Notebook pronto com GPU/CPU no Colab
│
└── solidos/                      # Diretório de saída onde são geradas as soluções
    └── <NomeDoSolido>/
        ├── minimos.npy           # Banco binário de soluções inéditas
        ├── pontos.txt            # Histórico de coordenadas dos vértices encontrados
        ├── minimos_locais/       # Mínimos locais (JSON e TXT — uso local, não publicado no site)
        └── minimos_globais/      # Mínimos globais separados por convexidade e autointerseção
            ├── convexos/
            │   ├── sem_autointersecao/  # Mínimos globais convexos válidos -> aba RESULTADOS do site
            │   └── com_autointersecao/  # Registro local (fora do site)
            └── nao_convexos/
                ├── sem_autointersecao/  # Mínimos globais não convexos válidos -> aba DESCOBERTAS do site
                └── com_autointersecao/  # Registro local (fora do site)
```

---

## 🎯 Classes Oficiais e Responsabilidades

### 1. `CarregadorTopologia` (pasta `dados/`)
- Lê o arquivo `faces.txt` contendo a representação de ciclos de cada face e número de vértices.
- Permite verificar a existência de um sólido (`existe_solido(nome)`) e obter sua lista de faces brutas.

### 2. `OrientadorFaces` (pasta `topologia/`)
- **Correção Topológica:** Aplica Busca em Largura (BFS) sobre o grafo dual de adjacência de arestas para garantir coerência de sentido nas faces (normais apontando consistentemente para o exterior).
- **Métrica dos Polígonos:** Calcula o comprimento ideal ao quadrado $d_{ij}^2$ das arestas e diagonais internas para qualquer polígono regular de $n$ lados de aresta unitária:
  $$R = \frac{1}{2 \sin(\pi / n)}, \quad k = \min(|i - j|, n - |i - j|), \quad d_{ij} = 2 R \sin\left(\frac{k \pi}{n}\right)$$
- **Segmentos de Restrição:** Gera a matriz de restrições com todas as arestas e diagonais internas.

### 3. `GeradorCondicoesIniciais` (pasta `condicoes_iniciais/`)
- **Hipercubo Teorema 1:** Calcula o lado mínimo analítico $L$ para amostragem uniforme em $[-L, L]^3$ que garante conter o sólido sem distorção métrica:
  $$L = d_{\max} \cdot \sqrt{V}$$
- **Projeção Esferográfica Tratada:** Gera o grafo topológico planar, calcula o embedding planar e aplica a projeção inversa estereográfica para a esfera unitária $S^2$:
  $$x = \frac{2u}{u^2 + w^2 + 1}, \quad y = \frac{2w}{u^2 + w^2 + 1}, \quad z = \frac{u^2 + w^2 - 1}{u^2 + w^2 + 1}$$
- **Perturbação Cúbica:** Aplica deslocamento aleatório uniforme em cada vértice dentro de um cubo de aresta $\epsilon = 0.1$ para amostras subsequentes (caso a primeira não convirja para o mínimo global).

### 4. `OtimizadorGradiente` (pasta `otimizador/`)
- **Potencial Elástico:** Função objetivo teórica:
  $$E(V) = \frac{1}{2} \sum_{(i,j) \in \text{segmentos}} \left( \|\mathbf{v}_i - \mathbf{v}_j\|^2 - d_{ij}^2 \right)^2$$
- **Gradiente Analítico:** Vetor de forças internas com limitação opcional de passo (`max_step = 0.1`).
- **Sistema Dinâmico Dissipativo (Velocity Gradient):**
  $$\mathbf{v}_{t+1} = \beta \, \mathbf{v}_t - \alpha \, \nabla E(\mathbf{x}_t), \quad \mathbf{x}_{t+1} = \mathbf{x}_t + \mathbf{v}_{t+1}$$
  com taxa de aprendizado $\alpha = 0.01$, amortecimento $\beta = 0.9$ e critério de parada $\|\nabla E\| \le 10^{-14}$.
- **Hessiana e Autovalores:** Diferenças finitas para cálculo da estabilidade do ponto de equilíbrio.

### 5. `VerificadorGeometrico` (pasta `verificadores/`)
- **Distâncias Mútuas:** Vetor ordenado de todas as distâncias entre pares de vértices.
- **Ângulos Diedrais:** Cálculo robusto da normal de Newell para cada face e ângulo diedral orientado ao longo das arestas compartilhadas.
- **Degenerações:** Verificação de volume nulo ($|V| < 10^{-4}$), vértices colapsados ($d_{\min} < 10^{-4}$), faces de área zero ($A < 10^{-5}$) e achatamento do bounding box.
- **Colinearidade em Faces:** Detecção de colinearidade entre quaisquer 3 vértices pertencentes à mesma face.
- **Convexidade Poliédrica (`verificar_convexidade`):** Certificado matemático com 4 critérios independentes (planos suporte, diedrais internos orientados em $[0^\circ, 360^\circ)$, vértices interiores à envoltória convexa e razão volumétrica $|V|/V_{\text{CH}}$).
- **Autointerseção de Faces (`verificar_autointersecao_faces`):** Teste exato 3D par-a-par de triângulos (Möller–Trumbore + recorte coplanar 2D de Sutherland–Hodgman), separando soluções em `sem_autointersecao/` (publicadas no site em Resultados ou Descobertas) e `com_autointersecao/` (mantidas apenas localmente).

### 6. `GerenciadorSolucoes` (pasta `persistencia/`)
- Compara a solução obtida com o histórico salvo em `minimos.npy` (tolerância $10^{-6}$ em distâncias, diedrais e energia).
- Salva dados completos em `.json` e relatório detalhado legível em `.txt`.

### 7. `ExportadorPythonSCAD` (pasta `exportadores/`)
- Exporta scripts PythonSCAD (`.py`) para **mínimos globais** encontrados, aplicando fator de escala 20x e chamada `show(obj)` para visualização interativa instantânea.

---

## 🚀 Como Executar o Programa

O programa principal é executado a partir de:
```bash
python standbyalone2.py
```
*(ou `python standalone2.py`)*

### Fluxo Interativo:
1. **Quantidade de sólidos:** Informar quantos sólidos serão calculados nesta sessão.
2. **Tamanho da amostra:** Número de repetições/amostras para cada sólido (ou pressionar `Enter` para ilimitado).
3. **Identificação do sólido:** Digitar o nome (ex: `J1`, `J86`, `Cube`, `Icosahedron`).
4. **Método de inicialização:**
   - `1`: Hipercubo $[-L, L]^3$ derivado pelo Teorema 1.
   - `2`: Projeção Esferográfica (pura na 1ª tentativa; com perturbação cúbica $\epsilon=0.1$ nas seguintes).
