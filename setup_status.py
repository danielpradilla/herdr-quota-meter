#!/usr/bin/env python3
"""Prepare a persistent copy of the meter and print a Herdr tab-bar stanza."""

import os
from pathlib import Path
import shlex
import shutil


def main():
    config_dir = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
    if not config_dir:
        raise SystemExit("HERDR_PLUGIN_CONFIG_DIR is missing; invoke via Herdr plugin action")
    target_dir = Path(config_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "meter.py"
    shutil.copy2(Path(__file__).with_name("meter.py"), target)
    target.chmod(0o755)

    providers_file = target_dir / "providers.txt"
    if not providers_file.exists():
        shutil.copy2(Path(__file__).with_name("providers.txt"), providers_file)
    providers = providers_file.read_text(encoding="utf-8").strip()
    args = ["--all"] if providers.lower() == "all" else [
        "--providers", providers,
    ]
    command = " ".join([
        "python3", shlex.quote(str(target)), "--line",
        *(shlex.quote(arg) for arg in args),
    ])
    print("Add this entry under [ui] in ~/.config/herdr/config.toml:")
    print()
    print("[[ui.tab_bar_right]]")
    print('type = "command"')
    print(f'command = {toml_string(command)}')
    print("interval_seconds = 60")
    print("timeout_seconds = 25")
    print()
    print(f"Meter copied to {target}")
    print("This action does not edit Herdr config or reload the server.")


def toml_string(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


if __name__ == "__main__":
    main()
