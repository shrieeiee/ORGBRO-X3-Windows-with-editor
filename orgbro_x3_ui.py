import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Missing pyserial. Install with: py -m pip install pyserial pillow")
    raise SystemExit(1)

try:
    from PIL import Image, ImageOps, ImageTk
except ImportError:
    print("Missing Pillow. Install with: py -m pip install pillow")
    raise SystemExit(1)


APP_TITLE = "ORGBRO X3 Printer UI"
WIDTH = 864
BYTES_PER_ROW = WIDTH // 8
PAYLOAD_SIZE = 432  # 4 raster rows per packet

INIT_1 = bytes.fromhex("640a03010055000000009b")
INIT_2 = bytes.fromhex("64090401000c000000009b")


def prepare_image(path, threshold=160, dither=True, invert=False):
    img = Image.open(path).convert("L")
    img = ImageOps.autocontrast(img)

    if img.width != WIDTH:
        new_h = max(1, round(img.height * WIDTH / img.width))
        img = img.resize((WIDTH, new_h), Image.Resampling.LANCZOS)

    if invert:
        img = ImageOps.invert(img)

    if dither:
        bw = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    else:
        bw = img.point(lambda p: 255 if p >= threshold else 0, mode="1")

    padded_h = ((bw.height + 3) // 4) * 4
    if padded_h != bw.height:
        padded = Image.new("1", (WIDTH, padded_h), 1)
        padded.paste(bw, (0, 0))
        bw = padded

    return bw


def image_to_raster(img):
    pixels = img.load()
    out = bytearray()

    for y in range(img.height):
        for byte_x in range(BYTES_PER_ROW):
            value = 0
            base_x = byte_x * 8
            for bit in range(8):
                x = base_x + bit
                if pixels[x, y] == 0:  # black pixel
                    value |= 1 << (7 - bit)
            out.append(value)

    return bytes(out)


def data_frame(seq, payload):
    return (
        b"\x64\x00"
        + bytes([seq & 0xFF])
        + len(payload).to_bytes(2, "little")
        + payload
        + b"\x00\x00\x00\x00\x9b"
    )


def build_frames(raster):
    frames = [INIT_1, INIT_2]
    seq = 5

    for pos in range(0, len(raster), PAYLOAD_SIZE):
        payload = raster[pos:pos + PAYLOAD_SIZE]
        frames.append(data_frame(seq, payload))
        seq = (seq + 1) & 0xFF

    frames.append(
        b"\x64\x02"
        + bytes([seq])
        + b"\x02\x00\xc8\x00\x00\x00\x00\x00\x9b"
    )
    return frames


class OrgbroApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1180x760")
        self.root.minsize(980, 680)

        self.image_path = None
        self.prepared_bw = None
        self.preview_photo = None
        self.is_printing = False

        self.port_var = tk.StringVar()
        self.file_var = tk.StringVar(value="No image selected")
        self.status_var = tk.StringVar(value="Ready")
        self.delay_var = tk.DoubleVar(value=0.02)
        self.threshold_var = tk.IntVar(value=160)
        self.dither_var = tk.BooleanVar(value=True)
        self.invert_var = tk.BooleanVar(value=False)
        self.fit_mode_var = tk.StringVar(value="fit_width")

        self._build_ui()
        self.refresh_ports()
        self.update_preview()

    def _build_ui(self):
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=12)
        left.grid(row=0, column=0, sticky="nsw")
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(self.root, padding=(0, 12, 12, 12))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        # Left panel
        ttk.Label(left, text="Printer", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        port_row = ttk.Frame(left)
        port_row.grid(row=1, column=0, sticky="ew", pady=(6, 14))
        port_row.columnconfigure(0, weight=1)

        self.port_combo = ttk.Combobox(port_row, textvariable=self.port_var, state="readonly", width=34)
        self.port_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ttk.Button(port_row, text="Refresh", command=self.refresh_ports).grid(row=0, column=1)

        ttk.Label(left, text="Image", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, sticky="w")
        ttk.Button(left, text="Choose image...", command=self.choose_image).grid(row=3, column=0, sticky="ew", pady=(6, 6))
        ttk.Label(left, textvariable=self.file_var, wraplength=320).grid(row=4, column=0, sticky="w", pady=(0, 14))

        ttk.Label(left, text="Print settings", font=("Segoe UI", 11, "bold")).grid(row=5, column=0, sticky="w")

        settings = ttk.Frame(left)
        settings.grid(row=6, column=0, sticky="ew", pady=(6, 14))
        settings.columnconfigure(1, weight=1)

        ttk.Checkbutton(settings, text="Use dithering", variable=self.dither_var, command=self.update_preview).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=2
        )
        ttk.Checkbutton(settings, text="Invert black / white", variable=self.invert_var, command=self.update_preview).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=2
        )

        ttk.Label(settings, text="Threshold").grid(row=2, column=0, sticky="w", pady=(10, 2))
        self.threshold_scale = ttk.Scale(
            settings, from_=0, to=255, orient="horizontal",
            command=self._on_threshold_changed
        )
        self.threshold_scale.set(self.threshold_var.get())
        self.threshold_scale.grid(row=2, column=1, sticky="ew", pady=(10, 2))
        self.threshold_label = ttk.Label(settings, text=str(self.threshold_var.get()))
        self.threshold_label.grid(row=3, column=1, sticky="e")

        ttk.Label(settings, text="Packet delay (sec)").grid(row=4, column=0, sticky="w", pady=(10, 2))
        delay_spin = ttk.Spinbox(settings, from_=0.0, to=0.2, increment=0.01, textvariable=self.delay_var, width=10)
        delay_spin.grid(row=4, column=1, sticky="w", pady=(10, 2))

        ttk.Label(settings, text="Scaling").grid(row=5, column=0, sticky="w", pady=(10, 2))
        fit_row = ttk.Frame(settings)
        fit_row.grid(row=5, column=1, sticky="w", pady=(10, 2))
        ttk.Radiobutton(fit_row, text="Fit width", value="fit_width", variable=self.fit_mode_var, command=self.update_preview).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(fit_row, text="Original size", value="original", variable=self.fit_mode_var, command=self.update_preview).grid(row=1, column=0, sticky="w")

        action_row = ttk.Frame(left)
        action_row.grid(row=7, column=0, sticky="ew", pady=(10, 10))
        action_row.columnconfigure(0, weight=1)
        action_row.columnconfigure(1, weight=1)

        ttk.Button(action_row, text="Update preview", command=self.update_preview).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.print_btn = ttk.Button(action_row, text="Print", command=self.start_print)
        self.print_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ttk.Button(left, text="Save preview PNG", command=self.save_preview).grid(row=8, column=0, sticky="ew")

        ttk.Separator(left).grid(row=9, column=0, sticky="ew", pady=14)

        ttk.Label(left, text="Status", font=("Segoe UI", 11, "bold")).grid(row=10, column=0, sticky="w")
        ttk.Label(left, textvariable=self.status_var, wraplength=320).grid(row=11, column=0, sticky="w", pady=(6, 6))

        self.progress = ttk.Progressbar(left, mode="determinate", length=300)
        self.progress.grid(row=12, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(left, text="Log", font=("Segoe UI", 11, "bold")).grid(row=13, column=0, sticky="w")
        self.log = tk.Text(left, height=15, width=42, wrap="word")
        self.log.grid(row=14, column=0, sticky="nsew")
        left.rowconfigure(14, weight=1)

        # Right panel
        ttk.Label(right, text="Preview", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))

        preview_frame = ttk.Frame(right)
        preview_frame.grid(row=1, column=0, sticky="nsew")
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(preview_frame, bg="#f0f0f0", highlightthickness=1, highlightbackground="#cccccc")
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        self.preview_canvas.bind("<Configure>", lambda e: self._render_preview_image())

        note = (
            "Tip: Start with a simple black-and-white image or logo.\n"
            "If the result looks too noisy, disable dithering.\n"
            "COM port should be the working Bluetooth serial port you found earlier."
        )
        ttk.Label(right, text=note, foreground="#555555").grid(row=2, column=0, sticky="w", pady=(8, 0))

    def log_msg(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def set_status(self, text):
        self.status_var.set(text)
        self.root.update_idletasks()

    def refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        descriptions = {p.device: p.description for p in list_ports.comports()}

        self.port_combo["values"] = ports
        if ports and (self.port_var.get() not in ports):
            self.port_var.set(ports[0])

        self.log_msg("Ports refreshed:")
        if ports:
            for p in ports:
                self.log_msg(f"  {p} - {descriptions[p]}")
        else:
            self.log_msg("  No COM ports found.")

    def choose_image(self):
        path = filedialog.askopenfilename(
            title="Choose image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        self.image_path = Path(path)
        self.file_var.set(str(self.image_path))
        self.log_msg(f"Selected image: {self.image_path}")
        self.update_preview()

    def _on_threshold_changed(self, value):
        try:
            self.threshold_var.set(int(float(value)))
        except Exception:
            return
        self.threshold_label.config(text=str(self.threshold_var.get()))
        if not self.dither_var.get():
            self.update_preview()

    def _prepare_current_image(self):
        if not self.image_path:
            return None

        fit_mode = self.fit_mode_var.get()
        invert = self.invert_var.get()
        dither = self.dither_var.get()
        threshold = self.threshold_var.get()

        img = Image.open(self.image_path).convert("L")
        img = ImageOps.autocontrast(img)

        if fit_mode == "fit_width":
            if img.width != WIDTH:
                new_h = max(1, round(img.height * WIDTH / img.width))
                img = img.resize((WIDTH, new_h), Image.Resampling.LANCZOS)
        else:
            if img.width > WIDTH:
                new_h = max(1, round(img.height * WIDTH / img.width))
                img = img.resize((WIDTH, new_h), Image.Resampling.LANCZOS)

        if invert:
            img = ImageOps.invert(img)

        if dither:
            bw = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
        else:
            bw = img.point(lambda p: 255 if p >= threshold else 0, mode="1")

        padded_h = ((bw.height + 3) // 4) * 4
        if padded_h != bw.height:
            padded = Image.new("1", (bw.width, padded_h), 1)
            padded.paste(bw, (0, 0))
            bw = padded

        return bw

    def update_preview(self):
        if not self.image_path:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                40, 40, anchor="nw",
                text="Choose an image to see the print preview.",
                fill="#666666",
                font=("Segoe UI", 12),
            )
            self.prepared_bw = None
            self.set_status("Ready")
            return

        try:
            self.prepared_bw = self._prepare_current_image()
            self._render_preview_image()
            self.set_status(f"Preview updated: {self.prepared_bw.width} x {self.prepared_bw.height} px")
        except Exception as e:
            messagebox.showerror("Preview error", str(e))
            self.log_msg(f"Preview error: {e}")
            self.set_status("Preview error")

    def _render_preview_image(self):
        self.preview_canvas.delete("all")
        if self.prepared_bw is None:
            return

        canvas_w = max(10, self.preview_canvas.winfo_width())
        canvas_h = max(10, self.preview_canvas.winfo_height())

        img = self.prepared_bw.convert("L")
        scale = min((canvas_w - 20) / img.width, (canvas_h - 20) / img.height)
        scale = max(0.1, scale)

        disp_w = max(1, int(img.width * scale))
        disp_h = max(1, int(img.height * scale))
        display = img.resize((disp_w, disp_h), Image.Resampling.NEAREST)

        self.preview_photo = ImageTk.PhotoImage(display)
        x = canvas_w // 2
        y = canvas_h // 2
        self.preview_canvas.create_image(x, y, image=self.preview_photo)
        self.preview_canvas.create_rectangle(
            x - disp_w // 2, y - disp_h // 2, x + disp_w // 2, y + disp_h // 2,
            outline="#aaaaaa"
        )

    def save_preview(self):
        if self.prepared_bw is None:
            messagebox.showinfo("No preview", "Choose an image first.")
            return

        path = filedialog.asksaveasfilename(
            title="Save preview",
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
            initialfile="orgbro_preview.png",
        )
        if not path:
            return

        try:
            self.prepared_bw.convert("L").save(path)
            self.log_msg(f"Preview saved: {path}")
            self.set_status("Preview saved")
        except Exception as e:
            messagebox.showerror("Save error", str(e))

    def start_print(self):
        if self.is_printing:
            return

        if not self.port_var.get():
            messagebox.showwarning("No COM port", "Choose the Bluetooth COM port first.")
            return

        if self.prepared_bw is None:
            messagebox.showwarning("No image", "Choose an image first.")
            return

        self.is_printing = True
        self.print_btn.config(state="disabled")
        self.progress["value"] = 0
        self.set_status("Preparing print job...")

        thread = threading.Thread(target=self._print_worker, daemon=True)
        thread.start()

    def _print_worker(self):
        try:
            raster = image_to_raster(self.prepared_bw)
            frames = build_frames(raster)
            total_packets = len(frames) - 3
            delay = float(self.delay_var.get())
            port = self.port_var.get()

            self._ui_log(f"Opening {port}...")
            self._ui_log(f"Image: {self.prepared_bw.width} x {self.prepared_bw.height}")
            self._ui_log(f"Raster bytes: {len(raster)}")
            self._ui_log(f"Print packets: {total_packets}")

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

                    if i == 0:
                        self._ui_status("Sending init 1...")
                    elif i == 1:
                        self._ui_status("Sending init 2...")
                    elif i == len(frames) - 1:
                        self._ui_status("Sending final feed...")
                    else:
                        current = i - 1
                        percent = current / max(1, total_packets) * 100
                        self._ui_progress(percent)
                        self._ui_status(f"Printing... packet {current}/{total_packets}")

                    time.sleep(delay)

                    if ser.in_waiting:
                        ser.read(ser.in_waiting)

                time.sleep(0.6)
                if ser.in_waiting:
                    rx = ser.read(ser.in_waiting)
                    self._ui_log("Final RX: " + rx.hex(" "))

            self._ui_progress(100)
            self._ui_status("Print finished.")
            self._ui_log("Done.")

        except serial.SerialTimeoutException:
            self._ui_status("Write timeout. Check port / printer / Bluetooth connection.")
            self._ui_log("ERROR: write timeout.")
            self._ui_error("Write timeout.\n\nCheck that:\n- the printer is on\n- the phone is disconnected\n- the correct COM port is selected")
        except Exception as e:
            self._ui_status("Print failed.")
            self._ui_log(f"ERROR: {e}")
            self._ui_error(str(e))
        finally:
            self.root.after(0, self._finish_print)

    def _finish_print(self):
        self.is_printing = False
        self.print_btn.config(state="normal")

    def _ui_status(self, text):
        self.root.after(0, lambda: self.set_status(text))

    def _ui_progress(self, value):
        self.root.after(0, lambda: self.progress.configure(value=value))

    def _ui_log(self, text):
        self.root.after(0, lambda: self.log_msg(text))

    def _ui_error(self, text):
        self.root.after(0, lambda: messagebox.showerror("Print error", text))


def main():
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    app = OrgbroApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
