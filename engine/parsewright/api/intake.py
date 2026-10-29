"""Upload checks (design "Uploads", threats T3.6, T3.7): content-based, before anything is stored.

- At most 10 MB after decompression; a single-file .gz is the only compression accepted, and it
  is decompressed in bounded chunks, so a decompression bomb stops at the cap.
- No archives (tar, zip, 7z, rar), no binary files, UTF-8 only, at least 50 events.
- Drop folders: each subfolder is one job; symlinks are never followed.
"""

import gzip
import hashlib
import io
import os
import re
import stat
import zlib
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
MIN_EVENTS = 50
MAX_LINE = 10_000  # Splunk's default TRUNCATE; a longer line would go whole to the model (M3)
CHUNK = 64 * 1024
ARCHIVE_MAGIC = {
    b"PK\x03\x04": "zip",
    b"7z\xbc\xaf\x27\x1c": "7z",
    b"Rar!\x1a\x07": "rar",
    b"\x1f\x9d": "compress",
    b"BZh": "bzip2",
    b"\xfd7zXZ\x00": "xz",
}
NAME = re.compile(r"[A-Za-z0-9._-]{1,100}")


class UploadRefused(ValueError):
    pass


@dataclass(frozen=True)
class Sample:
    text: str
    sha256: str
    events: int


def _decompress_gz(data: bytes) -> bytes:
    """Bounded gzip decompression: refuses more than MAX_BYTES and multi-member archives."""
    d = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    out = io.BytesIO()
    view = memoryview(data)
    for i in range(0, len(view), CHUNK):
        out.write(d.decompress(view[i : i + CHUNK], MAX_BYTES + 1 - out.tell()))
        if out.tell() > MAX_BYTES or d.unconsumed_tail:
            raise UploadRefused("more than 10 MB after decompression")
    out.write(d.flush(MAX_BYTES + 1 - out.tell()))
    if out.tell() > MAX_BYTES:
        raise UploadRefused("more than 10 MB after decompression")
    if d.unused_data:
        raise UploadRefused("only a single-file .gz is accepted")
    return out.getvalue()


def check(data: bytes) -> Sample:
    """Return the sample's text if it is an acceptable log file, else raise UploadRefused."""
    if len(data) > MAX_BYTES:
        raise UploadRefused("more than 10 MB")
    if data[:2] == b"\x1f\x8b":
        try:
            data = _decompress_gz(data)
        except (zlib.error, EOFError, gzip.BadGzipFile) as e:
            raise UploadRefused(f"not a valid .gz file ({type(e).__name__})") from None
    for magic, kind in ARCHIVE_MAGIC.items():
        if data.startswith(magic):
            raise UploadRefused(f"{kind} archives are not accepted: upload one log file")
    if len(data) > 262 and data[257:262] == b"ustar":
        raise UploadRefused("tar archives are not accepted: upload one log file")
    if b"\x00" in data:
        raise UploadRefused("binary file: upload a text log")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise UploadRefused("not UTF-8 text") from None
    text = text.removeprefix("﻿").replace("\r\n", "\n")
    if any(len(line) > MAX_LINE for line in text.splitlines()):
        raise UploadRefused(f"a line is longer than {MAX_LINE} characters")
    events = sum(1 for line in text.splitlines() if line.strip())
    if events < MIN_EVENTS:
        raise UploadRefused(f"{events} events: at least {MIN_EVENTS} are needed")
    return Sample(text=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), events=events)


def safe_name(name: str) -> str:
    """A plain file name; anything with a path in it is refused, not quietly trimmed."""
    base = Path(name).name
    if base != name or "\\" in name or not NAME.fullmatch(base) or base.startswith("."):
        raise UploadRefused("file name may use letters, digits, dot, dash and underscore only")
    return base


def drop_folder_files(root: Path) -> list[Path]:
    """Files in a drop folder's job subfolders. Symlinks anywhere are refused, never followed."""
    found = []
    for job_dir in sorted(root.iterdir()):
        if job_dir.is_symlink():
            raise UploadRefused(f"{job_dir.name}: symlinks are not followed")
        if not job_dir.is_dir():
            continue
        for entry in sorted(job_dir.iterdir()):
            st = os.lstat(entry)
            if stat.S_ISLNK(st.st_mode):
                raise UploadRefused(f"{job_dir.name}/{entry.name}: symlinks are not followed")
            if stat.S_ISREG(st.st_mode) and entry.name != "job.yaml":
                found.append(entry)
    return found


def save(uploads: Path, job: str, sample: Sample, manifest: bytes) -> tuple[Path, str]:
    """Keep a job's sample and manifest under fixed names in a fresh private folder (they are
    the regression set of every later parser update), written O_EXCL|O_NOFOLLOW. Returns the
    sample path and the manifest's SHA-256."""
    folder = uploads / job
    folder.mkdir(mode=0o700)
    for name, data in (
        ("sample.log", sample.text.encode("utf-8")),
        ("sample.manifest.json", manifest),
    ):
        fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    return folder / "sample.log", hashlib.sha256(manifest).hexdigest()


def estimate_tokens(sample: Sample) -> int:
    """Rough model tokens for one run, from the 200-line sample the agents see (design)."""
    lines = [ln for ln in sample.text.splitlines() if ln.strip()][:200]
    sample_tokens = sum(len(ln) for ln in lines) // 3
    # Profiler + ~1.5 attempts per stage, each sending the sample, plus reasoning output.
    return int(sample_tokens * 5 + 30_000)
