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

1. `python -m app.faq.ingest` lê o PDF e o divide em chunks de 700 caracteres,
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
python -m app.faq.ingest
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