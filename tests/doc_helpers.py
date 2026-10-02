"""CP8.19 helpers: a synthetic lecture page (shape of ph.tinhtong.vn: ``#bodytext`` + a gzip continuation link) and a
fake opener, so nothing touches the network."""

from __future__ import annotations

import gzip
import io
import json
import socket
from pathlib import Path

BASE_URL = "https://ph.tinhtong.vn/Home/KinhThu?d=KinhThu_001.html"
GZ_PATH = "/html-end/KinhThu/KinhThu_001.gz.z?v=abc123"

HEAD_PARAGRAPHS = [
    "Chúng ta học Phật đã nhiều năm, vậy bạn rốt cuộc có giác ngộ hay không? Không thể nói là không có. Có! "
    "Nhưng chỉ là chút ít thôi, hay nói cách khác, đối với thế gian cùng xuất thế gian pháp không quá mê hoặc. "
    "Không mê chính là không bị nó xoay chuyển.",
    "Tâm thanh tịnh là gốc của mọi công đức. Người thông thường sáu căn tiếp xúc với cảnh giới sáu trần sẽ khởi tâm "
    "động niệm, sinh ra vô số vọng tưởng, phân biệt và chấp trước. Đại đức xưa thường nói: “ Cảnh giới tu tập mỗi "
    "năm không như nhau ”, cho nên phải đem những chỗ ngộ mới nêu ra cùng chia sẻ.",
]
GZ_PARAGRAPHS = [
    "Đồng tu cần nhớ, tâm thanh tịnh là gốc của mọi công đức, cũng là gốc của vãng sanh. Nếu hủy báng Tam bảo thì tự "
    "mình chuốc lấy quả báo. Cho nên mỗi ngày chúng ta phải niệm Phật, không để tâm chạy theo cảnh giới bên ngoài. "
    "A Di Đà Phật!",
]


def page_html(paragraphs: list[str] = HEAD_PARAGRAPHS, *, gz_path: str | None = GZ_PATH) -> str:
    head = ('<html><head><title>x</title>' + (f'<link rel="preload" href="{gz_path}" as="fetch" />' if gz_path else "")
            + '<script>var a = "<p>không phải đoạn</p>";</script></head><body><div id="nav"><p>Menu</p></div>'
            '<div id="bodytext">\n<p class="text-center mb-0"><b>TÊN KINH</b></p>\n'
            '<p class="text-center"><b>Tập 1</b></p><br>\n<p><b>I. DUYÊN KHỞI</b></p>\n')
    body = "\n".join(f"<p>{p}</p>" for p in paragraphs)
    return head + body + '\n<div class="inner"><span>x</span></div></div><div id="footer"><p>Chân trang</p></div></body></html>'


def gz_html(paragraphs: list[str] = GZ_PARAGRAPHS) -> bytes:
    return gzip.compress("\n".join(f"<p>{p}</p>" for p in paragraphs).encode("utf-8"))


class _Resp:
    def __init__(self, body: bytes, ctype: str):
        self._io = io.BytesIO(body)
        self.headers = {"Content-Type": ctype}

    def read(self, n: int = -1) -> bytes:
        return self._io.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """``fetch(url, opener=FakeOpener(routes))``: ``routes`` maps a URL (full) to bytes; unknown -> HTTP 404."""

    def __init__(self, routes: dict[str, bytes | str]):
        self.routes = routes
        self.requests: list[str] = []

    def __call__(self):
        return self

    def open(self, req, timeout=None):
        import urllib.error

        url = req.full_url
        self.requests.append(url)
        body = self.routes.get(url)
        if body is None:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        if isinstance(body, str):
            body = body.encode("utf-8")
        return _Resp(body, "text/html; charset=utf-8")


def public_resolver(_host, port, **_kw):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def private_resolver(_host, port, **_kw):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]


def full_routes(url: str = BASE_URL, head=HEAD_PARAGRAPHS, tail=GZ_PARAGRAPHS) -> dict:
    return {url: page_html(head), "https://ph.tinhtong.vn" + GZ_PATH: gz_html(tail)}


def write_playlist(work: Path, pid: str, entries: list[tuple[str, str | None]], doc_url: str | None = BASE_URL) -> Path:
    """``<work>/_playlists/<pid>.json`` with ``(video_id, episode)`` entries."""
    root = work / "_playlists"
    root.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "playlist_id": pid, "title": "t", "url": "u", "fetched_at": "x",
           "entries": [{"index": n, "video_id": v, "title": "T", "duration": 1.0, "episode": e, "available": True}
                       for n, (v, e) in enumerate(entries, 1)]}
    if doc_url is not None:
        doc["doc_url"] = doc_url
    path = root / f"{pid}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path
