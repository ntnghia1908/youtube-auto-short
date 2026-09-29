"""CP8.9 AC1: a Short episode (no ``khaithi.json``) keeps every config hash, ``used_config``, ``params`` and
prompt byte for byte. The expected values below were computed from the code BEFORE CP8.9 (base ``92e6343``);
they must never change because of the khai thị feature (no Short may become stale after the upgrade)."""

import hashlib

from auto_short.analysis.stage import PARAM_KEYS as ANALYSIS_PARAM_KEYS
from auto_short.analysis.stage import used_config as analysis_used
from auto_short.config import Config
from auto_short.hashing import canonical_json, config_hash
from auto_short.ingest.source import classify
from auto_short.ingest.stage import _used_config as ingest_used
from auto_short.render import stage as render_stage
from auto_short.selection.prompt import prompt_sha256, system_prompt
from auto_short.selection.stage import PARAM_KEYS as SELECTION_PARAM_KEYS
from auto_short.selection.stage import used_config as selection_used
from auto_short.titling.stage import used_config as titling_used
from auto_short.transcript.stage import used_config as transcript_used
from selection_helpers import real_docs

PRE_CP89 = {
    "ingest": "9ffbef19db25a0403e9765970c07e740cf637e34b5ee24205128f64b6eefe42f",
    "transcript": "d73f8c86dd966a93009ae63a41b771d79116f6e57deb8377619272b7eea6a094",
    "analysis": "f2d2b9cbcc033c6a523b60ed1adf1e6b3ecd80bd5fca778776075215069b4ad9",
    "selection": "0a5b40d77f21706590e87a218288a3a8d1ef354d3701758f4d471a1f579f4d99",
    "titling": "18f9745465037ecc93e6755116ee0cbc38c183c7ff80fe6c8bd6fcd6b3d6886a",
    # CP8.14 (layout V16, L2/L5) changed the [render] defaults on purpose: every episode's render becomes
    # stale once (pre-CP8.14 value: 9bbcaa463bf566149158677269a881dde76ca15aa8e77dffe1dccd8652bd8d0f).
    "render": "de0b688d5755f64bf5e1bf2483081492f4e91fdbcfe1bceccbca49631d795cfb",
}
PRE_PROMPTS = {
    "v1": "0ff963d1f415c0a74c7b320d772ab8400d282ecc848f4903bfd05141e4bf4d7c",
    "v2": "95c13065a5eb6820aebf7f335005fdee8bdc5d08b59eb1510f4a923be8b5c15a",
    "v3": "7475ca8bf165b9ffd11dbee0a657a6f1932790bc5ed485389dd90b6ab1e82c83",
}
PRE_SYSTEM_V3 = "855d95c2435c2e3414f6e8a9bf6db7bdc9ea0fc2e1b4432471ebe075ffe24702"
PRE_ANALYSIS_PARAMS = {"min_boundary_silence": 3.0, "align_tolerance": 0.5, "hard_break_silence": 10.0,
                       "max_pause": 1.0, "boundary_pad": 0.3, "min_duration": 30.0, "max_duration": 180.0,
                       "target_min": 60.0, "target_max": 90.0, "shot_guard": 1.0, "intro_window": 60.0,
                       "intro_min_silence": 1.0, "outro_window": 180.0}
PRE_SELECTION_PARAMS = {"max_clips": 25, "min_score": 7, "max_window_words": 2500, "retries": 2,
                        "head_cut_words": ("cho nên", "vì vậy", "thế nên", "thế là", "do đó", "và", "nhưng", "mà",
                                           "rồi", "còn", "thì"),
                        "head_cut_pad": 0.1}
# candidates.json of the real fixture (rbjfCfFq3Dk) with the default [analysis]
PRE_REAL_CANDIDATES = "e250c0c0b8452ffe683910a2e70ad8fc00dda2dfe206ad0f5775c76a82919134"


def test_short_config_hashes_unchanged():
    c = Config()
    got = {
        "ingest": config_hash(ingest_used(classify("https://youtu.be/rbjfCfFq3Dk"), c)),
        "transcript": config_hash(transcript_used(c)),
        "analysis": config_hash(analysis_used(c)),
        "selection": config_hash(selection_used(c)),
        "titling": config_hash(titling_used(c, ["HT.Tịnh Không", "Kinh A (tập 1)"])),
        "render": config_hash(render_stage.used_config(c.render, "f" * 64)),
    }
    assert got == PRE_CP89


def test_short_prompts_and_params_unchanged():
    c = Config()
    assert {v: prompt_sha256(v) for v in PRE_PROMPTS} == PRE_PROMPTS
    assert hashlib.sha256(system_prompt("v3", c.selection.head_cut_words).encode()).hexdigest() == PRE_SYSTEM_V3
    assert {k: getattr(c.analysis, k) for k in ANALYSIS_PARAM_KEYS} == PRE_ANALYSIS_PARAMS
    assert {k: getattr(c.selection, k) for k in SELECTION_PARAM_KEYS} == PRE_SELECTION_PARAMS
    assert c.selection.prompt_version == "v3"


def test_short_candidates_unchanged():
    cand_doc, _, _ = real_docs()
    assert hashlib.sha256(canonical_json(cand_doc).encode()).hexdigest() == PRE_REAL_CANDIDATES
