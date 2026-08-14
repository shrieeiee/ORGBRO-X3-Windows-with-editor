import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial is not installed.")
    print("Run: py -m pip install pyserial")
    raise SystemExit(1)

WIDTH = 864
HEIGHT = 120
BYTES_PER_ROW = WIDTH // 8   # 108 bytes

INIT_1 = bytes.fromhex("640a03010055000000009b")
INIT_2 = bytes.fromhex("64090401000c000000009b")

def set_black(bitmap, x, y):
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
        return
    i = y * BYTES_PER_ROW + (x // 8)
    bitmap[i] |= 1 << (7 - (x % 8))

def line_h(b, x0, x1, y, t=1):
    for dy in range(t):
        for x in range(x0, x1 + 1):
            set_black(b, x, y + dy)

def line_v(b, x, y0, y1, t=1):
    for dx in range(t):
        for y in range(y0, y1 + 1):
            set_black(b, x + dx, y)

def make_bitmap():
    b = bytearray(BYTES_PER_ROW * HEIGHT)

    # Large centered rectangle
    x0, x1 = 80, WIDTH - 81
    y0, y1 = 20, 100

    line_h(b, x0, x1, y0, 2)
    line_h(b, x0, x1, y1, 2)
    line_v(b, x0, y0, y1, 2)
    line_v(b, x1, y0, y1, 2)

    # True center cross
    cx = WIDTH // 2
    cy = 60

    line_h(b, cx - 60, cx + 60, cy, 3)
    line_v(b, cx, cy - 25, cy + 25, 3)

    # 7 vertical reference marks across the printable width
    positions = [108, 216, 324, 432, 540, 648, 756]
    for n, x in enumerate(positions, 1):
        line_v(b, x, 35, 85, min(n, 6))

    # left marker = small solid square
    for y in range(35, 50):
        for x in range(95, 110):
            set_black(b, x, y)

    # right marker = wider solid square
    for y in range(35, 50):
        for x in range(745, 775):
            set_black(b, x, y)

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

    # Native packet payload from capture = 432 bytes = 4 rows x 108 bytes.
    seq = 5
    for pos in range(0, len(bitmap), 432):
        frames.append(make_data_frame(seq, bitmap[pos:pos+432]))
        seq = (seq + 1) & 0xFF

    frames.append(
        b"\x64\x02"
        + bytes([seq])
        + b"\x02\x00\xc8\x00\x00\x00\x00\x00\x9b"
    )
    return frames

def show_ports():
    print("Available COM ports:")
    for p in list_ports.comports():
        print(f"  {p.device}: {p.description}")

def main():
    if len(sys.argv) < 2:
        show_ports()
        print("\nUsage: py orgbro_x3_864_test.py COM5")
        return 1

    port = sys.argv[1]
    frames = make_stream()

    print(f"Opening {port}...")
    print(f"Native test bitmap: {WIDTH} x {HEIGHT}")
    print(f"{BYTES_PER_ROW} bytes/row; 432-byte packet = 4 raster rows")
    print()

    try:
        with serial.Serial(
            port=port,
            baudrate=115200,
            timeout=0.25,
            write_timeout=4.0,
        ) as ser:
            ser.reset_input_buffer()

            image_count = len(frames) - 3

            for i, frame in enumerate(frames):
                ser.write(frame)
                ser.flush()

                if i < 2:
                    print(f"TX init {i+1}: {len(frame)} bytes")
                elif i == len(frames) - 1:
                    print(f"TX final: {len(frame)} bytes")
                else:
                    print(f"TX image {i-1:02d}/{image_count}: {len(frame)} bytes")

                time.sleep(0.02)

                if ser.in_waiting:
                    rx = ser.read(ser.in_waiting)
                    print("RX:", rx.hex(" "))

            time.sleep(0.7)
            if ser.in_waiting:
                print("Final RX:", ser.read(ser.in_waiting).hex(" "))

    except serial.SerialTimeoutException:
        print("ERROR: write timeout.")
        return 2
    except serial.SerialException as e:
        print("Serial error:", e)
        return 3

    print("\nDone.")
    print("Expected: ONE wide rectangle with a centered + and vertical marks.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
