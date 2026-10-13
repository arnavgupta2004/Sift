"""Background whole-laptop indexer: Sift searches everything on this machine, with no
"pick a folder" step.

It works like Spotlight, in two passes that overlap with searching:

  1. SWEEP (minutes): walk the machine's user-file roots and record every file's name,
     path, type, size and dates. As soon as a file is recorded it is findable by name
     and by filename keywords, so search is useful long before contents are read.
  2. READ (hours on a big laptop): pull text out of documents, code and PDFs, embed it
     for semantic search, and embed images for visual search - most recently modified
     documents first, so what you are likely to look for becomes searchable first.

Both passes are incremental and safe to interrupt: every server start resumes where it
stopped, re-sweeps pick up new/changed/deleted files, and nothing is ever re-embedded
unless the file changed. `IndexState` tracks each file's progress.

Not indexed on purpose: hidden items, caches, package/build directories, app bundles,
OS directories (only user-file roots are walked), and cloud-only placeholder files
(reading those would make macOS download them from iCloud).
"""

from __future__ import annotations

import getpass
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, SQLModel, select

from app.config import MAX_EXTRACTED_CONTENT_CHARS
from app.datasources.filesystem_source import TEXT_NATIVE_EXTENSIONS, _extract_text
from app.db import DATA_DIR, DEFAULT_DB_PATH, get_engine
from app.models import AccessEvent, FileRecord, IndexState, UserRecord

log = logging.getLogger("sift.indexer")

# --- what gets read ---------------------------------------------------------------

_TEXT_EXTRA = {
    "ipynb", "toml", "ini", "cfg", "conf", "log", "xml", "rst", "tex", "sql", "java", "c",
    "h", "cpp", "hpp", "cc", "go", "rs", "rb", "php", "swift", "kt", "r", "tsv", "srt",
    "rtf", "jsonl", "mdx", "lua", "pl", "scala",
}
_OFFICE_TYPES = {"pdf", "docx", "xlsx", "pptx"}
EXTRACTABLE = TEXT_NATIVE_EXTENSIONS | _TEXT_EXTRA | _OFFICE_TYPES
IMAGE_TYPES = {"png", "jpg", "jpeg"}
_DOCUMENT_TYPES = {"pdf", "docx", "pptx", "xlsx", "md", "txt", "rtf"}
MAX_READ_BYTES = 50 * 1024 * 1024  # don't open anything bigger to extract text from it
_DATALESS_FLAG = 0x40000000  # macOS: file contents live in the cloud, not on disk

# --- what gets walked -------------------------------------------------------------

_SKIP_DIR_NAMES = {
    "node_modules", "__pycache__", "site-packages", "venv", "Library", "AppData", "Caches",
    "Cache", "DerivedData", "Pods", "dist", "build", "$RECYCLE.BIN", "System Volume Information",
    "miniconda3", "anaconda3", "miniforge3", "mambaforge", "Trash",
}
_SKIP_DIR_SUFFIXES = (
    ".app", ".framework", ".photoslibrary", ".musiclibrary", ".tvlibrary", ".imovielibrary",
    ".lrdata", ".bundle", ".xcarchive", ".dSYM", ".xcodeproj", ".xcworkspace",
)
SWEEP_BATCH = 2000
CONTENT_BATCH = 48


_SYSTEM_VOLUMES = {"Recovery", "Preboot", "VM", "Update", "xarts", "iSCPreboot", "Hardware"}


def _is_user_volume(v: Path) -> bool:
    """External drives yes; the boot volume alias, system volumes and read-only mounted
    installer images (.dmg) no."""
    try:
        if not v.is_dir() or v.is_symlink() or v.name in _SYSTEM_VOLUMES:
            return False
        return not (os.statvfs(v).f_flag & os.ST_RDONLY)
    except OSError:
        return False


def default_roots() -> list[Path]:
    """The user-file roots of this machine. SIFT_INDEX_ROOTS (os.pathsep-separated)
    overrides the default, mainly for tests and unusual setups."""
    override = os.environ.get("SIFT_INDEX_ROOTS")
    if override:
        return [Path(p).expanduser() for p in override.split(os.pathsep) if p.strip()]

    roots = [Path.home()]
    if sys.platform == "darwin":
        icloud = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
        if icloud.is_dir():
            roots.append(icloud)
        # OneDrive / Google Drive / Dropbox mount here (the ~/OneDrive-style shortcuts are
        # symlinks into it, which the crawler deliberately does not follow).
        cloud = Path.home() / "Library" / "CloudStorage"
        if cloud.is_dir():
            roots += [d for d in cloud.iterdir() if d.is_dir()]
        volumes = Path("/Volumes")
        if volumes.is_dir():
            roots += [v for v in volumes.iterdir() if _is_user_volume(v)]
    elif sys.platform == "win32":
        home_drive = Path.home().drive.upper()
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:\\")
            if f"{letter}:" != home_drive and drive.exists():
                roots.append(drive)
    else:
        for base in ("/mnt", "/media"):
            b = Path(base)
            if b.is_dir():
                roots += [d for d in b.iterdir() if d.is_dir()]
    return roots


def _skip_dir(name: str) -> bool:
    return name.startswith(".") or name in _SKIP_DIR_NAMES or name.endswith(_SKIP_DIR_SUFFIXES)


def _skip_file(name: str) -> bool:
    return name.startswith(".") or name.startswith("~$")  # ~$ = Office lock files


# --- status -----------------------------------------------------------------------


@dataclass
class IndexerStatus:
    running: bool = False
    phase: str = "idle"  # starting | scanning | reading | idle
    roots: list[str] = field(default_factory=list)
    last_sweep_finished: str | None = None
    unreadable_dirs: int = 0
    last_error: str | None = None


def get_status(status: IndexerStatus, db_path: Path = DEFAULT_DB_PATH) -> dict:
    engine = get_engine(db_path)
    with Session(engine) as s:
        found = s.exec(select(func.count(FileRecord.id))).one()
        try:
            done = s.exec(select(func.count()).select_from(IndexState).where(IndexState.stage == 1)).one()
        except Exception:  # database created before the indexer existed: no progress table yet
            done = found
    return {
        "running": status.running,
        "phase": status.phase,
        "roots": status.roots,
        "files_found": found,
        "files_searchable": done,
        "files_pending": max(0, found - done),
        "unreadable_dirs": status.unreadable_dirs,
        "last_sweep_finished": status.last_sweep_finished,
        "last_error": status.last_error,
    }


# --- schema -----------------------------------------------------------------------


def ensure_schema(engine) -> None:
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(filename, body)")
        n_files = conn.exec_driver_sql("SELECT count(*) FROM files").scalar()
        n_fts = conn.exec_driver_sql("SELECT count(*) FROM files_fts").scalar()
        if n_files != n_fts:
            conn.exec_driver_sql("DELETE FROM files_fts")
            conn.exec_driver_sql(
                "INSERT INTO files_fts(rowid, filename, body) SELECT id, filename, extracted_text FROM files"
            )


def _priority(file_type: str, modified: datetime, now: float) -> tuple[int, int]:
    """(stage, priority). Files with nothing to read are done immediately; the rest are
    ordered documents -> other text/code -> images, most recently modified first."""
    ext = file_type.lower()
    if ext in _DOCUMENT_TYPES:
        cls = 0
    elif ext in EXTRACTABLE:
        cls = 1
    elif ext in IMAGE_TYPES:
        cls = 2
    else:
        return 1, 0
    age = max(0, int(now - modified.timestamp()))
    return 0, cls * 10**10 + age


def backfill_state(engine, embedded_ids: set[int]) -> None:
    """Gives IndexState rows to files that predate the indexer (the demo corpus, or
    files indexed by the old folder flow). Files already embedded are marked done so
    they are not embedded twice."""
    now = time.time()
    with Session(engine) as s:
        missing = s.exec(
            select(FileRecord.id, FileRecord.file_type, FileRecord.modified_at)
            .outerjoin(IndexState, IndexState.file_id == FileRecord.id)
            .where(IndexState.file_id.is_(None))
        ).all()
        for fid, ftype, modified in missing:
            stage, prio = (1, 0) if fid in embedded_ids else _priority(ftype, modified, now)
            s.add(IndexState(file_id=fid, stage=stage, priority=prio))
        s.commit()


# --- pass 1: sweep ----------------------------------------------------------------


def sweep(roots: list[Path], status: IndexerStatus, stop: threading.Event, db_path: Path = DEFAULT_DB_PATH) -> dict:
    """Records every file under `roots`; adds new ones, flags changed ones for
    re-reading, and removes ones that no longer exist."""
    engine = get_engine(db_path)
    with Session(engine) as s:
        known = {path: (fid, modified.timestamp()) for fid, path, modified in
                 s.exec(select(FileRecord.id, FileRecord.path, FileRecord.modified_at))}

    skip_abs = {str(DATA_DIR)}
    seen: set[str] = set()
    new_rows: list[FileRecord] = []
    changed_ids: list[int] = []
    stats = {"new": 0, "changed": 0, "removed": 0}
    now = time.time()

    def flush() -> None:
        if not new_rows:
            return
        with Session(engine) as s:
            s.add_all(new_rows)
            s.flush()
            for r in new_rows:
                stage, prio = _priority(r.file_type, r.modified_at, now)
                s.add(IndexState(file_id=r.id, stage=stage, priority=prio))
            fts = [(r.id, r.filename, "") for r in new_rows]
            s.connection().exec_driver_sql("INSERT INTO files_fts(rowid, filename, body) VALUES (?, ?, ?)", fts)
            s.commit()
        stats["new"] += len(new_rows)
        new_rows.clear()

    def on_error(_err: OSError) -> None:
        status.unreadable_dirs += 1

    status.unreadable_dirs = 0
    completed = True
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root, onerror=on_error):
            if stop.is_set():
                completed = False
                break
            dirnames[:] = [d for d in dirnames if not _skip_dir(d) and os.path.join(dirpath, d) not in skip_abs]
            for name in filenames:
                if _skip_file(name):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                if getattr(st, "st_flags", 0) & _DATALESS_FLAG:
                    continue
                seen.add(full)
                prev = known.get(full)
                if prev is None:
                    ext = os.path.splitext(name)[1].lstrip(".").lower() or "unknown"
                    created = getattr(st, "st_birthtime", st.st_ctime)
                    new_rows.append(FileRecord(
                        filename=name, path=full, file_type=ext, size_bytes=st.st_size,
                        created_at=datetime.fromtimestamp(created), modified_at=datetime.fromtimestamp(st.st_mtime),
                        topic_cluster="uncategorized", extracted_text="",
                    ))
                    if len(new_rows) >= SWEEP_BATCH:
                        flush()
                elif abs(prev[1] - st.st_mtime) > 1:
                    changed_ids.append(prev[0])
                    known[full] = (prev[0], st.st_mtime)
        if not completed:
            break
    flush()

    if changed_ids:
        with Session(engine) as s:
            for i in range(0, len(changed_ids), 500):
                chunk = changed_ids[i:i + 500]
                for rec in s.exec(select(FileRecord).where(FileRecord.id.in_(chunk))):
                    rec.modified_at = datetime.fromtimestamp(known[rec.path][1])
                    rec.extracted_text = ""
                    stage, prio = _priority(rec.file_type, rec.modified_at, now)
                    state = s.get(IndexState, rec.id)
                    if state:
                        state.stage, state.priority = stage, prio
                    s.connection().exec_driver_sql("UPDATE files_fts SET body='' WHERE rowid=?", (rec.id,))
            s.commit()
        stats["changed"] = len(changed_ids)

    if completed:
        stats["removed"] = _remove_vanished(engine, known, seen, roots)
        status.last_sweep_finished = datetime.now().isoformat(timespec="seconds")
    return stats


def _under(path: str, roots: list[Path]) -> bool:
    return any(path == str(r) or path.startswith(str(r) + os.sep) for r in roots)


def _remove_vanished(engine, known: dict, seen: set[str], roots: list[Path]) -> int:
    gone = [(fid, p) for p, (fid, _) in known.items() if p not in seen and _under(p, roots)]
    in_scope = sum(1 for p in known if _under(p, roots))
    # An unmounted drive or a revoked permission looks like "everything was deleted";
    # refuse to wipe a big share of the index on that evidence.
    if in_scope > 100 and len(gone) > in_scope * 0.5:
        log.warning("sweep: %d of %d known files missing - not removing (drive unmounted?)", len(gone), in_scope)
        return 0
    ids = [fid for fid, _ in gone]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        with engine.begin() as conn:
            conn.exec_driver_sql(f"DELETE FROM files_fts WHERE rowid IN ({ph})", tuple(chunk))
            conn.exec_driver_sql(f"DELETE FROM index_state WHERE file_id IN ({ph})", tuple(chunk))
            conn.exec_driver_sql(f"DELETE FROM files WHERE id IN ({ph})", tuple(chunk))
    if ids:
        _drop_vectors(ids)
    return len(ids)


def _drop_vectors(ids: list[int]) -> None:
    from app.retrieval import image_search, semantic_search

    str_ids = [str(i) for i in ids]
    for get_collection in (semantic_search._get_collection, image_search._get_collection):
        try:
            col = get_collection()
            for i in range(0, len(str_ids), semantic_search.CHROMA_BATCH):
                col.delete(ids=str_ids[i:i + semantic_search.CHROMA_BATCH])
        except Exception:
            log.exception("could not drop vectors")


# --- pass 2: read contents --------------------------------------------------------


def _resolve(rec: FileRecord) -> Path:
    p = Path(rec.path)
    return p if p.is_absolute() else DATA_DIR / "files_corpus" / rec.path


def _read_text(path: Path, ext: str) -> str:
    if ext in _TEXT_EXTRA:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")[:MAX_EXTRACTED_CONTENT_CHARS]
        except Exception:
            return ""
    return _extract_text(path, ext)


def process_pending(
    status: IndexerStatus, stop: threading.Event, db_path: Path = DEFAULT_DB_PATH, embed: bool = True
) -> int:
    """Reads and embeds files until none are pending (or stop is set). Returns how many
    files were finished."""
    engine = get_engine(db_path)
    finished = 0
    while not stop.is_set():
        with Session(engine) as s:
            ids = s.exec(
                select(IndexState.file_id).where(IndexState.stage == 0).order_by(IndexState.priority).limit(CONTENT_BATCH)
            ).all()
            if not ids:
                break
            recs = s.exec(select(FileRecord).where(FileRecord.id.in_(ids))).all()

        texts: list[tuple[int, str]] = []  # (file_id, text to store)
        docs: list[tuple[int, str, str]] = []  # to embed
        images: list[FileRecord] = []
        for rec in recs:
            ext = rec.file_type.lower()
            text = rec.extracted_text
            path = _resolve(rec)
            if ext in EXTRACTABLE and not text:
                try:
                    if path.is_file() and path.stat().st_size <= MAX_READ_BYTES:
                        text = _read_text(path, ext)
                except Exception:
                    text = ""
            if text != rec.extracted_text:
                texts.append((rec.id, text))
            if text:
                docs.append((rec.id, rec.filename, text))
            if ext in IMAGE_TYPES:
                images.append(rec)

        try:
            if embed:
                from app.retrieval import image_search, semantic_search

                semantic_search.add_documents(docs)
                image_search.add_images(images)
        except Exception as e:  # models missing/offline: keep the batch pending, retry next round
            status.last_error = f"embedding failed: {e}"
            log.exception("embedding failed")
            break

        with engine.begin() as conn:
            if texts:
                conn.exec_driver_sql("UPDATE files SET extracted_text=? WHERE id=?", [(t, i) for i, t in texts])
                conn.exec_driver_sql("UPDATE files_fts SET body=? WHERE rowid=?", [(t, i) for i, t in texts])
            conn.exec_driver_sql("UPDATE index_state SET stage=1 WHERE file_id=?", [(i,) for i in ids])
        finished += len(ids)
        time.sleep(0.02)  # leave the machine responsive
    return finished


# --- single user + personalization seed ---------------------------------------------


def _owner_name() -> str:
    try:
        import pwd

        full = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
        if full:
            return full
    except Exception:
        pass
    return getpass.getuser()


def ensure_owner(db_path: Path = DEFAULT_DB_PATH) -> int:
    """The one user of this laptop. Created on first run."""
    engine = get_engine(db_path)
    with Session(engine) as s:
        user = s.exec(select(UserRecord).where(UserRecord.persona_key == "owner")).first()
        if user is None:
            user = UserRecord(name=_owner_name(), persona_key="owner")
            s.add(user)
            s.commit()
            s.refresh(user)
        return user.id


def seed_from_spotlight(user_id: int, db_path: Path = DEFAULT_DB_PATH, days: int = 90, cap: int = 3000) -> int:
    """Cold start for personalization (macOS): Spotlight already knows which files this
    person actually opened recently and how often. Seeds one-time access events from
    that, so the profile reflects real habits from the first search. Everywhere else the
    profile starts empty and learns from files opened/rated through Sift."""
    if sys.platform != "darwin":
        return 0
    engine = get_engine(db_path)
    with Session(engine) as s:
        if s.exec(select(func.count()).select_from(AccessEvent).where(
            AccessEvent.user_id == user_id, AccessEvent.session_id.like("spotlight-%")
        )).one():
            return 0
    try:
        out = subprocess.run(
            ["mdfind", "-onlyin", str(Path.home()), f"kMDItemLastUsedDate >= $time.today(-{days})"],
            capture_output=True, text=True, timeout=120,
        ).stdout
    except Exception:
        return 0
    paths = [p for p in out.splitlines() if p][: cap * 3]

    events = 0
    with Session(engine) as s:
        for i in range(0, len(paths), 100):
            chunk = paths[i:i + 100]
            id_by_path = dict(s.exec(select(FileRecord.path, FileRecord.id).where(FileRecord.path.in_(chunk))).all())
            if not id_by_path:
                continue
            try:
                raw = subprocess.run(
                    ["mdls", "-raw", "-name", "kMDItemLastUsedDate", "-name", "kMDItemUseCount", *chunk],
                    capture_output=True, text=True, timeout=60,
                ).stdout.split("\0")
            except Exception:
                continue
            for j, p in enumerate(chunk):
                if p not in id_by_path or len(raw) < 2 * j + 2:
                    continue
                try:
                    used = datetime.strptime(raw[2 * j].strip()[:19], "%Y-%m-%d %H:%M:%S")
                    count = int(raw[2 * j + 1]) if raw[2 * j + 1].strip() not in ("", "(null)") else 1
                except ValueError:
                    continue
                for k in range(max(1, min(count, 10))):
                    s.add(AccessEvent(
                        user_id=user_id, file_id=id_by_path[p], action="open",
                        timestamp=used - timedelta(hours=k),
                        session_id=f"spotlight-{id_by_path[p]}-{k}",
                    ))
                    events += 1
            if events >= cap * 3:
                break
        s.commit()
    return events


# --- the thread -------------------------------------------------------------------


class Indexer:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH, roots: list[Path] | None = None,
                 sweep_interval: float = 900.0, embed: bool = True):
        self.db_path = db_path
        self.roots = roots if roots is not None else default_roots()
        self.sweep_interval = sweep_interval
        self.embed = embed
        self.status = IndexerStatus(roots=[str(r) for r in self.roots])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        engine = get_engine(self.db_path)
        ensure_schema(engine)
        self.status.running, self.status.phase = True, "starting"
        if self.embed:
            # From here on the vector indexes are owned by this thread: searches must
            # never trigger a full rebuild (it would re-embed the whole machine).
            from app.retrieval import image_search, semantic_search

            semantic_search.INCREMENTAL = True
            image_search.INCREMENTAL = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sift-indexer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.status.running = False

    def _run(self) -> None:
        engine = get_engine(self.db_path)
        try:
            embedded: set[int] = set()
            if self.embed:
                from app.retrieval import image_search, semantic_search

                for get_collection in (semantic_search._get_collection, image_search._get_collection):
                    embedded |= {int(i) for i in get_collection().get()["ids"]}
            backfill_state(engine, embedded)
            owner = ensure_owner(self.db_path)
        except Exception as e:
            self.status.last_error = f"startup failed: {e}"
            log.exception("indexer startup failed")
            self.status.running = False
            return

        seeded = False
        while not self._stop.is_set():
            try:
                self.status.phase = "scanning"
                sweep(self.roots, self.status, self._stop, self.db_path)
                if not seeded:
                    seeded = True
                    seed_from_spotlight(owner, self.db_path)
                self.status.phase = "reading"
                process_pending(self.status, self._stop, self.db_path, self.embed)
                self.status.phase = "idle"
            except Exception as e:
                self.status.last_error = str(e)
                log.exception("indexer pass failed")
                self.status.phase = "idle"
            self._stop.wait(self.sweep_interval)
        self.status.running = False


_indexer: Indexer | None = None


def start() -> Indexer:
    global _indexer
    if _indexer is None:
        _indexer = Indexer()
    _indexer.start()
    return _indexer


def stop() -> None:
    if _indexer:
        _indexer.stop()


def current_status() -> dict:
    if _indexer is None:
        return get_status(IndexerStatus())
    return get_status(_indexer.status, _indexer.db_path)
