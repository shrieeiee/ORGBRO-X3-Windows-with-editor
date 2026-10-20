# ORGBRO X3 Studio — fork of ORGBRO X3 Windows Printer

> ⚠️ **This fork is vibe coded.** Everything this fork adds was written with AI assistance
> (Claude, building on a layout editor first drafted with Gemini) and has **not** been
> carefully hand-reviewed. It is tested automatically (unit tests, plus browser tests against
> a simulated printer on a virtual COM port), but it has **not yet been confirmed on real
> ORGBRO X3 hardware** for every feature. Settings marked *experimental* are educated guesses
> about the printer protocol. Use at your own risk, and please open an issue if something breaks.

This is a fork of **[isma-co/ORGBRO-X3-Windows](https://github.com/isma-co/ORGBRO-X3-Windows)**,
which reverse engineered the ORGBRO X3's Bluetooth protocol and provides a simple Windows app
for printing a single image. All credit for the protocol work goes to the original author.

## What this fork adds

The original app prints an existing image file. This fork adds **ORGBRO X3 Studio**: one
Windows 11 x64 program where you **design** stickers, labels and receipts and **print** them,
with no saving and reloading of PNGs in between.

### Paper and stickers
* **80 mm and 57 mm rolls.** 57 mm paper is printed in the right-hand 615 px of the 864 px head
  (the offset is adjustable).
* **Continuous paper** with repeats, a gap between copies and dashed cut lines.
* **Sticker label presets:**
  * 80 mm rolls: 80×40, 80×50, 80×60, 80×80, 76×51 (3×2 in), 70×50, 60×40 mm, plus **round**
    Ø 70, 60, 50 and 40 mm
  * 57 mm rolls: 57×30, 57×40, 57×50, 50×25, 50×30, 50×40, 50×50, 40×30, 40×40 mm, plus
    **round** Ø 50, 40, 30 and 25 mm
  * **Custom** width, height and shape
* **Labels:** content is centred on each label and shrunk if it doesn't fit. Round labels clip
  to the circle. The gap between labels and a top offset are adjustable, so the print can line
  up with your roll.
* **Rotate 90°** to print a design sideways along the roll. On continuous paper, choose the
  length along the roll.
* **Automatic numbering and dates:** `{n}`, `{n:3}` (001, 002…), `{total}`, `{date}` and `{time}`
  work in text and in QR/barcode data. There is also a start-number setting.

### Content blocks
* **Text:**
  * 13 **bundled fonts** that work offline, with their real weights (Thin → Black) and real
    italics. Styles a font doesn't have are disabled rather than faked.
  * Windows fonts, **every installed system font** (Scan System Fonts) or any font typed by name.
  * Long words and URLs wrap instead of running off the edge.
  * Optional **shrink to fit** keeps each line from wrapping.
* **Images:** scale, alignment and repeat. Images are converted to black and white with
  Floyd–Steinberg dithering or a threshold. Transparent areas print white.
* **QR codes** (error-correction L/M/Q/H) and **barcodes** (Code 128, EAN-13, EAN-8, UPC-A,
  Code 39). Bars and modules are drawn crisply at whole-dot widths, with a warning when they're
  too small to scan or the data is invalid.
* **For every block:** per-block spacing, duplicate, drag to reorder (⠿) and ▲/▼ buttons.

### Editing and files
* **Undo / redo** (Ctrl+Z / Ctrl+Y).
* **Save / open layouts** as `.orgbro` files, with images embedded. There's a **Recent** list
  and **autosave**, which restores your last layout when the app reopens. Ctrl+S, Ctrl+O and
  Ctrl+P work.
* **Exact 1-bit preview** of what will print, with sticker outlines and the 57 mm paper edge
  shown on screen only.

### Printing
* COM-port picker and **Find printer**. Find printer sends the official app's status request to
  every port and selects the one that answers.
* Progress bar, **cancel**, log and **Save PNG**.
* **Split long prints** *(experimental)*. The protocol's packet counter is one byte, so it wraps
  after 256 packets (about 9–10 cm). This option sends longer prints as back-to-back parts with
  no paper feed between them.
* **Density** *(experimental)*. This sets the byte in the start-up command that is believed to
  control heat or darkness. The app's own value is "Normal".
* **Feed after print** *(experimental)*. *Auto* feeds a whole number of labels in sticker mode,
  so consecutive prints stay in step with the labels.
* **Test prints:**
  * a **calibration sheet**, with mm rulers and the 57 mm paper box, to check the zone offset
    and dots per mm
  * a **long-print test** that prints across the packet-counter wrap points

### Under the hood
* `editor.html` runs in a native window (Edge WebView2 via pywebview). If WebView2 can't start,
  it falls back to an Edge app window.
* `orgbro_x3_studio.py` provides a local API that **only listens on 127.0.0.1** and requires a
  random per-launch token.
* `orgbro_x3_protocol.py` is the protocol code from the original `orgbro_x3_ui.py`, moved into its
  own module and extended. It has been verified byte-for-byte against the original.
* `tests/` holds unit tests for the protocol and the API. They run in CI and in `build_exe.bat`.
* GitHub Actions builds the app on every code push (documentation-only changes are skipped).
  Bumping the number in `VERSION` on `main` (or pushing a `studio-v*` tag) publishes a
  **Release** with the zip and the portable .exe.

## Download

Get the latest build from **[Releases](../../releases)**:

* **ORGBRO_X3_Studio-win-x64.zip** (recommended): unzip it and run `ORGBRO_X3_Studio.exe` inside
  the folder.
* **ORGBRO_X3_Studio-portable.exe**: a single file. It starts more slowly and is more likely to
  trigger antivirus false positives.

The app isn't code-signed, so Windows SmartScreen may warn you. Click *More info → Run anyway*.

## First-time setup

1. Pair the ORGBRO X3 in **Settings → Bluetooth & devices**, and disconnect your phone from it.
2. Open the app and click **Find printer**, or pick the Bluetooth COM port yourself.
3. Choose **Paper & Stickers → Calibration → Print calibration sheet**.
   * If the 50 mm ruler doesn't measure 50 mm, set *Dots per mm* to `10.8 × 50 ÷ measured`.
   * On 57 mm paper, if the printed box doesn't sit on the paper edges, adjust the
     *57 mm zone offset*.
4. For sticker rolls, print a couple of labels. Then adjust **Gap between labels** and **Top
   offset** until the print lines up with the stickers.
5. Optionally run the **long-print test**. If the print stops or garbles at the black
   "sequence wrap" band, turn on **Split long prints**.

## Build it yourself (Windows 11 x64)

1. Install **Python 3.12 (64-bit)** from python.org, ticking *Add python.exe to PATH*.
2. Double-click **`build_exe.bat`**. It creates a private `.venv`, installs the requirements,
   runs the tests and builds `dist\ORGBRO_X3_Studio\ORGBRO_X3_Studio.exe`.
   * Run `build_exe.bat onefile` for a single portable .exe instead.
3. To run from source without building, double-click **`run_studio.bat`**.

Errors are logged to `%LOCALAPPDATA%\ORGBRO_X3_Studio\error.log`. Autosave and recent files are
kept in the same folder. To force the Edge app window instead of WebView2, run
`ORGBRO_X3_Studio.exe --browser`.

## Credits and licenses

* Protocol research and the original app: [isma-co](https://github.com/isma-co/ORGBRO-X3-Windows)
  (MIT).
* Fonts from [Google Fonts](https://github.com/google/fonts), subset to Latin. They're under the
  SIL Open Font License 1.1, except Special Elite, which is Apache 2.0. See `fonts/licenses/`.
* [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) (MIT, Kazuhiko Arase).
* [JsBarcode](https://github.com/lindell/JsBarcode) (MIT, Johan Lindell). See
  `vendor/THIRD_PARTY_NOTICES.txt`.

---

# Original project README

*The text below is the upstream README by isma-co, kept unchanged. The original
single-image printer UI (`orgbro_x3_ui.py`) is still included in this fork.*

A simple Windows application for printing images directly to the **ORGBRO X3 thermal printer over Bluetooth**.

The ORGBRO X3 works well with its mobile application, but I could not find a usable Windows driver or desktop application for printing directly from a PC.

So I reverse engineered the Bluetooth communication used by the printer and created this small Windows application.

## Features

* Print directly from Windows over Bluetooth
* PNG, JPG, JPEG, BMP, GIF and WebP support
* Automatic image resizing
* 864 px native print width
* Black and white conversion
* Floyd-Steinberg dithering
* Adjustable threshold
* Invert black / white
* Print preview
* Automatic raster conversion
* Bluetooth Serial Port (SPP) communication
* Simple graphical interface

## Download

The easiest way to use the application is to download the latest Windows executable from the **Releases** section.

Download:

`ORGBRO_X3_Printer.exe`

Python is **not required** when using the compiled `.exe`.

## How to use

### 1. Pair the printer with Windows

Turn on your ORGBRO X3 and open:

**Windows Settings → Bluetooth & devices → Add device → Bluetooth**

Pair the printer with your computer.

Windows should create one or more Bluetooth serial COM ports.

### 2. Disconnect your phone

Make sure your phone or tablet is not currently connected to the ORGBRO X3.

The printer should only have one active Bluetooth connection while printing.

### 3. Start the application

Run:

`ORGBRO_X3_Printer.exe`

### 4. Select the COM port

Choose the Bluetooth COM port associated with your ORGBRO X3.

Depending on your computer it may be something like:

`COM3`

`COM5`

`COM7`

The port number is different on every computer.

### 5. Select an image

Click **Choose image** and select the image you want to print.

The application automatically converts the image into the format required by the printer.

### 6. Print

Check the preview and click **Print**.

## Running from source

Requirements:

* Python 3
* Pillow
* pyserial

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the application:

```bash
python src/orgbro_x3_ui.py
```

On Windows you can also use:

```powershell
py src/orgbro_x3_ui.py
```

## Building the Windows executable

The project can be compiled into a standalone Windows executable using PyInstaller.

Install PyInstaller:

```bash
pip install pyinstaller
```

Example build command:

```powershell
py -m PyInstaller --noconfirm --clean --onefile --windowed --name "ORGBRO_X3_Printer" --collect-all PIL --hidden-import serial.tools.list_ports src/orgbro_x3_ui.py
```

The generated executable will be located in:

```text
dist/ORGBRO_X3_Printer.exe
```

## Technical details

The ORGBRO X3 uses Bluetooth Serial Port communication.

The printer raster format used by this project is currently understood as:

* Print width: **864 pixels**
* 1-bit monochrome raster
* 108 bytes per raster row
* MSB-first pixel packing
* 432-byte image payloads
* 4 raster rows per payload

The protocol was determined by analyzing communication between the official mobile application and the printer and performing calibration prints.

## Compatibility

Currently tested with:

* ORGBRO X3
* Windows
* Bluetooth Serial Port / SPP

Other ORGBRO printers may use a similar protocol, but they are **not currently tested**.

## Disclaimer

This project is an independent community project.

It is **not affiliated with, endorsed by, or officially supported by ORGBRO**.

Use it at your own risk.

## Contributing

Bug reports, testing on other computers, protocol research and pull requests are welcome.

If the application works with your ORGBRO X3, feel free to open an issue and report your Windows version and printer model.

## License

This project is released under the MIT License.

See `LICENSE` for details.
