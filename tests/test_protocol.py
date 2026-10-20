"""Smoke tests for the ORGBRO X3 protocol and the Studio's local API (run: python -m unittest)."""

import io
import json
import os
import random
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image  # noqa: E402

import orgbro_x3_protocol as proto  # noqa: E402


def reference_raster(img):
    """The pixel-by-pixel packing from the original orgbro_x3_ui.py."""
    px = img.load()
    out = bytearray()
    for y in range(img.height):
        for bx in range(proto.BYTES_PER_ROW):
            v = 0
            for bit in range(8):
                if px[bx * 8 + bit, y] == 0:
                    v |= 1 << (7 - bit)
            out.append(v)
    return bytes(out)


def random_png(height=37):
    img = Image.new("L", (proto.WIDTH, height), 255)
    rnd = random.Random(1)
    for _ in range(4000):
        img.putpixel((rnd.randrange(proto.WIDTH), rnd.randrange(height)), 0)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class ProtocolTests(unittest.TestCase):
    def test_raster_matches_original_packing(self):
        bw = proto.load_print_image(random_png())
        self.assertEqual(bw.size, (864, 40))  # padded to a multiple of 4 rows
        self.assertEqual(proto.image_to_raster(bw), reference_raster(bw))

    def test_frames_match_captured_format(self):
        self.assertEqual(proto.INIT_1, bytes.fromhex("640a03010055000000009b"))
        self.assertEqual(proto.INIT_2, bytes.fromhex("64090401000c000000009b"))
        frames = proto.build_frames(bytes(proto.PAYLOAD_SIZE * 3))
        self.assertEqual(frames[2][:5], bytes.fromhex("640005b001"))
        self.assertEqual(len(frames[2]), 5 + 432 + 5)
        self.assertEqual(frames[-1], bytes.fromhex("64020802" "00c800000000009b"))

    def test_density_and_feed(self):
        frames = proto.build_frames(bytes(proto.PAYLOAD_SIZE), density=0x70, feed=300)
        self.assertEqual(frames[0][5], 0x70)
        self.assertEqual(int.from_bytes(frames[-1][5:7], "little"), 300)

    def test_split_long_jobs(self):
        raster = bytes(proto.PAYLOAD_SIZE * 450)
        frames = proto.build_frames(raster, split_packets=200)
        data = [f for f in frames if proto.is_data_frame(f)]
        ends = [f for f in frames if f[1] == 0x02]
        self.assertEqual(len(data), 450)
        self.assertEqual(len(ends), 3)
        self.assertEqual([int.from_bytes(f[5:7], "little") for f in ends], [0, 0, 200])
        self.assertTrue(all(f[2] < 256 for f in data))

    def test_transparent_png_is_white(self):
        img = Image.new("RGBA", (864, 8), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        raster = proto.image_to_raster(proto.load_print_image(buf.getvalue()))
        self.assertEqual(set(raster), {0})


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import orgbro_x3_studio as studio
        cls.tmp = tempfile.TemporaryDirectory()
        cls.api = studio.StudioApi(data_dir=cls.tmp.name)
        cls.server = studio.make_server(cls.api, "secret")
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def post(self, name, payload, token="secret"):
        req = urllib.request.Request(self.base + "/api/" + name, data=json.dumps(payload).encode(),
                                     headers={"X-Orgbro-Token": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.load(r)

    def test_editor_and_assets_served(self):
        with urllib.request.urlopen(self.base + "/") as r:
            html = r.read().decode()
        self.assertIn('content="secret"', html)
        for path in ("/fonts/Inter.woff2", "/vendor/qrcode.js", "/vendor/JsBarcode.all.min.js", "/assets/icon.png"):
            with urllib.request.urlopen(self.base + path) as r:
                self.assertGreater(len(r.read()), 1000, path)

    def test_path_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/fonts/../orgbro_x3_studio.py")
        self.assertEqual(cm.exception.code, 404)

    def test_token_required(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("ping", {}, token="wrong")
        self.assertEqual(cm.exception.code, 403)
        self.assertTrue(self.post("ping", {})["ok"])

    def test_project_round_trip(self):
        project = {"format": "orgbro-x3-studio", "version": 1, "doc": {"blocks": []}, "images": {}}
        path = os.path.join(self.tmp.name, "a.orgbro")
        self.assertEqual(self.post("project_save", {"project": project, "path": path})["saved"], path)
        self.assertEqual(self.post("project_open", {"path": path})["project"], project)
        self.assertEqual(self.post("recent", {})["recent"][0]["path"], path)
        self.post("autosave", {"project": project})
        self.assertEqual(self.post("autoload", {})["project"], project)


if __name__ == "__main__":
    unittest.main()
