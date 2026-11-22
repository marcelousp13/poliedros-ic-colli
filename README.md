# Sólidos de Johnson — Iniciação Científica (IME-USP)

**Determinação de poliedros de faces regulares por otimização não-linear**  
Instituto de Matemática, Estatística e Ciência da Computação — Universidade de São Paulo (IME-USP)

**Catálogo online (atualizado automaticamente):**  
https://marcelousp13.github.io/poliedros-ic-colli/

---

## Como usar (fluxo completo em 3 passos)

### 1. Instalar dependências (somente se ainda não tiver `numpy`, `scipy` e `networkx`)
No Spyder / Anaconda essas bibliotecas já vêm instaladas. Caso use Python puro:
```bash
pip install -r requirements.txt
```

### 2. Executar o programa principal
Abra e rode **`standbyalone2.py`** (no Spyder, VS Code ou terminal):
```bash
python standbyalone2.py
```

- **Na 1ª execução em um computador novo**, o programa perguntará uma única vez:
  1. `Ativar envio automático para o site do Atlas? [S/n]:` responda **`S`**
  2. `Seu nome:` informe seu nome (ex.: `Thomas` ou `Eduardo Colli`)
  3. `Cole a chave da equipe (TEAM_KEY):` cole a senha compartilhada da equipe
- A configuração fica salva localmente em `web/config_github.json` e não será pedida novamente.

### 3. Acompanhar os resultados no catálogo online
1. Cada mínimo global **sem autointerseção de faces** (convexo ou não convexo) é salvo em `solidos/<Sólido>/minimos_globais/(convexos|nao_convexos)/sem_autointersecao/` com `.json`, `.txt` e `*_pythonscad.py`, incluindo condição inicial (`x₀`), método, amostra atual, tamanho da amostra, energia inicial, iterações e tempo.
2. **Ao final de cada sólido** (inclusive se você interromper com `Ctrl+C`), todos os novos mínimos globais daquele sólido são enviados automaticamente em um único lote ao GitHub (ignorando apenas se outra pessoa já registrou exatamente os mesmos vértices).
3. Em ~1 minuto, o GitHub Actions valida matematicamente, renderiza as imagens PythonSCAD/OpenSCAD e publica a ficha atualizada com visualização 3D interativa em https://marcelousp13.github.io/poliedros-ic-colli/.

*(Mínimos locais e mínimos globais com autointerseção de faces permanecem apenas no registro local em `solidos/`.)*

---

## Estrutura enxuta do projeto

- `standbyalone2.py` — Programa principal de otimização e captura de telemetria
- `dados/` — Base topológica oficial (`faces.txt`) e carregador
- `topologia/` — Orientação de faces e segmentos métricos
- `condicoes_iniciais/` — Hipercubo $L$ (Teorema 1) e Projeção Esferográfica
- `otimizador/` — Otimização por gradiente amortecido e Hessiana
- `verificadores/` — Verificação geométrica, convexidade, autointerseção e isomorfismo
- `persistencia/` — Salvamento `.json`/`.txt` e controle de classes locais
- `exportadores/` — Exportação automática `*_pythonscad.py`
- `web/` — Sincronização automática com o GitHub/Worker e construção do catálogo estático
- `solidos/` — Resultados gravados automaticamente por sólido
