# Cloudflare Worker — Ponte Automática do Atlas (IC com Colli)

Este Worker permite que **Marcelo, Thomas e Prof. Colli** apenas executem o código oficial `standbyalone2.py` em suas máquinas e os novos mínimos globais validados sejam enviados automaticamente para o repositório `marcelousp13/poliedros-ic-colli` — disparando o GitHub Actions que atualiza o site:

**https://marcelousp13.github.io/poliedros-ic-colli/**

Sem precisar colocar nenhum token do GitHub nas máquinas da equipe!

---

## Como colocar no ar (leva ~3 minutos, 100% gratuito)

### Passo 1 — Criar o Worker no painel do Cloudflare (sem instalar nada)
1. Acesse [dash.cloudflare.com](https://dash.cloudflare.com/) e faça login (conta gratuita).
2. No menu esquerdo, clique em **Compute (Workers) → Workers & Pages → Create → Create Worker**.
3. Dê o nome `poliedros-ic-colli-sync` e clique em **Deploy**.
4. Clique em **Edit code**, apague o código de exemplo e cole todo o conteúdo de `cloudflare_worker/worker.js`.
5. Clique em **Deploy** (canto superior direito).
6. Copie a URL gerada, por exemplo:
   `https://poliedros-ic-colli-sync.SEU-SUBDOMINIO.workers.dev`

### Passo 2 — Configurar os 2 Secrets no Worker
No painel do Worker criado, vá em **Settings → Variables and Secrets → Add**:
1. **Secret 1:**
   - Type: `Secret`
   - Name: `GITHUB_TOKEN`
   - Value: seu Fine-Grained Personal Access Token do GitHub com permissão **Contents: Read and write** apenas no repositório `marcelousp13/poliedros-ic-colli`.
2. **Secret 2:**
   - Type: `Secret`
   - Name: `TEAM_KEY`
   - Value: uma senha simples só da equipe (ex.: `IC-Colli-Poliedros-2026`).
3. *(Opcional)* Variáveis de texto (já têm esses valores como padrão no código):
   - `GITHUB_OWNER` = `marcelousp13`
   - `GITHUB_REPO` = `poliedros-ic-colli`
   - `GITHUB_BRANCH` = `main`

Clique em **Save / Deploy**.

### Passo 3 — Salvar a URL do Worker no repositório
Abra o arquivo `web/config_worker.json` na raiz do projeto e coloque a URL do seu Worker:
```json
{
  "worker_url": "https://poliedros-ic-colli-sync.SEU-SUBDOMINIO.workers.dev",
  "owner": "marcelousp13",
  "repo": "poliedros-ic-colli",
  "branch": "main"
}
```
> Esse arquivo **pode** ir para o GitHub normalmente porque não contém nenhuma senha!

### Passo 4 — Garantir que o GitHub Pages usa o GitHub Actions
No repositório do GitHub (`marcelousp13/poliedros-ic-colli`):
1. Vá em **Settings → Pages**.
2. Em **Build and deployment → Source**, selecione **GitHub Actions**.

Pronto! A partir daí, sempre que você, Thomas ou Prof. Colli rodarem `standbyalone2.py`:
1. Na **1ª execução**, o `standbyalone2.py` pergunta apenas o nome da pessoa e a `TEAM_KEY` (salva localmente em `web/config_github.json`, ignorado pelo Git).
2. Da **2ª execução em diante**, é só dar Play no `standbyalone2.py`: ao final de cada sólido, todos os novos mínimos globais (sem autointerseção) sobem em lote pelo Worker → gravam em `solidos/...` → disparam o GitHub Actions → atualizam o site público automaticamente em ~1 minuto!

---

## Alternativa: Deploy via CLI (Wrangler)
Se preferir via terminal dentro da pasta `cloudflare_worker/`:
```bash
npx wrangler login
npx wrangler deploy
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put TEAM_KEY
```
