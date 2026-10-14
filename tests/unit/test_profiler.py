import io
import json

import pandas as pd
import pytest

from app.analysis.profiler import MAX_TEXT_LENGTH, SAMPLE_ROWS, profile_dataset


def frame(text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text))


def column(profile, name):
    return next(c for c in profile.column_profiles if c.name == name)


def test_counts_and_types():
    profile = profile_dataset(frame("city,sales,active\nPune,10,True\nDelhi,20.5,False\nPune,30,True\n"))
    assert (profile.rows, profile.columns) == (3, 3)
    assert column(profile, "sales").dtype == "float64"
    assert column(profile, "city").unique == 2


def test_missing_values_per_column():
    profile = profile_dataset(frame("a,b,c\n1,,x\n2,5,\n,6,\n"))
    assert {c.name: c.missing for c in profile.column_profiles} == {"a": 1, "b": 1, "c": 2}


def test_duplicate_rows():
    profile = profile_dataset(frame("a,b\n1,x\n1,x\n2,y\n1,x\n"))
    assert profile.duplicate_rows == 2


def test_numeric_summary():
    summary = column(profile_dataset(frame("v\n1\n2\n3\n10\n")), "v").numeric
    assert summary.min == 1
    assert summary.max == 10
    assert summary.mean == 4
    assert summary.median == 2.5
    assert summary.std == pytest.approx(4.0825, abs=1e-4)


def test_empty_column_has_null_stats():
    profile = profile_dataset(frame("a,empty\n1,\n2,\n"))
    empty = column(profile, "empty")
    assert empty.missing == 2
    assert empty.unique == 0
    assert empty.numeric.mean is None
    assert empty.numeric.max is None


def test_mixed_types_column_is_not_numeric():
    mixed = column(profile_dataset(frame("v\n1\ntwo\n3\n")), "v")
    assert mixed.numeric is None
    assert mixed.dtype in ("str", "object")


def test_boolean_column_is_not_numeric():
    assert column(profile_dataset(frame("flag\nTrue\nFalse\n")), "flag").numeric is None


def test_infinity_does_not_break_json():
    profile = profile_dataset(frame("v\n1\ninf\n"))
    assert column(profile, "v").numeric.max is None
    assert profile.sample[1]["v"] is None
    json.dumps(profile.model_dump(), allow_nan=False)


def test_sample_is_bounded():
    rows = "\n".join(f"{i},{'x' * 500}" for i in range(50))
    profile = profile_dataset(frame("id,text\n" + rows))
    assert len(profile.sample) == SAMPLE_ROWS
    assert len(profile.sample[0]["text"]) == MAX_TEXT_LENGTH + 3
    assert profile.sample[0]["id"] == 0
