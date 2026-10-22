"""
"Cat printer" support for ORGBRO X3 Studio (GB01/GB02/GB03, MX05-MX11, YT01 and similar
Bluetooth LE mini thermal printers).

Protocol notes (as documented by the Cat-Printer / kitty-printer projects by NaitLee,
whose protocol description file is public domain):

  * Bluetooth LE. Printers advertise service 0xAF30; printing uses service 0xAE30 with
    characteristic 0xAE01 (write without response) and 0xAE02 (notifications).
  * 384-dot print head, about 8 dots/mm (48 mm printable on 57/58 mm paper).
  * Each command:  51 78 <cmd> 00 <len lo> <len hi> <payload...> <crc8(payload)> ff
  * Bitmap rows are 48 bytes, least-significant bit = leftmost pixel, 1 = black.
  * The printer sends flow-control notifications; byte 6 bit 0x10 means "pause".

This file implements the protocol from scratch; it is not a copy of either project.
The BLE transport uses `bleak` (WinRT on Windows) and is only imported when needed.
"""

import asyncio
import io
import re
import threading
import time

from PIL import Image

WIDTH = 384
BYTES_PER_ROW = WIDTH // 8
DOTS_PER_MM = 8

SERVICE_ADVERTISED = "0000af30-0000-1000-8000-00805f9b34fb"
SERVICE_PRINT = "0000ae30-0000-1000-8000-00805f9b34fb"
CHAR_TX = "0000ae01-0000-1000-8000-00805f9b34fb"
CHAR_RX = "0000ae02-0000-1000-8000-00805f9b34fb"

# Names seen on printers that speak this protocol (others are still accepted if they
# advertise the 0xAF30 service).
KNOWN_NAME = re.compile(r"^(GB0\d|GT0\d|MX\d{2}|YT0\d|_ZZ\d*|MXTP|LY\d{2}|AI\d{2}|EWTTO|BQ\d{2})", re.I)

CMD_RETRACT = 0xA0
CMD_FEED = 0xA1
CMD_BITMAP = 0xA2
CMD_STATE = 0xA3
CMD_DPI = 0xA4
CMD_LATTICE = 0xA6
CMD_INFO = 0xA8
CMD_UPDATE = 0xA9
CMD_FLOW = 0xAE
CMD_ENERGY = 0xAF
CMD_CAMERA = 0xBC
CMD_SPEED = 0xBD
CMD_APPLY_ENERGY = 0xBE

SPEEDS = {"quick": 8, "fast": 16, "normal": 32}
ENERGIES = {"low": 12000, "medium": 24000, "high": 48000}
DEFAULT_SPEED = 32
DEFAULT_ENERGY = 24000
DEFAULT_FEED = 100
BLANK_SPEED = 8

STATE_OUT_OF_PAPER = 0x01
STATE_COVER_OPEN = 0x02
STATE_OVERHEAT = 0x04
STATE_LOW_POWER = 0x08
STATE_PAUSE = 0x10
STATE_BUSY = 0x80


def _crc8_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
        table.append(c)
    return table


_CRC8 = _crc8_table()


def crc8(data):
    c = 0
    for b in data:
        c = _CRC8[(c ^ b) & 0xFF]
    return c


def command(cmd, payload=b""):
    payload = bytes(payload)
    return (bytes([0x51, 0x78, cmd & 0xFF, 0x00, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF])
            + payload + bytes([crc8(payload), 0xFF]))


def u16(value):
    value = int(max(0, min(value, 0xFFFF)))
    return bytes([value & 0xFF, value >> 8])


LATTICE_START = command(CMD_LATTICE, bytes.fromhex("aa551738445f5f5f44382c"))
LATTICE_END = command(CMD_LATTICE, bytes.fromhex("aa5517" + "00" * 7 + "17"))
# Captured verbatim from a camera-style model (its framing differs, so it is sent as-is).
CAMERA_PREPARE = bytes.fromhex("5178bc000102012dff")


def parse_state(message):
    """Decode a state / flow-control notification. Returns None if it isn't one."""
    if len(message) < 7 or message[0] != 0x51 or message[1] != 0x78:
        return None
    if message[2] not in (CMD_STATE, CMD_FLOW):
        return None
    s = message[6]
    return {
        "out_of_paper": bool(s & STATE_OUT_OF_PAPER),
        "cover_open": bool(s & STATE_COVER_OPEN),
        "overheat": bool(s & STATE_OVERHEAT),
        "low_power": bool(s & STATE_LOW_POWER),
        "pause": bool(s & STATE_PAUSE),
        "busy": bool(s & STATE_BUSY),
    }


# --------------------------------------------------------------------------- images

def load_print_image(png_bytes, threshold=128):
    """Rendered layout PNG -> 384-px-wide 1-bit image (transparent areas become white)."""
    img = Image.open(io.BytesIO(png_bytes))
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        img = bg
    img = img.convert("L")
    if img.width != WIDTH:
        new_h = max(1, round(img.height * WIDTH / img.width))
        img = img.resize((WIDTH, new_h), Image.Resampling.LANCZOS)
    return img.point(lambda p: 255 if p >= threshold else 0, mode="1")


_REVERSE = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


def image_to_rows(img):
    """Mode-'1' 384-px image -> list of 48-byte rows (LSB = leftmost pixel, 1 = black)."""
    if img.mode != "1" or img.width != WIDTH:
        raise ValueError(f"image must be mode '1' and {WIDTH}px wide")
    # Pillow packs MSB-first with 1 = white: invert, then reverse the bit order.
    data = bytes(_REVERSE[b ^ 0xFF] for b in img.tobytes())
    return [data[i:i + BYTES_PER_ROW] for i in range(0, len(data), BYTES_PER_ROW)]


# --------------------------------------------------------------------------- jobs

def job_start(speed=DEFAULT_SPEED, energy=DEFAULT_ENERGY):
    return [
        command(CMD_STATE, b"\x00"),
        CAMERA_PREPARE,                    # needed by some camera-style models; ignored by others
        command(CMD_DPI, bytes([50])),
        command(CMD_SPEED, bytes([int(speed) & 0xFF])),
        command(CMD_ENERGY, u16(energy)),
        command(CMD_APPLY_ENERGY, b"\x01"),
        command(CMD_UPDATE, b"\x00"),
        LATTICE_START,
    ]


def job_end(feed=DEFAULT_FEED):
    out = [LATTICE_END, command(CMD_SPEED, bytes([BLANK_SPEED]))]
    feed = int(max(0, feed))
    while feed > 0:                      # feed is 16-bit; split very long feeds
        step = min(feed, 0xFFFF)
        out.append(command(CMD_FEED, u16(step)))
        feed -= step
    out.append(command(CMD_STATE, b"\x00"))
    return out


def row_commands(rows, speed=DEFAULT_SPEED):
    """
    Yield (row_index, [commands]) for the image body. Runs of blank rows are sent as
    a quick paper feed instead of empty bitmaps (faster, and what the official apps do).
    Trailing blank rows are returned separately so they can be added to the final feed.
    """
    pending_blank = 0
    for i, row in enumerate(rows):
        if not any(row):
            pending_blank += 1
            continue
        cmds = []
        if pending_blank:
            cmds += [command(CMD_SPEED, bytes([BLANK_SPEED])), command(CMD_FEED, u16(pending_blank)),
                     command(CMD_SPEED, bytes([int(speed) & 0xFF]))]
            pending_blank = 0
        cmds.append(command(CMD_BITMAP, row))
        yield i, cmds
    yield len(rows), ("trailing", pending_blank)


def build_job(rows, speed=DEFAULT_SPEED, energy=DEFAULT_ENERGY, feed=DEFAULT_FEED):
    """Complete command list for a job (used by tests and the dry-run path)."""
    out = job_start(speed, energy)
    trailing = 0
    for _, cmds in row_commands(rows, speed):
        if isinstance(cmds, tuple):
            trailing = cmds[1]
        else:
            out += cmds
    return out + job_end(trailing + feed)


def pack(commands, mtu=200):
    """Group commands into writes of at most `mtu` bytes (never splitting a command if avoidable)."""
    packets, cur = [], b""
    for c in commands:
        if cur and len(cur) + len(c) > mtu:
            packets.append(cur)
            cur = b""
        while len(c) > mtu:              # only happens with tiny MTUs
            packets.append(c[:mtu])
            c = c[mtu:]
        cur += c
    if cur:
        packets.append(cur)
    return packets


# --------------------------------------------------------------------------- BLE transport

class BleWorker:
    """One asyncio loop on a background thread for all Bluetooth LE work."""

    def __init__(self):
        self._loop = None
        self._thread = None
        self._lock = threading.Lock()

    def _ensure(self):
        with self._lock:
            if self._loop is None:
                ready = threading.Event()

                def run():
                    try:  # bleak needs an MTA thread on Windows; undo STA if something set it
                        from bleak.backends.winrt.util import uninitialize_sta
                        uninitialize_sta()
                    except Exception:
                        pass
                    self._loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self._loop)
                    ready.set()
                    self._loop.run_forever()

                self._thread = threading.Thread(target=run, name="ble", daemon=True)
                self._thread.start()
                ready.wait(5)
        return self._loop

    def run(self, coro, timeout=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self._ensure())
        return fut.result(timeout)


async def scan(timeout=6.0):
    """Find nearby BLE devices. Cat printers are flagged `likely` and listed first."""
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    out = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        likely = SERVICE_ADVERTISED in uuids or SERVICE_PRINT in uuids or bool(KNOWN_NAME.match(name))
        if not name and not likely:
            continue
        out.append({"address": device.address, "name": name or "(unnamed)", "rssi": adv.rssi, "likely": likely})
    out.sort(key=lambda d: (not d["likely"], -(d["rssi"] or -999)))
    return out


async def print_rows(address, rows, speed=DEFAULT_SPEED, energy=DEFAULT_ENERGY, feed=DEFAULT_FEED,
                     delay=0.02, progress=None, log=None, cancel_event=None, client_factory=None):
    """
    Connect to a cat printer and print `rows`. Returns True if completed, False if cancelled.
    `client_factory(address)` can be supplied for testing.
    """
    progress = progress or (lambda pct, msg: None)
    log = log or (lambda text: None)
    if client_factory is None:
        from bleak import BleakClient

        def client_factory(addr):
            return BleakClient(addr, timeout=20.0)

    state = {"pause": False, "out_of_paper": False, "cover_open": False, "overheat": False, "low_power": False}
    warned = set()

    def on_notify(_sender, data):
        st = parse_state(bytes(data))
        if not st:
            return
        state.update(st)
        for key, text in (("out_of_paper", "Printer reports: out of paper"), ("cover_open", "Printer reports: cover open"),
                          ("overheat", "Printer reports: overheating - pausing"), ("low_power", "Printer reports: low battery")):
            if st[key] and key not in warned:
                warned.add(key)
                log(text)

    progress(0, "Connecting over Bluetooth LE...")
    client = client_factory(address)
    await client.connect()
    try:
        log(f"Connected to {address}")
        mtu = 200
        try:
            size = int(getattr(client, "mtu_size", 0) or 0)
            if size > 23:
                mtu = min(200, size - 3)
            elif size:
                mtu = 20
        except Exception:
            pass
        log(f"Write size: {mtu} bytes")
        try:
            await client.start_notify(CHAR_RX, on_notify)
        except Exception as e:
            log(f"Notifications unavailable ({e}); printing without flow control")

        buf = bytearray()

        async def flush():
            nonlocal buf
            waited = 0.0
            while state["pause"] or state["overheat"]:
                await asyncio.sleep(0.1)
                waited += 0.1
                if waited > 60:
                    raise RuntimeError("The printer stayed paused for over a minute.")
            for packet in pack([bytes(buf)], mtu) if buf else []:
                await client.write_gatt_char(CHAR_TX, packet, response=False)
                await asyncio.sleep(delay)
            buf = bytearray()

        async def send(cmds):
            nonlocal buf
            for c in cmds:
                if len(buf) + len(c) > mtu:
                    await flush()
                buf += c

        await send(job_start(speed, energy))
        await flush()
        await asyncio.sleep(0.2)
        if state["out_of_paper"]:
            raise RuntimeError("The printer is out of paper.")
        if state["cover_open"]:
            raise RuntimeError("The printer's cover is open.")

        total = max(1, len(rows))
        trailing, cancelled, last_pct = 0, False, -1
        for i, cmds in row_commands(rows, speed):
            if isinstance(cmds, tuple):
                trailing = cmds[1]
                break
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                log("Cancelled - finishing the job.")
                break
            await send(cmds)
            pct = int(i * 100 / total)
            if pct != last_pct:
                last_pct = pct
                progress(pct, f"Printing... row {i + 1}/{total}")
        await send(job_end((0 if cancelled else trailing) + feed))
        await flush()
        progress(100, "Feeding paper...")
        await asyncio.sleep(0.5)
        try:
            await client.stop_notify(CHAR_RX)
        except Exception:
            pass
        return not cancelled
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def print_image(worker, address, png_bytes, **kw):
    bw = load_print_image(png_bytes)
    rows = image_to_rows(bw)
    return worker.run(print_rows(address, rows, **kw)), bw
