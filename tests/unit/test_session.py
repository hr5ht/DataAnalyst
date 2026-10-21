from datetime import date

from pydantic import SecretStr

from app.auth import SESSION_SECONDS, Usage, make_token, valid_token
from app.config import Settings


def demo(password="open sesame", username="recruiter"):
    return Settings(_env_file=None, demo_username=username, demo_password=SecretStr(password))


def test_token_is_valid_until_it_expires():
    token = make_token(demo(), now=1000)
    assert valid_token(demo(), token, now=1000 + SESSION_SECONDS - 1)
    assert not valid_token(demo(), token, now=1000 + SESSION_SECONDS)


def test_tampered_or_foreign_tokens_are_rejected():
    token = make_token(demo(), now=1000)
    username, expires, signature = token.rsplit(":", 2)
    assert not valid_token(demo(), f"{username}:{int(expires) + 9999}:{signature}", now=1000)
    assert not valid_token(demo(), f"admin:{expires}:{signature}", now=1000)
    assert not valid_token(demo(), "", now=1000)
    assert not valid_token(demo(), "not-a-token", now=1000)


def test_changing_the_password_signs_everyone_out():
    token = make_token(demo(), now=1000)
    assert not valid_token(demo(password="new password"), token, now=1000)


def test_usernames_with_colons_still_work():
    settings = demo(username="demo:user")
    assert valid_token(settings, make_token(settings, now=1000), now=1000)


def test_usage_caps_each_kind_and_resets_daily():
    day = [date(2026, 1, 1)]
    usage = Usage(today=lambda: day[0])
    assert [usage.take("questions", 2) for _ in range(3)] == [True, True, False]
    assert usage.take("uploads", 1)
    assert usage.used("questions") == 2
    day[0] = date(2026, 1, 2)
    assert usage.used("questions") == 0
    assert usage.take("questions", 2)
