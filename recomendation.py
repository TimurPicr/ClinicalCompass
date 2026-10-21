import sys
from pathlib import Path

import ollama
import pymupdf
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient, models

EMBED_MODEL = "qwen3-embedding:0.6b"
LLM_MODEL = "qwen3:8b"
COLLECTION = "clinical_guidelines"

db = QdrantClient(path="./qdrant_db")
app = FastAPI()


def embed(text: str):
    return ollama.embed(
        model=EMBED_MODEL,
        input=text
    ).embeddings[0]


def split_text(text, size=1400, overlap=200):
    text = " ".join(text.split())

    for start in range(0, len(text), size - overlap):
        chunk = text[start:start + size]

        if len(chunk) > 100:
            yield chunk


def build_index():
    records = []

    for path in Path(COLLECTION).glob("*.pdf"):
        with pymupdf.open(path) as doc:
            for page_number, page in enumerate(doc, 1):
                for chunk in split_text(page.get_text()):
                    records.append({
                        "text": chunk,
                        "document": path.name,
                        "page": page_number,
                    })

    if not records:
        raise RuntimeError("Не найдены текстовые PDF")

    dimension = len(embed(records[0]["text"]))

    if db.collection_exists(COLLECTION):
        db.delete_collection(COLLECTION)

    db.create_collection(
        collection_name=COLLECTION,
        vectors_config=models.VectorParams(
            size=dimension,
            distance=models.Distance.COSINE,
        ),
    )

    for start in range(0, len(records), 16):
        batch = records[start:start + 16]

        vectors = ollama.embed(
            model=EMBED_MODEL,
            input=[r["text"] for r in batch],
        ).embeddings

        db.upsert(
            collection_name=COLLECTION,
            points=[
                models.PointStruct(
                    id=start + i,
                    vector=list(vector),
                    payload=record,
                )
                for i, (record, vector)
                in enumerate(zip(batch, vectors))
            ],
        )

    print(f"Проиндексировано {len(records)} фрагментов")


class Question(BaseModel):
    question: str = Field(min_length=5)


class Draft(BaseModel):
    answer: str
    source_ids: list[int]
    missing_information: list[str]


@app.post("/recommend")
def recommend(request: Question):
    if not db.collection_exists(COLLECTION):
        raise HTTPException(503, "Индекс пока не создан")

    hits = db.query_points(
        collection_name=COLLECTION,
        query=embed(request.question),
        limit=5,
        with_payload=True,
    ).points

    context = "\n\n".join(
        f"[{i}] {hit.payload['text']}"
        for i, hit in enumerate(hits, 1)
    )

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты медицинский справочный ассистент. "
                    "Используй исключительно предоставленные "
                    "фрагменты клинических документов. "
                    "Не выдумывай рекомендации или дозировки. "
                    "Указывай номера источников [1], [2]. "
                    "Если данных недостаточно, сообщи об этом. "
                    "Не принимай клинических решений за врача."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Вопрос: {request.question}\n\n"
                    f"Документы:\n{context}"
                ),
            },
        ],
        format=Draft.model_json_schema(),
        options={"temperature": 0, "num_ctx": 8192},
    )

    draft = Draft.model_validate_json(
        response.message.content
    )

    valid_ids = set(range(1, len(hits) + 1))

    return {
        "answer": draft.answer,
        "missing_information": draft.missing_information,
        "source_ids": [
            i for i in draft.source_ids if i in valid_ids
        ],
        "sources": [
            {
                "id": i,
                "document": hit.payload["document"],
                "page": hit.payload["page"],
            }
            for i, hit in enumerate(hits, 1)
        ],
        "requires_doctor_review": True,
    }


if __name__ == "__main__" and "--index" in sys.argv:
    build_index()