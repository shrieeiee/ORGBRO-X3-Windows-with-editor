# ORGBRO X3 Windows Printer

## ORGBRO X3 Studio (layout editor + printing in one app)

`orgbro_x3_studio.py` combines the sticker/label layout editor (`editor.html`) with this
project's Bluetooth printing, so you can design and print from one window on Windows 11 x64.

* Text blocks with Google Fonts, built-in Windows fonts, **every installed system font**
  (Scan System Fonts) or a custom font name; bold / italic / underline / alignment
* Image blocks with scale, alignment, repeat, Floyd–Steinberg dithering or threshold
* 57 mm roll (right 615 px zone of the 864 px head) or full 80 mm layout
* Repeat the layout as a sticker roll with gaps and cut lines
* Exact 1-bit preview of what will print, threshold and invert controls
* COM-port picker, packet delay, progress bar, cancel, log, Save PNG

### Build the EXE (Windows 11 x64)

1. Install **Python 3.12 (64-bit)** from python.org (tick *Add python.exe to PATH*).
2. Double-click **`build_exe.bat`**. It creates a private `.venv`, installs
   Pillow, pyserial, pywebview and PyInstaller, then builds
   `dist\ORGBRO_X3_Studio.exe` (a single file, no Python needed to run it).

To run from source instead, double-click **`run_studio.bat`**.

The window uses Microsoft Edge WebView2, which is built into Windows 11. If it can't
start, the app automatically opens the same editor in an Edge app window instead
(force this with `ORGBRO_X3_Studio.exe --browser`). Errors are logged to
`%LOCALAPPDATA%\ORGBRO_X3_Studio\error.log`.

Google Fonts need an internet connection; system fonts work offline.

Pushing this repository to GitHub also builds the EXE automatically
(`.github/workflows/build-windows.yml`, download it from the run's *Artifacts*).

---

The original single-image printer UI (`orgbro_x3_ui.py`) is still included and documented below.

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
