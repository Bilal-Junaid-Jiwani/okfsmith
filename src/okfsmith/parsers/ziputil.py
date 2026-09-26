"""Safe zip extraction for untrusted archives (Notion exports, generic zips).

Two defenses in one helper:

1. **Decompression-bomb cap** (audit-3 finding 2): the total uncompressed
   size and the member count are checked *before* anything is written. A
   few-KB zip must not be allowed to expand to gigabytes in ``/tmp`` or to
   thousands of members that each get parsed into memory.
2. **Explicit ZipSlip containment** (audit-3 finding 5): each member is
   extracted individually and the destination is resolved and checked to
   stay inside the target directory. The stdlib already strips ``..`` /
   absolute components, but we do not rely on implicit behavior.

Limits: 512 MiB total uncompressed, 100 000 members. Both are generous for
legitimate document archives and far below denial-of-service territory.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

#: Refuse archives whose members would uncompress beyond this many bytes.
MAX_TOTAL_UNCOMPRESSED = 512 * 1024 * 1024

#: Refuse archives with more members than this.
MAX_MEMBERS = 100_000


def safe_extract(zf: zipfile.ZipFile, target: str | Path) -> Path:
    """Extract *zf* into *target* after size/member caps and per-member checks.

    Raises :class:`ValueError` when the archive exceeds the caps or when a
    member would escape *target*. Returns the resolved target directory.
    """
    dest_root = Path(target).resolve()
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise ValueError(
            f"refusing to extract zip: {len(infos)} members exceeds the "
            f"limit of {MAX_MEMBERS}"
        )
    total = sum(info.file_size for info in infos)
    if total > MAX_TOTAL_UNCOMPRESSED:
        raise ValueError(
            f"refusing to extract zip: {total} bytes uncompressed exceeds "
            f"the limit of {MAX_TOTAL_UNCOMPRESSED}"
        )
    for info in infos:
        name = info.filename
        # Skip directory entries; files land via explicit member extraction.
        if name.endswith("/"):
            continue
        dest = (dest_root / name).resolve()
        if dest != dest_root and not str(dest).startswith(str(dest_root) + os.sep):
            raise ValueError(f"refusing to extract zip: unsafe member {name!r}")
        # ``ZipInfo.is_dir()`` exists on 3.6+; fall back to the name check.
        is_dir = info.is_dir() if hasattr(info, "is_dir") else False
        if is_dir:
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, open(dest, "wb") as out:
            out.write(src.read())
    return dest_root


__all__ = ["MAX_MEMBERS", "MAX_TOTAL_UNCOMPRESSED", "safe_extract"]
