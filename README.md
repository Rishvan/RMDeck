# RMDex — RV's Mix Deck

Send exactly the audio you want from your gaming PC to your streaming PC.
Pick the apps (the game, Discord, music…), mix them with your microphone, set
each one's volume, and play the mix out to the device that feeds your stream.

## Main use: two-PC streaming

You game on one PC and stream from another. RMDex runs on the **gaming PC**
and controls which sound reaches the **streaming PC**:

```
Gaming PC                                         Streaming PC
┌──────────────────────────────┐                  ┌──────────────────┐
│ Game      ──┐                │                  │                  │
│ Discord   ──┼─ RMDex mix ───┼── "Listen on" ──►│  capture card /  │──► OBS ──► stream
│ Music     ──┤  (per-app vol) │   output device  │  line-in / USB   │
│ Mic (NS)  ──┘                │                  │  audio interface │
└──────────────────────────────┘                  └──────────────────┘
```

1. Add the apps that should be heard on stream and switch them on. Anything
   you don't add (browser tabs, notifications, private calls) never reaches the stream.
2. Balance them with each app's own volume slider, e.g. game at 70 %, Discord at 120 %.
3. Optionally mix in your mic, with **Noise suppression** on to remove fan and room noise.
4. In **Listen on**, pick the output that goes to the streaming PC: the HDMI/capture-card
   audio, a line-out cabled to the streaming PC's line-in, or a USB audio interface.
5. Press **Listen**. On the streaming PC, add that capture/line-in device as an audio
   source in OBS (or your streaming software).

You keep hearing your full game audio on your own headphones as usual; only the
RMDex mix goes to the stream.

It works on a single PC too: pick your headphones in **Listen on** to monitor the mix.

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

Download `RMDex-Setup-<version>.exe` from the [Releases](../../releases) page and run it.
No admin rights needed.

> **"Windows protected your PC"?** The installer isn't code-signed yet, so Microsoft
> Defender SmartScreen shows *Unknown publisher* for new downloads. Click
> **More info → Run anyway** to install. The full source is in this repo and the
> installer is built from it with `build_installer.bat`. See the
> [Code signing policy](#code-signing-policy).

## Run from source

Needs Python 3.10+.

```bat
run.bat
```

or

```bat
python -m pip install -r requirements.txt
python rmdex.py
```

## Build the installer

Needs Python 3.10+ and [Inno Setup 6](https://jrsoftware.org/isdl.php).

```bat
build_installer.bat
```

The installer is written to `dist\RMDex-Setup-<version>.exe`.

## Project layout

| File | What it does |
| --- | --- |
| `rmdex.py` | App window, settings, audio engine (listen / playback) |
| `app_capture.py` | Per-app WASAPI capture, mixer, mic capture and noise suppression |
| `app_info.py` | App names, publishers and icons read from `.exe` files |
| `ui_kit.py` | Rounded Tkinter widgets and the app logo |
| `packaging/` | PyInstaller spec, Inno Setup script, icon/version generator |

## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io),
certificate by [SignPath Foundation](https://signpath.org).

- Committers and reviewers: [Rishvan](https://github.com/Rishvan)
- Approvers: [Rishvan](https://github.com/Rishvan)

Every release installer is built from this repository by the
[Build installer](.github/workflows/build.yml) GitHub Actions workflow, and each
signing request is approved manually.

### Privacy policy

This program will not transfer any information to other networked systems unless
specifically requested by the user or the person installing or operating it.
RMDex only plays audio on the output device you choose; it has no network
features, telemetry or update checks.

## License

[MIT](LICENSE) © 2026 Rishvan

---

Developed by Rishvan.
