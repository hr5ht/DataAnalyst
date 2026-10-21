import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, field_validator

from app.agent.graph import describe, operation_steps, run_analysis
from app.agent.planner import clean_question
from app.agent.state import AnalysisState, Status
from app.analysis.charts import ChartSpec, chart_for
from app.analysis.profiler import DatasetProfile
from app.analysis.tools import TableResult
from app.api.datasets import find_dataset
from app.auth import Usage, get_usage, require_session, spend
from app.config import Settings, get_settings
from app.llm import LLMError, get_chat_model
from app.retrieval.glossary import Definition, search_glossary
from app.storage import DatasetStore, get_store

router = APIRouter(prefix="/datasets", tags=["questions"], dependencies=[Depends(require_session)])

MAX_TABLE_ROWS = 200
MAX_CELL_LENGTH = 200


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str

    @field_validator("question")
    @classmethod
    def usable_question(cls, value: str) -> str:
        return clean_question(value)


class Operation(BaseModel):
    tool: str
    description: str
    steps: list[str]
    arguments: dict[str, Any]


class Table(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int


class QuestionResponse(BaseModel):
    request_id: str
    question: str
    status: Status
    answer: str
    operation: Operation | None = None
    table: Table | None = None
    chart: ChartSpec | None = None
    definitions: list[Definition] = []
    warnings: list[str] = []


def get_model(settings: Annotated[Settings, Depends(get_settings)]) -> BaseChatModel:
    try:
        return get_chat_model(settings)
    except LLMError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from None


def get_glossary_search() -> Callable[[str, list[str]], list[Definition]] | None:
    return search_glossary


@router.post("/{dataset_id}/questions")
def ask_question(
    dataset_id: str,
    body: QuestionRequest,
    store: Annotated[DatasetStore, Depends(get_store)],
    model: Annotated[BaseChatModel, Depends(get_model)],
    search: Annotated[Callable[[str, list[str]], list[Definition]] | None, Depends(get_glossary_search)],
    settings: Annotated[Settings, Depends(get_settings)],
    usage: Annotated[Usage, Depends(get_usage)],
) -> QuestionResponse:
    df = find_dataset(dataset_id, store)
    spend("questions", settings, usage)
    state = run_analysis(body.question, df, model, search)
    if state.get("provider_error"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, state["message"])
    return build_response(body.question, state)


def build_response(question: str, state: AnalysisState) -> QuestionResponse:
    response = QuestionResponse(
        request_id=uuid.uuid4().hex,
        question=question,
        status=state["status"],
        answer=state["message"],
        definitions=state.get("definitions", []),
        warnings=list(dict.fromkeys(state.get("warnings", []))),
    )
    intent = state.get("intent")
    if intent is None or intent.tool in ("clarify", "unsupported"):
        return response

    response.operation = Operation(
        tool=intent.tool,
        description=describe(intent),
        steps=operation_steps(intent),
        arguments=intent.model_dump(mode="json", exclude={"tool"}),
    )
    result = state.get("result")
    if result is None:
        return response
    table = profile_table(result) if isinstance(result, DatasetProfile) else result
    response.table = Table(
        columns=table.columns,
        rows=[[_clip(cell) for cell in row] for row in table.rows[:MAX_TABLE_ROWS]],
        total_rows=len(table.rows),
    )
    if len(table.rows) > MAX_TABLE_ROWS:
        response.warnings.append(f"The table shows the first {MAX_TABLE_ROWS} of {len(table.rows)} rows.")
    if response.status == "answered":
        response.chart = chart_for(intent.tool, describe(intent), table)
    return response


def profile_table(profile: DatasetProfile) -> TableResult:
    return TableResult(
        columns=["column", "type", "missing", "unique"],
        rows=[[c.name, c.kind, c.missing, c.unique] for c in profile.column_profiles],
    )


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_LENGTH:
        return value[:MAX_CELL_LENGTH] + "..."
    return value
