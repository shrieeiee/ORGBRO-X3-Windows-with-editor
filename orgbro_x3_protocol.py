"""
ORGBRO X3 printer protocol helpers (shared by ORGBRO X3 Studio).

Raster format (see README):
  * 864 px wide, 1-bit, MSB-first, black = 1
  * 108 bytes per row, 432-byte payloads (4 rows per packet)
"""

import base64
import io
import time

from PIL import Image

WIDTH = 864
BYTES_PER_ROW = WIDTH // 8
PAYLOAD_SIZE = 432  # 4 raster rows per packet

INIT_1 = bytes.fromhex("640a03010055000000009b")
INIT_2 = bytes.fromhex("64090401000c000000009b")


def decode_data_url(data_url):
    """Return raw bytes from a 'data:image/png;base64,...' string (or plain base64)."""
    if "," in data_url and data_url.lstrip().startswith("data:"):
        data_url = data_url.split(",", 1)[1]
    return base64.b64decode(data_url)


def load_print_image(png_bytes, threshold=128):
    """
    Turn a rendered layout PNG into a padded 1-bit image ready for the printer.
    The editor already produces pure black/white pixels; the threshold here only
    guards against any stray grey from scaling.
    """
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

    bw = img.point(lambda p: 255 if p >= threshold else 0, mode="1")

    padded_h = ((bw.height + 3) // 4) * 4
    if padded_h != bw.height:
        padded = Image.new("1", (WIDTH, padded_h), 1)
        padded.paste(bw, (0, 0))
        bw = padded
    return bw


def image_to_raster(img):
    """Pack a mode-'1' 864px image into printer raster bytes (black pixel = bit 1)."""
    if img.mode != "1":
        raise ValueError("image must be mode '1'")
    if img.width != WIDTH:
        raise ValueError(f"image must be {WIDTH}px wide")
    # Pillow packs mode '1' MSB-first with 1 = white, so invert every byte.
    return bytes(b ^ 0xFF for b in img.tobytes())


def data_frame(seq, payload):
    return (
        b"\x64\x00"
        + bytes([seq & 0xFF])
        + len(payload).to_bytes(2, "little")
        + payload
        + b"\x00\x00\x00\x00\x9b"
    )


def end_frame(seq):
    return b"\x64\x02" + bytes([seq & 0xFF]) + b"\x02\x00\xc8\x00\x00\x00\x00\x00\x9b"


def build_frames(raster):
    frames = [INIT_1, INIT_2]
    seq = 5
    for pos in range(0, len(raster), PAYLOAD_SIZE):
        frames.append(data_frame(seq, raster[pos:pos + PAYLOAD_SIZE]))
        seq = (seq + 1) & 0xFF
    frames.append(end_frame(seq))
    return frames


def list_com_ports():
    from serial.tools import list_ports
    return [
        {"device": p.device, "description": p.description or ""}
        for p in sorted(list_ports.comports(), key=lambda p: p.device)
    ]


def send_frames(port, frames, delay=0.02, progress=None, log=None, cancel_event=None):
    """
    Send frames to the printer. progress(percent, message) and log(text) are optional
    callbacks. If cancel_event is set mid-job, the remaining image data is skipped and
    the end/feed frame is still sent so the printer finishes cleanly.
    Returns True if completed, False if cancelled.
    """
    import serial

    progress = progress or (lambda pct, msg: None)
    log = log or (lambda text: None)
    total_packets = max(1, len(frames) - 3)
    cancelled = False

    with serial.Serial(port=port, baudrate=115200, timeout=0.25, write_timeout=4.0) as ser:
        try:
            ser.reset_input_buffer()
        except Exception:
            pass

        last = len(frames) - 1
        for i, frame in enumerate(frames):
            if cancel_event is not None and cancel_event.is_set() and 1 < i < last:
                cancelled = True
                log("Cancelled - sending end-of-job frame.")
                ser.write(frames[last])
                ser.flush()
                break

            ser.write(frame)
            ser.flush()

            if i == 0:
                progress(0, "Sending init 1...")
            elif i == 1:
                progress(0, "Sending init 2...")
            elif i == last:
                progress(100, "Sending final feed...")
            else:
                current = i - 1
                progress(current / total_packets * 100, f"Printing... packet {current}/{total_packets}")

            time.sleep(delay)
            if ser.in_waiting:
                ser.read(ser.in_waiting)

        time.sleep(0.6)
        if ser.in_waiting:
            rx = ser.read(ser.in_waiting)
            log("Final RX: " + rx.hex(" "))

    return not cancelled
