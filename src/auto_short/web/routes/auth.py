"""Auth routes extracted from the app factory."""

from __future__ import annotations

import asyncio
import html
import json
import logging
from urllib.parse import parse_qs

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..auth import COOKIE_NAME
from ..context import WebContext

log = logging.getLogger("auto_short")
LOGIN_DELAY = 1.0  # seconds to wait after a wrong password


def _safe_next(value: str | None) -> str:
    """Only same-site absolute paths (no ``//host`` or backslash tricks)."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value \
            or any(ord(c) < 32 for c in value):
        return "/"
    return value


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    def _login_page(days: int, error: str | None = None, next_path: str = "/", status: int = 200) -> HTMLResponse:
        page = (ctx.static_dir / "login.html").read_text(encoding="utf-8").replace("{{days}}", str(days))
        page = page.replace("{{next}}", html.escape(next_path, quote=True))
        page = page.replace("{{error}}", f'<p class="error">{html.escape(error)}</p>' if error else "")
        return HTMLResponse(page, status_code=status)

    @router.get("/login")
    async def login_form(request: Request, next: str = "/"):
        if ctx.signer.verify(request.cookies.get(COOKIE_NAME)):
            return RedirectResponse(_safe_next(next), status_code=303)
        return _login_page(ctx.config.web.session_days, next_path=_safe_next(next))

    @router.post("/login")
    async def login(request: Request):
        body = await request.body()
        if len(body) > 4096:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        is_json = request.headers.get("content-type", "").startswith("application/json")
        try:
            if is_json:
                data = json.loads(body or b"{}")
                password, next_path = str(data.get("password", "")), data.get("next")
            else:
                form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                password, next_path = (form.get("password") or [""])[0], (form.get("next") or [None])[0]
        except (ValueError, AttributeError):
            password, next_path = "", None
        next_path = _safe_next(next_path)
        if not ctx.signer.check_password(password):
            await asyncio.sleep(LOGIN_DELAY)
            log.warning("web: failed login from %s", request.client.host if request.client else "?")
            if is_json:
                return JSONResponse({"detail": "sai mật khẩu"}, status_code=401)
            return _login_page(ctx.config.web.session_days, "Sai mật khẩu.", next_path, status=401)
        response = (JSONResponse({"ok": True}) if is_json else RedirectResponse(next_path, status_code=303))
        response.set_cookie(COOKIE_NAME, ctx.signer.issue(), max_age=ctx.signer.max_age, httponly=True, samesite="lax",
                            path="/")
        log.info("web: login from %s", request.client.host if request.client else "?")
        return response

    @router.post("/logout")
    async def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
        return response

    return router
