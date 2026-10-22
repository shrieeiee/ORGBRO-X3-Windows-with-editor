"""Tests for cat printer support (protocol + simulated Bluetooth LE printer)."""

import asyncio
import io
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image, ImageDraw  # noqa: E402

import cat_printer as cat  # noqa: E402


class FakePrinter:
    """Pretends to be a BLE cat printer: records writes, sends flow-control notifications."""

    def __init__(self, address, pause_after=None, out_of_paper=False):
        self.address = address
        self.writes = []
        self.handler = None
        self.connected = False
        self.mtu_size = 247
        self.pause_after = pause_after
        self.out_of_paper = out_of_paper
        self.paused_once = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def start_notify(self, char, handler):
        assert char == cat.CHAR_RX
        self.handler = handler

    async def stop_notify(self, char):
        self.handler = None

    async def write_gatt_char(self, char, data, response=False):
        assert char == cat.CHAR_TX and response is False
        assert len(data) <= self.mtu_size - 3
        self.writes.append(bytes(data))
        if self.out_of_paper and len(self.writes) == 1:
            self.handler(None, bytearray.fromhex("5178a30101000100ff"))
        if self.pause_after and len(self.writes) == self.pause_after and not self.paused_once:
            self.paused_once = True
            self.handler(None, bytearray.fromhex("5178ae0101001070ff"))   # pause

            async def resume():
                await asyncio.sleep(0.3)
                self.handler(None, bytearray.fromhex("5178ae0101000000ff"))
            asyncio.get_running_loop().create_task(resume())

    def stream(self):
        return b"".join(self.writes)


def split_commands(stream):
    out, i = [], 0
    while i < len(stream):
        if stream[i:i + 9] == cat.CAMERA_PREPARE:
            out.append(cat.CAMERA_PREPARE)
            i += 9
            continue
        assert stream[i:i + 2] == b"\x51\x78", stream[i:i + 12].hex()
        n = stream[i + 4] | (stream[i + 5] << 8)
        frame = stream[i:i + 6 + n + 2]
        assert frame[-1] == 0xFF and frame[-2] == cat.crc8(frame[6:6 + n]), frame.hex()
        out.append(frame)
        i += 6 + n + 2
    return out


def test_png(height=60):
    img = Image.new("RGBA", (384, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 10, 7, 19), fill=(0, 0, 0, 255))        # leftmost 8 px black on rows 10-19
    d.rectangle((100, 40, 300, 44), fill=(0, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class ProtocolTests(unittest.TestCase):
    def test_crc_and_framing_match_reference(self):
        # Known-good packets from the reference implementation.
        self.assertEqual(cat.command(cat.CMD_STATE, b"\x00"), bytes.fromhex("5178a3000100" "00" "00" "ff"))
        self.assertEqual(cat.command(cat.CMD_SPEED, bytes([32])).hex(), "5178bd00010020" + f"{cat.crc8(bytes([32])):02x}" + "ff")
        self.assertEqual(cat.crc8(b"\x01"), 0x07)
        self.assertEqual(cat.crc8(bytes.fromhex("aa551738445f5f5f44382c")), cat.LATTICE_START[-2])
        self.assertEqual(len(cat.LATTICE_END), 6 + 11 + 2)
        self.assertEqual(cat.command(cat.CMD_ENERGY, cat.u16(24000))[6:8], bytes([24000 & 0xFF, 24000 >> 8]))

    def test_row_packing_lsb_first(self):
        rows = cat.image_to_rows(cat.load_print_image(test_png()))
        self.assertEqual(len(rows), 60)
        self.assertTrue(all(len(r) == 48 for r in rows))
        self.assertEqual(rows[0], bytes(48))                    # transparent -> white
        self.assertEqual(rows[10][0], 0xFF)                     # 8 black px at the left edge
        img = Image.new("1", (384, 1), 1)
        img.putpixel((0, 0), 0)                                 # only the leftmost pixel
        self.assertEqual(cat.image_to_rows(img)[0][0], 0x01)

    def test_job_skips_blank_rows_and_feeds(self):
        rows = cat.image_to_rows(cat.load_print_image(test_png()))
        cmds = cat.build_job(rows, speed=16, energy=12000, feed=100)
        bitmaps = [c for c in cmds if c[2] == cat.CMD_BITMAP]
        self.assertEqual(len(bitmaps), 10 + 5)                  # only non-blank rows are sent
        feeds = [c[6] | (c[7] << 8) for c in cmds if c[2] == cat.CMD_FEED]
        self.assertEqual(feeds, [10, 20, 15 + 100])             # leading, middle and trailing+final
        self.assertEqual(cmds[-1], cat.command(cat.CMD_STATE, b"\x00"))

    def test_pack_respects_mtu(self):
        cmds = [cat.command(cat.CMD_BITMAP, bytes(48))] * 10
        for mtu in (200, 100, 20):
            packets = cat.pack(cmds, mtu)
            self.assertTrue(all(len(p) <= mtu for p in packets))
            self.assertEqual(b"".join(packets), b"".join(cmds))


class SimulatedPrinterTests(unittest.TestCase):
    def run_job(self, printer, **kw):
        rows = cat.image_to_rows(cat.load_print_image(test_png(400)))
        log = []
        done = asyncio.run(cat.print_rows("AA:BB", rows, delay=0, log=log.append,
                                          client_factory=lambda a: printer, **kw))
        return done, log

    def test_full_print_with_pause_resume(self):
        p = FakePrinter("AA:BB", pause_after=3)
        done, log = self.run_job(p)
        self.assertTrue(done)
        self.assertFalse(p.connected)
        cmds = split_commands(p.stream())
        self.assertEqual(cmds[:2], [cat.command(cat.CMD_STATE, b"\x00"), cat.CAMERA_PREPARE])
        self.assertEqual(sum(1 for c in cmds if c[2] == cat.CMD_BITMAP), 15)
        self.assertIn(cat.LATTICE_END, cmds)

    def test_out_of_paper_aborts(self):
        p = FakePrinter("AA:BB", out_of_paper=True)
        with self.assertRaises(RuntimeError):
            self.run_job(p)
        self.assertFalse(p.connected)

    def test_cancel_still_finishes_job(self):
        p = FakePrinter("AA:BB")
        ev = threading.Event()
        ev.set()
        done, log = self.run_job(p, cancel_event=ev)
        self.assertFalse(done)
        cmds = split_commands(p.stream())
        self.assertEqual(sum(1 for c in cmds if c[2] == cat.CMD_BITMAP), 0)
        self.assertIn(cat.LATTICE_END, cmds)

    def test_small_mtu(self):
        p = FakePrinter("AA:BB")
        p.mtu_size = 23
        done, _ = self.run_job(p)
        self.assertTrue(done)
        self.assertTrue(all(len(w) <= 20 for w in p.writes))
        split_commands(p.stream())


if __name__ == "__main__":
    unittest.main()
