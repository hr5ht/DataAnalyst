import pytest
from langchain_core.messages import AIMessage

from app.agent.explainer import ExplanationError, build_explain_messages, explain_result, ungrounded_numbers
from app.analysis.tools import TableResult

TABLE = TableResult(
    columns=["period", "sum_Revenue"],
    rows=[["2010-12", 90], ["2011-01", 57.125], ["2011-02", 1184.5]],
    warnings=["Ignored 1 row with a missing Revenue value."],
)


class Reply:
    def __init__(self, text):
        self.text = text

    def invoke(self, messages):
        return AIMessage(self.text)


@pytest.mark.parametrize(
    "text",
    [
        "Revenue peaked in 2011-02 at 1,184.5.",
        "January 2011 brought in 57.13, rounded.",
        "December 2010 had 90 and the table has 3 periods.",
        "There is no number here.",
    ],
)
def test_numbers_from_the_table_are_grounded(text):
    assert ungrounded_numbers(text, [*TABLE.columns, len(TABLE.rows), *TABLE.rows]) == []


@pytest.mark.parametrize(
    ("text", "unknown"),
    [
        ("Revenue grew 1,231.5 in total.", ["1,231.5"]),
        ("That is a 25% rise.", ["25"]),
        ("January was 57.2.", ["57.2"]),
        ("Revenue was -90.", ["-90"]),
    ],
)
def test_invented_numbers_are_caught(text, unknown):
    assert ungrounded_numbers(text, [*TABLE.columns, len(TABLE.rows), *TABLE.rows]) == unknown


def test_numbers_in_the_question_and_step_are_allowed():
    text = "These are the top 5 customers since 2011."
    assert ungrounded_numbers(text, ["Top 5 customers since 2011?", "Top 5 CustomerID by sum of Revenue"]) == []


def test_grounded_explanation_is_returned():
    text = explain_result(Reply("  Revenue peaked in 2011-02 at 1184.5. "), "When?", "Sum of Revenue per month", TABLE)
    assert text == "Revenue peaked in 2011-02 at 1184.5."


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ("", "empty explanation"),
        ("x" * 601, "too long"),
        ("Revenue doubled to 2,369.", "not in the result: 2,369"),
    ],
)
def test_bad_explanations_are_rejected(reply, message):
    with pytest.raises(ExplanationError, match=message):
        explain_result(Reply(reply), "When?", "Sum of Revenue per month", TABLE)


def test_prompt_shows_the_table_warnings_and_cut_off():
    big = TableResult(columns=["n"], rows=[[i] for i in range(40)], warnings=["Showing the first 500 of 900 groups."])
    human = build_explain_messages("How many?", "Row count", big)[1].content
    assert "Result table (first 30 of 40 rows)" in human
    assert '"rows": [[0], [1]' in human and "[30]" not in human
    assert human.endswith("Warnings:\nShowing the first 500 of 900 groups.")
