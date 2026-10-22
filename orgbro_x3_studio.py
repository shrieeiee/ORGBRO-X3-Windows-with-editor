"""
ORGBRO X3 Studio - layout editor + Bluetooth printing in one Windows app.

The editor (editor.html) runs in a native window (Edge WebView2 via pywebview).
A small localhost-only HTTP API, protected by a random per-launch token, gives the
editor access to COM ports, installed system fonts, project files and printing.

If pywebview / WebView2 is unavailable the same editor opens in Microsoft Edge
"app mode" instead, so printing still works.

Usage:
    py orgbro_x3_studio.py            (normal)
    py orgbro_x3_studio.py --browser  (force Edge app-mode window)
"""

import json
import mimetypes
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

import cat_printer as cat
import orgbro_x3_protocol as proto

APP_NAME = "ORGBRO X3 Studio"
def _read_version():
    for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))):
        try:
            with open(os.path.join(base or "", "VERSION"), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    return "dev"


APP_VERSION = _read_version()
MAX_BODY = 160 * 1024 * 1024  # projects embed images; rendered rolls can be large
STATIC_DIRS = ("fonts", "vendor", "assets")
PROJECT_EXT = ".orgbro"
MAX_RECENT = 10


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
    def __init__(self, data_dir=None):
        self.window = None  # pywebview window when running natively
        self.data_dir = data_dir or app_data_dir()
        os.makedirs(self.data_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._state = {"state": "idle", "progress": 0, "message": "Ready"}
        self._log = []
        self._ble = None
        self.ble_client_factory = None   # tests can inject a simulated printer

    def _ble_worker(self):
        if self._ble is None:
            self._ble = cat.BleWorker()
        return self._ble

    # -- helpers
    def _add_log(self, text):
        with self._lock:
            self._log.append(text)

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    def _recent_file(self):
        return os.path.join(self.data_dir, "recent.json")

    def _load_recent(self):
        try:
            with open(self._recent_file(), encoding="utf-8") as f:
                items = json.load(f)
            return [p for p in items if isinstance(p, str) and os.path.isfile(p)][:MAX_RECENT]
        except Exception:
            return []

    def _add_recent(self, path):
        items = [p for p in self._load_recent() if os.path.normcase(p) != os.path.normcase(path)]
        items.insert(0, path)
        try:
            with open(self._recent_file(), "w", encoding="utf-8") as f:
                json.dump(items[:MAX_RECENT], f)
        except Exception:
            pass

    def _dialog(self, kind, **kw):
        import webview
        fd = getattr(webview, "FileDialog", None)
        dtype = getattr(fd, kind, None) if fd else None
        if dtype is None:
            dtype = getattr(webview, kind + "_DIALOG")
        result = self.window.create_file_dialog(dtype, **kw)
        if not result:
            return None
        return result if isinstance(result, str) else result[0]

    # -- endpoints
    def ping(self, _):
        return {"ok": True, "app": APP_NAME, "version": APP_VERSION, "native": self.window is not None}

    def ports(self, _):
        return {"ports": proto.list_com_ports()}

    def probe(self, _):
        """Ask every COM port for the printer's status reply, in parallel."""
        if self._state["state"] == "printing":
            return {"error": "Can't search for the printer while printing."}
        ports = proto.list_com_ports()
        results = {p["device"]: {"device": p["device"], "description": p["description"],
                                 "responded": False, "reply": "", "error": ""} for p in ports}

        def worker(dev):
            try:
                reply = proto.probe_port(dev)
                results[dev]["responded"] = bool(reply)
                results[dev]["reply"] = reply.hex(" ")
            except Exception as e:
                results[dev]["error"] = str(e)

        threads = [threading.Thread(target=worker, args=(p["device"],), daemon=True) for p in ports]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        for r in results.values():
            if r["responded"]:
                self._add_log(f"Printer replied on {r['device']}: {r['reply']}")
        return {"ports": list(results.values())}

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

    def ble_scan(self, payload):
        """Scan for Bluetooth LE cat printers."""
        if self._state["state"] == "printing":
            return {"error": "Can't scan while printing."}
        try:
            import bleak  # noqa: F401
        except ImportError:
            return {"error": "Bluetooth LE support (bleak) is not installed."}
        timeout = min(max(float(payload.get("timeout", 6) or 6), 2), 20)
        try:
            devices = self._ble_worker().run(cat.scan(timeout), timeout + 10)
        except Exception as e:
            msg = str(e) or e.__class__.__name__
            if "adapter" in msg.lower() or "radio" in msg.lower() or "not available" in msg.lower():
                msg = "Bluetooth seems to be off or missing. Turn it on in Windows Settings > Bluetooth & devices."
            return {"error": msg}
        likely = [d for d in devices if d["likely"]]
        self._add_log(f"Bluetooth LE scan: {len(devices)} devices, {len(likely)} look like cat printers")
        return {"devices": devices}

    def print(self, payload):
        with self._lock:
            if self._state["state"] == "printing":
                return {"error": "A print job is already running."}
        if payload.get("printer") == "cat":
            return self._print_cat(payload)
        port = (payload.get("port") or "").strip()
        if not port:
            return {"error": "Choose the printer's Bluetooth COM port first."}

        def num(key, default, lo, hi, cast=float):
            try:
                return min(max(cast(payload.get(key, default)), lo), hi)
            except (TypeError, ValueError):
                return default

        delay = num("delay", 0.02, 0.0, 0.5)
        density = num("density", proto.DEFAULT_DENSITY, 0, 255, int)
        feed = num("feed", proto.DEFAULT_FEED, 0, 2000, int)
        split = num("split_packets", 0, 0, 250, int) or None

        bw = proto.load_print_image(proto.decode_data_url(payload.get("image", "")))
        raster = proto.image_to_raster(bw)
        frames = proto.build_frames(raster, density=density, feed=feed, split_packets=split)
        packets = sum(1 for f in frames if proto.is_data_frame(f))
        jobs = sum(1 for f in frames if f[1] == 0x02)

        self._cancel.clear()
        self._set(state="printing", progress=0, message=f"Opening {port}...")
        self._add_log(f"Opening {port}...")
        self._add_log(f"Image: {bw.width} x {bw.height} px, {packets} packets"
                      + (f" in {jobs} parts" if jobs > 1 else "")
                      + f", density 0x{density:02x}, feed {feed}")

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
        return {"ok": True, "packets": packets, "height": bw.height}

    def _print_cat(self, payload):
        address = (payload.get("address") or "").strip()
        if not address:
            return {"error": "Choose your cat printer first (click Scan)."}

        def num(key, default, lo, hi, cast=int):
            try:
                return min(max(cast(payload.get(key, default)), lo), hi)
            except (TypeError, ValueError):
                return default

        speed = num("speed", cat.DEFAULT_SPEED, 1, 255)
        energy = num("energy", cat.DEFAULT_ENERGY, 1000, 65535)
        feed = num("feed", cat.DEFAULT_FEED, 0, 2000)
        delay = num("delay", 0.02, 0.0, 0.5, float)
        name = payload.get("name") or address

        bw = cat.load_print_image(proto.decode_data_url(payload.get("image", "")))
        rows = cat.image_to_rows(bw)
        self._cancel.clear()
        self._set(state="printing", progress=0, message=f"Connecting to {name}...")
        self._add_log(f"Cat printer {name} ({address}): {bw.width} x {bw.height} px, "
                      f"speed {speed}, energy {energy}, feed {feed}")

        def worker():
            try:
                done = self._ble_worker().run(cat.print_rows(
                    address, rows, speed=speed, energy=energy, feed=feed, delay=delay,
                    progress=lambda pct, msg: self._set(progress=pct, message=msg),
                    log=self._add_log, cancel_event=self._cancel,
                    client_factory=self.ble_client_factory,
                ))
                if done:
                    self._set(state="done", progress=100, message="Print finished.")
                    self._add_log("Done.")
                else:
                    self._set(state="cancelled", message="Print cancelled.")
            except Exception as e:
                msg = str(e) or e.__class__.__name__
                low = msg.lower()
                if "not found" in low or "was not found" in low or "timeout" in low or "timed out" in low:
                    msg = (f"Couldn't connect to {name}. Make sure it's switched on, close any phone app "
                           "that is connected to it, and try Scan again.")
                self._set(state="error", message=msg)
                self._add_log("ERROR: " + msg)
                write_crash_log(traceback.format_exc())

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "rows": len(rows), "height": bw.height}

    def save_png(self, payload):
        """Native Save dialog when running in the app window; browser download otherwise."""
        if self.window is None:
            return {"fallback": True}
        path = self._dialog("SAVE", save_filename=payload.get("filename") or "orgbro_x3_print.png",
                            file_types=("PNG image (*.png)",))
        if not path:
            return {"cancelled": True}
        if not path.lower().endswith(".png"):
            path += ".png"
        with open(path, "wb") as f:
            f.write(proto.decode_data_url(payload.get("image", "")))
        return {"saved": path}

    # -- projects
    def project_save(self, payload):
        project = payload.get("project")
        if not isinstance(project, dict):
            return {"error": "Nothing to save."}
        path = payload.get("path")
        if not path or payload.get("save_as"):
            if self.window is None:
                return {"fallback": True}
            path = self._dialog("SAVE", save_filename=payload.get("filename") or "layout" + PROJECT_EXT,
                                file_types=(f"ORGBRO layout (*{PROJECT_EXT})", "All files (*.*)"))
            if not path:
                return {"cancelled": True}
            if not os.path.splitext(path)[1]:
                path += PROJECT_EXT
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(project, f)
        os.replace(tmp, path)
        self._add_recent(path)
        return {"saved": path, "name": os.path.basename(path)}

    def project_open(self, payload):
        path = payload.get("path")
        if not path:
            if self.window is None:
                return {"fallback": True}
            path = self._dialog("OPEN", file_types=(f"ORGBRO layout (*{PROJECT_EXT})", "All files (*.*)"))
            if not path:
                return {"cancelled": True}
        with open(path, encoding="utf-8") as f:
            project = json.load(f)
        self._add_recent(path)
        return {"project": project, "path": path, "name": os.path.basename(path)}

    def recent(self, _):
        return {"recent": [{"path": p, "name": os.path.basename(p)} for p in self._load_recent()]}

    def autosave(self, payload):
        project = payload.get("project")
        if isinstance(project, dict):
            tmp = os.path.join(self.data_dir, "autosave.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(project, f)
            os.replace(tmp, os.path.join(self.data_dir, "autosave" + PROJECT_EXT))
        return {"ok": True}

    def autoload(self, _):
        try:
            with open(os.path.join(self.data_dir, "autosave" + PROJECT_EXT), encoding="utf-8") as f:
                return {"project": json.load(f)}
        except Exception:
            return {"project": None}


# --------------------------------------------------------------------------- HTTP

def make_server(api, token, host="127.0.0.1", port=0):
    html_template = Path(resource_path("editor.html")).read_text(encoding="utf-8")
    html = html_template.replace("__ORGBRO_TOKEN__", token).encode("utf-8")
    endpoints = {name: getattr(api, name) for name in (
        "ping", "ports", "probe", "ble_scan", "fonts", "status", "cancel", "print", "save_png",
        "project_save", "project_open", "recent", "autosave", "autoload",
    )}
    static_roots = {d: os.path.realpath(resource_path(d)) for d in STATIC_DIRS}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # no console in windowed builds
            pass

        def _send(self, code, body, ctype, cache=False):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html", "/editor.html"):
                return self._send(200, html, "text/html; charset=utf-8")
            parts = path.lstrip("/").split("/", 1)
            if len(parts) == 2 and parts[0] in static_roots:
                root = static_roots[parts[0]]
                full = os.path.realpath(os.path.join(root, parts[1]))
                if full.startswith(root + os.sep) and os.path.isfile(full):
                    ctype = {".woff2": "font/woff2", ".js": "text/javascript"}.get(
                        os.path.splitext(full)[1].lower()) or mimetypes.guess_type(full)[0] or "application/octet-stream"
                    with open(full, "rb") as f:
                        return self._send(200, f.read(), ctype, cache=True)
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
                return self._json(413, {"error": "Request is too large."})
            try:
                payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
                self._json(200, fn(payload if isinstance(payload, dict) else {}))
            except Exception as e:
                write_crash_log(traceback.format_exc())
                self._json(500, {"error": str(e)})

    return ThreadingHTTPServer((host, port), Handler)


# --------------------------------------------------------------------------- windows

def run_native_window(api, url):
    import webview
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:
        pass
    window = webview.create_window(f"{APP_NAME} {APP_VERSION}", url, width=1440, height=960,
                                   min_size=(1000, 700))
    api.window = window
    storage = os.path.join(app_data_dir(), "webview")
    icon = resource_path(os.path.join("assets", "icon.ico"))
    kwargs = dict(gui="edgechromium", private_mode=False, storage_path=storage)
    if os.path.isfile(icon):
        kwargs["icon"] = icon
    try:
        webview.start(**kwargs)
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
            "--no-first-run", "--no-default-browser-check", "--window-size=1440,960",
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


def selftest(out_path):
    """Used by CI on the frozen EXE: check bundled modules import, write the result to a file."""
    results = []
    for mod in ("serial.tools.list_ports", "PIL.Image", "webview", "bleak", "cat_printer",
                "bleak.backends.winrt.scanner", "bleak.backends.winrt.client"):
        try:
            __import__(mod)
            results.append(f"ok {mod}")
        except Exception as e:
            results.append(f"FAIL {mod}: {e!r}")
    for name in ("editor.html", "VERSION", os.path.join("fonts", "Inter.woff2"), os.path.join("vendor", "qrcode.js")):
        results.append(("ok " if os.path.isfile(resource_path(name)) else "FAIL missing ") + name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")
    return 1 if any(r.startswith("FAIL") for r in results) else 0


def main():
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        out = sys.argv[i + 1] if len(sys.argv) > i + 1 else "selftest.txt"
        sys.exit(selftest(out))
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
