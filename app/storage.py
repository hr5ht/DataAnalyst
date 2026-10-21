import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from functools import lru_cache

import pandas as pd

from app.config import get_settings


class DatasetStore:
    def __init__(self, max_datasets: int, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.max_datasets = max_datasets
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._items: OrderedDict[str, tuple[float, pd.DataFrame]] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, df: pd.DataFrame) -> str:
        dataset_id = uuid.uuid4().hex
        with self._lock:
            self._drop_expired()
            self._items[dataset_id] = (self.clock(), df)
            while len(self._items) > self.max_datasets:
                self._items.popitem(last=False)
        return dataset_id

    def get(self, dataset_id: str) -> pd.DataFrame | None:
        with self._lock:
            self._drop_expired()
            item = self._items.get(dataset_id)
            if item is None:
                return None
            self._items[dataset_id] = (self.clock(), item[1])
            self._items.move_to_end(dataset_id)
            return item[1]

    def __len__(self) -> int:
        with self._lock:
            self._drop_expired()
            return len(self._items)

    def _drop_expired(self) -> None:
        cutoff = self.clock() - self.ttl_seconds
        while self._items and next(iter(self._items.values()))[0] < cutoff:
            self._items.popitem(last=False)


@lru_cache
def get_store() -> DatasetStore:
    settings = get_settings()
    return DatasetStore(settings.max_datasets, settings.dataset_ttl_minutes * 60)
