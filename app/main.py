from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import auth
from app.api import datasets, questions
from app.config import Settings, get_settings

app = FastAPI(title="AI Data Analyst")
app.include_router(auth.router)
app.include_router(datasets.router)
app.include_router(questions.router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    problems = []
    for item in error.errors()[:3]:
        message = item["msg"]
        if message.startswith("Value error, "):
            problems.append(message.removeprefix("Value error, "))
        else:
            field = ".".join(str(part) for part in item["loc"] if part != "body")
            problems.append(f"{field}: {message}" if field else message)
    return JSONResponse(status_code=422, content={"detail": " ".join(problems)})


@app.get("/health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str | bool | float]:
    return {
        "status": "ok",
        "env": settings.app_env,
        "llm_configured": settings.groq_api_key is not None,
        "glossary_configured": settings.gemini_api_key is not None,
        "max_upload_mb": settings.max_upload_mb,
    }


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
