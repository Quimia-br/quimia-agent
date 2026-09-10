# Arquitetura do Sistema - Kemi

O **quimia-agent** é um backend desenvolvido em **FastAPI** voltado para servir como o motor de inteligência artificial do assistente inteligente **Kemi** em uma aplicação móvel. O sistema utiliza uma arquitetura orquestrada de **múltiplos agentes**, **guardrails de segurança em duas etapas** e **integração com banco de dados PostgreSQL** via ferramentas (*tools*).

---

## 📁 Estrutura de Diretórios

A estrutura do projeto foi organizada de forma modular para garantir a separação clara de responsabilidades, facilitando a escalabilidade, manutenção e testes automatizados.

```text
quimia-agent/
├── app/
│   ├── agent/                      # Core da orquestração de Inteligência Artificial
│   │   ├── guardrails/             # Camadas de segurança e validação
│   │   │   ├── input_guardrail.py  # Filtro de entrada (ofensas, fora de escopo)
│   │   │   └── output_guardrail.py # Filtro de saída (ética, erros de escrita, segurança)
│   │   ├── specialists/            # Agentes especialistas do domínio
│   │   │   ├── químico.py          # Dúvidas químicas, rótulos e compatibilidade
│   │   │   ├── gps.py              # Descarte correto de produtos e localização
│   │   │   └── bau.py              # Catálogo pessoal e histórico de interações
│   │   └── tools/                  # Ferramentas específicas executáveis pelos agentes
│   │       ├── postgres_tool.py    # Consulta e atualização no PostgreSQL
│   │       └── location_tool.py    # Cruzamento de CEP/Bairro/Cidade
│   ├── core/                       # Configurações globais, segurança (JWT) e variáveis (.env)
│   ├── database/                   # Configuração de conexão ORM/Asyncpg com o Postgres
│   ├── routes/                     # Endpoints da API FastAPI (REST & SSE/WebSockets)
│   ├── schemas/                    # Schemas Pydantic para validação de dados
│   ├── services/                   # Serviços de integração e regras de negócio acessórias
│   └── main.py                     # Ponto de entrada da aplicação FastAPI
├── .env                            # Variáveis de ambiente locais
├── .env.example                    # Modelo de variáveis de ambiente
├── .gitignore                      # Arquivos ignorados pelo Git
├── LICENSE                         # Licença do projeto
├── README.md                       # Documentação principal
└── requirements.txt                # Dependências Python do projeto
