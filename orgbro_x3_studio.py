"""
ORGBRO X3 Studio - layout editor + Bluetooth printing in one Windows app.

The editor (editor.html) runs in a native window (Edge WebView2 via pywebview).
A small localhost-only HTTP API, protected by a random per-launch token, gives the
editor access to COM ports, installed system fonts, file saving and printing.

If pywebview / WebView2 is unavailable the same editor opens in Microsoft Edge
"app mode" instead, so printing still works.

Usage:
    py orgbro_x3_studio.py            (normal)
    py orgbro_x3_studio.py --browser  (force Edge app-mode window)
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# PyInstaller --windowed builds have no console: make print()/logging safe.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import orgbro_x3_protocol as proto

APP_NAME = "ORGBRO X3 Studio"
MAX_BODY = 96 * 1024 * 1024  # rendered sticker rolls can be large


def resource_path(name):
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def app_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "share")
    path = os.path.join(base, "ORGBRO_X3_Studio")
    os.makedirs(path, exist_ok=True)
    return path


def write_crash_log(text):
    try:
        with open(os.path.join(app_data_dir(), "error.log"), "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- fonts

def list_system_fonts():
    """Installed font family names (Windows GDI enumeration, Tk fallback)."""
    names = set()
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class LOGFONTW(ctypes.Structure):
                _fields_ = [
                    ("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG),
                    ("lfEscapement", wintypes.LONG), ("lfOrientation", wintypes.LONG),
                    ("lfWeight", wintypes.LONG), ("lfItalic", wintypes.BYTE),
                    ("lfUnderline", wintypes.BYTE), ("lfStrikeOut", wintypes.BYTE),
                    ("lfCharSet", wintypes.BYTE), ("lfOutPrecision", wintypes.BYTE),
                    ("lfClipPrecision", wintypes.BYTE), ("lfQuality", wintypes.BYTE),
                    ("lfPitchAndFamily", wintypes.BYTE), ("lfFaceName", wintypes.WCHAR * 32),
                ]

            FONTENUMPROCW = ctypes.WINFUNCTYPE(
                ctypes.c_int, ctypes.POINTER(LOGFONTW), ctypes.c_void_p, wintypes.DWORD, wintypes.LPARAM
            )
            user32 = ctypes.WinDLL("user32")
            gdi32 = ctypes.WinDLL("gdi32")
            user32.GetDC.argtypes = [wintypes.HWND]
            user32.GetDC.restype = wintypes.HDC
            user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            gdi32.EnumFontFamiliesExW.argtypes = [
                wintypes.HDC, ctypes.POINTER(LOGFONTW), FONTENUMPROCW, wintypes.LPARAM, wintypes.DWORD
            ]

            def _cb(lf, _tm, _ftype, _lparam):
                face = lf.contents.lfFaceName
                if face and not face.startswith("@"):
                    names.add(face)
                return 1

            proc = FONTENUMPROCW(_cb)
            hdc = user32.GetDC(None)
            try:
                lf = LOGFONTW()
                lf.lfCharSet = 1  # DEFAULT_CHARSET
                gdi32.EnumFontFamiliesExW(hdc, ctypes.byref(lf), proc, 0, 0)
            finally:
                user32.ReleaseDC(None, hdc)
        except Exception:
            write_crash_log("Font enumeration failed:\n" + traceback.format_exc())

    if not names:
        try:
            import tkinter
            import tkinter.font
            root = tkinter.Tk()
            root.withdraw()
            names.update(f for f in tkinter.font.families(root) if not f.startswith("@"))
            root.destroy()
        except Exception:
            pass
    return sorted(names, key=str.lower)


# --------------------------------------------------------------------------- API

class StudioApi:
    def __init__(self):
        self.window = None  # pywebview window when running natively
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._state = {"state": "idle", "progress": 0, "message": "Ready"}
        self._log = []

    # -- helpers
    def _add_log(self, text):
        with self._lock:
            self._log.append(text)

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    # -- endpoints
    def ping(self, _):
        return {"ok": True, "app": APP_NAME, "native": self.window is not None}

    def ports(self, _):
        return {"ports": proto.list_com_ports()}

    def fonts(self, _):
        return {"fonts": list_system_fonts()}

    def status(self, payload):
        since = int(payload.get("since", 0) or 0)
        with self._lock:
            out = dict(self._state)
            out["log"] = self._log[since:]
            out["next"] = len(self._log)
        return out

    def cancel(self, _):
        self._cancel.set()
        return {"ok": True}

    def print(self, payload):
        with self._lock:
            if self._state["state"] == "printing":
                return {"error": "A print job is already running."}
        port = (payload.get("port") or "").strip()
        if not port:
            return {"error": "Choose the printer's Bluetooth COM port first."}
        try:
            delay = float(payload.get("delay", 0.02))
        except (TypeError, ValueError):
            delay = 0.02
        delay = min(max(delay, 0.0), 0.5)

        bw = proto.load_print_image(proto.decode_data_url(payload.get("image", "")))
        raster = proto.image_to_raster(bw)
        frames = proto.build_frames(raster)

        self._cancel.clear()
        self._set(state="printing", progress=0, message=f"Opening {port}...")
        self._add_log(f"Opening {port}...")
        self._add_log(f"Image: {bw.width} x {bw.height} px, {len(frames) - 3} packets")

        def worker():
            try:
                done = proto.send_frames(
                    port, frames, delay,
                    progress=lambda pct, msg: self._set(progress=pct, message=msg),
                    log=self._add_log,
                    cancel_event=self._cancel,
                )
                if done:
                    self._set(state="done", progress=100, message="Print finished.")
                    self._add_log("Done.")
                else:
                    self._set(state="cancelled", message="Print cancelled.")
            except Exception as e:  # serial errors, timeouts, port busy...
                import serial
                if isinstance(e, serial.SerialTimeoutException):
                    msg = ("Write timeout. Check that the printer is on, your phone is "
                           "disconnected from it, and the correct COM port is selected.")
                else:
                    msg = str(e)
                self._set(state="error", message=msg)
                self._add_log("ERROR: " + msg)

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "packets": len(frames) - 3, "height": bw.height}

    def save_png(self, payload):
        """Native Save dialog when running in the app window; browser download otherwise."""
        if self.window is None:
            return {"fallback": True}
        import webview
        name = payload.get("filename") or "orgbro_x3_print.png"
        dialog = getattr(getattr(webview, "FileDialog", None), "SAVE", None)
        if dialog is None:
            dialog = webview.SAVE_DIALOG
        result = self.window.create_file_dialog(
            dialog, save_filename=name, file_types=("PNG image (*.png)",)
        )
        if not result:
            return {"cancelled": True}
        path = result if isinstance(result, str) else result[0]
        if not path.lower().endswith(".png"):
            path += ".png"
        with open(path, "wb") as f:
            f.write(proto.decode_data_url(payload.get("image", "")))
        return {"saved": path}


# --------------------------------------------------------------------------- HTTP

def make_server(api, token):
    html_template = Path(resource_path("editor.html")).read_text(encoding="utf-8")
    html = html_template.replace("__ORGBRO_TOKEN__", token).encode("utf-8")
    endpoints = {
        "ping": api.ping, "ports": api.ports, "fonts": api.fonts, "status": api.status,
        "cancel": api.cancel, "print": api.print, "save_png": api.save_png,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # no console in windowed builds
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self):
            if self.path in ("/", "/index.html", "/editor.html"):
                self._send(200, html, "text/html; charset=utf-8")
            else:
                self._send(404, b"Not found", "text/plain")

        def do_POST(self):
            if not self.path.startswith("/api/"):
                return self._json(404, {"error": "Not found"})
            if not secrets.compare_digest(self.headers.get("X-Orgbro-Token", ""), token):
                return self._json(403, {"error": "Forbidden"})
            fn = endpoints.get(self.path[len("/api/"):])
            if fn is None:
                return self._json(404, {"error": "Unknown API call"})
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length > MAX_BODY:
                return self._json(413, {"error": "Layout image is too large."})
            try:
                payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
                self._json(200, fn(payload if isinstance(payload, dict) else {}))
            except Exception as e:
                write_crash_log(traceback.format_exc())
                self._json(500, {"error": str(e)})

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


# --------------------------------------------------------------------------- windows

def run_native_window(api, url):
    import webview
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:
        pass
    window = webview.create_window(APP_NAME, url, width=1400, height=940, min_size=(1000, 700))
    api.window = window
    storage = os.path.join(app_data_dir(), "webview")
    try:
        webview.start(gui="edgechromium", private_mode=False, storage_path=storage)
    except TypeError:  # older pywebview
        webview.start(gui="edgechromium")


def find_edge():
    candidates = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def run_browser_window(url):
    browser = find_edge()
    if browser:
        profile = os.path.join(app_data_dir(), "browser-profile")
        proc = subprocess.Popen([
            browser, f"--app={url}", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", "--window-size=1400,940",
        ])
        proc.wait()
        return

    # Last resort: default browser + a small window that keeps the app alive.
    import tkinter as tk
    import webbrowser
    webbrowser.open(url)
    root = tk.Tk()
    root.title(APP_NAME)
    tk.Label(root, text=f"{APP_NAME} is running in your web browser.\n\n{url}\n\n"
                        "Close this window to quit.", padx=24, pady=24).pack()
    root.mainloop()


def main():
    api = StudioApi()
    token = secrets.token_urlsafe(24)
    server = make_server(api, token)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        if "--browser" in sys.argv:
            raise RuntimeError("browser mode requested")
        run_native_window(api, url)
    except Exception:
        write_crash_log("Native window unavailable, using browser window:\n" + traceback.format_exc())
        api.window = None
        run_browser_window(url)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
