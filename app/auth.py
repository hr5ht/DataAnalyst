import hashlib
import hmac
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings

COOKIE = "session"
SESSION_SECONDS = 12 * 60 * 60

Kind = Literal["questions", "uploads"]

router = APIRouter(prefix="/auth", tags=["auth"])


class Usage:
    def __init__(self, today: Callable[[], date] = lambda: datetime.now(UTC).date()):
        self.today = today
        self.day: date | None = None
        self.counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def take(self, kind: Kind, limit: int) -> bool:
        with self._lock:
            self._roll_over()
            if self.counts.get(kind, 0) >= limit:
                return False
            self.counts[kind] = self.counts.get(kind, 0) + 1
            return True

    def used(self, kind: Kind) -> int:
        with self._lock:
            self._roll_over()
            return self.counts.get(kind, 0)

    def _roll_over(self) -> None:
        today = self.today()
        if today != self.day:
            self.day = today
            self.counts = {}


@lru_cache
def get_usage() -> Usage:
    return Usage()


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(max_length=200)
    password: str = Field(max_length=200)


class SessionInfo(BaseModel):
    auth_required: bool
    authenticated: bool
    username: str | None = None
    questions_left: int | None = None
    uploads_left: int | None = None


def auth_enabled(settings: Settings) -> bool:
    return settings.demo_username is not None and settings.demo_password is not None


def make_token(settings: Settings, now: float | None = None) -> str:
    expires = int((time.time() if now is None else now) + SESSION_SECONDS)
    payload = f"{settings.demo_username}:{expires}"
    return f"{payload}:{_sign(settings, payload)}"


def valid_token(settings: Settings, token: str, now: float | None = None) -> bool:
    try:
        payload, signature = token.rsplit(":", 1)
        username, expires = payload.rsplit(":", 1)
        expires_at = int(expires)
    except ValueError:
        return False
    return (
        hmac.compare_digest(signature, _sign(settings, payload))
        and username == settings.demo_username
        and expires_at > (time.time() if now is None else now)
    )


def require_session(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    if auth_enabled(settings) and not valid_token(settings, request.cookies.get(COOKIE, "")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")


def spend(kind: Kind, settings: Settings, usage: Usage) -> None:
    if not auth_enabled(settings):
        return
    limit = _limit(kind, settings)
    if not usage.take(kind, limit):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"The daily limit is {limit} {kind} and today's are used up. It resets at midnight UTC.",
        )


@router.get("/session")
def session(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    usage: Annotated[Usage, Depends(get_usage)],
) -> SessionInfo:
    signed_in = auth_enabled(settings) and valid_token(settings, request.cookies.get(COOKIE, ""))
    return _info(settings, usage, signed_in)


@router.post("/login")
def login(
    body: Credentials,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    usage: Annotated[Usage, Depends(get_usage)],
) -> SessionInfo:
    if not auth_enabled(settings):
        return _info(settings, usage, False)
    username_ok = hmac.compare_digest(body.username.encode(), settings.demo_username.encode())
    password_ok = hmac.compare_digest(body.password.encode(), settings.demo_password.get_secret_value().encode())
    if not (username_ok and password_ok):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password.")
    response.set_cookie(
        COOKIE,
        make_token(settings),
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    return _info(settings, usage, True)


@router.post("/logout")
def logout(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    usage: Annotated[Usage, Depends(get_usage)],
) -> SessionInfo:
    response.delete_cookie(COOKIE)
    return _info(settings, usage, False)


def _info(settings: Settings, usage: Usage, signed_in: bool) -> SessionInfo:
    if not auth_enabled(settings):
        return SessionInfo(auth_required=False, authenticated=True)
    if not signed_in:
        return SessionInfo(auth_required=True, authenticated=False)
    return SessionInfo(
        auth_required=True,
        authenticated=True,
        username=settings.demo_username,
        questions_left=max(0, settings.demo_daily_questions - usage.used("questions")),
        uploads_left=max(0, settings.demo_daily_uploads - usage.used("uploads")),
    )


def _limit(kind: Kind, settings: Settings) -> int:
    return settings.demo_daily_questions if kind == "questions" else settings.demo_daily_uploads


def _sign(settings: Settings, payload: str) -> str:
    key = hashlib.sha256(b"session:" + settings.demo_password.get_secret_value().encode()).digest()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
