# ESP32 Windows Media Companion

A small Windows app that reads the current media session and serves a
phone-friendly controller over the local network. It is the Windows half of
the ESP32 media-controller project.

## What it does

- Reads the Windows System Media Transport Controls (SMTC) session:
  title, artist, album, source app, playback state, timeline, album art.
- Controls the **default output device's master volume**, play/pause,
  next, and previous.
- Serves a simple web UI on the LAN. The controller is **gesture-only**:
  - **Tap** anywhere: play/pause
  - **Swipe left**: next track
  - **Swipe right**: previous track
  - **Swipe up**: volume +5%
  - **Swipe down**: volume −5%
- Runs silently from the tray with no main window and can start at login.
- **No authentication in Phase 1.** Anyone who can reach the port on the LAN
  can control the PC's media and volume. Use this only on a trusted home
  network and never port-forward the port to the internet.

## Requirements

- Windows 10 (1809+) or Windows 11, x64.
- Python 3.11+; the checked-in setup uses a Python 3.14 virtual environment.
- A media app that publishes SMTC metadata (Spotify, Edge/Chrome, Windows
  Media Player, VLC with SMTC support, etc.).

The companion uses:

- `winrt-Windows.Media.Control` (PyWinRT) for SMTC metadata/art/transport.
- `pycaw` for the default audio endpoint volume.
- FastAPI + uvicorn for the LAN server.
- `pystray` + Pillow for the system tray.

## Setup

```powershell
cd win_companion
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

If the virtual environment does not exist yet:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Run

Foreground with console logs (best while developing):

```powershell
.\scripts\run_dev.ps1
```

or directly:

```powershell
.\.venv\Scripts\python.exe app.py --console
```

Tray mode (no console window):

```powershell
.\.venv\Scripts\pythonw.exe app.py
```

`pythonw` intentionally has no console or main window. In tray mode it now
shows an **OK confirmation dialog** with the local and phone URLs after
startup, adds a tray icon, and shows a startup balloon. On Windows 10/11 a
new tray icon often lands in the hidden-icons overflow: click the `^` arrow
near the clock, or open **Settings > Personalization > Taskbar > Select
which icons appear on the taskbar** to pin it. The tray menu has **Open
controller**, **Copy phone URL**, and **Quit**.

- `--no-dialog` suppresses the OK confirmation (autostart uses this).
- `--console` runs in the foreground, logs to the console, and intentionally
  **does not create a tray icon**.

Do not run `--console` if you want the tray icon. Stop the console instance
(Ctrl+C) before starting `pythonw`; the single-instance guard will not let a
second tray instance run alongside it.

### If the tray icon does not appear

1. Make sure you are not running with `--console`.
2. Check the log. It should contain `tray icon visible` and
   `tray icon ready`.
3. Make sure the Python launchers are not running at **Low integrity**.
   Low-integrity processes are denied access to the notification area, SMTC,
   the registry, and AppData, which produces `WinError 5`:

   ```powershell
   icacls ".venv\Scripts\python.exe"
   icacls ".venv\Scripts\pythonw.exe"
   ```

   If either prints `Mandatory Label\Low Mandatory Level`, correct it from the
   `win_companion` folder:

   ```powershell
   icacls ".venv\Scripts\python.exe" /setintegritylevel Medium
   icacls ".venv\Scripts\pythonw.exe" /setintegritylevel Medium
   ```

   Then start the app from a normal desktop terminal. A sandboxed/restricted
   terminal can pass its restrictions to child processes.
4. New tray icons often hide in the `^` overflow; pin them via
   **Settings > Personalization > Taskbar > Select which icons appear**.

The console prints the URL(s) in `--console` mode:

```
ESP32 Media Controller 0.1.0
Local: http://127.0.0.1:8722/
LAN:   http://192.168.31.198:8722/  [Ethernet]
LAN:   http://10.8.0.2:8722/        [OpenVPN Data Channel Offload]
```

Open the **Ethernet/Wi-Fi** LAN URL on a phone connected to the same network.
The tray menu also has **Copy phone URL**.

## Phone / LAN troubleshooting

First confirm the server itself is reachable on this PC:

```powershell
Invoke-WebRequest http://127.0.0.1:8722/ -UseBasicParsing
```

Then check the firewall profile of the adapter:

```powershell
Get-NetConnectionProfile
```

If the phone cannot connect and the adapter is **Public**, Windows Firewall
blocks inbound traffic by default. Choose one of these fixes in an **elevated**
PowerShell:

```powershell
cd win_companion

# Option A (recommended, narrow): add a LAN-only rule for TCP 8722 on the
# current profile. The rule is scoped to LocalSubnet.
.\scripts\allow_firewall.ps1 -Profile Any

# Option B (safer network classification): mark the home adapter Private,
# then add the default Private-only rule.
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
.\scripts\allow_firewall.ps1

# Remove the rule later:
.\scripts\allow_firewall.ps1 -Remove
```

To launch the elevated prompt from a normal terminal:

```powershell
Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\Marco\Documents\Github\ESP32-Windows-thing\win_companion\scripts\allow_firewall.ps1" -Profile Any'
```

Verify the rule (works without elevation):

```powershell
netsh advfirewall firewall show rule name="ESP32 Media Controller (8722)"
```

It should show inbound TCP 8722, action Allow, remote address `LocalSubnet`.

If the phone still times out, also check for accidental **block rules for
Python** created by an earlier Windows Firewall prompt. Block rules override
allow rules:

```powershell
$fw = New-Object -ComObject HNetCfg.FwPolicy2
@($fw.Rules) |
  Where-Object { $_.ApplicationName -match 'python' } |
  Select-Object Name, ApplicationName, Direction, Action, Profiles, Enabled
```

`Action = 0` is Block and `Direction = 1` is Inbound. Remove only those
inbound Python block rules from an elevated PowerShell, then retry. If a
Windows Firewall prompt appears for Python, choose **Allow**.

More checks:

1. Use the LAN URL for the physical Ethernet/Wi-Fi adapter, not `127.0.0.1`
   and not a VPN interface.
2. If the machine is on a VPN, choose the printed 192.168.x / Wi-Fi address.
3. Make sure the phone is on the same subnet and not on a guest network with
   client isolation.
4. The app binds to `0.0.0.0` and serves plain HTTP; there is no TLS in
   Phase 1. Do not port-forward it to the internet.

## Tray menu

- Current track (opens the controller when clicked)
- Open controller
- Copy phone URL
- Start with Windows (per-user `HKCU\...\Run` entry; no admin)
- Open logs folder
- Open config folder
- Quit

The tray icon, browser favicon, and no-art/idle placeholder all use
[companion/assets/no_info.png](companion/assets/no_info.png), converted from
the supplied `no_info.jfif` (JPEG/JFIF) to a real PNG. Replace that asset with
a square PNG to customize the artwork; the tray version is downscaled to 64×64
at startup.

Chrome sometimes supplies its own app logo as the SMTC thumbnail instead of
album art. The companion detects that logo with a perceptual hash and treats
it as no artwork, so the UI uses the same `no_info.png` placeholder as the
idle/no-session state. Real album art is left untouched.

## Gestures

The whole screen is the gesture surface. There are no media buttons.

| Gesture | Action |
|---|---|
| Tap (short, little movement) | Play/pause |
| Swipe left | Next track |
| Swipe right | Previous track |
| Swipe up | Volume +5% |
| Swipe down | Volume −5% |

A volume gesture while muted unmutes the output. Thresholds and the volume
step live at the top of `companion/web/gestures.mjs` (`VOLUME_STEP` in
`app.js`) if you want to tune them after trying on the phone.

## Configuration

Config lives outside the repository so autostart works regardless of the
working directory:

```
%LOCALAPPDATA%\EspMediaController\config.json
```

If that location is not writable (for example inside a restricted/sandboxed
session), the app automatically falls back to `win_companion\.data` and then
the temp directory, and logs which one it used. The fallback is git-ignored;
normal desktop and autostart runs use `%LOCALAPPDATA%`.

Default config:

```json
{
  "host": "0.0.0.0",
  "port": 8722,
  "poll_interval_ms": 500,
  "art": {
    "max_bytes": 8388608,
    "default_width": 640,
    "max_width": 2048
  },
  "log_level": "INFO"
}
```

Logs are written to `%LOCALAPPDATA%\EspMediaController\logs\app.log`.

### Development data directory override

Sandboxed or portable development runs can force all state inside the repo:

```powershell
$env:ESP_MEDIA_CONTROLLER_DATA = "$PWD\.data"
.\.venv\Scripts\python.exe app.py --console
```

This is optional: the app already falls back to `win_companion\.data` when
AppData is not writable. `--config PATH` overrides only the config file. The
environment variable moves config and logs together and is not needed for
normal use.

## Autostart

From the tray: **Start with Windows**. Or:

```powershell
.\.venv\Scripts\python.exe app.py --install-startup
.\.venv\Scripts\python.exe app.py --uninstall-startup
```

This writes a per-user registry value:

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
  EspMediaController = "<pythonw.exe>" "<absolute>\app.py" --config "<absolute>\config.json"
```

No administrator rights are required. If the repository is moved, toggle the
tray option off/on to rewrite the absolute paths.

## HTTP API (Phase 1)

State (polled by the web UI every ~750 ms):

```http
GET /api/state
```

Actions:

```http
POST /api/action
Content-Type: application/json

{"action":"play_pause"}
{"action":"next"}
{"action":"previous"}
{"action":"volume_step","delta":0.05}
```

The action response contains the fresh state:

```json
{"ok": true, "state": { "...": "..." }}
```

Failure statuses: `409` (no session / not supported), `503` (volume
unavailable), `504` (timeout), `429` (busy), `422` (invalid body).

Album art is content-addressed:

```http
GET /api/art/{art_id}?w=640
```

`w` is optional (32–2048), downscales only, and returns JPEG. The ESP32 can
later request a small version such as `?w=240`. Health:

```http
GET /healthz
```

### State shape

```json
{
  "schema_version": 1,
  "seq": 123,
  "updated_at": 1760000000.123,
  "server": {"version": "0.1.0"},
  "health": {"media": "ok", "volume": "ok"},
  "media": {
    "active": true,
    "app_id": "Spotify.exe",
    "title": "Song title",
    "artist": "Artist",
    "album": "Album",
    "playback_status": "playing",
    "position_ms": 12345,
    "duration_ms": 210000,
    "can_play_pause": true,
    "can_next": true,
    "can_previous": true,
    "art_id": "a1b2c3d4e5f60708"
  },
  "volume": {"available": true, "level": 0.42, "muted": false}
}
```

`playback_status` is one of `playing`, `paused`, `stopped`, `closed`,
`opened`, `changing`, `unknown`. While playing, `position_ms` is extrapolated
from SMTC's `last_updated_time`, so players (notably Chrome) that only update
the timeline on play/pause still produce a continuously moving progress bar.
The UI also interpolates between polls.

## Diagnostics

Print one live snapshot and exit (also validates SMTC, album art, and volume):

```powershell
.\.venv\Scripts\python.exe app.py --probe
```

Example while a browser is playing a test page:

```json
{
  "health": {"media": "ok", "volume": "ok"},
  "media": {"title": "Probe Song", "artist": "Probe Artist", "art_id": "..."},
  "probe": {"worker_alive": true, "art_bytes": 1410, "art_content_type": "image/png"}
}
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests\web\gestures.test.mjs
```

The Python tests use fakes and do not need media to be playing. The Node test
covers the pure swipe/tap classifier; Node is only needed for this optional
test, not to run the app.

## Architecture

```
phone browser
  GET /api/state (poll), POST /api/action, GET /api/art/{id}
        |
   FastAPI / uvicorn (main thread)
        |  reads StateStore, submits commands
   MediaWorker (dedicated MTA COM thread)
        |  SMTC (WinRT) + pycaw volume
        v
   StateStore + ArtCache
        ^
   pystray tray thread (status, URLs, autostart, quit)
```

- uvicorn runs on the main thread; the tray runs in a Windows-safe background
  thread; all COM/WinRT calls are serialized on one worker thread with
  per-operation timeouts.
- The worker publishes a snapshot every ~500 ms; the browser polls it.
- Album art is read from the SMTC thumbnail stream, hashed by content, and
  cached in memory.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Phone cannot connect | LAN URL, firewall rule, Public vs Private profile, same subnet, guest isolation |
| Public network profile | `Get-NetConnectionProfile`; run `allow_firewall.ps1 -Profile Any` or mark the network Private |
| `pythonw` shows nothing | It is tray-only; check the `^` overflow, the startup balloon, and the log. Use `--console` to see logs |
| Phone shows idle but PC is playing | Player does not publish SMTC, or session is not the OS "current" session |
| No album art | The player does not expose a thumbnail; the placeholder is expected |
| `--probe` says `no_session` | Start playback in Spotify/Edge/VLC and run it again |
| Tray icon missing | Ensure you are not using `--console`; check for Low integrity on the venv Python launchers; check the log for `tray icon ready`; look in the `^` overflow |
| WinError 5 on AppData/registry/tray | Python is running at Low integrity. Set the venv Python launchers to Medium (see above) and run from a normal terminal |
| Autostart did not work | Toggle it again after moving the repo; check the Run registry value |
| Start with Windows says Access denied | The registry write was blocked (common in restricted/sandboxed terminals). Run `--install-startup` from a normal PowerShell window or use the tray menu there |
| Volume unavailable | No active default output device |
| Port already in use | Change `port` in `config.json`; update the firewall rule |

## Phase 2 hand-off

The Web API is intentionally usable by the ESP32 firmware:

- `GET /api/state` for metadata/playback/volume.
- `POST /api/action` for transport and volume steps (the EC11 encoder maps
  naturally to `volume_step`).
- `GET /api/art/{art_id}?w=240` for a small JPEG to draw on the SPI screen.

The next phase adds the USB serial bridge and firmware; no web API changes
should be necessary.
