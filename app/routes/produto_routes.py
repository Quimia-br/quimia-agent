"""Leitura de rótulo por foto, chamada pela API do Quimia na busca de produto pela câmera."""
import asyncio
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.agent.rotulo import ler_rotulo
from app.core.config import carregar_config
from app.observability.telemetry import mark
from app.schemas.schemas import BuscaPorImagemResponse

logger = logging.getLogger(__name__)

TAMANHO_MAXIMO_BYTES = 5 * 1024 * 1024

router = APIRouter(tags=["produtos"])


def tipo_da_imagem(conteudo: bytes) -> str | None:
    """O tipo vem dos primeiros bytes: o `Content-Type` declarado pelo cliente não prova nada."""
    if conteudo.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if conteudo.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.post("/produtos/busca-por-imagem", response_model=BuscaPorImagemResponse)
async def buscar_por_imagem(imagem: UploadFile | None = File(None)) -> BuscaPorImagemResponse:
    """Lê o rótulo da foto e devolve produtos candidatos; a API decide qual deles existe no catálogo.

    A foto não é gravada nem registrada em log. Uma imagem sem rótulo legível é resposta normal, com lista vazia.
    """
    if imagem is None:
        raise HTTPException(400, "Envie a foto do rótulo no campo `imagem`.")
    conteudo = await imagem.read(TAMANHO_MAXIMO_BYTES + 1)
    if not conteudo:
        raise HTTPException(400, "A imagem está vazia.")
    if len(conteudo) > TAMANHO_MAXIMO_BYTES:
        raise HTTPException(413, "A imagem passa de 5 MB.")
    tipo = tipo_da_imagem(conteudo)
    if tipo is None:
        raise HTTPException(415, "Use uma imagem JPEG, PNG ou WebP.")
    try:
        async with asyncio.timeout(carregar_config().rotulo_budget_seconds):
            candidatos = await ler_rotulo(conteudo, tipo)
    except asyncio.TimeoutError:
        logger.warning("Leitura de rótulo acima do orçamento de tempo")
        mark(outcome="timeout")
        raise HTTPException(504, "A leitura do rótulo demorou mais que o esperado. Tente novamente.") from None
    except Exception:
        logger.exception("Falha ao ler o rótulo")
        raise HTTPException(503, "Não foi possível ler o rótulo agora. Tente novamente em instantes.") from None
    return BuscaPorImagemResponse(candidatos=candidatos)
