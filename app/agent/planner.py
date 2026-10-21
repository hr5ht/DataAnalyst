import json

import pandas as pd
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.agent.intent import Intent, IntentError, check_columns, parse_intent
from app.agent.prompts import PLANNER_PROMPT
from app.analysis.tools import list_columns
from app.llm import invoke_llm
from app.retrieval.glossary import Definition

MAX_QUESTION_LENGTH = 500


def clean_question(question: str) -> str:
    question = question.strip()
    if not question:
        raise IntentError("Ask a question about the dataset.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise IntentError(f"Keep the question under {MAX_QUESTION_LENGTH} characters.")
    return question


def plan_question(
    model: BaseChatModel,
    question: str,
    df: pd.DataFrame,
    definitions: list[Definition] = (),
    feedback: str | None = None,
) -> Intent:
    question = clean_question(question)
    columns = list_columns(df).rows
    messages = build_messages(question, columns, definitions, feedback)
    reply = invoke_llm(model.bind(response_format={"type": "json_object"}), messages)
    intent = parse_intent(reply.content if isinstance(reply.content, str) else "")
    check_columns(intent, [name for name, _ in columns])
    return intent


def build_messages(
    question: str,
    columns: list[list[str]],
    definitions: list[Definition] = (),
    feedback: str | None = None,
) -> list[BaseMessage]:
    listing = json.dumps([{"name": name, "type": kind} for name, kind in columns], ensure_ascii=False)
    parts = [f"Columns:\n{listing}"]
    if definitions:
        glossary = [{"term": d.term, "kind": d.kind, "definition": d.text} for d in definitions]
        parts.append(f"Definitions:\n{json.dumps(glossary, ensure_ascii=False)}")
    parts.append(f"Question: {question}")
    if feedback:
        parts.append(f"Your previous plan was rejected: {feedback}\nReply with a corrected plan.")
    return [SystemMessage(PLANNER_PROMPT), HumanMessage("\n\n".join(parts))]
