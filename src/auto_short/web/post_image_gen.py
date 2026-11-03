"""IMG1 background service, sharing the cover suggestion Codex admission lock."""
from __future__ import annotations

import threading

from ..packaging import cover_suggest
from ..post import imggen, imgsearch
from .episode_thumbs import EpisodeThumbs


class PostImageGen:
    def __init__(self, config, *, codex_runner=None):
        self.config, self.codex_runner = config, codex_runner
        self.thread = None
        self.cancel_event = threading.Event()
        self.active = None
        imggen.recover(config)

    def unavailable(self):
        return cover_suggest.available(self.config)

    def start(self, keyword):
        if not imgsearch.tokens(keyword):
            raise imgsearch.SearchError("nhập từ khóa")
        if not EpisodeThumbs.codex_lock.acquire(blocking=False):
            raise cover_suggest.Busy("Codex đang bận; thử lại sau")
        doc = None
        try:
            problem = self.unavailable()
            if problem:
                raise cover_suggest.MissingCodex(problem)
            doc = imggen.create(self.config, keyword)
            cancel = threading.Event()
            self.cancel_event, self.active = cancel, doc["search_id"]

            def work():
                try:
                    imggen.execute(self.config, doc["search_id"], runner=self.codex_runner, cancel=cancel)
                finally:
                    self.active = None
                    EpisodeThumbs.codex_lock.release()

            self.thread = threading.Thread(target=work, name="post-image-gen", daemon=True)
            self.thread.start()
            return self.view(doc)
        except BaseException:
            try:
                self.active = None
                if doc:
                    doc.update(status="failed", error="không khởi động được lượt vẽ")
                    imggen.save(imggen.directory(self.config, doc["search_id"]), doc)
            finally:
                EpisodeThumbs.codex_lock.release()
            raise

    @staticmethod
    def view(doc):
        if doc is None:
            return None
        keys = ("search_id", "keyword", "status", "error", "tokens", "candidates", "skipped", "notes", "sources")
        out = {k: doc[k] for k in keys}
        fields = ("id", "width", "height", "bytes", "origin", "page", "url", "flag", "thumb")
        out["candidates"] = [{k: c.get(k) for k in fields} for c in doc["candidates"]]
        return out

    def get(self, search_id):
        return self.view(imggen.state(self.config, search_id))

    def latest(self):
        return self.view(imggen.latest(self.config))

    def dismiss(self, search_id):
        return self.view(imggen.dismiss(self.config, search_id))

    def cancel(self, search_id):
        doc = imggen.state(self.config, search_id)
        if self.active == search_id:
            self.cancel_event.set()
        return self.view(doc)
