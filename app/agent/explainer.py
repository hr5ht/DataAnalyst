import json
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.agent.prompts import EXPLAIN_PROMPT
from app.analysis.tools import TableResult
from app.llm import invoke_llm

PROMPT_ROWS = 30
MAX_ANSWER_LENGTH = 600
NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


class ExplanationError(ValueError):
    pass


def explain_result(model: BaseChatModel, question: str, step: str, table: TableResult) -> str:
    reply = invoke_llm(model, build_explain_messages(question, step, table))
    text = reply.content.strip() if isinstance(reply.content, str) else ""
    if not text:
        raise ExplanationError("The model returned an empty explanation.")
    if len(text) > MAX_ANSWER_LENGTH:
        raise ExplanationError("The explanation was too long.")
    unknown = ungrounded_numbers(text, [question, step, *table.columns, len(table.rows), *table.rows])
    if unknown:
        raise ExplanationError(f"The explanation used numbers that are not in the result: {', '.join(unknown[:3])}.")
    return text


def build_explain_messages(question: str, step: str, table: TableResult) -> list[BaseMessage]:
    shown = table.rows[:PROMPT_ROWS]
    size = f"{len(table.rows)} rows" if len(shown) == len(table.rows) else f"first {len(shown)} of {len(table.rows)} rows"
    parts = [
        f"Question: {question}",
        f"Step that ran: {step}",
        f"Result table ({size}):\n{json.dumps({'columns': table.columns, 'rows': shown}, ensure_ascii=False)}",
    ]
    if table.warnings:
        parts.append("Warnings:\n" + "\n".join(table.warnings))
    return [SystemMessage(EXPLAIN_PROMPT), HumanMessage("\n\n".join(parts))]


def ungrounded_numbers(text: str, evidence: list[Any]) -> list[str]:
    known = set(_numbers(evidence))
    unknown = []
    for token in NUMBER.findall(text):
        value = float(token.replace(",", ""))
        step = 10 ** -len(token.partition(".")[2])
        if not any(abs(value - number) <= step / 2 + 1e-9 for number in known):
            unknown.append(token)
    return unknown


def _numbers(evidence: Any):
    if isinstance(evidence, bool) or evidence is None:
        return
    if isinstance(evidence, (int, float)):
        yield float(evidence)
    elif isinstance(evidence, str):
        for token in NUMBER.findall(evidence):
            yield float(token.replace(",", ""))
    elif isinstance(evidence, (list, tuple)):
        for item in evidence:
            yield from _numbers(item)
