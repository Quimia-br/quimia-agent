# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import validar_config
from app.routes.health_routes import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Valida se todas as variáveis obrigatórias (.env) 
    erros = validar_config()
    if erros:
        mensagem = "\n".join(erros)
        raise RuntimeError(f"Erro ao iniciar a aplicação:\n{mensagem}")
    
    print(" Configurações validadas com sucesso!")
    
    yield
    
    print(" Encerrando aplicação...")


app = FastAPI(
    title="Quimia Agent API",
    description="Backend do assistente Kemi com múltiplos agentes e guardrails.",
    version="1.0.0",
    lifespan=lifespan
)

# Configuração de CORS para liberar conexões da aplicação móvel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro das rotas ativas
app.include_router(health_router)


@app.get("/")
async def root():
    return {
        "message": "Quimia Agent API está online."
                }