import io

import pandas as pd
import pytest

from app.analysis.tools import normalize_dtypes

ORDERS = """order_id,country,amount,qty,paid,ordered_at
1,UK,10.5,1,True,2011-01-03
2,France,20,2,False,2011-01-15
3,UK,,3,True,2011-02-01
4,Germany,7.25,1,True,2011-02-20
5,UK,100,10,False,2011-03-05
6,,3,1,True,
"""


def read(text: str) -> pd.DataFrame:
    return normalize_dtypes(pd.read_csv(io.StringIO(text)))


@pytest.fixture
def load():
    return read


@pytest.fixture
def orders():
    return read(ORDERS)
