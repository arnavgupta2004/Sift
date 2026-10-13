"""The whole-laptop background indexer, exercised on throwaway folders and databases
(never the real index): sweep, change/removal detection, prioritized content reading,
full-text search over what it read, and the single laptop user."""

import os
import threading
import time

import pytest
from sqlmodel import Session, select

from app import indexer
from app.db import get_engine
from app.models import FileRecord, IndexState, UserRecord
from app.retrieval import keyword_search


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "_drop_vectors", lambda ids: None)  # no vector store in these tests
    db = tmp_path / "db.sqlite"
    root = tmp_path / "laptop"
    root.mkdir()
    indexer.ensure_schema(get_engine(db))
    return db, root, indexer.IndexerStatus(), threading.Event()


def _write(root, rel, text="hello"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _names(db):
    with Session(get_engine(db)) as s:
        return {r.filename for r in s.exec(select(FileRecord))}


def _by_name(db, name):
    with Session(get_engine(db)) as s:
        rec = s.exec(select(FileRecord).where(FileRecord.filename == name)).one()
        state = s.get(IndexState, rec.id)
        return rec, state


class TestSweep:
    def test_records_every_visible_file_and_skips_noise(self, env):
        db, root, status, stop = env
        _write(root, "notes/plan.md")
        _write(root, "movie.mkv", "x")
        _write(root, ".hidden/secret.txt")
        _write(root, "proj/node_modules/lib.js")
        _write(root, "proj/__pycache__/x.pyc")
        _write(root, "~$lock.docx")
        _write(root, ".DS_Store")
        stats = indexer.sweep([root], status, stop, db)
        assert _names(db) == {"plan.md", "movie.mkv"}
        assert stats["new"] == 2

    def test_files_are_findable_by_name_before_contents_are_read(self, env):
        db, root, status, stop = env
        _write(root, "quarterly_budget_review.txt", "numbers")
        indexer.sweep([root], status, stop, db)
        assert [m.file_id for m in keyword_search._fts_search("quarterly budget", 5, db)]

    def test_unreadable_types_are_done_immediately_readable_ones_are_pending(self, env):
        db, root, status, stop = env
        _write(root, "a.md")
        _write(root, "clip.mkv", "x")
        indexer.sweep([root], status, stop, db)
        assert _by_name(db, "a.md")[1].stage == 0
        assert _by_name(db, "clip.mkv")[1].stage == 1

    def test_second_sweep_adds_nothing_when_nothing_changed(self, env):
        db, root, status, stop = env
        _write(root, "a.md")
        indexer.sweep([root], status, stop, db)
        assert indexer.sweep([root], status, stop, db) == {"new": 0, "changed": 0, "removed": 0}

    def test_detects_changed_and_deleted_files(self, env):
        db, root, status, stop = env
        keep = _write(root, "keep.md", "old text")
        gone = _write(root, "gone.md")
        indexer.sweep([root], status, stop, db)
        indexer.process_pending(status, stop, db, embed=False)
        assert _by_name(db, "keep.md")[1].stage == 1

        keep.write_text("brand new text")
        os.utime(keep, (time.time() + 100, time.time() + 100))
        gone.unlink()
        stats = indexer.sweep([root], status, stop, db)
        assert stats["changed"] == 1 and stats["removed"] == 1
        assert "gone.md" not in _names(db)
        rec, state = _by_name(db, "keep.md")
        assert state.stage == 0 and rec.extracted_text == ""  # queued to be re-read


class TestReadingContents:
    def test_reads_text_and_makes_it_searchable(self, env):
        db, root, status, stop = env
        _write(root, "thesis.md", "gradient descent converges slowly on ill-conditioned problems")
        indexer.sweep([root], status, stop, db)
        assert indexer.process_pending(status, stop, db, embed=False) == 1
        rec, state = _by_name(db, "thesis.md")
        assert "gradient descent" in rec.extracted_text and state.stage == 1
        hits = keyword_search._fts_search("ill-conditioned gradient", 5, db)
        assert hits and hits[0].file_id == rec.id

    def test_documents_are_read_before_code_and_recent_before_old(self, env):
        db, root, status, stop = env
        old_doc = _write(root, "old.md")
        new_doc = _write(root, "new.md")
        code = _write(root, "tool.py")
        os.utime(old_doc, (1_600_000_000, 1_600_000_000))
        indexer.sweep([root], status, stop, db)
        prio = {n: _by_name(db, n)[1].priority for n in ("old.md", "new.md", "tool.py")}
        assert prio["new.md"] < prio["old.md"] < prio["tool.py"]

    def test_stop_event_halts_reading(self, env):
        db, root, status, stop = env
        _write(root, "a.md", "text")
        indexer.sweep([root], status, stop, db)
        stop.set()
        assert indexer.process_pending(status, stop, db, embed=False) == 0


class TestFullTextFallback:
    def test_not_used_when_the_index_table_does_not_exist(self, tmp_path):
        from sqlmodel import SQLModel

        db = tmp_path / "plain.sqlite"
        SQLModel.metadata.create_all(get_engine(db))
        assert keyword_search._fts_ready(db) is False


class TestSingleUser:
    def test_owner_is_created_once(self, env):
        db, *_ = env
        first = indexer.ensure_owner(db)
        assert indexer.ensure_owner(db) == first
        with Session(get_engine(db)) as s:
            owners = s.exec(select(UserRecord).where(UserRecord.persona_key == "owner")).all()
        assert len(owners) == 1 and owners[0].name


class TestRoots:
    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SIFT_INDEX_ROOTS", f"{tmp_path}{os.pathsep}{tmp_path / 'b'}")
        assert indexer.default_roots() == [tmp_path, tmp_path / "b"]


class TestImagesAddedLater:
    def test_webp_files_marked_done_before_images_were_read_are_queued_once(self, env):
        db, root, status, stop = env
        _write(root, "pic.webp", "not really an image")
        _write(root, "kept.png", "x")
        indexer.sweep([root], status, stop, db)
        with get_engine(db).begin() as conn:
            conn.exec_driver_sql("UPDATE index_state SET stage=1")  # as an older indexer left them
        webp, _ = _by_name(db, "pic.webp")
        png, _ = _by_name(db, "kept.png")
        engine = get_engine(db)
        assert indexer.requeue_unembedded_images(engine, embedded_ids={png.id}) == 1
        assert _by_name(db, "pic.webp")[1].stage == 0
        assert _by_name(db, "kept.png")[1].stage == 1  # old formats are never retried
        assert indexer.requeue_unembedded_images(engine, embedded_ids={webp.id}) == 0
