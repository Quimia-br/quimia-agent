# Arquitetura do Sistema - Quimia Kemi

O **quimia-agent** é um backend desenvolvido em **FastAPI** voltado para servir como o motor de inteligência artificial do assistente inteligente **Kemi** em uma aplicação móvel. O sistema utiliza uma arquitetura orquestrada de **múltiplos agentes**, **guardrails de segurança em duas etapas** e persistência híbrida (**PostgreSQL** para dados estruturados/catálogo e **MongoDB** para histórico de sessões/mensagens).

---

## Estrutura de Diretórios e Mapeamento de Arquivos `.py`


```text
quimia-agent/
├── app/
│   ├── agent/                              # Core de IA e orquestração
│   │   ├── guardrails/
│   │   │   ├── input_guardrail.py          # Validação da entrada do usuário
│   │   │   └── output_guardrail.py         # Validação da resposta final
│   │   ├── specialists/                    # Agentes especialistas
│   │   │   ├── faq/
│   │   │   │   ├── faq_agent.py            # Agente de dúvidas gerais do Quimia
│   │   │   │   ├── ingest.py               # Ingestão do PDF no Qdrant
│   │   │   │   ├── retriever.py            # Recuperação semântica dos chunks
│   │   │   │   └── vectorstore.py          # Clientes de embeddings e Qdrant
│   │   │   ├── bau_agent.py                # Consultas pessoais, Estante e histórico
│   │   │   ├── gps_agent.py                # Orientação segura de descarte
│   │   │   └── quimico_agent.py            # Produtos, substâncias e compatibilidade
│   │   ├── base.py                         # Base para agentes com saída estruturada
│   │   ├── contracts.py                    # Contratos Pydantic entre os agentes
│   │   ├── judge.py                        # Avaliação de confiabilidade e segurança
│   │   ├── llms.py                         # Configuração dos modelos de linguagem
│   │   ├── orchestrator.py                 # Classificação de intenção e roteamento
│   │   ├── prompts.py                      # Prompts dos agentes
│   │   ├── synthesizer.py                  # Consolidação das respostas
│   │   └── workflow.py                     # Fluxo de execução dos agentes
│   ├── core/
│   │   └── config.py                       # Configuração e variáveis de ambiente
│   ├── database/
│   │   ├── mongo.py                        # Conexão com MongoDB
│   │   └── postgres.py                     # Conexão com PostgreSQL
│   ├── routes/
│   │   ├── chat_routes.py                  # Rotas do chat e do encerramento de sessão
│   │   └── health_routes.py                # Verificação de saúde dos serviços
│   ├── schemas/
│   │   └── schemas.py                      # Schemas de entrada e saída da API
│   └── main.py                             # Inicialização da aplicação FastAPI
├── data/
│   └── quimia_instrucao_normativa_faq_funcionalidades_v1.0.pdf
├── tests/
│   ├── test_agents.py
│   ├── test_config.py
│   ├── test_faq.py
│   ├── test_health.py
│   └── test_llms.py
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
e retornam contratos Pydantic. Por padrão, os agentes rápidos usam
`Qwen/Qwen3.8-Flash` e os especialistas usam `Qwen/Qwen3.8-27B`. Configure
`COMMANDCODE_FAST_MODEL` e `COMMANDCODE_SPECIALIST_MODEL` para trocar esses modelos.
O juiz usa `typesafe/jev-1.14.0` no endpoint `/systemone`, com a mesma chave.
O FAQ ainda usa `GEMINI_API_KEY` para embeddings, pois a Provider API documentada
não oferece um endpoint de embeddings.


## Verificações

- `GET /` confirma que a API iniciou.
- `GET /health/` executa `SELECT 1` no PostgreSQL e `ping` no MongoDB.
- `pytest -q` executa os testes automatizados.

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
