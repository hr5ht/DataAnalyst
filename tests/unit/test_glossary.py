import json

import huggingface_hub
import numpy as np
import pytest

from app.config import Settings
from app.retrieval import glossary
from app.retrieval.glossary import GlossaryError, GlossaryIndex, load_glossaries, load_model

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


def test_results_are_ranked_capped_and_thresholded(word_index):
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


def test_model_that_cannot_load_is_reported(monkeypatch):
    def offline(*args, **kwargs):
        raise OSError("network is unreachable")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", offline)
    with pytest.raises(GlossaryError, match="Could not load the embedding model some/model: network is unreachable"):
        load_model("some/model")


def test_embedding_failure_is_reported():
    with pytest.raises(GlossaryError, match="Could not embed the text: out of memory"):
        GlossaryIndex(load_glossaries(), BrokenModel())


def test_default_model_is_the_small_static_one():
    assert Settings(_env_file=None).embedding_model == "minishlab/potion-base-8M"


@pytest.fixture(scope="module")
def real_index():
    try:
        model = load_model(Settings(_env_file=None).embedding_model)
    except GlossaryError as error:
        pytest.skip(str(error))
    return GlossaryIndex(load_glossaries(), model)


@pytest.mark.parametrize(
    ("question", "columns", "expected"),
    [
        ("What were total sales by country?", RETAIL, "Revenue"),
        ("Which product is best?", RETAIL, "Best-selling product"),
        ("How many orders were cancelled?", RETAIL, "Cancellations and returns"),
        ("Who are our top customers?", RETAIL, "CustomerID"),
        ("How much does the weather affect rentals?", BIKE, "weathersit"),
        ("Are there more rides in summer?", BIKE, "season"),
        ("What is the average temperature in degrees?", BIKE, "temp"),
        ("Do people ride more on working days?", BIKE, "workingday"),
    ],
)
def test_real_model_retrieves_the_relevant_entry(real_index, question, columns, expected):
    assert expected in [item.term for item in real_index.search(question, columns)]


@pytest.mark.parametrize("question", ["What is the capital of France?", "Tell me a joke", "hello"])
def test_real_model_ignores_unrelated_questions(real_index, question):
    assert real_index.search(question, RETAIL + BIKE) == []
