"""YouTube device authorization and the four PUB2 API operations."""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..workspace import atomic_write_json, read_json_dict
from . import PublishError

DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_URL = "https://www.googleapis.com/youtube/v3/"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
SCOPES = "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload"
FULL_SCOPE = "https://www.googleapis.com/auth/youtube"


def default_client():
    return Path.home() / ".local/share/auto-short/youtube-client.json"


def default_token():
    return Path.home() / ".local/share/auto-short/youtube-token.json"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urllib_transport(method, url, headers, body):
    """One HTTP boundary; redirects never forward credentials elsewhere."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, dict(exc.headers), exc.read()


def _credentials(path):
    doc = read_json_dict(Path(path)) or {}
    doc = doc.get("installed", doc)
    if not isinstance(doc, dict) or any(not isinstance(doc.get(k), str) or not doc[k].strip()
                                        for k in ("client_id", "client_secret")):
        raise PublishError("file OAuth client không hợp lệ: cần client_id và client_secret")
    return {k: doc[k] for k in ("client_id", "client_secret")}


def _save_token(path, token):
    """Stage privately so even the atomic writer's temporary file stays private."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".youtube-token-", dir=path.parent) as folder:
        staged = Path(folder) / "token.json"
        atomic_write_json(staged, token)
        staged.chmod(0o600)
        os.replace(staged, path)


def _positive(value, what):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise PublishError(f"phản hồi OAuth thiếu {what} hợp lệ")
    return value


def _token_doc(doc, now, previous=None, scope=None):
    if not isinstance(doc.get("access_token"), str) or not doc["access_token"]:
        raise PublishError("phản hồi OAuth thiếu access token; chạy lại auth")
    refresh = doc.get("refresh_token") or (previous or {}).get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise PublishError("phản hồi OAuth thiếu refresh token; chạy lại auth")
    return dict(access_token=doc["access_token"], refresh_token=refresh,
                expires_at=now + _positive(doc.get("expires_in"), "expires_in"),
                scope=scope or (previous or {}).get("scope", SCOPES))


def _exchange(send, method, url, headers, body):
    try:
        status, _, data = send(method, url, headers, body)
    except (OSError, urllib.error.URLError, ValueError):
        raise PublishError("không kết nối được YouTube / OAuth; hãy thử lại") from None
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeError):
        raise PublishError("phản hồi YouTube / OAuth không phải JSON hợp lệ") from None
    if not isinstance(doc, dict):
        raise PublishError("phản hồi YouTube / OAuth không hợp lệ")
    return status, doc


def _form(send, url, fields):
    return _exchange(send, "POST", url, {"Content-Type": "application/x-www-form-urlencoded"},
                     urllib.parse.urlencode(fields).encode())


def _oauth_error(doc):
    if doc.get("error") == "invalid_grant":
        raise PublishError("phiên OAuth hết hạn hoặc bị thu hồi; chạy lại auth (Testing có thể hết hạn sau 7 ngày)")
    if doc.get("error") in ("expired_token", "access_denied"):
        raise PublishError("mã đăng nhập đã hết hạn hoặc bị từ chối; chạy lại auth")
    raise PublishError("OAuth thất bại; kiểm tra OAuth client và chạy lại auth")


def auth(client_path=None, token_path=None, *, transport=None, sleep=None, now=None, output=print):
    """Authorize on a second device; only the user code and URL are displayed."""
    send, sleep, now = transport or urllib_transport, sleep or time.sleep, now or time.time
    credentials = _credentials(client_path or default_client())
    for scope in (SCOPES, FULL_SCOPE):
        status, device = _form(send, DEVICE_URL, dict(client_id=credentials["client_id"], scope=scope))
        if device.get("error") == "invalid_scope" and scope == SCOPES:
            continue
        if status != 200 or device.get("error"):
            _oauth_error(device)
        if any(not isinstance(device.get(k), str) or not device[k]
               for k in ("device_code", "user_code")):
            raise PublishError("phản hồi OAuth thiếu mã đăng nhập")
        url = device.get("verification_url") or device.get("verification_uri")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise PublishError("phản hồi OAuth thiếu URL xác minh")
        interval = _positive(device.get("interval", 5), "interval")
        deadline = now() + _positive(device.get("expires_in"), "expires_in")
        output(f"Scope: {scope}")
        output(f"Đăng nhập tại {url} — mã: {device['user_code']}")
        while True:
            sleep(max(0, min(interval, deadline - now())))
            if now() >= deadline:
                raise PublishError("mã đăng nhập đã hết hạn; chạy lại auth")
            status, doc = _form(send, TOKEN_URL, dict(credentials, device_code=device["device_code"],
                               grant_type="urn:ietf:params:oauth:grant-type:device_code"))
            if doc.get("error") == "authorization_pending":
                continue
            if doc.get("error") == "slow_down":
                interval += 5
                continue
            if doc.get("error") == "invalid_scope" and scope == SCOPES:
                break
            if status != 200 or doc.get("error"):
                _oauth_error(doc)
            _save_token(token_path or default_token(), _token_doc(doc, now(), scope=scope))
            return {"status": "đã đăng nhập", "scope": scope}


def _api_error(status, doc):
    error = doc.get("error", {})
    errors = error.get("errors", []) if isinstance(error, dict) else []
    errors = errors if isinstance(errors, list) else []
    reasons = {e.get("reason") for e in errors if isinstance(e, dict) and isinstance(e.get("reason"), str)}
    if status == 401:
        raise PublishError("YouTube từ chối đăng nhập sau refresh; chạy lại auth")
    if status == 403 and "quotaExceeded" in reasons:
        raise PublishError("YouTube quotaExceeded: đã hết hạn mức; dừng và chạy lại ngày mai")
    if status == 403 and "forbidden" in reasons:
        raise PublishError("YouTube forbidden: kiểm tra quyền và xác minh kênh để dùng thumbnail tùy chỉnh")
    raise PublishError(f"YouTube trả lỗi HTTP {status}; đã dừng")


class YouTube:
    """Read owned uploads and set thumbnails, refreshing once on HTTP 401."""

    def __init__(self, client_path=None, token_path=None, *, transport=None, now=None):
        self.client_path = client_path or default_client()
        self.token_path = token_path or default_token()
        self.send = transport or urllib_transport
        self.now = now or time.time
        self.token = read_json_dict(Path(self.token_path)) or {}

    def _refresh(self):
        refresh = self.token.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            raise PublishError("chưa có phiên OAuth hợp lệ; chạy lại auth")
        status, doc = _form(self.send, TOKEN_URL, dict(_credentials(self.client_path),
                           grant_type="refresh_token", refresh_token=refresh))
        if status != 200 or doc.get("error"):
            _oauth_error(doc)
        token = _token_doc(doc, self.now(), self.token)
        _save_token(self.token_path, token)
        self.token = token

    def _request(self, method, url, body=None):
        expiry = self.token.get("expires_at", 0)
        if not isinstance(self.token.get("access_token"), str) or not self.token["access_token"] \
                or type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= self.now():
            self._refresh()
        for attempt in range(2):
            headers = {"Authorization": "Bearer " + self.token["access_token"]}
            if body is not None:
                headers["Content-Type"] = "image/jpeg"
            status, doc = _exchange(self.send, method, url, headers, body)
            if status == 401 and attempt == 0:
                self._refresh()
                continue
            if not 200 <= status < 300 or doc.get("error"):
                _api_error(status, doc)
            return doc

    def _list(self, resource, **params):
        return self._request("GET", API_URL + resource + "?" + urllib.parse.urlencode(params))

    def videos(self):
        """Enumerate every uploads page, then request fileDetails in batches of 50."""
        channel = self._list("channels", part="contentDetails", mine="true")
        try:
            uploads = channel["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            if not isinstance(uploads, str) or not uploads:
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise PublishError("không tìm thấy playlist uploads của kênh") from None
        ids, seen_ids, seen_pages, page = [], set(), set(), None
        while True:
            params = dict(part="contentDetails", playlistId=uploads, maxResults=50)
            if page:
                params["pageToken"] = page
            doc = self._list("playlistItems", **params)
            try:
                for item in doc["items"]:
                    ident = item["contentDetails"]["videoId"]
                    if not isinstance(ident, str) or not ident:
                        raise ValueError
                    if ident not in seen_ids:
                        ids.append(ident)
                        seen_ids.add(ident)
            except (KeyError, TypeError, ValueError):
                raise PublishError("danh sách uploads không hợp lệ") from None
            page = doc.get("nextPageToken")
            if not page:
                break
            if not isinstance(page, str) or page in seen_pages:
                raise PublishError("phân trang uploads không hợp lệ")
            seen_pages.add(page)
        result = []
        for offset in range(0, len(ids), 50):
            doc = self._list("videos", part="fileDetails,snippet", id=",".join(ids[offset:offset + 50]))
            if not isinstance(doc.get("items"), list):
                raise PublishError("danh sách video không hợp lệ")
            result.extend(doc["items"])
        return result

    def set_thumbnail(self, youtube_id, body):
        return self._request("POST", UPLOAD_URL + "?" + urllib.parse.urlencode(
            dict(videoId=youtube_id, uploadType="media")), body)
