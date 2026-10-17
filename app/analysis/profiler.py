import json
import math
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel

SAMPLE_ROWS = 5
MAX_TEXT_LENGTH = 100
NUMERIC_STATS = ("mean", "std", "min", "median", "max")


class NumericSummary(BaseModel):
    mean: float | None
    std: float | None
    min: float | None
    median: float | None
    max: float | None


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    missing: int
    unique: int
    numeric: NumericSummary | None = None


class DatasetProfile(BaseModel):
    rows: int
    columns: int
    duplicate_rows: int
    column_profiles: list[ColumnProfile]
    sample: list[dict[str, Any]]


def _finite(value: Any) -> float | None:
    if pd.isna(value):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
        return value[:MAX_TEXT_LENGTH] + "..."
    return value


def _numeric_summary(series: pd.Series) -> NumericSummary | None:
    if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return None
    with np.errstate(invalid="ignore"):
        return NumericSummary(**{stat: _finite(getattr(series, stat)()) for stat in NUMERIC_STATS})


def profile_dataset(df: pd.DataFrame) -> DatasetProfile:
    records = json.loads(
        df.head(SAMPLE_ROWS).to_json(orient="records", date_format="iso", default_handler=str)
    )
    return DatasetProfile(
        rows=len(df),
        columns=len(df.columns),
        duplicate_rows=int(df.duplicated().sum()),
        column_profiles=[
            ColumnProfile(
                name=str(name),
                dtype=str(series.dtype),
                missing=int(series.isna().sum()),
                unique=int(series.nunique()),
                numeric=_numeric_summary(series),
            )
            for name, series in df.items()
        ],
        sample=[{key: _clip(value) for key, value in row.items()} for row in records],
    )
