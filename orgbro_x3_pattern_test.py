import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial is not installed.")
    print("Run: py -m pip install pyserial")
    raise SystemExit(1)

WIDTH = 432
HEIGHT = 194
BYTES_PER_ROW = WIDTH // 8

# Commands captured from the Android -> ORGBRO X3 session.
INIT_1 = bytes.fromhex("640a03010055000000009b")
INIT_2 = bytes.fromhex("64090401000c000000009b")

def set_black(bitmap, x, y):
    """Set one pixel black. Captured data strongly suggests 1 = black."""
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
        return
    i = y * BYTES_PER_ROW + (x // 8)
    bitmap[i] |= 1 << (7 - (x % 8))  # MSB first

def make_test_bitmap():
    """
    Safe sparse pattern:
    - outer rectangle
    - diagonals
    - several vertical bars
    Avoids a large solid black area to reduce thermal load.
    """
    b = bytearray(BYTES_PER_ROW * HEIGHT)

    # Rectangle, inset from the paper edges.
    left, right = 40, WIDTH - 41
    top, bottom = 55, 125

    for x in range(left, right + 1):
        set_black(b, x, top)
        set_black(b, x, top + 1)
        set_black(b, x, bottom)
        set_black(b, x, bottom - 1)

    for y in range(top, bottom + 1):
        set_black(b, left, y)
        set_black(b, left + 1, y)
        set_black(b, right, y)
        set_black(b, right - 1, y)

    # X inside the box.
    w = right - left
    h = bottom - top
    for dy in range(h + 1):
        x1 = left + int(dy * w / h)
        x2 = right - int(dy * w / h)
        y = top + dy
        set_black(b, x1, y)
        set_black(b, x1 + 1, y)
        set_black(b, x2, y)
        set_black(b, x2 - 1, y)

    # Barcode-like marks in the middle.
    for x in range(155, 278, 12):
        for xx in range(x, min(x + 4, WIDTH)):
            for y in range(78, 104):
                set_black(b, xx, y)

    return bytes(b)

def make_data_frame(seq, payload):
    # Observed frame:
    # 64 00 <seq> <payload_len LE16> <payload> 00 00 00 00 9b
    return (
        b"\x64\x00"
        + bytes([seq & 0xFF])
        + len(payload).to_bytes(2, "little")
        + payload
        + b"\x00\x00\x00\x00\x9b"
    )

def make_stream():
    bitmap = make_test_bitmap()

    frames = [INIT_1, INIT_2]

    # Captured app used 432-byte payloads:
    # 432 bytes = 8 raster rows because each row is 54 bytes.
    seq = 5
    for pos in range(0, len(bitmap), 432):
        frames.append(make_data_frame(seq, bitmap[pos:pos + 432]))
        seq += 1

    # Captured final command:
    # 64 02 1e 02 00 c8 00 00 00 00 00 9b
    # seq is 0x1e after image frames 0x05..0x1d.
    frames.append(
        b"\x64\x02"
        + bytes([seq & 0xFF])
        + b"\x02\x00\xc8\x00\x00\x00\x00\x00\x9b"
    )
    return frames

def show_ports():
    ports = list(list_ports.comports())
    print("Available COM ports:")
    for p in ports:
        print(f"  {p.device}: {p.description}")
    if not ports:
        print("  (none)")

def read_available(ser, wait=0.15):
    time.sleep(wait)
    waiting = ser.in_waiting
    if waiting:
        data = ser.read(waiting)
        print("RX:", data.hex(" "))
        return data
    return b""

def main():
    if len(sys.argv) < 2:
        show_ports()
        print()
        print("Usage: py orgbro_x3_pattern_test.py COM5")
        return 1

    port = sys.argv[1]
    frames = make_stream()

    print(f"Opening {port}...")
    print(f"Test image: {WIDTH} x {HEIGHT}, 1-bit, {BYTES_PER_ROW} bytes/row")
    print("Pattern: rectangle + X + vertical bars")
    print()

    try:
        # Same simple serial-over-Bluetooth approach as the working replay.
        with serial.Serial(
            port=port,
            baudrate=115200,
            timeout=0.25,
            write_timeout=4.0,
        ) as ser:
            ser.reset_input_buffer()

            for i, frame in enumerate(frames):
                ser.write(frame)
                ser.flush()

                if i < 2:
                    print(f"TX init {i+1}: {len(frame)} bytes")
                elif i == len(frames) - 1:
                    print(f"TX final command: {len(frame)} bytes")
                else:
                    print(f"TX image {i-1:02d}/25: {len(frame)} bytes")

                # Keep conservative pacing over Bluetooth SPP.
                time.sleep(0.02)

                # Read any immediate printer response.
                if ser.in_waiting:
                    read_available(ser, 0.02)

            print()
            print("Waiting for final printer response...")
            read_available(ser, 0.7)

    except serial.SerialTimeoutException:
        print("ERROR: write timeout. This is probably the wrong Bluetooth COM port.")
        return 2
    except serial.SerialException as e:
        print("Serial error:", e)
        return 3

    print()
    print("Done.")
    print("Tell me what happened:")
    print("  A) rectangle/X/bars printed")
    print("  B) paper moved but stayed blank")
    print("  C) garbage/partial image printed")
    print("  D) nothing happened")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
