"""Package revision directories retained for compilation thumbnails and existing media."""
import re

from ..compilation import store
from . import PackageError

PLAN_ID = re.compile(r"[a-z0-9]{8,32}")
SHA = re.compile(r"[a-f0-9]{64}")


def directory(output_dir, pid, plan_id, revision):
    if not PLAN_ID.fullmatch(plan_id) or type(revision) is not int or not 1 <= revision <= 9999999999:
        raise PackageError("invalid package plan/revision")
    # Playlist identities are checked at the web boundary; also guard direct callers.
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,64}", pid):
        raise PackageError("invalid playlist id")
    folder = store.directory(output_dir, pid) / "theme" / "pkg" / f"{plan_id}-r{revision}"
    if any(p.is_symlink() for p in (folder, *folder.parents)):
        raise PackageError("package directory must not contain symlinks")
    return folder
