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
HEIGHT = 180
BYTES_PER_ROW = WIDTH // 8

INIT_1 = bytes.fromhex("640a03010055000000009b")
INIT_2 = bytes.fromhex("64090401000c000000009b")

def set_black(bitmap, x, y):
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
        return
    i = y * BYTES_PER_ROW + (x // 8)
    bitmap[i] |= 1 << (7 - (x % 8))

def vline(bitmap, x, y0=20, y1=150, thickness=1):
    for dx in range(thickness):
        xx = x + dx
        for y in range(y0, y1 + 1):
            set_black(bitmap, xx, y)

def hline(bitmap, y, x0=0, x1=WIDTH-1, thickness=1):
    for dy in range(thickness):
        yy = y + dy
        for x in range(x0, x1 + 1):
            set_black(bitmap, x, yy)

def make_bitmap():
    b = bytearray(BYTES_PER_ROW * HEIGHT)

    # Horizontal reference lines
    hline(b, 20, 0, WIDTH - 1, 1)
    hline(b, 150, 0, WIDTH - 1, 1)

    # Vertical calibration positions.
    # Thickness changes so positions can be identified even if order is odd.
    marks = [
        (0,   1),
        (54,  2),
        (108, 3),
        (162, 4),
        (216, 5),
        (270, 6),
        (324, 7),
        (378, 8),
        (430, 2),
    ]

    for x, thickness in marks:
        vline(b, x, 20, 150, thickness)

    # Small corner markers:
    # top-left block
    for y in range(30, 45):
        for x in range(10, 25):
            set_black(b, x, y)

    # top-right block, wider
    for y in range(30, 45):
        for x in range(WIDTH - 35, WIDTH - 10):
            set_black(b, x, y)

    # Center cross
    cx = WIDTH // 2
    cy = 85
    for x in range(cx - 15, cx + 16):
        set_black(b, x, cy)
        set_black(b, x, cy + 1)
    for y in range(cy - 15, cy + 16):
        set_black(b, cx, y)
        set_black(b, cx + 1, y)

    return bytes(b)

def make_data_frame(seq, payload):
    return (
        b"\x64\x00"
        + bytes([seq & 0xFF])
        + len(payload).to_bytes(2, "little")
        + payload
        + b"\x00\x00\x00\x00\x9b"
    )

def make_stream():
    bitmap = make_bitmap()
    frames = [INIT_1, INIT_2]

    seq = 5
    for pos in range(0, len(bitmap), 432):
        frames.append(make_data_frame(seq, bitmap[pos:pos + 432]))
        seq += 1

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

def main():
    if len(sys.argv) < 2:
        show_ports()
        print()
        print("Usage: py orgbro_x3_calibration.py COM5")
        return 1

    port = sys.argv[1]
    frames = make_stream()

    print(f"Opening {port}...")
    print(f"Calibration bitmap: {WIDTH} x {HEIGHT}")
    print("Vertical marks at x = 0, 54, 108, 162, 216, 270, 324, 378, 430")
    print("Each mark has a different thickness.")
    print()

    try:
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
                    print(f"TX final: {len(frame)} bytes")
                else:
                    print(f"TX image {i-1:02d}/{len(frames)-3}: {len(frame)} bytes")

                time.sleep(0.02)

                if ser.in_waiting:
                    rx = ser.read(ser.in_waiting)
                    print("RX:", rx.hex(" "))

            time.sleep(0.7)
            if ser.in_waiting:
                rx = ser.read(ser.in_waiting)
                print("Final RX:", rx.hex(" "))

    except serial.SerialTimeoutException:
        print("ERROR: write timeout.")
        return 2
    except serial.SerialException as e:
        print("Serial error:", e)
        return 3

    print()
    print("Done.")
    print("Take a photo of the printed calibration pattern and send it to me.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
