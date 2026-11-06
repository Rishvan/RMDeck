# PyInstaller spec - build step 2 (run through build_installer.bat).
# One-folder build: starts faster than --onefile and trips antivirus less;
# the installer bundles the folder into a single Setup.exe.
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(SPECPATH)

datas, binaries, hiddenimports = collect_all("pyaudiowpatch")
hiddenimports += ["pystray._win32", "comtypes.stream", "PIL._tkinter_finder"]

a = Analysis(
    [os.path.join(ROOT, "rmdeck.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RMDeck",
    console=False,
    icon=os.path.join(SPECPATH, "app.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="RMDeck", upx=False)
