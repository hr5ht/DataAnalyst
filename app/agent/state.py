import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

import pandas as pd
from langchain_core.language_models import BaseChatModel

from app.agent.intent import Intent
from app.analysis.profiler import DatasetProfile
from app.analysis.tools import TableResult
from app.retrieval.glossary import Definition

Status = Literal["answered", "empty", "clarify", "unsupported", "error"]


class AnalysisState(TypedDict, total=False):
    question: str
    definitions: list[Definition]
    intent: Intent | None
    attempts: int
    feedback: str | None
    result: TableResult | DatasetProfile
    answer: str
    error: str
    provider_error: bool
    empty: bool
    warnings: Annotated[list[str], operator.add]
    status: Status
    message: str


@dataclass(frozen=True)
class AnalysisContext:
    df: pd.DataFrame
    model: BaseChatModel
    search_glossary: Callable[[str, list[str]], list[Definition]] | None = None
