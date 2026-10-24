"""CP8.38 fixtures shared by deletion and web tests; reuse the CP8.15 episode fixture."""

from auto_short import khaithi
from auto_short.post import store
from post_helpers import EID, make_post_episode

NOW = "2026-10-24T10:00:00Z"


def make_episode(root, output_dir, *, episode_id=EID):
    ws = make_post_episode(root, output_dir, episode_id=episode_id)
    if episode_id.endswith(khaithi.SUFFIX):
        khaithi.write(ws.dir, khaithi.KhaiThi(episode_id.removesuffix(khaithi.SUFFIX), 4, 7))
    return ws


def write_posts(ws, *, posted=()):
    doc = store.empty_posts(ws.episode_id)
    order = ["k01", "k02", "k03"]
    for cid in order:
        doc = store.with_compose(doc, order, clip_id=cid, candidate_id="c00001",
                                 source_sha256="a" * 64, paragraphs=[f"Nội dung {cid}.", "Đoạn thứ hai."],
                                 origin=store.MANUAL, image="shared.png", now=NOW)
        doc = store.with_fields(doc, order, cid, {"link": f"https://youtu.be/{ws.episode_id}?clip={cid}"}, now=NOW)
        if cid in posted:
            doc = store.with_posted(doc, order, cid, True, now=NOW)
    store.write(ws.dir / store.POSTS_NAME, doc)
    return doc
