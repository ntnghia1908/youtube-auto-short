"""Amendment B: select an existing owned playlist and cache membership per run."""
import re

from ..render.text import nfc

RANGE = re.compile(r"^\[\s*Tập\s+([0-9]+)\s*-\s*([0-9]+)\s*\]\s*"
                   r"(Kh[aạ]i\s*Th[ịi]\s*Ng[ắa]n|Short)\b", re.I)
VERTICAL = re.compile(r"\[\s*HD[\s-]*Mob(?:ile|lie)\s*\]", re.I)


def select(catalog, kind, episode):
    """Pure B1 match by product/range; channel ownership supplies the series boundary."""
    matches = []
    for playlist in catalog:
        title = nfc(playlist["snippet"]["title"])
        match = RANGE.match(title)
        if kind == "vertical":
            fits = VERTICAL.search(title) is not None
        else:
            fits = (match is not None and int(match[1]) <= episode <= int(match[2])
                    and kind == ("short" if match[3].casefold() == "short" else "kt"))
        if fits:
            matches.append(playlist)
    warning = "thiếu danh sách phát" if not matches else "nhiều danh sách phát khớp" if len(matches) > 1 else ""
    chosen = matches[0] if not warning else None
    return dict(playlist_id=chosen["id"] if chosen else "",
                playlist_title=chosen["snippet"]["title"] if chosen else "", playlist_warning=warning)


def assign(rows, catalog):
    """Decorate planned rows without changing their selected times."""
    result = []
    for original in rows:
        row = dict(original)
        row.update(select(catalog, row["kind"], row.get("episode", 0)))
        if row["kind"] and row["status"] == "sẵn sàng" and row["playlist_warning"]:
            row["reason"] = "; ".join(filter(None, (row["reason"], row["playlist_warning"])))
        result.append(row)
    return result


class Memberships:
    """List each selected playlist once, and remember every successful insertion."""

    def __init__(self, client):
        self.client = client
        self.ids = {}

    def contains(self, playlist_id, youtube_id):
        if playlist_id not in self.ids:
            self.ids[playlist_id] = set(self.client.playlist_ids(playlist_id))
        return youtube_id in self.ids[playlist_id]

    def add(self, row):
        pid, ident = row["playlist_id"], row["youtube_id"]
        if not pid or self.contains(pid, ident):
            return False
        self.client.add_to_playlist(pid, ident)
        self.ids[pid].add(ident)
        return True
