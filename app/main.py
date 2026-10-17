from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import datasets
from app.config import get_settings

app = FastAPI(title="AI Data Analyst")
app.include_router(datasets.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": get_settings().app_env}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
