# RMDeck — RV's Mix Deck

Pick the apps you want to hear (Discord, Chrome, a game…), mix them with your
microphone and listen to the result live on any headphones or speakers.

## Features

- **Per-app capture** – only the apps you add are captured (Windows process loopback), nothing else on your PC.
- **Separate volume for every app** – each app has its own slider (0–200 %) and a live level meter.
- **Microphone mix** – add your mic with its own volume.
- **Noise suppression** – removes steady background noise (fans, hum, hiss) from the mic in real time.
- **Listen anywhere** – play the mix on any output device, with a master volume and level meter.
- **Runs in the tray** – optional; keeps playing when the window is closed.

## Requirements

Windows 10 version 2004 (build 19041) or newer, 64-bit.

## Install

Download `RMDeck-Setup-<version>.exe` from the [Releases](../../releases) page and run it.
No admin rights needed.

## Run from source

Needs Python 3.10+.

```bat
run.bat
```

or

```bat
python -m pip install -r requirements.txt
python rmdeck.py
```

## Build the installer

Needs Python 3.10+ and [Inno Setup 6](https://jrsoftware.org/isdl.php).

```bat
build_installer.bat
```

The installer is written to `dist\RMDeck-Setup-<version>.exe`.

## Project layout

| File | What it does |
| --- | --- |
| `rmdeck.py` | App window, settings, audio engine (listen / playback) |
| `app_capture.py` | Per-app WASAPI capture, mixer, mic capture and noise suppression |
| `app_info.py` | App names, publishers and icons read from `.exe` files |
| `ui_kit.py` | Rounded Tkinter widgets and the app logo |
| `packaging/` | PyInstaller spec, Inno Setup script, icon/version generator |

---

Developed by Rishvan.
