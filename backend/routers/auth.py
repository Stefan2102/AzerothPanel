import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import security
from ..deps import get_settings
from ..services import audit
from ..settings import Settings

router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[Depends(security.require_same_origin)])


class LoginBody(BaseModel):
    username: str
    password: str


class ChangePasswordBody(BaseModel):
    current: str
    new: str


def _ip(request: Request) -> str:
    return request.client.host if request.client else "-"


def _set_cookie(request: Request, response: Response, settings: Settings, must_change: bool) -> None:
    token, _ = security.issue_session(settings.session_hours, must_change)
    response.set_cookie(security.SESSION_COOKIE, token, max_age=settings.session_hours * 3600,
                        httponly=True, samesite="strict", path="/", secure=request.url.scheme == "https")


def _signed_in(request: Request) -> dict:
    """Session check that also admits a session still on the default password
    (it may only change the password)."""
    payload = security.session_payload(request.cookies.get(security.SESSION_COOKIE))
    if payload is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return payload


@router.get("/state")
def state(request: Request):
    payload = security.session_payload(request.cookies.get(security.SESSION_COOKIE))
    return {
        "authenticated": payload is not None,
        "username": security.username() if payload else None,
        "must_change_password": bool(payload and payload.get("mc")),
    }


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response, settings: Settings = Depends(get_settings)):
    ip = _ip(request)
    locked = security.login_limiter.locked_for(ip)
    if locked:
        raise HTTPException(status_code=429, detail=f"Too many failed logins. Try again in {locked // 60 + 1} min.")
    if not await asyncio.to_thread(security.verify_credentials, body.username, body.password):
        await asyncio.sleep(1.0)   # slows down guessing
        audit.record(request, "login.failed", f"username '{body.username}'", "WARN", who="-")
        if security.login_limiter.failed(ip):
            audit.record(request, "login.locked", f"{ip} locked for 15 min after repeated failures", "WARN", who="-")
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    security.login_limiter.succeeded(ip)
    must_change = security.is_default_password(body.password)
    _set_cookie(request, response, settings, must_change)
    audit.record(request, "login", "default password, change required" if must_change else "", who=security.username())
    return {"ok": True, "must_change_password": must_change}


@router.post("/logout")
def logout(request: Request, response: Response):
    audit.record(request, "logout")
    response.delete_cookie(security.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/password")
async def change_password(body: ChangePasswordBody, request: Request, response: Response,
                          settings: Settings = Depends(get_settings)):
    _signed_in(request)
    if not await asyncio.to_thread(security.verify_credentials, security.username(), body.current):
        raise HTTPException(status_code=401, detail="Current password is wrong.")
    try:
        security.change_password(body.new)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # The signing key changed, so re-issue this browser's session (others are signed out).
    _set_cookie(request, response, settings, must_change=False)
    audit.record(request, "password.changed", "other sessions signed out", who=security.username())
    return {"ok": True}
