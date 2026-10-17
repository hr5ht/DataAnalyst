import pandas as pd

from app.analysis.profiler import profile_dataset
from app.analysis.tools import column_kind


def test_iso_dates_become_datetimes(load):
    df = load("d,t\n2011-01-03,2011-01-03 08:26:00\n,2011-01-04T10:00:00\n")
    assert column_kind(df["d"]) == "datetime"
    assert column_kind(df["t"]) == "datetime"
    assert df["d"].isna().sum() == 1


def test_other_date_formats_and_mixed_values_stay_text(load):
    df = load("us,mixed,code\n01/03/2011,2011-01-03,85123A\n02/03/2011,soon,71053\n")
    assert [column_kind(df[c]) for c in df.columns] == ["text", "text", "text"]


def test_timezone_offsets_are_converted_to_utc(load):
    df = load("t\n2011-01-01T10:00:00+05:30\n")
    assert df["t"].iloc[0] == pd.Timestamp("2011-01-01 04:30:00")


def test_whole_number_floats_become_integers(load):
    df = load("customer,price,empty\n17850,1.5,\n,2.25,\n13047,3,\n")
    assert str(df["customer"].dtype) == "Int64"
    assert df["customer"].tolist()[0] == 17850
    assert str(df["price"].dtype) == "float64"
    assert str(df["empty"].dtype) == "float64"


def test_infinity_keeps_float_type(load):
    assert str(load("v\n1\ninf\n")["v"].dtype) == "float64"


def test_profile_handles_nullable_integers(load):
    profile = profile_dataset(load("customer\n17850\n\n"))
    summary = profile.column_profiles[0].numeric
    assert summary.mean == 17850
    assert summary.std is None
    assert profile.sample[0]["customer"] == 17850
