import pandas as pd

from app.storage import DatasetStore


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def frame(value):
    return pd.DataFrame({"a": [value]})


def test_each_id_returns_its_own_dataset():
    store = DatasetStore(max_datasets=5, ttl_seconds=60)
    first, second = store.add(frame(1)), store.add(frame(2))
    assert first != second
    assert store.get(first)["a"].item() == 1
    assert store.get(second)["a"].item() == 2
    assert store.get("missing") is None


def test_datasets_expire_after_the_idle_time():
    clock = Clock()
    store = DatasetStore(max_datasets=5, ttl_seconds=60, clock=clock)
    kept, dropped = store.add(frame(1)), store.add(frame(2))
    clock.now = 50
    store.get(kept)
    clock.now = 100
    assert store.get(dropped) is None
    assert store.get(kept)["a"].item() == 1
    clock.now = 200
    assert len(store) == 0


def test_least_recently_used_dataset_is_dropped_when_full():
    clock = Clock()
    store = DatasetStore(max_datasets=2, ttl_seconds=60, clock=clock)
    oldest = store.add(frame(1))
    clock.now = 1
    newer = store.add(frame(2))
    clock.now = 2
    store.get(oldest)
    clock.now = 3
    newest = store.add(frame(3))
    assert store.get(newer) is None
    assert store.get(oldest) is not None and store.get(newest) is not None
    assert len(store) == 2
