from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


def _first_user_id() -> int:
    return client.get("/api/users").json()[0]["id"]


class TestUsersEndpoint:
    def test_returns_three_seeded_personas(self):
        resp = client.get("/api/users")
        assert resp.status_code == 200
        users = resp.json()
        assert len(users) == 3
        assert {u["persona_key"] for u in users} == {
            "priya_grad_student", "david_analyst", "maria_freelancer",
        }


class TestSingleUserEndpoints:
    def test_me_returns_the_laptop_owner(self, monkeypatch):
        # The real ensure_owner() would add an "owner" row to the shared test database.
        monkeypatch.setattr("app.api.indexer.ensure_owner", lambda: _first_user_id())
        resp = client.get("/api/me")
        assert resp.status_code == 200
        assert {"id", "name", "persona_key"} <= set(resp.json())

    def test_index_status_shape(self):
        body = client.get("/api/index/status").json()
        assert {"running", "phase", "files_found", "files_searchable", "files_pending"} <= set(body)
        assert body["files_pending"] == max(0, body["files_found"] - body["files_searchable"])

    def test_folder_mounting_endpoints_are_gone(self):
        assert client.post("/api/ingest", json={"root": "/tmp"}).status_code == 404
        assert client.get("/api/browse").status_code == 404


class TestImageEndpoints:
    def _add_png(self, tmp_path, name="photo.png", size=(900, 600)):
        from datetime import datetime

        from PIL import Image

        from app.db import get_session
        from app.models import FileRecord

        path = tmp_path / name
        Image.new("RGB", size, (200, 40, 40)).save(path)
        with get_session() as s:
            rec = FileRecord(filename=name, path=str(path), file_type="png", size_bytes=1,
                             created_at=datetime(2026, 1, 1), modified_at=datetime(2026, 1, 1),
                             topic_cluster="uncategorized")
            s.add(rec)
            s.commit()
            s.refresh(rec)
            return rec.id

    def _remove(self, file_id):
        from app.db import DATA_DIR, get_session
        from app.models import FileRecord

        with get_session() as s:
            rec = s.get(FileRecord, file_id)
            if rec:
                s.delete(rec)
                s.commit()
        (DATA_DIR / "thumbs" / f"{file_id}.jpg").unlink(missing_ok=True)

    def test_thumbnail_is_a_small_jpeg_of_the_image(self, tmp_path):
        import io

        from PIL import Image

        fid = self._add_png(tmp_path)
        try:
            resp = client.get(f"/api/thumbnail/{fid}")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "image/jpeg"
            assert max(Image.open(io.BytesIO(resp.content)).size) <= 320
        finally:
            self._remove(fid)

    def test_thumbnail_refuses_non_images_and_unknown_ids(self):
        assert client.get("/api/thumbnail/99999999").status_code == 404
        from sqlmodel import select

        from app.db import get_session
        from app.models import FileRecord

        with get_session() as s:
            not_image = s.exec(select(FileRecord).where(FileRecord.file_type == "md")).first()
        assert client.get(f"/api/thumbnail/{not_image.id}").status_code == 404

    def test_image_search_returns_described_matches(self, tmp_path, monkeypatch):
        from app.retrieval.base import ScoredFile

        fid = self._add_png(tmp_path, "red_square.png")
        monkeypatch.setattr(
            "app.api.image_search.search",
            lambda q, limit=10: [ScoredFile(file_id=fid, score=0.31, source="image_semantic", explanation="x")],
        )
        try:
            body = client.get("/api/images", params={"query": "a red square"}).json()
            assert [r["filename"] for r in body["results"]] == ["red_square.png"]
            assert body["results"][0]["score"] == 0.31
        finally:
            self._remove(fid)


class TestOnlyLocalPagesMayCallTheApi:
    def test_a_foreign_website_gets_no_cors_permission(self):
        resp = client.get("/api/users", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in resp.headers

    def test_the_local_ui_does(self):
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            resp = client.get("/api/users", headers={"Origin": origin})
            assert resp.headers.get("access-control-allow-origin") == origin


class TestOpenEndpoint:
    def _add(self, tmp_path, name, ext):
        from app.db import get_session
        from app.models import FileRecord
        from datetime import datetime
        f = tmp_path / name
        f.write_text("hello")
        with get_session() as s:
            rec = FileRecord(filename=name, path=str(f), file_type=ext, size_bytes=5,
                             created_at=datetime(2026, 1, 1), modified_at=datetime(2026, 1, 1),
                             topic_cluster="uncategorized")
            s.add(rec)
            s.commit()
            s.refresh(rec)
            return rec.id

    def _cleanup(self, file_id):
        from app.db import get_session
        from app.models import FileRecord
        with get_session() as s:
            rec = s.get(FileRecord, file_id)
            if rec:
                s.delete(rec)
                s.commit()

    def test_opens_an_indexed_file(self, tmp_path, monkeypatch):
        opened = []
        monkeypatch.setattr("app.api._launch", lambda p: opened.append(p))
        fid = self._add(tmp_path, "notes.txt", "txt")
        try:
            resp = client.post("/api/open", json={"file_id": fid}, headers={"Origin": "http://localhost:5173"})
            assert resp.status_code == 200
            assert opened and opened[0].name == "notes.txt"
        finally:
            self._cleanup(fid)

    def test_refuses_executables_and_foreign_origins_and_unknown_ids(self, tmp_path, monkeypatch):
        opened = []
        monkeypatch.setattr("app.api._launch", lambda p: opened.append(p))
        exe = self._add(tmp_path, "setup.exe", "exe")
        txt = self._add(tmp_path, "ok.txt", "txt")
        try:
            assert client.post("/api/open", json={"file_id": exe}).status_code == 403
            assert client.post("/api/open", json={"file_id": txt},
                               headers={"Origin": "https://evil.example"}).status_code == 403
            assert client.post("/api/open", json={"file_id": 99999999}).status_code == 404
            assert opened == []
        finally:
            self._cleanup(exe)
            self._cleanup(txt)


class TestQueryEndpoint:
    def test_fast_route_query(self):
        resp = client.post(
            "/api/query", json={"query": "show me my pptx files from last week", "user_id": _first_user_id()}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["routing_trace"]["tier"] == "fast"
        assert "results" in body

    def test_invalid_body_rejected(self):
        resp = client.post("/api/query", json={"query": "no user id"})
        assert resp.status_code == 422


class TestPersonalizationEndpoint:
    def test_returns_insights_shape(self):
        resp = client.get(f"/api/personalization/{_first_user_id()}")
        assert resp.status_code == 200
        body = resp.json()
        assert "preferred_file_types" in body
        assert "recurring_patterns" in body
        assert "active_context_boost_now" in body


class TestBaselineComparisonEndpoint:
    def test_returns_the_checked_in_summary(self):
        resp = client.get("/api/eval/baseline-comparison")
        assert resp.status_code == 200
        body = resp.json()
        assert "full_system" in body
        assert "naive_keyword" in body


class TestFeedbackEndpoint:
    def test_records_valid_feedback(self):
        resp = client.post(
            "/api/feedback",
            json={"user_id": _first_user_id(), "file_id": 1, "query": "test query", "signal": "thumbs_up"},
        )
        assert resp.status_code == 200
        assert resp.json()["recorded"] is True

    def test_rejects_invalid_signal(self):
        resp = client.post(
            "/api/feedback",
            json={"user_id": _first_user_id(), "file_id": 1, "query": "test query", "signal": "shrug"},
        )
        assert resp.status_code == 422


class TestQueryStreamEndpoint:
    def test_stream_ends_with_done_event_containing_trace(self):
        with client.stream(
            "GET", "/api/query/stream",
            params={"query": "gradient_descent_v2.md", "user_id": _first_user_id()},
        ) as resp:
            assert resp.status_code == 200
            events = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(line[len("data: "):])

        assert events
        import json
        parsed = [json.loads(e) for e in events]
        assert parsed[-1]["type"] == "done"
        assert "routing_trace" in parsed[-1]
        assert any(e["type"] == "route" for e in parsed)
        assert any(e["type"] == "stage" for e in parsed)
