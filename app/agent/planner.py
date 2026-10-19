import json

import pandas as pd
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.agent.intent import Intent, IntentError, check_columns, parse_intent
from app.agent.prompts import PLANNER_PROMPT
from app.analysis.tools import list_columns
from app.llm import invoke_llm

MAX_QUESTION_LENGTH = 500


def plan_question(model: BaseChatModel, question: str, df: pd.DataFrame) -> Intent:
    question = question.strip()
    if not question:
        raise IntentError("Ask a question about the dataset.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise IntentError(f"Keep the question under {MAX_QUESTION_LENGTH} characters.")

    columns = list_columns(df).rows
    reply = invoke_llm(model.bind(response_format={"type": "json_object"}), build_messages(question, columns))
    intent = parse_intent(reply.content if isinstance(reply.content, str) else "")
    check_columns(intent, [name for name, _ in columns])
    return intent


def build_messages(question: str, columns: list[list[str]]) -> list[BaseMessage]:
    listing = json.dumps([{"name": name, "type": kind} for name, kind in columns], ensure_ascii=False)
    return [
        SystemMessage(PLANNER_PROMPT),
        HumanMessage(f"Columns:\n{listing}\n\nQuestion: {question}"),
    ]
