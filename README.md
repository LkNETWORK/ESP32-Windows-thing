# ESP32-Windows-thing

An external media controller for a Windows PC — something like a Spotify Car
Thing, with an ESP32 touch screen and a rotary encoder.

## Project phases

1. **Windows companion (current).** A tray-resident Python app that reads the
   Windows media session, shows metadata/album art, and controls playback and
   volume from a LAN web UI with swipe gestures. Testable today from a phone.
2. **USB bridge + ESP32 firmware.** Send state and album art over USB serial,
   receive encoder/touch commands on the PC.
3. **Device UI.** SPI touch screen with album art, hardware gestures, and the
   EC11 encoder.

## Phase 1 quick start

```powershell
cd win_companion
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\scripts\run_dev.ps1
```

Open the printed LAN URL (for example `http://192.168.31.198:8722/`) on a
phone connected to the same Wi-Fi. The tray app version runs with:

```powershell
.\.venv\Scripts\pythonw.exe app.py
```

If the phone cannot connect, run `win_companion\scripts\allow_firewall.ps1`
from an elevated PowerShell. It adds a LocalSubnet-only inbound rule for TCP
8722. If Windows classifies the Ethernet/Wi-Fi adapter as **Public**, use
`-Profile Any` (or mark the network Private).

### Gestures

There are no on-screen media buttons.

| Gesture | Action |
|---|---|
| Tap | Play/pause |
| Swipe left | Next track |
| Swipe right | Previous track |
| Swipe up | Volume +5% |
| Swipe down | Volume −5% |

### Phase 1 notes

- **No authentication yet.** The web UI is meant for a trusted home LAN; do
  not expose the port to the internet.
- Uses SMTC for metadata/art and the default output endpoint for volume.
- Config and logs live in `%LOCALAPPDATA%\EspMediaController`. If that
  location is not writable, the app automatically uses `win_companion\.data`;
  `ESP_MEDIA_CONTROLLER_DATA` can force a specific location.
- Detailed setup, API, gestures, tests, and troubleshooting:
  [win_companion/README.md](win_companion/README.md).

## Hardware

The `esp32_firmware/` directory is reserved for Phase 2/3. The current PC API
is already shaped for it: `/api/state`, `/api/action`, and
`/api/art/{id}?w=240`.
