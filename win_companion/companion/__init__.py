"""Windows companion for the ESP32 media controller.

The package is Windows-only: it reads the Windows System Media Transport
Controls (SMTC) API and controls the default audio endpoint.
"""

from __future__ import annotations

import sys

# comtypes (imported by pycaw) chooses the COM apartment of the thread that
# imports it. Keep that thread in the multithreaded apartment so WinRT async
# operations behave consistently. The media worker initializes its own MTA
# explicitly before touching WinRT or pycaw.
sys.coinit_flags = 0

APP_NAME = "ESP32 Media Controller"
CONFIG_DIR_NAME = "EspMediaController"
__version__ = "0.1.0"
