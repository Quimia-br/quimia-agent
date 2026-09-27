from types import SimpleNamespace

from langchain_core.runnables import RunnableLambda
from qdrant_client import QdrantClient

from app.agent.contracts import Evidence, FaqResult
from app.agent.specialists.faq.faq_agent import FAQ_NOT_FOUND, FaqAgent
from app.core.config import FAQ_PDF_PATH
from app.agent.specialists.faq.ingest import ingest_faq
from app.agent.specialists.faq.retriever import retrieve_faq_evidence


class FakeChatModel:
    def __init__(self, response):
        self.response = response
        self.last_payload = None

    def with_structured_output(self, _schema):
        def invoke(payload):
            self.last_payload = payload
            return self.response

        return RunnableLambda(invoke)


def test_faq_agent_answers_only_after_retrieval():
    evidence = Evidence(
        source_id="faq:1",
        title="FAQ oficial",
        content="A Proximidade apresenta pontos de descarte próximos.",
        page=4,
    )
    model = FakeChatModel(
        {
            "dominio": "faq",
            "intencao": "consultar",
            "resposta": "A Proximidade apresenta pontos de descarte próximos.",
        }
    )
    agent = FaqAgent(model=model, retriever=lambda _question: [evidence])

    result, used_evidence = agent.invoke_with_evidence(
        "Como funciona a Proximidade?"
    )

    assert result == FaqResult(
        intencao="consultar",
        resposta="A Proximidade apresenta pontos de descarte próximos.",
    )
    assert used_evidence == [evidence]
    assert "página" not in result.resposta
    assert "Proximidade" in str(model.last_payload)


def test_faq_agent_does_not_call_model_without_evidence():
    model = FakeChatModel(
        {
            "dominio": "faq",
            "intencao": "consultar",
            "resposta": "Resposta inventada.",
        }
    )
    agent = FaqAgent(model=model, retriever=lambda _question: [])

    result = agent.invoke("Qual é o plano premium?")

    assert result.resposta == FAQ_NOT_FOUND
    assert model.last_payload is None


def test_retriever_maps_qdrant_payload_to_evidence():
    point = SimpleNamespace(
        id="abc",
        payload={
            "page_content": "A Estante organiza produtos selecionados.",
            "page_number": 3,
            "source": "faq.pdf",
        },
    )

    class FakeEmbeddings:
        def embed_query(self, question):
            assert question == "Como funciona a Estante?"
            return [0.1, 0.2, 0.3]

    class FakeClient:
        def query_points(self, **kwargs):
            assert kwargs["collection_name"] == "faq-test"
            assert kwargs["query"] == [0.1, 0.2, 0.3]
            assert kwargs["limit"] == 4
            assert kwargs["score_threshold"] == 0.5
            return SimpleNamespace(points=[point])

    config = SimpleNamespace(
        faq_collection="faq-test",
        faq_top_k=4,
        faq_score_threshold=0.5,
    )

    result = retrieve_faq_evidence(
        "Como funciona a Estante?",
        client=FakeClient(),
        embeddings=FakeEmbeddings(),
        config=config,
    )

    assert result == [
        Evidence(
            source_id="faq:abc",
            title="Quimia - Instrução Normativa de Uso FAQ de Funcionalidades",
            content="A Estante organiza produtos selecionados.",
            uri="faq.pdf",
            page=3,
        )
    ]


def test_ingest_splits_attached_pdf_and_upserts_page_metadata():
    class FakeEmbeddings:
        def embed_documents(self, texts):
            return [[0.1, 0.2, 0.3] for _text in texts]

    class FakeClient:
        def __init__(self):
            self.upserted = []
            self.created = False

        def collection_exists(self, collection_name):
            assert collection_name == "faq-test"
            return self.created

        def create_collection(self, **kwargs):
            assert kwargs["collection_name"] == "faq-test"
            self.created = True

        def get_collection(self, collection_name):
            assert collection_name == "faq-test"
            return SimpleNamespace(points_count=0)

        def upsert(self, **kwargs):
            assert kwargs["collection_name"] == "faq-test"
            self.upserted.extend(kwargs["points"])

    client = FakeClient()
    config = SimpleNamespace(
        faq_collection="faq-test",
        embedding_dimension=3,
    )

    count = ingest_faq(
        pdf_path=FAQ_PDF_PATH,
        client=client,
        embeddings=FakeEmbeddings(),
        config=config,
    )

    assert count > 7
    assert len(client.upserted) == count
    assert {point.payload["page_number"] for point in client.upserted} == set(
        range(1, 8)
    )
    assert all(point.payload["page_content"] for point in client.upserted)


def test_ingest_and_retrieve_with_in_memory_qdrant():
    class FakeEmbeddings:
        def embed_documents(self, texts):
            return [[1.0, 0.0, 0.0] for _text in texts]

        def embed_query(self, _question):
            return [1.0, 0.0, 0.0]

    client = QdrantClient(":memory:")
    embeddings = FakeEmbeddings()
    config = SimpleNamespace(
        faq_collection="faq-in-memory",
        embedding_dimension=3,
        faq_top_k=3,
        faq_score_threshold=0.0,
    )

    first_count = ingest_faq(
        pdf_path=FAQ_PDF_PATH,
        client=client,
        embeddings=embeddings,
        config=config,
    )
    second_count = ingest_faq(
        pdf_path=FAQ_PDF_PATH,
        client=client,
        embeddings=embeddings,
        config=config,
    )
    evidence = retrieve_faq_evidence(
        "Como funciona o Quimia?",
        client=client,
        embeddings=embeddings,
        config=config,
    )

    assert second_count == first_count
    assert client.get_collection("faq-in-memory").points_count == first_count
    assert evidence
    assert all(item.page is not None for item in evidence)