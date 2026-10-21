from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import faiss
import httpx
import numpy as np
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings

KNOWLEDGE_BASE = Path(__file__).resolve().parents[2] / "knowledge_base"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
DIMENSIONS = 768
BATCH_SIZE = 100
MIN_SCORE = 0.65


class GlossaryError(RuntimeError):
    pass


class Entry(BaseModel):
    term: str = Field(min_length=1)
    kind: Literal["column", "metric", "caveat"]
    text: str = Field(min_length=1)


class Glossary(BaseModel):
    name: str
    columns: list[str] = Field(min_length=1)
    entries: list[Entry] = Field(min_length=1)

    def applies_to(self, columns: list[str]) -> bool:
        return set(self.columns) <= set(columns)


class Definition(BaseModel):
    term: str
    kind: str
    text: str
    glossary: str
    source: str
    score: float


class GeminiEmbedder:
    def __init__(self, api_key: str, model: str, timeout: float):
        self.url = GEMINI_URL.format(model=model)
        self.model = f"models/{model}"
        self.headers = {"x-goog-api-key": api_key}
        self.timeout = timeout

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors += self._embed_batch(texts[start : start + BATCH_SIZE])
        return np.array(vectors, dtype="float32")

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        requests = [
            {"model": self.model, "content": {"parts": [{"text": text}]}, "output_dimensionality": DIMENSIONS}
            for text in texts
        ]
        try:
            response = httpx.post(self.url, headers=self.headers, json={"requests": requests}, timeout=self.timeout)
        except httpx.TimeoutException:
            raise GlossaryError("Gemini took too long to embed the text. Try again.") from None
        except httpx.HTTPError:
            raise GlossaryError("Could not reach Gemini to embed the text. Try again in a moment.") from None
        if response.status_code != 200:
            raise GlossaryError(f"Gemini could not embed the text (HTTP {response.status_code}): {_error_message(response)}")
        return [item["values"] for item in response.json()["embeddings"]]


class GlossaryIndex:
    def __init__(self, glossaries: dict[str, Glossary], model: Any):
        self.glossaries = glossaries
        self.model = model
        self.items = [(source, entry) for source, glossary in glossaries.items() for entry in glossary.entries]
        vectors = self._embed([f"title: {entry.term} | text: {entry.text}" for _, entry in self.items])
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)

    def search(self, question: str, columns: list[str], k: int = 4) -> list[Definition]:
        sources = {source for source, glossary in self.glossaries.items() if glossary.applies_to(columns)}
        if not sources:
            return []
        query = self._embed([f"task: question answering | query: {question}"])
        scores, ids = self.index.search(query, len(self.items))
        found = []
        for score, i in zip(scores[0], ids[0]):
            source, entry = self.items[i]
            if source in sources and score >= MIN_SCORE:
                found.append(
                    Definition(
                        **entry.model_dump(),
                        glossary=self.glossaries[source].name,
                        source=source,
                        score=round(float(score), 3),
                    )
                )
        return found[:k]

    def _embed(self, texts: list[str]) -> np.ndarray:
        try:
            vectors = np.ascontiguousarray(self.model.encode(texts), dtype="float32")
        except GlossaryError:
            raise
        except Exception as error:
            raise GlossaryError(f"Could not embed the text: {error}") from None
        faiss.normalize_L2(vectors)
        return vectors


def load_glossaries(directory: Path = KNOWLEDGE_BASE) -> dict[str, Glossary]:
    glossaries = {}
    for path in sorted(directory.glob("*.json")):
        try:
            glossaries[path.name] = Glossary.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as error:
            raise GlossaryError(f"{path.name} is not a valid glossary ({error.error_count()} problems).") from None
    if not glossaries:
        raise GlossaryError(f"No glossary files found in {directory}.")
    return glossaries


def get_embedder(settings: Settings) -> GeminiEmbedder:
    if settings.gemini_api_key is None:
        raise GlossaryError("GEMINI_API_KEY is not set, so the glossary can't be searched. Add it to .env and restart.")
    return GeminiEmbedder(
        settings.gemini_api_key.get_secret_value(), settings.embedding_model, settings.llm_timeout_seconds
    )


@lru_cache
def get_glossary_index() -> GlossaryIndex:
    return GlossaryIndex(load_glossaries(), get_embedder(get_settings()))


def _error_message(response: httpx.Response) -> str:
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = response.reason_phrase
    return str(message)[:200]
