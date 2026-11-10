from __future__ import annotations

from pathlib import Path

from companion import startup


def test_build_command_quotes_paths() -> None:
    command = startup.build_command(
        Path(r"C:\Program Files\Python\pythonw.exe"),
        Path(r"C:\Users\Marco\My App\app.py"),
        Path(r"C:\Users\Marco\AppData\Local\Config\config.json"),
    )
    assert command.startswith(r'"C:\Program Files\Python\pythonw.exe"')
    assert r'"C:\Users\Marco\My App\app.py"' in command
    assert r'--config "C:\Users\Marco\AppData\Local\Config\config.json"' in command
    assert command.endswith("--no-dialog")


def test_pythonw_executable_is_executable_like() -> None:
    executable = startup.pythonw_executable()
    assert isinstance(executable, Path)
    assert executable.name
