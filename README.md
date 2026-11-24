# Catajobs

Pipeline diário: busca vagas, filtra, avalia o fit com IA, gera currículo ATS e carta personalizados por vaga, faz a candidatura pelo navegador e atualiza o dashboard.

```
buscar ──> filtro por regras ──> avaliação IA (nota 0-100) ──> CV ATS + carta ──> candidatura (Playwright MCP) ──> dashboard.html
Gupy, LinkedIn,      título, nível,        lotes de 12 vagas          PDF + DOCX + carta.txt     um navegador logado,
Greenhouse, Lever    área, local           por chamada                 em saida/<data>_<vaga>/    uma vaga por vez
```

## Arquitetura

- **Software Python** para o que é determinístico e precisa ser rápido: coleta por API, deduplicação, filtro por regras, banco SQLite (`dados/catajobs.db`), geração de PDF e DOCX, dashboard.
- **Claude Code headless** (`claude -p`) para o que precisa de julgamento: nota de fit, personalização do currículo, carta na sua voz (lê a skill `my-writing-style` a cada execução) e o agente de candidatura que opera o navegador via Playwright MCP em qualquer plataforma.
- Usa a sua assinatura do Claude Code já logada. Não precisa de chave de API.

## Primeira configuração

O jeito mais fácil é o onboarding guiado, que faz as perguntas uma a uma e salva cada resposta na hora:

```
.venv\Scripts\python -m catajobs onboarding
```

1. **Currículo**: importa PDF, DOCX, TXT ou MD (ou cola o texto). Opcionalmente o Claude lê o currículo, organiza em Markdown e sugere as respostas das próximas etapas (Enter aceita a sugestão).
2. **Dados pessoais**: nome, e-mail, telefone, LinkedIn, cidade, estado, nascimento, CPF (com validação e formatação).
3. **Modelo de trabalho**: remoto, híbrido, presencial, cidades aceitas, início, mudança, viagens, visto, CNPJ, liderança.
4. **Remuneração**: pretensão CLT, PJ e em dólar, salário atual, variável.
5. **Formação e idiomas**.
6. **Diversidade** (opcional, aceita "Prefiro não informar").
7. **O que você procura**: cargos buscados, áreas, palavras de área no título, nível mínimo, o que não quer, trilhas, nota mínima, limite diário, criação de conta e um exemplo de escrita para o tom das cartas.

Em qualquer pergunta: `?` explica, `<` volta, `-` deixa em branco, `sair` para (o que já foi respondido fica salvo). Rodando de novo, dá para **revisar/completar** etapas específicas ou **criar um perfil novo** (o anterior vai para `config/backups/`, junto com o histórico de vagas, se você quiser).

O onboarding grava em `config/perfil.yaml`, `config/busca.yaml` (termos, localização, filtros e a seção `perfil_alvo`, usada pela IA na nota de fit), `config/voz.md` e `dados/curriculo_base.md`. Dá para editar esses arquivos à mão também.

Depois do onboarding:

1. Logar o navegador do robô (uma vez, e quando a sessão expirar):
   ```
   .venv\Scripts\python -m catajobs login
   ```
   Faça login no LinkedIn e na Gupy e feche o navegador.
2. Opcional: `python -m catajobs modelos` gera os modelos ATS base (marketing, dados, IA, produto, em PT e EN) em `modelos/`.

## Uso diário

```
.\rodar_diario.ps1                 # tudo, com log em logs\
.\agendar_tarefa.ps1 -Hora 08:00   # agenda no Windows
```

Comandos avulsos: `python -m catajobs buscar | avaliar | personalizar | aplicar --limite 5 | dashboard | status | reabrir | retriar`.

- `aplicar --simular --limite 3`: preenche os formulários sem enviar, para você conferir o comportamento antes de liberar.
- `retriar`: reaplica o filtro por regras depois de mudar `config/busca.yaml`.
- LinkedIn limita a taxa de requisições: quando isso acontece, as vagas entram sem descrição e são completadas nas execuções seguintes.

- `dashboard.html`: abre no navegador. Encontradas, filtradas, com fit, inscritas, o que precisa de você, por dia e por fonte, com link para cada CV e carta.
- **Precisa de você**: CAPTCHA, código por e-mail, login expirado ou cadastro obrigatório. Resolva (ex.: `catajobs login`) e rode `python -m catajobs reabrir` para devolver à fila.

## Regras do agente de candidatura

- Responde só com base no currículo e no `perfil.yaml`. Dado faltando = para e marca "precisa de você".
- Não resolve CAPTCHA, não faz testes da Gupy (perfil, lógica, inglês) e não cria conta em sites, a menos que `permitir_criar_conta: true` e a variável `CATAJOBS_SENHA_ATS` estejam definidas.
- Falha técnica tenta de novo uma vez na execução seguinte.
