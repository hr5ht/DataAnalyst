import pytest

from app.config import Settings, get_settings
from app.main import app


@pytest.fixture(autouse=True)
def settings_without_env_file():
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    yield
    app.dependency_overrides.pop(get_settings, None)
