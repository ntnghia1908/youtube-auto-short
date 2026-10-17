"""CP8.33: ghép khai thị yêu thích thành video dài (concat / loop / auto). Pure spec + ffmpeg assembly + stored files;
the web layer (``auto_short.web.compilations``) only calls it.

Canonical contract: docs/tasks/CP8.33-khaithi-compilation.md (G1-G10).
"""

from . import meta, store
from .assemble import Assembled, Encode, assemble
from .probe import MediaInfo, Runner, compatible, probe
from .probe import run as run_command
from .spec import (CID_RE, MODES, CompilationError, Item, Spec, auto_plan, build_auto, build_concat, build_loop,
                   check_minutes, check_total, item_from_json, loop_count)

__all__ = ["Assembled", "CID_RE", "CompilationError", "Encode", "Item", "MODES", "MediaInfo", "Spec", "assemble",
           "auto_plan", "build_auto", "build_concat", "build_loop", "check_minutes", "check_total", "compatible",
           "item_from_json", "loop_count", "meta", "probe", "run_command", "Runner", "store"]
