from fastapi import FastAPI

from app.config import get_settings

app = FastAPI(title="AI Data Analyst")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": get_settings().app_env}
