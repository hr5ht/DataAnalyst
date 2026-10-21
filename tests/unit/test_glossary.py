import json

import httpx
import numpy as np
import pytest

from app.config import Settings
from app.retrieval import glossary
from app.retrieval.glossary import GeminiEmbedder, GlossaryError, GlossaryIndex, get_embedder, load_glossaries

RETAIL = ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID", "Country"]
BIKE = ["dteday", "season", "yr", "mnth", "holiday", "weekday", "workingday", "weathersit", "temp", "cnt"]


class WordModel:
    words = ["revenue", "sales", "customer", "weather", "rentals", "season", "cancel"]

    def encode(self, texts):
        return np.array([[text.lower().count(word) for word in self.words] for text in texts], dtype=float)


class BrokenModel:
    def encode(self, texts):
        raise RuntimeError("out of memory")


@pytest.fixture(scope="module")
def word_index():
    return GlossaryIndex(load_glossaries(), WordModel())


def write(directory, name, data):
    (directory / name).write_text(json.dumps(data), encoding="utf-8")


def test_bundled_glossaries_load():
    glossaries = load_glossaries()
    assert set(glossaries) == {"online_retail.json", "bike_sharing.json"}
    for item in glossaries.values():
        terms = [entry.term for entry in item.entries]
        assert len(terms) == len(set(terms))
        assert set(item.columns) <= set(terms)


def test_only_glossaries_for_the_uploaded_columns_are_searched(word_index):
    found = word_index.search("How did the weather change rentals?", RETAIL)
    assert all(item.source == "online_retail.json" for item in found)
    assert word_index.search("How did the weather change rentals?", ["a", "b"]) == []


def test_results_carry_source_metadata(word_index):
    top = word_index.search("Total sales and revenue", RETAIL)[0]
    assert top.term == "Revenue"
    assert (top.kind, top.glossary, top.source) == ("metric", "UCI Online Retail", "online_retail.json")
    assert 0 < top.score <= 1


def test_results_are_ranked_capped_and_thresholded(word_index, monkeypatch):
    monkeypatch.setattr(glossary, "MIN_SCORE", 0.3)
    found = word_index.search("weather rentals season", BIKE, k=2)
    assert len(found) == 2
    assert found[0].score >= found[1].score
    assert word_index.search("zzz", BIKE) == []


def test_invalid_glossary_names_the_file(tmp_path):
    write(tmp_path, "good.json", {"name": "Good", "columns": ["a"], "entries": [{"term": "a", "kind": "column", "text": "A"}]})
    write(tmp_path, "bad.json", {"name": "Bad", "columns": [], "entries": [{"term": "a", "kind": "guess", "text": ""}]})
    with pytest.raises(GlossaryError, match="bad.json is not a valid glossary"):
        load_glossaries(tmp_path)


def test_empty_knowledge_base_is_an_error(tmp_path):
    with pytest.raises(GlossaryError, match="No glossary files"):
        load_glossaries(tmp_path)


def test_embedding_failure_is_reported():
    with pytest.raises(GlossaryError, match="Could not embed the text: out of memory"):
        GlossaryIndex(load_glossaries(), BrokenModel())


class FakeGemini:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, json, timeout):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def embeddings(count):
    return httpx.Response(200, json={"embeddings": [{"values": [1.0, float(i)]} for i in range(count)]})


@pytest.fixture
def fake_gemini(monkeypatch):
    def install(*responses):
        fake = FakeGemini(*responses)
        monkeypatch.setattr(glossary.httpx, "post", fake)
        return fake

    return install


def test_embedder_sends_key_in_header_and_returns_vectors(fake_gemini):
    fake = fake_gemini(embeddings(2))
    vectors = GeminiEmbedder("gsk_secret", "gemini-embedding-2", 5).encode(["a", "b"])
    assert vectors.shape == (2, 2)
    call = fake.calls[0]
    assert call["url"].endswith("/models/gemini-embedding-2:batchEmbedContents")
    assert "gsk_secret" not in call["url"]
    assert call["headers"] == {"x-goog-api-key": "gsk_secret"}
    assert call["timeout"] == 5
    assert call["json"]["requests"][1] == {
        "model": "models/gemini-embedding-2",
        "content": {"parts": [{"text": "b"}]},
        "output_dimensionality": 768,
    }


def test_embedder_splits_large_inputs_into_batches(fake_gemini):
    fake = fake_gemini(embeddings(100), embeddings(30))
    assert GeminiEmbedder("key", "m", 5).encode([str(i) for i in range(130)]).shape == (130, 2)
    assert [len(call["json"]["requests"]) for call in fake.calls] == [100, 30]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            httpx.Response(400, json={"error": {"message": "API key not valid. Please pass a valid API key."}}),
            r"Gemini could not embed the text \(HTTP 400\): API key not valid",
        ),
        (httpx.Response(429, text="slow down"), r"\(HTTP 429\): Too Many Requests"),
        (httpx.ReadTimeout("timed out"), "took too long"),
        (httpx.ConnectError("no route"), "Could not reach Gemini"),
    ],
)
def test_embedder_failures_are_reported(fake_gemini, response, message):
    fake_gemini(response)
    with pytest.raises(GlossaryError, match=message) as raised:
        GeminiEmbedder("gsk_secret", "m", 5).encode(["a"])
    assert "gsk_secret" not in str(raised.value)


def test_index_keeps_gemini_errors_as_they_are(fake_gemini):
    fake_gemini(httpx.Response(403, json={"error": {"message": "Permission denied."}}))
    with pytest.raises(GlossaryError, match=r"^Gemini could not embed the text \(HTTP 403\): Permission denied.$"):
        GlossaryIndex(load_glossaries(), GeminiEmbedder("key", "m", 5))


def test_missing_gemini_key_is_reported():
    with pytest.raises(GlossaryError, match="GEMINI_API_KEY is not set"):
        get_embedder(Settings(_env_file=None, gemini_api_key=" "))


def test_default_embedding_model_is_gemini():
    assert Settings(_env_file=None).embedding_model == "gemini-embedding-2"
