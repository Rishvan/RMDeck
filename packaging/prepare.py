"""
Build step 1: writes packaging/app.ico and packaging/version_info.txt from
APP_VERSION in rmdeck.py, then prints the version (for the build script).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

with open(os.path.join(ROOT, "rmdeck.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'^APP_VERSION = "([\d.]+)"', fh.read(), re.M).group(1)

# -- icon: the same rounded logo the app draws for its window and tray
from ui_kit import app_logo  # noqa: E402

# every size is drawn separately (small ones are simplified) instead of downscaled
sizes = [256, 128, 64, 48, 40, 32, 24, 20, 16]
frames = [app_logo(s) for s in sizes]
frames[0].save(os.path.join(HERE, "app.ico"), sizes=[(s, s) for s in sizes],
               append_images=frames[1:])
frames[0].save(os.path.join(HERE, "app.png"))

# -- Windows version resource shown in the exe's Properties > Details
nums = (VERSION.split(".") + ["0"] * 4)[:4]
tup = "(%s)" % ", ".join(nums)
with open(os.path.join(HERE, "version_info.txt"), "w", encoding="utf-8") as fh:
    fh.write("""VSVersionInfo(
  ffi=FixedFileInfo(filevers=%(tup)s, prodvers=%(tup)s, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Rishvan'),
      StringStruct('FileDescription', "RMDeck - RV's Mix Deck"),
      StringStruct('LegalCopyright', '(c) Rishvan. Developed by Rishvan.'),
      StringStruct('FileVersion', '%(v)s'),
      StringStruct('InternalName', 'RMDeck'),
      StringStruct('OriginalFilename', 'RMDeck.exe'),
      StringStruct('ProductName', 'RMDeck'),
      StringStruct('ProductVersion', '%(v)s')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""" % {"tup": tup, "v": VERSION})

print(VERSION)
