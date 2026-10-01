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
│   │   ├── chat_routes.py                  # Rotas do chat
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

Os agentes usam `ChatGroq` por meio do LangChain e retornam contratos Pydantic.
Por padrão, Orquestrador e Sintetizador usam `qwen/qwen3.6-27b`, enquanto os
especialistas e o Juiz usam `openai/gpt-oss-120b`. Os modelos podem ser
alterados pelas variáveis `GROQ_FAST_MODEL`, `GROQ_SPECIALIST_MODEL`. Os agentes especialistas tem um fallback para o modelo do
`Gemini` o `gemini-3.6-flash`


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
orquestrador -> especialistas -> sintetizador -> juiz.
Rotas independentes executam em paralelo; rotas dependentes recebem os resultados
anteriores. Quando uma dependência exige esclarecimento, sua consulta dependente
não é executada. Pedidos fora de escopo ou ambíguos seguem para sintetizador e
juiz sem chamar especialistas.

O juiz recebe as evidências das tools e do FAQ. Se pedir revisão, a resposta
volta ao sintetizador uma vez e é julgada novamente. Respostas bloqueadas ou
que continuem sem aprovação são substituídas por uma mensagem conservadora.
Erros em especialistas são tratados como indisponibilidade, não como evidência.

O MongoDB armazena pares de pergunta/resposta em `chat_turns`, particionados
por `user_id` e `session_id`. O histórico não é recuperado nem enviado ao grafo;
a memória com resumo será implementada posteriormente.
O turno só é salvo após o fluxo terminar. Falhas de persistência ou processamento
retornam 503 com uma mensagem pública, sem detalhes de credenciais.
A execução do grafo tem timeout de 180 segundos. Os guardrails separados ainda
não fazem parte deste fluxo; a avaliação final é realizada pelo juiz.
