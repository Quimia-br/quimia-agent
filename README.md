# Arquitetura do Sistema - Quimia Kemi

O **quimia-agent** é um backend desenvolvido em **FastAPI** voltado para servir como o motor de inteligência artificial do assistente inteligente **Kemi** em uma aplicação móvel. O sistema utiliza uma arquitetura orquestrada de **múltiplos agentes**, **guardrails de segurança em duas etapas** e persistência híbrida (**PostgreSQL** para dados estruturados/catálogo e **MongoDB** para histórico de sessões/mensagens).

---

## Estrutura de Diretórios e Mapeamento de Arquivos `.py`


```text
quimia-agent/
├── app/
│   ├── agent/                                  # Core de IA e orquestração
│   │   ├── guardrails/                         # Validação da entrada e da resposta final
│   │   │   ├── input_guardrail.py
│   │   │   └── output_guardrail.py
│   │   ├── specialists/                        # Agentes especialistas e suas ferramentas
│   │   │   ├── bau/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── bau_agent.py
│   │   │   │   └── bau_tools.py
│   │   │   ├── faq/
│   │   │   │   ├── faq_agent.py
│   │   │   │   ├── faq_tools.py                # Tool de consulta ao FAQ
│   │   │   │   ├── ingest.py                   # Ingestão do PDF no Qdrant
│   │   │   │   ├── retriever.py                # Recuperação semântica dos chunks
│   │   │   │   └── vectorstore.py              # Clientes de embeddings e Qdrant
│   │   │   ├── gps/
│   │   │   │   ├── __init__.py
│   │   │   │   └── gps_agent.py
│   │   │   ├── quimico/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── quimico_agent.py
│   │   │   │   └── quimico_tools.py
│   │   │   ├── sql_tools.py                    # Execução de consultas parametrizadas
│   │   │   └── tool_agent.py                   # Base para agentes com tools
│   │   ├── base.py                             # Base para agentes com saída estruturada
│   │   ├── contracts.py                        # Contratos Pydantic entre agentes
│   │   ├── jev.py                              # Cliente CommandCode para decisões do JEV
│   │   ├── judge.py                            # Avaliação das respostas com evidências
│   │   ├── llms.py                             # Modelo principal e fallback
│   │   ├── orchestrator.py                     # Classificação de intenção e roteamento
│   │   ├── prompts.py                          # Prompts dos agentes
│   │   ├── summarizer.py                       # Resumo de sessões encerradas
│   │   ├── synthesizer.py                      # Entrega da resposta revisada
│   │   └── workflow.py                         # Grafo de execução LangGraph
│   ├── core/
│   │   └── config.py                           # Configuração e variáveis de ambiente
│   ├── database/
│   │   ├── chat_history.py                     # Persistência e leitura de turnos
│   │   ├── chat_summaries.py                   # Persistência de resumos de sessão
│   │   ├── mongo.py                            # Conexão com MongoDB
│   │   └── postgres.py                         # Conexão com PostgreSQL
│   ├── observability/                          # Métricas SRE e integração com LangSmith
│   │   ├── static/                             # Interface do painel de observabilidade
│   │   │   ├── icon/                           # Ícones SVG e logos do Quimia
│   │   │   │   ├── calendar-fold.svg
│   │   │   │   ├── chevron-left.svg
│   │   │   │   ├── chevron-right.svg
│   │   │   │   ├── geral.svg
│   │   │   │   ├── history.svg
│   │   │   │   ├── logo-quimia-symbol.svg
│   │   │   │   ├── logo-quimia.svg
│   │   │   │   └── puzzle.svg
│   │   │   ├── brand.css                       # Tokens da identidade visual
│   │   │   ├── index.html                      # Estrutura HTML do painel
│   │   │   ├── monitor.css                     # Layout responsivo e temas
│   │   │   └── monitor.js                      # Consulta, visualização e feedback
│   │   ├── __init__.py
│   │   ├── callbacks.py                        # Callbacks de modelos e tools LangChain
│   │   ├── metrics.py                          # SLI, SLO, custos, cenários e ROI
│   │   ├── pricing.json                        # Preços de referência e fontes
│   │   ├── storage.py                          # Exportação, consulta e feedback no LangSmith
│   │   └── telemetry.py                        # Contexto por requisição e tempos das etapas
│   ├── routes/
│   │   ├── chat_routes.py                      # Chat e encerramento de sessão
│   │   ├── health_routes.py                    # Saúde dos serviços
│   │   └── monitor_routes.py                   # Métricas, feedback e arquivos do painel
│   ├── schemas/
│   │   └── schemas.py                          # Schemas de entrada e saída da API
│   └── main.py                                 # Inicialização da aplicação FastAPI
├── data/
│   └── quimia_instrucao_normativa_faq_funcionalidades_v1.0.pdf
├── tests/
│   ├── conftest.py                             # Isolamento do LangSmith nos testes
│   ├── test_agents.py
│   ├── test_chat_sessions.py
│   ├── test_chat_workflow.py
│   ├── test_config.py
│   ├── test_faq.py
│   ├── test_guardrails.py
│   ├── test_health.py
│   ├── test_jev.py
│   ├── test_llms.py
│   ├── test_observability.py                   # Traces, paginação, custos, ROI e privacidade
│   └── test_specialist_tools.py
├── .env
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
├── requirements-dev.txt
└── requirements.txt
```

## FAQ com RAG e Qdrant

O agente de FAQ responde dúvidas gerais sobre o aplicativo mobile, o portal web,
os perfis de uso, as funcionalidades e os limites do Kemi. A fonte autorizada é
`data/quimia_instrucao_normativa_faq_funcionalidades_v1.0.pdf`.

1. `python -m app.agent.specialists.faq` lê o PDF e o divide em chunks de 700 caracteres,
   com sobreposição de 150.
2. O Gemini gera embeddings de 768 dimensões.
3. Os chunks e os metadados de página são armazenados na collection
   `quimia_faq_chunks` do Qdrant.
4. Para cada pergunta, o retriever busca até seis chunks semanticamente
   relacionados.
5. O agente responde apenas com base nas evidências recuperadas. Quando não há
   sustentação suficiente, ele informa que não encontrou a resposta no FAQ.

Configure `GEMINI_API_KEY`, `QDRANT_URL` e, no Qdrant Cloud,
`QDRANT_API_KEY`. Depois execute:

```bash
python -m app.agent.specialists.faq.ingest
```

Rode a ingestão novamente sempre que o PDF oficial for substituído. O script é
idempotente para a collection dedicada: remove os chunks anteriores antes de
inserir a nova versão.

## Ambiente local

O projeto usa Python 3.12. As dependências de produção ficam em
`requirements.txt`; ferramentas de desenvolvimento e testes ficam em
`requirements-dev.txt`.

```bash
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
```

Configure `CORS_ORIGINS` com uma lista de origens web separadas por vírgula.
Como a API aceita credenciais, o curinga `*` não é permitido.

### Modelos dos agentes

Os agentes de chat usam a Provider API da CommandCode com `COMMANDCODE_API_KEY`
e retornam contratos Pydantic. Todos usam `COMMANDCODE_MODEL` (padrão:
`xiaomi/mimo-v2.6-flash`) com `COMMANDCODE_MODEL_FALLBACK` (padrão:
`xiaomi/mimo-v2.6-pro`) quando a chamada principal falha. O fallback usa a mesma
chave e também se aplica às chamadas com ferramentas. A URL raiz
`https://api.commandcode.ai/` é normalizada para `/provider/v1`.
O juiz usa `typesafe/jev-1.14.0` no endpoint `/systemone`, com a mesma chave.
O FAQ ainda usa `GEMINI_API_KEY` para embeddings, pois a Provider API documentada
não oferece um endpoint de embeddings.


## Verificações

- `GET /` confirma que a API iniciou.
- `GET /health/` executa `SELECT 1` no PostgreSQL e `ping` no MongoDB.
- `pytest -q` executa os testes automatizados.

## Observabilidade e SRE do Kemi

Abra `http://127.0.0.1:8000/monitor.html` depois de iniciar a API. A interface usa
os tokens de cores, tipografia e símbolos de `quimia-bd/docs/catalog`.
Os arquivos da interface ficam em `app/observability/static`: HTML, CSS e JavaScript
na raiz; os SVGs ficam em `icon/`. As URLs públicas continuam sendo `/monitor.html`
e `/monitor-assets/`, com os ícones em `/monitor-assets/icon/`.
Ela consulta `GET /monitor` a cada 10 segundos. Não gera mensagens nem consulta
os provedores de IA para atualizar métricas. O painel começa vazio: não há dados de demonstração.

### Coleta e persistência

- `POST /chat`: tempo total do servidor, incluindo validação, histórico MongoDB,
  agentes e persistência da resposta. O header `X-Trace-Id` identifica a operação.
- `POST /chat/sessions/close`: operação de resumo separada, com consumo de modelo.
  Seu custo é incluído no total e amortizado sobre os turnos nas projeções observadas.
- Callbacks `BaseCallbackHandler` do LangChain capturam chamadas de chat e tools,
  modelo solicitado, `usage_metadata`, duração e tipo de erro. A configuração do
  callback acompanha o LangGraph e suas chamadas descendentes.
- Spans próprios registram etapas do grafo, cada especialista, MongoDB, embedding
  Gemini e consulta Qdrant. Os intervalos entre etapas são o tempo entre o fim de
  uma etapa principal e o início da próxima, não latência de rede isolada.
- O JEV usa `/systemone`, fora do cliente de chat LangChain; seu campo `usage`
  é coletado explicitamente. Seu consumo aparece junto aos demais modelos.
- O wrapper de embeddings LangChain não expõe o usage da resposta. Essa chamada
  aparece com consumo/custo desconhecido. Não se estima token por caractere.
- A coleta não grava perguntas, respostas, evidências, prompts, chaves, `user_id`
  ou `session_id`. Erros são gravados apenas pelo nome da classe da exceção.

Os registros e confirmações de resolução ficam no **LangSmith**, no projeto
`LANGSMITH_PROJECT`. Não há banco local, arquivo SQLite ou fallback em disco.
Cada requisição gera um trace raiz, com filhos para etapas, dependências e
chamadas dos modelos. Os callbacks do LangChain alimentam os metadados; a
exportação manual pelo SDK evita enviar estado do grafo, mensagens ou evidências.
O JEV e os embeddings também aparecem nos traces, embora não usem o cliente
LangChain de chat. Tokens e custos conhecidos são enviados no formato
`usage_metadata` do SDK; consumo desconhecido permanece sinalizado.

A leitura do HTML vem da API do LangSmith. Há cache em memória de 30 segundos
para reduzir consultas; não é um armazenamento persistente. Os dados podem levar
alguns segundos para aparecer após a ingestão. O painel agrega até 20.000 traces
raiz por janela e mostra os 100 mais recentes. Confirmações usam a chave de
feedback `quimia.resolved` com score 1 ou 0 e ID determinístico por turno.
Somente os traces desse projeto marcados `quimia-sre-v1` são considerados.

A retenção, as cotas e a disponibilidade dos traces dependem da configuração e
do plano do LangSmith; não há exclusão automática de traces pela aplicação.
A janela de consulta continua sendo de 1, 7 ou 30 dias. Múltiplas instâncias
podem enviar para o mesmo projeto, inclusive o backend usado pelo aplicativo
mobile no Discloud. O indicador “em andamento” permanece restrito ao processo
que atendeu à consulta do painel.

O envio usa o batching em segundo plano do SDK e faz flush no encerramento
normal. Falhas de telemetria não devem impedir respostas do chat. Sem chave ou
com o serviço indisponível, não há armazenamento alternativo: os traces podem
ser perdidos e a consulta de métricas retorna HTTP 503, sem simular sucesso.
Encerramento forçado também pode perder traces que ainda estavam na fila.
Não há migração automática do antigo histórico local.
Ingestão offline do PDF, faturamento dos provedores, disponibilidade de terceiros
e trânsito do navegador até a API não são medidos como operações online.

### SLI, SLO e resultados

- Latência: média, p50, p95 e p99 do `/chat`. Percentis usam nearest-rank.
- Índice de erros: turnos HTTP 5xx ou degradados / total de turnos. Uma falha
  capturada no guardrail de saída é degradada mesmo que a API entregue HTTP 200.
- Erros de validação HTTP 422 aparecem separados; entram no total de requisições.
- Bloqueios legítimos de entrada/saída e rejeições do JEV não são erros técnicos.
- Fallback: chamadas do modelo configurado em `COMMANDCODE_MODEL_FALLBACK`, com
  quantidade de chamadas e de turnos. Erro de uma chamada primária recuperado por
  fallback conta como falha de dependência, mas não como falha do turno.
- Tools: quantidade, tempo e falhas. FAQ: turnos sem evidências.
- SLO inicial: p95 até 8.000 ms e índice de erros até 5%, conforme o roteiro.
  Esses valores são metas configuráveis, não um SLA contratual. O painel sinaliza
  violações; não há envio de alerta para serviços externos.
- Saldo do orçamento de erro: `max(0, quantidade_turnos × limite_erros − erros)`.
  Com poucas amostras, não se deve tomar o percentil como capacidade comprovada.

### Custos e cenários semanais

Preços em USD por milhão de tokens ficam em `app/observability/pricing.json`,
com data da consulta e fontes. Para sobrescrever um preço:

```dotenv
SRE_PRICING_JSON={"xiaomi/mimo-v2.6-flash":{"input":0.14,"output":0.28}}
```

O cálculo é `(tokens_entrada × preço_entrada + tokens_saída × preço_saída) / 1.000.000`.
O custo aferível e a data da tabela são salvos ao encerrar cada operação, para uma
mudança de preços não reavaliar silenciosamente o histórico. Não se aplicam
descontos de cache, franquias gratuitas, multiplicadores de assinatura ou impostos.
São estimativas de tabela, não a fatura. Confira os preços do seu plano.

Uma chamada sem usage ou sem preço é **desconhecida**, não gratuita. São exibidos
subtotal conhecido, cobertura de custo e número de chamadas sem custo aferível.
Falhas/retries do SDK podem consumir tokens sem retornar usage; os callbacks
contam chamadas lógicas, não todas as tentativas HTTP internas do SDK.

Para 100 e 1.000 usuários por semana:

1. `turnos_semanais = usuários × turnos_por_usuário`.
2. Com observações: `custo_turno = custo_conhecido_total / quantidade_turnos_chat`.
   Inclui custos observados de falhas e resumos. Trata-se de extrapolação linear
   do mix observado, não teste de carga nem garantia de capacidade.
3. Sem observações, o painel mostra uma **simulação** com 10.000 tokens de entrada
   e 2.000 de saída por turno, somente do modelo principal. Esses valores são
   premissas editáveis que representam a soma das chamadas de chat de um turno,
   não uma medição. JEV, embeddings e fallback não estão incluídos nessa simulação.
4. `custo_semanal = turnos_semanais × custo_turno + custos_fixos_semanais`.

Cinco turnos por usuário/semana e resolução assumida de 70% são premissas iniciais
do simulador, alteráveis no formulário. Sem confirmações, a taxa de resolução é
uma hipótese explícita. Com confirmações, usa-se `resoluções_confirmadas / todos_os_turnos`;
não se presume que turnos sem feedback foram resolvidos. A cobertura do feedback
também está disponível no JSON.

### Resolução e ROI por tempo economizado

Não se deduz resolução de HTTP 200 nem do veredito do JEV. No painel, abra um turno
de especialista aprovado e registre “Resolveu” ou “Não resolveu”. O registro é
idempotente por turno; trocar a avaliação substitui a anterior. Saudações,
pedidos de esclarecimento, respostas sem evidência, bloqueios, turnos degradados
e erros não podem ser confirmados como resoluções.

`POST /monitor/feedback/{trace_id}` com `{"resolved": true}` faz a mesma operação.
Essa é uma confirmação operacional/manual por turno; não é resolução de caso
com vários turnos ou satisfação coletada automaticamente do usuário final.

- `valor_resolução = minutos_economizados × custo_hora_USD / 60`.
- `benefício = resoluções_confirmadas × valor_resolução`.
- `custo_por_resolução = (custo_conhecido + custos_fixos_proporcionais_à_janela) / resoluções_confirmadas`.
- `ROI = (benefício − custo) / custo`. Sem feedback, benefício configurado ou custo
  positivo, o ROI fica indisponível. Custo parcial torna ROI e custo/resolução
  igualmente parciais. Infraestrutura, bancos e serviços entram no custo fixo
  informado pelo operador; não são consultados em contas externas.

### Acesso e configuração

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=sua_chave_langsmith
LANGSMITH_PROJECT=quimia-agent
# LANGSMITH_WORKSPACE_ID=se_necessario
SRE_LATENCY_P95_MS=8000
SRE_ERROR_RATE_LIMIT=0.05
```

As rotas de dados e feedback aceitam somente conexões loopback, sem token.
A página HTML e os assets são públicos e não contêm telemetria embutida.
Um proxy local pode aparecer como loopback; ao publicar por proxy ou túnel,
restrinja `/monitor` e `/monitor/feedback/` na camada de publicação.

Crie uma chave na sua conta do [LangSmith](https://smith.langchain.com/) e
configure as variáveis somente no servidor. Essa chave é independente das chaves
de IA e nunca é enviada ao JavaScript do painel. O SDK usa o endpoint padrão do LangSmith (`https://api.smith.langchain.com`).
Crie o projeto ou deixe a primeira ingestão criá-lo; em workspaces com agentes,
use em `LANGSMITH_PROJECT` o identificador de projeto compatível do ambiente
(`tracer_session_name`). No Discloud, configure as mesmas variáveis e acompanhe
os traces diretamente no LangSmith autenticado na sua conta. A restrição local
das rotas de dados do HTML permanece independente dessa integração.

`LANGSMITH_TRACING=false` desativa a exportação. Mesmo com a variável ativada,
o middleware desabilita o tracing automático de conteúdo durante `/chat` e
`/chat/sessions/close`: somente a exportação de metadados definida neste módulo
fica ativa. Inputs/outputs do cliente de exportação são ocultados, e erros são
somente classes ou indicações técnicas, sem corpo original da exceção.
Evite adicionar um tracer automático com outro cliente sem revisar os dados
que ele enviaria. As demais chamadas do projeto fora dessas rotas não estão
cobertas por esse contexto de supressão.

Referências oficiais: [consultar traces pelo SDK](https://docs.langchain.com/langsmith/export-traces),
[campos de tokens e custo](https://docs.langchain.com/langsmith/log-llm-trace),
[feedback](https://docs.langchain.com/langsmith/attach-user-feedback) e
[proteção de inputs/outputs](https://docs.langchain.com/langsmith/mask-inputs-outputs).

### Verificação

```powershell
python -m pytest -q tests/test_observability.py
python -m uvicorn app.main:app --reload
```

Abra `/monitor.html`, envie uma mensagem no Swagger e confira o turno e seus
modelos. Uma chamada real a modelos gera custo; a suíte usa HTTP simulado e
testa callbacks reais LangChain/LangGraph, concorrência, falha, fallback,
privacidade, exportação/consulta LangSmith simuladas, feedback, percentis e fórmulas financeiras.

## Tools dos especialistas

Os especialistas estão organizados em `specialists/bau`, `specialists/quimico`,
`specialists/gps` e `specialists/faq`, cada um com seu arquivo de agente.
Químico e Baú têm arquivos próprios de tools; GPS não possui tools.

- Químico: buscar_produto, consultar_composicao_produto,
  verificar_compatibilidade_produtos, consultar_incompatibilidades_produto,
  consultar_primeiros_socorros.
- Baú: listar_estantes_usuario, listar_produtos_estante,
  listar_produtos_por_comodo, consultar_historico_misturas,
  consultar_historico_recomendacoes.
- FAQ: consultar_faq, executada obrigatoriamente antes de responder.
- GPS: agente com LLM e sem tools, com orientação genérica e conservadora, direcionando à Proximidade.

Crie `VaultAgent(user_id=uuid_autenticado)` com a identidade fornecida pelo
backend. O modelo não pode selecionar outro usuário. Todas as consultas são
parametrizadas e somente leitura, com limite de linhas e timeout.
Químico e Baú executam até seis rodadas de tools antes da síntese estruturada.
Compatibilidade usa fn_match_produtos. A tool converte o retorno compativel
(ausência de regra encontrada) em nao_avaliado, informando que não há dados
suficientes no app para confirmar segurança. Incompatibilidades são preservadas. Não há gravação de histórico
pelas tools. As consultas usam FDS ativas; ausência de dados não confirma segurança.
O vínculo de cômodo segue o esquema atual: produto.id_comodo, com verificação
simultânea do dono do cômodo, da estante e da associação do produto.
As datas dos históricos usam início inclusivo e fim exclusivo em ISO 8601;
forneça o fuso America/Sao_Paulo ao converter períodos relativos.


## Chat e grafo

`POST /chat` recebe `user_id` (UUID do usuário), `session_id` e `pergunta`,
e retorna `{"resposta": "..."}`. A pergunta aceita até 4000 caracteres.
Esta rota permite testes locais pelo Swagger em `http://localhost:8000/docs`,
sem autenticação ou token de backend. Use um UUID real do banco para testar o Baú.

Execute `python -m uvicorn app.main:app --reload` e no Swagger selecione
POST /chat -> Try it out. Exemplo de corpo:

```json
{
  "pergunta": "Como funciona a Estante?",
  "session_id": "teste-1",
  "user_id": "00000000-0000-0000-0000-000000000001"
}
```

O fluxo implementado em `app/agent/workflow.py` usa LangGraph:
guardrail de entrada -> orquestrador -> especialistas -> juiz Jev ->
guardrail de saída -> sintetizador -> usuário.
Rotas independentes executam em paralelo; rotas dependentes recebem os resultados
anteriores. Quando uma dependência exige esclarecimento, sua consulta dependente
não é executada. Em saudações e pedidos sem especialista, o orquestrador escreve
a resposta, que passa pelo guardrail de saída e é entregue pelo sintetizador.

O juiz avalia cada resposta de especialista com suas próprias evidências das
tools ou do FAQ. Se não aprovar uma resposta, o turno usa uma mensagem
conservadora. O guardrail de saída preserva a resposta segura sem reescrevê-la
e substitui conteúdo inadequado por uma mensagem genérica. O sintetizador
entrega exatamente o texto aprovado pelo guardrail de saída. Falha técnica
do guardrail de entrada retorna 503, sem simular uma recusa por conteúdo.
Erros em especialistas são tratados como indisponibilidade, não como evidência.

O MongoDB armazena pares de pergunta/resposta em `chat_turns`, com `user_id`,
`session_id`, `pergunta`, `resposta` e `criado_em`. Antes de responder, o chat
recupera até oito turnos anteriores do mesmo usuário e da mesma sessão, em
ordem cronológica, e os envia como contexto ao orquestrador e aos especialistas
que recebem histórico. Cada pergunta e resposta é limitada a 1.000 e 2.000
caracteres no contexto, respectivamente. O histórico ajuda a interpretar a
pergunta atual, mas não serve como evidência técnica sobre produtos ou riscos.
O endpoint `/chat` recebe `user_id` do próprio cliente e não autentica essa
identidade; a integração com o aplicativo precisa validar o usuário antes de
expor o histórico em produção.
O turno só é salvo após o fluxo terminar. Falhas de persistência ou processamento
retornam 503 com uma mensagem pública, sem detalhes de credenciais.
A execução do grafo tem timeout de 180 segundos. Os guardrails de entrada e saída
fazem parte do fluxo; a avaliação do conteúdo dos especialistas é feita pelo juiz Jev.

### Encerramento de sessão

`POST /chat/sessions/close` recebe `user_id` e `session_id` quando o usuário
inicia um novo chat. O agente resume os até 40 turnos mais recentes da sessão
com o modelo rápido e grava o resumo em `chat_summaries` (`user_id`,
`session_id`, `resumo`, `turnos`, `criado_em`). A resposta é
`{"session_id": "...", "status": "..."}`:

- `resumida`: resumo novo salvo;
- `ja_resumida`: a sessão já tinha resumo; nada é refeito nem sobrescrito;
- `sem_turnos`: não havia conversa a resumir; nada é gravado.

Os turnos são enviados ao modelo como dados, não como instruções. Falhas
retornam 503 com mensagem pública. O resumo ainda não é usado como contexto de
novas sessões. Esta rota, como `/chat`, não autentica o `user_id`.
