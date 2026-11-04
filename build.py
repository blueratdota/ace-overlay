"""Build the portable Windows package: dist/ace-overlay-<version>-win64.zip.

    .venv\\Scripts\\python build.py

Needs PyInstaller in the environment (pip install pyinstaller).
"""

import hashlib
import shutil
import tomllib
from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZipFile

import PyInstaller.__main__

ROOT = Path(__file__).parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
NAME = "ace-overlay"
LOADER_RELEASE = "https://github.com/dreasgrech/ACEUIAppLoader/releases/download/v0.27.0/"
LOADER_ARCHIVE = "ACEUIAppLoader-0.27.0-0.9.1+release.6.zip"
LOADER_SHA256 = "fa127567e3e49a55c5e1f97c3af64ce14ed78663fe80b4be7a2ba8c9486fe086"

# Qt pieces PyInstaller bundles that a plain QPainter widget app never loads, relative to
# _internal/PySide6. They come in as dependencies of optional plugins (virtual keyboard -> Quick/QML,
# PDF image format, touch input -> Network, Direct2D backend -> OpenGL).
PRUNE = [
    "opengl32sw.dll",  # software OpenGL fallback; we draw with the raster engine
    "Qt6Pdf.dll", "plugins/imageformats/qpdf.dll",
    "Qt6VirtualKeyboard.dll", "plugins/platforminputcontexts",
    "Qt6Quick.dll", "Qt6Qml.dll", "Qt6QmlMeta.dll", "Qt6QmlModels.dll", "Qt6QmlWorkerScript.dll",
    "Qt6Network.dll", "plugins/generic",
    "Qt6OpenGL.dll", "plugins/platforms/qdirect2d.dll",
    "plugins/platforms/qminimal.dll", "plugins/platforms/qoffscreen.dll",
]


def make_icon(path):
    from PySide6.QtGui import QGuiApplication

    from ace_overlay.app import app_icon

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - QImage writers need an app
    if not app_icon(256).save(str(path)):
        raise RuntimeError(f"could not write {path}")


def prune(app_dir):
    qt = app_dir / "_internal" / "PySide6"
    removed = []
    for rel in PRUNE:
        path = qt / rel
        if path.is_dir():
            removed += [p.name for p in path.rglob("*.dll")]
            shutil.rmtree(path)
        elif path.exists():
            removed.append(path.name)
            path.unlink()
    # Safety net: fail the build if anything left behind still imports a DLL we removed.
    names = [n.encode() for n in removed if n.startswith("Qt6") or n == "opengl32sw.dll"]
    for binary in list(app_dir.rglob("*.dll")) + list(app_dir.rglob("*.pyd")) + [app_dir / f"{NAME}.exe"]:
        data = binary.read_bytes()
        for name in names:
            if name in data:
                raise RuntimeError(f"{binary.name} still references pruned {name.decode()}")
    print(f"Pruned {len(removed)} unused Qt files")


def bundle_standings(app_dir):
    archive = BUILD / LOADER_ARCHIVE
    if not archive.exists():
        download = archive.with_suffix(".download")
        urlretrieve(LOADER_RELEASE + LOADER_ARCHIVE.replace("+", "%2B"), download)
        download.replace(archive)
    with archive.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != LOADER_SHA256:
            raise RuntimeError(f"Unexpected checksum for {archive}")
    with ZipFile(archive) as release:
        member = "mods/ACEUIAppLoader.kspkg"
        with release.open(member) as source, (app_dir / Path(member).name).open("wb") as dest:
            shutil.copyfileobj(source, dest)
    shutil.copytree(ROOT / "packaging" / "ace-standings-bridge", app_dir / "ace-standings-bridge")


def main():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    BUILD.mkdir(exist_ok=True)
    icon = BUILD / "icon.ico"
    make_icon(icon)

    PyInstaller.__main__.run([
        str(ROOT / "packaging" / "launcher.py"),
        "--name", NAME,
        "--windowed",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--icon", str(icon),
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        # Only QtCore/QtGui/QtWidgets are used; keep the rest of Qt out.
        "--exclude-module", "tkinter",
        "--exclude-module", "PySide6.QtNetwork",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtOpenGL",
    ])

    app_dir = DIST / NAME
    prune(app_dir)
    for extra in ("README.txt", "Check telemetry.bat", "Setup standings.bat", "ACE UI App Loader LICENSE.txt"):
        shutil.copy(ROOT / "packaging" / extra, app_dir / extra)
    bundle_standings(app_dir)
    shutil.copy(ROOT / "LICENSE", app_dir / "LICENSE.txt")

    # Zip the folder itself so users get a single "ace-overlay" folder when they extract.
    archive = shutil.make_archive(str(DIST / f"{NAME}-{version}-win64"), "zip", DIST, NAME)
    size_mb = Path(archive).stat().st_size / 1e6
    print(f"\nBuilt {archive} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
