"""Runs Sift as a local web app with a system-wide quick-search shortcut.

    python -m app.launcher            start Sift, open it, and turn on the shortcut
    python -m app.launcher spotlight  open the quick-search window (what the shortcut runs)
    python -m app.launcher stop       stop a Sift server started in the background
    python -m app.launcher shortcut --remove   turn the shortcut off again

Everything stays on this machine: the server listens on 127.0.0.1 only.

A web page only sees keys while it has focus, so the shortcut needs help from the OS.
How it is wired depends on what the desktop allows:

  * Windows, macOS, Linux on X11: this process listens for the key combination itself
    (pynput) while it runs. macOS asks once for Accessibility permission.
  * Linux on GNOME/Wayland: Wayland lets no app watch the keyboard, so the shortcut is
    registered with GNOME (Settings > Keyboard > Custom Shortcuts). It keeps working
    after this process exits, and starts Sift on demand.
  * Other Wayland desktops (KDE, Sway, ...): bind the printed command to a key in the
    desktop's own shortcut settings.

The quick search opens in a small app window (Chrome, Edge, Chromium or Brave when one is
installed) that closes when you open a file, press Esc or click elsewhere; without one it
opens as a browser tab.

Settings (environment variables): SIFT_PORT (default 8000), SIFT_HOTKEY (default
"<ctrl>+<alt>+<space>", or "<cmd>+<shift>+<space>" on macOS; pynput's format).

Only the standard library is imported at module level, so the shortcut command starts fast.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("SIFT_PORT", "8000"))
URL = f"http://127.0.0.1:{PORT}"
# Ctrl+Option+Space is taken on macOS (it switches the keyboard input source), so Macs
# default to Cmd+Shift+Space, which macOS leaves free.
HOTKEY = os.environ.get("SIFT_HOTKEY", "<cmd>+<shift>+<space>" if sys.platform == "darwin" else "<ctrl>+<alt>+<space>")
UI_DIST = REPO_ROOT / "ui" / "frontend" / "dist"
STATE_DIR = Path(os.environ.get("SIFT_STATE_DIR") or Path.home() / ".local" / "state" / "sift")
PID_FILE = STATE_DIR / "server.pid"
LOG_FILE = STATE_DIR / "server.log"
SPOTLIGHT_SIZE = (820, 540)
QUICK_SEARCH_PATH = "/quick-search"
# Chrome names an --app window after its address ("chrome-<host>__<path>-<profile>") and
# Linux desktops pick the window's icon from the desktop entry with that name.
QUICK_SEARCH_APP_ID = "chrome-127.0.0.1__quick-search-Default"
ICON = REPO_ROOT / "ui" / "frontend" / "public" / "icon-512.png"


# --- the server ----------------------------------------------------------------------


def server_up(timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/me", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def ensure_ui_built() -> None:
    if (UI_DIST / "index.html").exists():
        return
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("The web app isn't built and npm isn't installed. Install Node.js, then run "
                 "`npm ci && npm run build` in ui/frontend.")
    print("Building the web app (first run only)…")
    frontend = REPO_ROOT / "ui" / "frontend"
    if not (frontend / "node_modules").exists():
        subprocess.run([npm, "ci"], cwd=frontend, check=True)
    subprocess.run([npm, "run", "build"], cwd=frontend, check=True)


def start_server(background: bool) -> subprocess.Popen | None:
    """Starts the API (which also serves the web app) unless one is already running."""
    if server_up():
        return None
    ensure_ui_built()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", str(PORT)]
    kwargs: dict = {"cwd": REPO_ROOT}
    if background:
        # Detached, so it outlives the shortcut command that started it.
        kwargs["stdout"] = kwargs["stderr"] = open(LOG_FILE, "ab")
        kwargs["stdin"] = subprocess.DEVNULL
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    PID_FILE.write_text(str(proc.pid))
    for _ in range(240):  # first start loads the search models
        if server_up():
            return proc
        if proc.poll() is not None:
            sys.exit(f"Sift's server stopped while starting. See {LOG_FILE if background else 'the output above'}.")
        time.sleep(0.5)
    sys.exit("Sift's server didn't answer within 2 minutes.")


def stop_server() -> None:
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        print("No background Sift server is recorded.")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print("Stopped Sift.")
    except OSError:
        print("Sift wasn't running.")
    PID_FILE.unlink(missing_ok=True)


# --- the quick-search window ------------------------------------------------------------


def _chromium() -> str | None:
    """A Chromium-based browser, which can open a page as a small app window."""
    names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"]
    for name in names:
        if path := shutil.which(name):
            return path
    candidates = {
        "darwin": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ],
        "win32": [
            rf"{os.environ.get(v, '')}\{p}"
            for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
            for p in (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe")
        ],
    }.get(sys.platform, [])
    return next((c for c in candidates if Path(c).is_file()), None)


def open_spotlight() -> None:
    start_server(background=True)
    url = f"{URL}{QUICK_SEARCH_PATH}"
    browser = _chromium()
    if browser is None:
        webbrowser.open(url)
        return
    width, height = SPOTLIGHT_SIZE
    # Its own browser profile keeps these windows separate from your normal browsing
    # (and lets the window size apply even while your browser is already open).
    profile = STATE_DIR / "spotlight-browser"
    subprocess.Popen(
        [browser, f"--app={url}", f"--user-data-dir={profile}", f"--window-size={width},{height}",
         "--no-first-run", "--no-default-browser-check"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=os.name != "nt",
    )


# --- the shortcut ------------------------------------------------------------------------


def install_desktop_entry() -> None:
    """Linux: gives the quick-search window Sift's icon in the dock and app switcher, and
    puts "Sift" in the app grid (opening it opens the quick search)."""
    apps = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    (apps / f"{QUICK_SEARCH_APP_ID}.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Sift\n"
        "Comment=Find the right file, even when you only remember part of it\n"
        f'Exec="{sys.executable}" -m app.launcher spotlight\n'
        f"Path={REPO_ROOT}\n"
        f"Icon={ICON}\n"
        f"StartupWMClass={QUICK_SEARCH_APP_ID}\n"
        "Categories=Utility;\n"
        "Terminal=false\n"
    )


def _gnome_wayland() -> bool:
    return (
        sys.platform.startswith("linux")
        and os.environ.get("XDG_SESSION_TYPE") == "wayland"
        and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        and shutil.which("gsettings") is not None
    )


def _spotlight_command() -> str:
    return f"sh -c {shlex.quote(f'cd {shlex.quote(str(REPO_ROOT))} && exec {shlex.quote(sys.executable)} -m app.launcher spotlight')}"


def _gnome_binding(hotkey: str) -> str:
    """pynput's "<ctrl>+<alt>+<space>" -> GNOME's "<Control><Alt>space"."""
    mods = {"<ctrl>": "<Control>", "<alt>": "<Alt>", "<shift>": "<Shift>", "<cmd>": "<Super>", "<super>": "<Super>"}
    parts = hotkey.lower().split("+")
    return "".join(mods.get(p, "") for p in parts[:-1]) + parts[-1].strip("<>")


_GNOME_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
_GNOME_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/sift/"


def _gsettings(*args: str) -> str:
    return subprocess.run(["gsettings", *args], capture_output=True, text=True, check=True).stdout.strip()


def install_gnome_shortcut(remove: bool = False) -> None:
    import ast

    current = _gsettings("get", _GNOME_KEYS, "custom-keybindings")
    paths = [] if current.startswith("@as") else ast.literal_eval(current)
    paths = [p for p in paths if p != _GNOME_PATH] + ([] if remove else [_GNOME_PATH])
    if not remove:
        schema = f"{_GNOME_KEYS}.custom-keybinding:{_GNOME_PATH}"
        _gsettings("set", schema, "name", "Sift quick search")
        _gsettings("set", schema, "command", _spotlight_command())
        _gsettings("set", schema, "binding", _gnome_binding(HOTKEY))
    _gsettings("set", _GNOME_KEYS, "custom-keybindings", str(paths))


def _pretty(hotkey: str) -> str:
    names = {"<ctrl>": "Ctrl", "<alt>": "Option" if sys.platform == "darwin" else "Alt", "<shift>": "Shift",
             "<cmd>": "⌘", "<super>": "Super", "<space>": "Space"}
    return "+".join(names.get(p, p.strip("<>").upper()) for p in hotkey.lower().split("+"))


def enable_shortcut() -> bool:
    """Turns the shortcut on. Returns True when this process has to keep running for it."""
    if sys.platform.startswith("linux"):
        install_desktop_entry()
    if _gnome_wayland():
        install_gnome_shortcut()
        print(f"Quick search: press {_pretty(HOTKEY)} anywhere (registered with GNOME, works even when Sift is closed).")
        return False
    if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland":
        print("This desktop doesn't let apps watch the keyboard. To get the quick-search shortcut, add a custom\n"
              f"shortcut in your desktop's keyboard settings that runs:\n  {_spotlight_command()}")
        return False
    try:
        from pynput import keyboard
    except ImportError:
        print("Install pynput (`pip install -r requirements.txt`) to enable the quick-search shortcut.")
        return False
    listener = keyboard.GlobalHotKeys({HOTKEY: open_spotlight})
    listener.daemon = True
    listener.start()
    note = " (macOS will ask to allow Accessibility access the first time)" if sys.platform == "darwin" else ""
    print(f"Quick search: press {_pretty(HOTKEY)} anywhere while Sift is running{note}.")
    return True


# --- commands ----------------------------------------------------------------------------


def run() -> None:
    proc = start_server(background=False)
    print(f"Sift is running at {URL}")
    enable_shortcut()
    webbrowser.open(URL)
    if proc is None:
        print("(Another Sift server was already running; this window only manages the shortcut.)")
    print("Press Ctrl+C to stop.")
    try:
        if proc is not None:
            proc.wait()
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
        PID_FILE.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sift", description="Run Sift as a local web app.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="start Sift, open it, and turn on the shortcut (default)")
    sub.add_parser("spotlight", help="open the quick-search window")
    sub.add_parser("stop", help="stop a Sift server started in the background")
    shortcut = sub.add_parser("shortcut", help="register the quick-search shortcut with GNOME")
    shortcut.add_argument("--remove", action="store_true", help="unregister it")
    args = parser.parse_args(argv)

    if args.command == "spotlight":
        open_spotlight()
    elif args.command == "stop":
        stop_server()
    elif args.command == "shortcut":
        if not _gnome_wayland():
            sys.exit("Registering a desktop shortcut is only needed on GNOME/Wayland; elsewhere `sift run` listens for it.")
        install_gnome_shortcut(remove=args.remove)
        if not args.remove:
            install_desktop_entry()
        print("Removed the Sift shortcut." if args.remove else f"Registered {_pretty(HOTKEY)} for Sift quick search.")
    else:
        run()


if __name__ == "__main__":
    main()
