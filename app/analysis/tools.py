import itertools
import json
import math
import operator
import re
from datetime import date
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

Operation = Literal["sum", "mean", "median", "count", "min", "max"]
SortOrder = Literal["asc", "desc"]
FilterOperator = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "is_null", "not_null"]
Interval = Literal["day", "week", "month", "quarter", "year"]

MAX_RESULT_ROWS = 500
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
PERIOD_FREQ = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
COMPARISONS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}


class AnalysisError(ValueError):
    pass


class TableResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    warnings: list[str] = []


class Condition(BaseModel):
    column: str
    operator: FilterOperator
    value: str | int | float | bool | list[str | int | float] | None = None


Filters = Annotated[list[Condition], Field(default_factory=list, max_length=5)]


class AggregateArgs(BaseModel):
    operation: Operation
    column: str | None = None
    group_by: list[str] = Field(default_factory=list, max_length=3)
    sort: SortOrder | None = "desc"
    filters: Filters


class TopNArgs(BaseModel):
    group_by: str
    operation: Operation = "sum"
    column: str | None = None
    n: int = Field(10, ge=1, le=100)
    sort: SortOrder = "desc"
    filters: Filters


class FilterArgs(BaseModel):
    conditions: list[Condition] = Field(min_length=1, max_length=5)
    columns: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(20, ge=1, le=100)


class CorrelationArgs(BaseModel):
    columns: list[str] = Field(min_length=2, max_length=10)
    method: Literal["pearson", "spearman"] = "pearson"
    filters: Filters


class TrendArgs(BaseModel):
    date_column: str
    interval: Interval = "month"
    operation: Operation = "sum"
    column: str | None = None
    start: date | None = None
    end: date | None = None
    filters: Filters


def column_kind(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "text"


def normalize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    for name in df.columns:
        series = df[name]
        if column_kind(series) == "text":
            dates = _parse_iso_dates(series)
            if dates is not None:
                df[name] = dates
        elif _is_whole_number_float(series):
            df[name] = series.astype("Int64")
    return df


def list_columns(df: pd.DataFrame) -> TableResult:
    return TableResult(
        columns=["column", "type"],
        rows=[[str(name), column_kind(series)] for name, series in df.items()],
    )


def aggregate_data(df: pd.DataFrame, args: AggregateArgs) -> TableResult:
    result, warnings = _aggregate(df, args)
    return _table(*_cap(result, warnings, "groups"))


def get_top_n(df: pd.DataFrame, args: TopNArgs) -> TableResult:
    aggregate = AggregateArgs(
        operation=args.operation,
        column=args.column,
        group_by=[args.group_by],
        sort=args.sort,
        filters=args.filters,
    )
    result, warnings = _aggregate(df, aggregate)
    return _table(result.head(args.n), warnings)


def filter_data(df: pd.DataFrame, args: FilterArgs) -> TableResult:
    _require_columns(df, args.columns)
    _require_distinct(args.columns, "columns")
    matched = apply_filters(df, args.conditions)
    warnings = []
    if matched.empty:
        warnings.append("No rows matched the filters.")
    elif len(matched) > args.limit:
        warnings.append(f"Showing the first {args.limit} of {len(matched)} matching rows.")
    shown = matched[args.columns] if args.columns else matched
    return _table(shown.head(args.limit), warnings)


def compute_correlation(df: pd.DataFrame, args: CorrelationArgs) -> TableResult:
    _require_distinct(args.columns, "columns")
    for column in args.columns:
        _require_numeric(df, column)
    data = apply_filters(df, args.filters)

    rows, warnings = [], []
    for a, b in itertools.combinations(args.columns, 2):
        pair = data[[a, b]].dropna().astype(float)
        value = None
        if len(pair) < 3:
            warnings.append(f"Not enough rows with both {a} and {b} to compute a correlation.")
        else:
            if args.method == "spearman":
                pair = pair.rank()
            with np.errstate(invalid="ignore", divide="ignore"):
                value = float(pair[a].corr(pair[b]))
            if math.isnan(value):
                value = None
                warnings.append(f"{a} or {b} has no variation, so their correlation is undefined.")
        rows.append([a, b, value, len(pair)])
    return TableResult(columns=["column_a", "column_b", "correlation", "rows_used"], rows=rows, warnings=warnings)


def analyze_time_trend(df: pd.DataFrame, args: TrendArgs) -> TableResult:
    _require_columns(df, [args.date_column])
    if column_kind(df[args.date_column]) != "datetime":
        raise AnalysisError(f"Column {args.date_column} is not a date column. Dates must look like YYYY-MM-DD.")
    _require_metric(df, args.operation, args.column)
    if args.start and args.end and args.start > args.end:
        raise AnalysisError("The start date is after the end date.")

    data = apply_filters(df, args.filters)
    warnings = []
    dates = data[args.date_column]
    if missing := int(dates.isna().sum()):
        warnings.append(f"Excluded {_rows(missing)} with a missing {args.date_column} value.")
    in_range = dates.notna()
    if args.start:
        in_range &= dates >= pd.Timestamp(args.start)
    if args.end:
        in_range &= dates < pd.Timestamp(args.end) + pd.Timedelta(days=1)
    data = data[in_range]

    value_name = _value_name(args.operation, args.column)
    if data.empty:
        warnings.append("No rows fall in the selected date range.")
        return TableResult(columns=["period", value_name], rows=[], warnings=warnings)
    warnings += _ignored_values(data, args.column)

    periods = data[args.date_column].dt.to_period(PERIOD_FREQ[args.interval])
    grouped = data.groupby(periods)
    values = grouped.size() if args.column is None else _reduce(grouped[args.column], args.operation)
    labels = [_period_label(p, args.interval) for p in values.index]
    result = pd.DataFrame({"period": labels, value_name: values.reset_index(drop=True)})
    return _table(*_cap(result, warnings, "periods"))


def apply_filters(df: pd.DataFrame, conditions: list[Condition]) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for condition in conditions:
        mask &= _condition_mask(df, condition)
    return df[mask]


def _aggregate(df: pd.DataFrame, args: AggregateArgs) -> tuple[pd.DataFrame, list[str]]:
    _require_columns(df, args.group_by)
    _require_distinct(args.group_by, "group_by")
    _require_metric(df, args.operation, args.column)

    filtered = apply_filters(df, args.filters)
    data = filtered.dropna(subset=args.group_by) if args.group_by else filtered
    warnings = []
    if excluded := len(filtered) - len(data):
        warnings.append(f"Excluded {_rows(excluded)} with a missing {', '.join(args.group_by)} value.")
    warnings += _ignored_values(data, args.column)

    value_name = _value_name(args.operation, args.column)
    if args.group_by:
        grouped = data.groupby(args.group_by, sort=True)
        values = grouped.size() if args.column is None else _reduce(grouped[args.column], args.operation)
        result = values.rename(value_name).reset_index()
        if args.sort:
            result = result.sort_values(
                value_name, ascending=args.sort == "asc", kind="stable", na_position="last"
            )
        if result.empty:
            warnings.append("No rows matched the filters.")
    else:
        value = len(data) if args.column is None else _reduce(data[args.column], args.operation)
        result = pd.DataFrame({value_name: [value]})
    return result, warnings


def _condition_mask(df: pd.DataFrame, condition: Condition) -> pd.Series:
    _require_columns(df, [condition.column])
    series = df[condition.column]
    op, value, name = condition.operator, condition.value, condition.column
    if op == "is_null":
        return series.isna()
    if op == "not_null":
        return series.notna()
    if value is None:
        raise AnalysisError(f"The {op} filter on {name} needs a value.")

    kind = column_kind(series)
    if op == "contains":
        if kind != "text" or not isinstance(value, str):
            raise AnalysisError("The contains filter only works on text columns with a text value.")
        return series.str.contains(value, case=False, regex=False, na=False)
    if op == "in":
        if not isinstance(value, list) or not value:
            raise AnalysisError(f"The in filter on {name} needs a non-empty list of values.")
        return series.isin([_coerce(v, kind, name) for v in value])
    if isinstance(value, list):
        raise AnalysisError(f"The {op} filter on {name} takes a single value, not a list.")
    if op in ("gt", "gte", "lt", "lte") and kind not in ("numeric", "datetime"):
        raise AnalysisError(f"Column {name} is {kind}, so it can only be filtered with eq, ne, in or contains.")
    matches = COMPARISONS[op](series, _coerce(value, kind, name)).fillna(False).astype(bool)
    return matches & series.notna()


def _coerce(value: Any, kind: str, column: str) -> Any:
    if kind == "numeric":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AnalysisError(f"Column {column} is numeric, so filter values must be numbers.")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise AnalysisError(f"Column {column} is true/false, so filter values must be true or false.")
        return value
    if kind == "datetime":
        if not isinstance(value, str) or not ISO_DATE.match(value):
            raise AnalysisError(f"Column {column} holds dates, so filter values must look like YYYY-MM-DD.")
        try:
            return pd.Timestamp(value)
        except ValueError:
            raise AnalysisError(f"{value} is not a valid date.") from None
    if not isinstance(value, str):
        raise AnalysisError(f"Column {column} is text, so filter values must be text.")
    return value


def _parse_iso_dates(series: pd.Series) -> pd.Series | None:
    present = series.dropna()
    if present.empty or not ISO_DATE.match(str(present.iloc[0])):
        return None
    try:
        dates = pd.to_datetime(series, format="ISO8601")
    except (ValueError, TypeError, OverflowError):
        return None
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert(None)
    return dates


def _is_whole_number_float(series: pd.Series) -> bool:
    if not pd.api.types.is_float_dtype(series):
        return False
    present = series.dropna()
    return not present.empty and present.abs().max() < 2**53 and bool((present % 1 == 0).all())


def _period_label(period: pd.Period, interval: str) -> str:
    if interval == "week":
        return period.start_time.date().isoformat()
    return str(period)


def _reduce(values: Any, operation: str) -> Any:
    if operation == "sum":
        return values.sum(min_count=1)
    return values.agg(operation)


def _require_metric(df: pd.DataFrame, operation: str, column: str | None) -> None:
    if operation == "count":
        if column is not None:
            _require_columns(df, [column])
    elif column is None:
        raise AnalysisError(f"The {operation} operation needs a numeric column.")
    else:
        _require_numeric(df, column)


def _ignored_values(data: pd.DataFrame, column: str | None) -> list[str]:
    if column is None:
        return []
    ignored = int(data[column].isna().sum())
    return [f"Ignored {_rows(ignored)} with a missing {column} value."] if ignored else []


def _value_name(operation: str, column: str | None) -> str:
    return f"{operation}_{column}" if column else "count"


def _cap(result: pd.DataFrame, warnings: list[str], noun: str) -> tuple[pd.DataFrame, list[str]]:
    if len(result) > MAX_RESULT_ROWS:
        warnings.append(f"Showing the first {MAX_RESULT_ROWS} of {len(result)} {noun}.")
        result = result.head(MAX_RESULT_ROWS)
    return result, warnings


def _rows(count: int) -> str:
    return f"{count} row" if count == 1 else f"{count} rows"


def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    unknown = [c for c in columns if c not in df.columns]
    if unknown:
        raise AnalysisError(f"Unknown column: {', '.join(unknown)}.")


def _require_distinct(columns: list[str], field: str) -> None:
    if len(set(columns)) != len(columns):
        raise AnalysisError(f"The same column appears more than once in {field}.")


def _require_numeric(df: pd.DataFrame, column: str) -> None:
    _require_columns(df, [column])
    if column_kind(df[column]) != "numeric":
        raise AnalysisError(f"Column {column} is not numeric.")


def _table(frame: pd.DataFrame, warnings: list[str]) -> TableResult:
    data = json.loads(frame.to_json(orient="split", index=False, date_format="iso"))
    return TableResult(columns=[str(c) for c in data["columns"]], rows=data["data"], warnings=warnings)
