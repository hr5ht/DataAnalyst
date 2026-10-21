from dataclasses import dataclass
from typing import Literal, TypedDict

import pandas as pd
from langchain_core.language_models import BaseChatModel

from app.agent.intent import Intent
from app.analysis.profiler import DatasetProfile
from app.analysis.tools import TableResult

Status = Literal["answered", "clarify", "unsupported", "error"]


class AnalysisState(TypedDict, total=False):
    question: str
    intent: Intent
    result: TableResult | DatasetProfile
    error: str
    status: Status
    message: str


@dataclass(frozen=True)
class AnalysisContext:
    df: pd.DataFrame
    model: BaseChatModel
