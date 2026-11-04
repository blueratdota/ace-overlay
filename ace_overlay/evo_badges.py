"""Read OEM badges from the local EVO package without unpacking or modifying it."""

import re
import struct
import winreg
from pathlib import Path

from PySide6.QtGui import QImage

# Package table layout documented by https://github.com/Nenkai/ACEvo.Package.
TABLE_BYTES = 64 * 1024 * 1024
ENTRY_BYTES = 256
TABLE_KEY = bytes.fromhex("c135117da921979f")
OEM_PREFIX = b"uiresources\\branding\\oem\\"
MIPS_SUFFIX = b"\\logo.texturemips"
LOGO_SIDE = 128
LOGO_BYTES = LOGO_SIDE * LOGO_SIDE * 4
MIPS_BYTES = 512 * 1024  # EVO OEM logos use an uncompressed BGRA mip allocation.


def find_package():
    for hive, key, value in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, key) as registry_key:
                steam = Path(winreg.QueryValueEx(registry_key, value)[0])
        except OSError:
            continue
        libraries = [steam]
        try:
            vdf = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
            libraries.extend(Path(path.replace("\\\\", "\\")) for path in re.findall(r'"path"\s+"([^"]+)"', vdf))
        except OSError:
            pass
        for library in libraries:
            package = library / "steamapps" / "common" / "Assetto Corsa EVO" / "content.kspkg"
            if package.is_file():
                return package
    return None


def decode_entry(data):
    return bytes(byte ^ TABLE_KEY[i % len(TABLE_KEY)] for i, byte in enumerate(data))


def load_badges(package):
    """Load the first mip of each supported OEM texture as an independently owned QImage."""
    badges = {}
    try:
        with package.open("rb") as source:
            size = source.seek(0, 2)
            if size < TABLE_BYTES:
                return badges
            table_start = source.seek(-TABLE_BYTES, 2)
            table = source.read(TABLE_BYTES)
            for match in re.finditer(re.escape(decode_entry(OEM_PREFIX)), table):
                start = match.start()
                if start % ENTRY_BYTES:
                    continue
                entry = decode_entry(table[start:start + ENTRY_BYTES])
                name = entry[:228].split(b"\0", 1)[0]
                if not name.endswith(MIPS_SUFFIX):
                    continue
                brand = name[len(OEM_PREFIX):-len(MIPS_SUFFIX)]
                if not re.fullmatch(rb"[a-z0-9_]+", brand):
                    continue
                flags = struct.unpack_from("<H", entry, 228)[0]
                length, offset = struct.unpack_from("<QQ", entry, 240)
                if flags or length != MIPS_BYTES or offset + length > table_start:
                    continue
                source.seek(offset)
                pixels = source.read(LOGO_BYTES)
                if len(pixels) == LOGO_BYTES and any(pixels[3::4]):
                    logo = QImage(pixels, LOGO_SIDE, LOGO_SIDE, LOGO_SIDE * 4, QImage.Format_ARGB32).copy()
                    badges[brand.decode().replace("_", "")] = logo
    except OSError:
        pass
    return badges
