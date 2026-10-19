from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import datasets
from app.config import Settings, get_settings

app = FastAPI(title="AI Data Analyst")
app.include_router(datasets.router)


@app.get("/health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str | bool]:
    return {"status": "ok", "env": settings.app_env, "llm_configured": settings.groq_api_key is not None}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
