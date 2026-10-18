import io
import uuid
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.analysis.profiler import DatasetProfile, profile_dataset
from app.analysis.tools import normalize_dtypes
from app.config import Settings, get_settings

router = APIRouter(prefix="/datasets", tags=["datasets"])

DATASETS: dict[str, pd.DataFrame] = {}


class DatasetResponse(BaseModel):
    dataset_id: str
    profile: DatasetProfile


class DatasetCreated(DatasetResponse):
    filename: str


def load_csv(raw: bytes, settings: Settings) -> pd.DataFrame:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = None
    if text is None or "\x00" in text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file must be a UTF-8 encoded text CSV.")

    try:
        df = pd.read_csv(io.StringIO(text), nrows=settings.max_rows + 1, low_memory=False)
    except pd.errors.EmptyDataError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty.") from None
    except pd.errors.ParserError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Could not parse the CSV. Check that quotes are closed and rows match the header's field count.",
        ) from None

    if not df.index.equals(pd.RangeIndex(len(df))):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Data rows have more fields than the header.")
    if df.empty:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The CSV has a header but no data rows.")
    if len(df.columns) > settings.max_columns:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"The CSV has more than {settings.max_columns} columns."
        )
    if len(df) > settings.max_rows:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"The CSV has more than {settings.max_rows} rows.")
    return normalize_dtypes(df)


@router.post("", status_code=status.HTTP_201_CREATED)
def upload_dataset(file: UploadFile, settings: Annotated[Settings, Depends(get_settings)]) -> DatasetCreated:
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .csv files are supported.")

    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    raw = file.file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"The file is larger than {settings.max_upload_mb:g} MB."
        )

    df = load_csv(raw, settings)
    dataset_id = uuid.uuid4().hex
    DATASETS[dataset_id] = df
    return DatasetCreated(dataset_id=dataset_id, filename=filename, profile=profile_dataset(df))


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str) -> DatasetResponse:
    df = DATASETS.get(dataset_id)
    if df is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found.")
    return DatasetResponse(dataset_id=dataset_id, profile=profile_dataset(df))
