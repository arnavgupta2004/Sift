import pytest

from app import api, launcher


class TestShortcutSetup:
    def test_gnome_binding_matches_the_pynput_hotkey(self):
        assert launcher._gnome_binding("<ctrl>+<alt>+<space>") == "<Control><Alt>space"
        assert launcher._gnome_binding("<cmd>+<shift>+k") == "<Super><Shift>k"

    def test_shortcut_command_runs_from_the_repo_with_this_python(self):
        cmd = launcher._spotlight_command()
        assert str(launcher.REPO_ROOT) in cmd and "app.launcher spotlight" in cmd


@pytest.mark.skipif(not api._UI_DIST.is_dir(), reason="web app not built (npm run build in ui/frontend)")
class TestServedWebApp:
    def test_page_is_rechecked_and_assets_cached_for_good(self):
        from fastapi.testclient import TestClient

        client = TestClient(api.app)
        page = client.get("/")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
        asset = page.text.split('src="/')[1].split('"')[0]
        assert "immutable" in client.get(f"/{asset}").headers["cache-control"]

    def test_unknown_api_paths_are_404_not_the_web_app(self):
        from fastapi.testclient import TestClient

        client = TestClient(api.app)
        assert client.get("/api/nope").status_code == 404
        assert client.post("/api/nope").status_code == 404
