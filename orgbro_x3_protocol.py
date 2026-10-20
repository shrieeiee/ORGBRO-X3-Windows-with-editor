"""
ORGBRO X3 printer protocol helpers (shared by ORGBRO X3 Studio).

Raster format (see README):
  * 864 px wide, 1-bit, MSB-first, black = 1
  * 108 bytes per row, 432-byte payloads (4 rows per packet)

Frame layout (as captured from the official app):
  64 <cmd> <seq> <len lo> <len hi> <payload...> 00 00 00 00 9b

  cmd 0x0a  payload 1 byte  (0x55 in the capture - believed to be print density/heat)
  cmd 0x09  payload 1 byte  (0x0c in the capture)
  cmd 0x00  payload 432 bytes of raster (4 rows)
  cmd 0x02  payload 2 bytes, little-endian (200 in the capture - believed to be feed in dots)
"""

import base64
import io
import time

from PIL import Image

WIDTH = 864
BYTES_PER_ROW = WIDTH // 8
ROWS_PER_PACKET = 4
PAYLOAD_SIZE = BYTES_PER_ROW * ROWS_PER_PACKET  # 432

DEFAULT_DENSITY = 0x55
DEFAULT_FEED = 200
FIRST_DATA_SEQ = 5

# Status requests the Android app sends before printing; the printer answers them.
STATUS_REQUESTS = (
    bytes.fromhex("641101000000000000"),
    bytes.fromhex("641202000000000000"),
)


def frame(cmd, seq, payload):
    return (
        b"\x64" + bytes([cmd & 0xFF, seq & 0xFF])
        + len(payload).to_bytes(2, "little")
        + payload
        + b"\x00\x00\x00\x00\x9b"
    )


def init_frames(density=DEFAULT_DENSITY):
    return [frame(0x0A, 3, bytes([int(density) & 0xFF])), frame(0x09, 4, b"\x0c")]


INIT_1, INIT_2 = init_frames()


def data_frame(seq, payload):
    return frame(0x00, seq, payload)


def end_frame(seq, feed=DEFAULT_FEED):
    return frame(0x02, seq, int(max(0, min(feed, 65535))).to_bytes(2, "little"))


def is_data_frame(fr):
    return len(fr) > 2 and fr[1] == 0x00


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

    padded_h = ((bw.height + ROWS_PER_PACKET - 1) // ROWS_PER_PACKET) * ROWS_PER_PACKET
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


def build_frames(raster, density=DEFAULT_DENSITY, feed=DEFAULT_FEED, split_packets=None):
    """
    Build the frame list for a job.

    split_packets: if set, the image is sent as several back-to-back jobs of at most
    this many packets (so the 1-byte sequence counter never wraps). Intermediate jobs
    use feed 0 so the paper does not advance between parts.
    """
    payloads = [raster[p:p + PAYLOAD_SIZE] for p in range(0, len(raster), PAYLOAD_SIZE)]
    if not payloads:
        payloads = [bytes(PAYLOAD_SIZE)]
    if split_packets:
        split_packets = max(1, min(int(split_packets), 250))
        groups = [payloads[i:i + split_packets] for i in range(0, len(payloads), split_packets)]
    else:
        groups = [payloads]

    frames = []
    for gi, group in enumerate(groups):
        frames += init_frames(density)
        seq = FIRST_DATA_SEQ
        for payload in group:
            frames.append(data_frame(seq, payload))
            seq = (seq + 1) & 0xFF
        frames.append(end_frame(seq, feed if gi == len(groups) - 1 else 0))
    return frames


def list_com_ports():
    from serial.tools import list_ports
    return [
        {"device": p.device, "description": p.description or ""}
        for p in sorted(list_ports.comports(), key=lambda p: p.device)
    ]


def probe_port(port, timeout=0.6):
    """Send the app's status requests; returns the printer's reply bytes (b'' if none)."""
    import serial
    reply = b""
    with serial.Serial(port=port, baudrate=115200, timeout=timeout, write_timeout=2.0) as ser:
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        for req in STATUS_REQUESTS:
            ser.write(req)
            ser.flush()
            time.sleep(0.15)
            reply += ser.read(512)
    return reply


def send_frames(port, frames, delay=0.02, progress=None, log=None, cancel_event=None):
    """
    Send frames to the printer. progress(percent, message) and log(text) are optional
    callbacks. If cancel_event is set mid-job, the remaining image data is skipped and
    an end-of-job frame is sent so the printer finishes cleanly.
    Returns True if completed, False if cancelled.
    """
    import serial

    progress = progress or (lambda pct, msg: None)
    log = log or (lambda text: None)
    total_packets = max(1, sum(1 for f in frames if is_data_frame(f)))
    sent_packets = 0
    cancelled = False

    with serial.Serial(port=port, baudrate=115200, timeout=0.25, write_timeout=4.0) as ser:
        try:
            ser.reset_input_buffer()
        except Exception:
            pass

        for i, fr in enumerate(frames):
            if cancel_event is not None and cancel_event.is_set() and is_data_frame(fr):
                cancelled = True
                log("Cancelled - sending end-of-job frame.")
                ser.write(end_frame(fr[2], DEFAULT_FEED))
                ser.flush()
                break

            ser.write(fr)
            ser.flush()

            if is_data_frame(fr):
                sent_packets += 1
                progress(sent_packets / total_packets * 100,
                         f"Printing... packet {sent_packets}/{total_packets}")
            elif fr[1] == 0x02:
                progress(sent_packets / total_packets * 100, "Feeding paper...")
            else:
                progress(sent_packets / total_packets * 100, "Starting job...")

            time.sleep(delay)
            if ser.in_waiting:
                ser.read(ser.in_waiting)

        time.sleep(0.6)
        if ser.in_waiting:
            rx = ser.read(ser.in_waiting)
            log("Final RX: " + rx.hex(" "))

    return not cancelled
