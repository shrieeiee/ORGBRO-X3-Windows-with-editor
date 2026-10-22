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
I am utterly incapable of writing something like this by myself, I just wanted a thing.

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

### Templates, including bottle labels
* **✦ Templates** opens a gallery with live previews. Templates can be undone like any other
  change.
* **General templates:** price tag, address label, name badge, round QR sticker, "Fragile"
  sticker and numbered batch label.
* **🍺 Bottle labels:**
  * **Beer bottle**: printed sideways on the 80 mm roll, 100 mm long
  * **Wine bottle**: 80×100 mm
  * **Gin / spirits**: 80×60 mm, optionally numbered "Bottle 1 of 3"
  * **Cider / mead**: 57×50 mm
  * **Neck band**: an 80×22 mm strip
  * **Cap / cork top**: round Ø 30 mm, numbered #01, #02…
* **Bottle form.** Each bottle template opens a short form for name, style, ABV, bottle size
  (with common sizes: 330, 440, 500, 568 ml pint, 700, 750 ml, 1 L), maker and tasting notes.
  * It works out **UK alcohol units** (ABV % × ml ÷ 1000) for you.
  * You can add a bottled date, bottle numbering, "Contains sulphites" (wine) and "Please drink
    responsibly".
  * A live preview updates as you type.

  These are for homebrew and gift labels. If you sell alcohol, check the labelling rules that
  apply to you.

### Interface
* **Click the preview to select.** Clicking text, an image or a code in the preview opens and
  highlights its block. Hovering a block outlines it on the preview.
* **Preview controls:** zoom (Fit / 100% / 200%), *One copy / One label* view, and a 1-bit toggle.
* **Collapsible blocks.** Each block collapses to a one-line summary, with Expand all /
  Collapse all.
* **Font picker** with search. Every font is shown in its own typeface, and installed system
  fonts are grouped separately.
* **Paste images** with Ctrl+V, or **drag and drop** image files (or a `.orgbro` layout) onto the
  window.
* **Image blocks** show a thumbnail and have **brightness and contrast** controls for better
  dithering.
* **Number boxes** next to every slider.
* **Visual label-size picker** that draws each sticker to scale, round ones included.
* **Pinned print bar** showing what will print ("3 × Ø40 mm round labels · ~129 mm") with
  Print and PNG buttons. Rarely used printer settings sit under *Advanced print settings*.
* **Printer status** in the top bar, plus a setup checklist when no printer is found.
* **Shortcuts:**
  * Del deletes the selected block, Ctrl+D duplicates it, Alt+↑/↓ moves it, and Enter expands or
    collapses it.
  * Esc closes pop-ups.
  * Ctrl+S / Ctrl+Shift+S save, Ctrl+O opens and Ctrl+P prints.
* **Light, dark or automatic theme**, plus visible keyboard focus outlines.

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

### Cat printers (Bluetooth LE)
Studio can also print to the cheap **"cat printers"**: the GB01, GB02, GB03, MX05, MX06, MX08,
MX10, YT01 and similar mini printers that use the iPrint / Fun Print style app.

* **Choosing a printer:** under **Printer**, pick **🐱 Cat printer (Bluetooth LE)**, then click
  **🔍 Scan** and choose your printer.
* **No Windows pairing needed:** cat printers connect over Bluetooth LE, so you don't pair them
  in Windows Settings. Just close the phone app if it's connected.
* **Paper size:** the layout switches automatically to the 384-dot head, which gives 48 mm of
  print width on 57/58 mm paper. Sticker presets, templates (including the bottle labels),
  rotate, numbering and QR codes all work.
* **Print settings:** you can choose **Darkness** (heating energy), **Speed** and *Feed after
  printing*.
* **Calibration:** there's a cat-printer calibration sheet with a 40 mm ruler.
* **Printing behaviour:** the app respects the printer's pause/resume signals. Blank space is fed
  quickly rather than printed line by line. Cancelling still finishes the job cleanly.
  "Out of paper" and "cover open" stop the print with a message.
* **Unsupported models:** printers that use a different protocol (for example MXW01) won't work.

The protocol was implemented from the public-domain description in NaitLee's
[Cat-Printer](https://github.com/NaitLee/Cat-Printer) /
[kitty-printer](https://github.com/NaitLee/kitty-printer) projects, which power
print.unseen-site.fun. Its command stream is tested byte-for-byte against that reference. No code
from those (AGPL/GPL) apps is included.

### Under the hood
* `cat_printer.py` contains the cat printer protocol and the Bluetooth LE transport. It uses
  [bleak](https://github.com/hbldh/bleak) with Windows' built-in WinRT Bluetooth API.
* `editor.html` runs in a native window (Edge WebView2 via pywebview). If WebView2 can't start,
  it falls back to an Edge app window.
* `orgbro_x3_studio.py` provides a local API that **only listens on 127.0.0.1** and requires a
  random per-launch token.
* `orgbro_x3_protocol.py` is the protocol code from the original `orgbro_x3_ui.py`, moved into its
  own module and extended. It has been verified byte-for-byte against the original.
* `tests/` holds unit tests for both printer protocols, a simulated Bluetooth LE printer, and the
  API. They run in CI and in `build_exe.bat`. CI also launches the built .exe in `--selftest`
  mode to check that Bluetooth LE support and the data files were bundled.
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

**Cat printer instead?**
1. Switch the printer on and make sure Windows Bluetooth is on.
2. Choose **Printer → 🐱 Cat printer**, click **🔍 Scan** and pick it from the list.
3. Print the calibration sheet. If the 40 mm ruler doesn't measure 40 mm, set *Dots per mm* to
   `8 × 40 ÷ measured`.

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
* Cat printer protocol description: [NaitLee](https://github.com/NaitLee/Cat-Printer)
  (the protocol file is CC0 / public domain).
* [bleak](https://github.com/hbldh/bleak) Bluetooth LE library (MIT).

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
