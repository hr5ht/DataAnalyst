import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import faiss
import numpy as np
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings

KNOWLEDGE_BASE = Path(__file__).resolve().parents[2] / "knowledge_base"
MODEL_DIR = Path(tempfile.gettempdir()) / "ai-data-analyst-models"
MIN_SCORE = 0.3
MODEL_FILES = ["config.json", "model.safetensors", "tokenizer.json"]


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


class GlossaryIndex:
    def __init__(self, glossaries: dict[str, Glossary], model: Any):
        self.glossaries = glossaries
        self.model = model
        self.items = [(source, entry) for source, glossary in glossaries.items() for entry in glossary.entries]
        vectors = self._embed([f"{entry.term}: {entry.text}" for _, entry in self.items])
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)

    def search(self, question: str, columns: list[str], k: int = 4) -> list[Definition]:
        sources = {source for source, glossary in self.glossaries.items() if glossary.applies_to(columns)}
        if not sources:
            return []
        scores, ids = self.index.search(self._embed([question]), len(self.items))
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


def load_model(name: str) -> Any:
    from huggingface_hub import snapshot_download
    from model2vec import StaticModel

    try:
        return StaticModel.from_pretrained(snapshot_download(name, cache_dir=MODEL_DIR, allow_patterns=MODEL_FILES))
    except Exception as error:
        raise GlossaryError(f"Could not load the embedding model {name}: {error}") from None


@lru_cache
def get_glossary_index() -> GlossaryIndex:
    return GlossaryIndex(load_glossaries(), load_model(get_settings().embedding_model))
