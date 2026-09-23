# Arquitetura do Sistema - Quimia Kemi

O **quimia-agent** é um backend desenvolvido em **FastAPI** voltado para servir como o motor de inteligência artificial do assistente inteligente **Kemi** em uma aplicação móvel. O sistema utiliza uma arquitetura orquestrada de **múltiplos agentes**, **guardrails de segurança em duas etapas** e persistência híbrida (**PostgreSQL** para dados estruturados/catálogo e **MongoDB** para histórico de sessões/mensagens).

---

## 📁 Estrutura de Diretórios e Mapeamento de Arquivos `.py`


```text
quimia-agent/
└── app/
    ├── __init__.py
    ├── main.py                     # Inicialização do FastAPI, CORS, middlewares, Lifespan e rotas
    │
    ├── agent/                      # Core de Inteligência Artificial e Orquestração
    │   ├── __init__.py
    │   ├── base.py                 # Base LangChain para agentes com saída estruturada
    │   ├── contracts.py            # Contratos Pydantic entre os agentes
    │   ├── llms.py                 # Seleção dos modelos Groq por perfil
    │   ├── prompts.py              # Central de System Prompts de todos os agentes e guardrails
    │   ├── orchestrator.py         # Agente Orquestrador (classificador de intenção e roteador)
    │   ├── synthesizer.py          # Agente Sintetizador (consolida respostas no tom de voz da Kemi)
    │   ├── judge.py                # Agente Juiz (confiabilidade, evidências e segurança)
    │   ├── workflow.py             # Montagem do Grafo conectando todo o fluxo de execução
    │   │
    │   ├── guardrails/             # Barreiras de Segurança e Validação
    │   │   ├── __init__.py
    │   │   ├── input_guardrail.py  # Filtra ofensas, linguagem inadequada e temas fora de escopo
    │   │   └── output_guardrail.py # Valida ética, formatação e segurança da resposta final
    │   │
    │   ├── specialists/            # Agentes Especialistas de Domínio
    │   │   ├── __init__.py
    │   │   ├── quimico_agent.py    # Dúvidas sobre química, rótulos e compatibilidades
    │   │   ├── gps_agent.py        # Orientação de descarte correto e pontos de coleta (CEP/Bairro)
    │   │   └── bau_agent.py        # Consulta ao catálogo pessoal do usuário e interações
    │   │
    │   └── tools/                  # Ferramentas Executáveis pelos Agentes
    │       ├── __init__.py
    │       ├── postgres_tool.py    # Tool de busca no catálogo/produtos no PostgreSQL
    │       └── location_tool.py    # Tool de cruzamento e validação de CEP, Bairro e Cidade
    │
    ├── core/                       # Configurações Globais e Segurança
    │   ├── __init__.py
    │   ├── config.py               # Gestão de variáveis de ambiente (.env) via Pydantic
    │   └── security.py             # Autenticação, validação de tokens JWT e chaves de API
    │
    ├── database/                   # Camada de Persistência Híbrida
    │   ├── __init__.py
    │   ├── postgres.py             # Engine, AsyncSession e conexão com PostgreSQL
    │   ├── mongo.py                # Cliente Motor/Beanie e conexão com MongoDB
    │   ├── models_pg.py            # Modelos relacionais (Catálogo de Produtos, Ecopontos/GPS)
    │   └── models_mongo.py         # Mapeamento de documentos (Histórico de Chat e Sessões)
    │
    ├── routes/                     # Endpoints da API FastAPI
    │   ├── __init__.py
    │   ├── chat_routes.py          # Endpoint POST /chat (recebe requisição do app e dispara o workflow)
    │   └── health_routes.py        # Endpoint GET /health (monitoramento do status dos serviços)
    │
    ├── schemas/                    # Validação de Payloads de Entrada/Saída (Pydantic)
    │   ├── __init__.py
    │   └── schemas.py              # Definição dos Schemas (ChatRequest e ChatResponse)
    │
    └── services/                   # Serviços Auxiliares de Negócio
        ├── __init__.py
        └── chat_service.py         # Camada intermediária de serviços do chat (integração DB/Workflow)
```

## Ambiente local

O projeto usa Python 3.12. As dependências de produção ficam em
`requirements.txt`; ferramentas de desenvolvimento e testes ficam em
`requirements-dev.txt`.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
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