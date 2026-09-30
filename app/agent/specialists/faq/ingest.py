"""Ingestão do PDF oficial do FAQ no Qdrant.

Execute novamente sempre que o PDF mudar:

    python -m app.faq.ingest
"""

from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from qdrant_client import models

from app.core.config import FAQ_PDF_PATH, AppConfig, carregar_config
from app.agent.specialists.faq.vectorstore import (
    ensure_faq_collection,
    get_embeddings,
    get_qdrant_client,
)

CHUNK_SIZE = 700
CHUNK_OVERLAP = 150
BATCH_SIZE = 50


def _document_id(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load_pdf_pages(path: Path) -> list[Document]:
    reader = PdfReader(path)
    return [
        Document(
            page_content=page.extract_text() or "",
            metadata={"page": index, "source": str(path)},
        )
        for index, page in enumerate(reader.pages)
    ]


def ingest_faq(
    *,
    pdf_path: Path = FAQ_PDF_PATH,
    client=None,
    embeddings=None,
    config: AppConfig | None = None,
) -> int:
    """Divide, vetoriza e substitui os chunks da collection dedicada ao FAQ."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF do FAQ não encontrado: {pdf_path}")

    active_config = config or carregar_config()
    active_client = client or get_qdrant_client()
    active_embeddings = embeddings or get_embeddings()
    ensure_faq_collection(active_client, active_config)

    pages = _load_pdf_pages(pdf_path)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(pages)
    if not chunks:
        raise ValueError("O PDF do FAQ não produziu nenhum trecho indexável.")

    collection = active_client.get_collection(active_config.faq_collection)
    if collection.points_count:
        active_client.delete(
            collection_name=active_config.faq_collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[]),
            ),
            wait=True,
        )

    document_id = _document_id(pdf_path)
    for offset in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[offset : offset + BATCH_SIZE]
        vectors = active_embeddings.embed_documents(
            [chunk.page_content for chunk in batch]
        )
        if len(vectors) != len(batch):
            raise RuntimeError("O provedor retornou uma quantidade inválida de embeddings.")

        points = []
        for local_index, (chunk, vector) in enumerate(zip(batch, vectors)):
            if len(vector) != active_config.embedding_dimension:
                raise RuntimeError(
                    "Dimensão do embedding incompatível com a collection do Qdrant."
                )
            chunk_index = offset + local_index
            page_number = int(chunk.metadata.get("page", 0)) + 1
            points.append(
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, f"{document_id}:{chunk_index}")),
                    vector=vector,
                    payload={
                        "page_content": chunk.page_content,
                        "page_number": page_number,
                        "source": pdf_path.name,
                        "document_id": document_id,
                        "chunk_index": chunk_index,
                    },
                )
            )

        active_client.upsert(
            collection_name=active_config.faq_collection,
            points=points,
            wait=True,
        )

    return len(chunks)


def main() -> None:
    count = ingest_faq()
    print(f"FAQ indexado com sucesso: {count} chunk(s).")


if __name__ == "__main__":
    main()