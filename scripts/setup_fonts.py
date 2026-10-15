#!/usr/bin/env python3
"""Install the approved OFL fonts once. Rendering itself never uses the network."""

import hashlib
import json
import tempfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent


def install():
    destination = ROOT / "fonts"
    destination.mkdir(exist_ok=True)
    fonts = json.loads((Path(__file__).parent / "fonts.json").read_text())
    for font in fonts:
        prefix = f"https://raw.githubusercontent.com/{font['repository']}/{font['revision']}/"
        assets = [
            (font["path"], font["name"], font["sha256"]),
            (font["license"], font["name"] + ".OFL.txt", font["license_sha256"]),
        ]
        for source, name, expected in assets:
            target = destination / name
            if (
                target.is_file()
                and hashlib.sha256(target.read_bytes()).hexdigest() == expected
            ):
                continue
            with urlopen(prefix + quote(source), timeout=60) as response:
                data = response.read(32 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"配布ファイルのSHA-256が一致しません: {name}")
            with tempfile.NamedTemporaryFile(
                dir=destination, delete=False
            ) as temporary:
                temporary.write(data)
                temporary_path = Path(temporary.name)
            temporary_path.replace(target)
            print(f"Installed: {target.name}")


if __name__ == "__main__":
    install()
