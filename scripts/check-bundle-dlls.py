"""Check the ICU exports Qt expects in a Windows bundle (read-only)."""
import argparse
from pathlib import Path
import pefile

parser = argparse.ArgumentParser()
parser.add_argument('--bundle', type=Path, default=Path(__file__).resolve().parents[1] / 'dist/OnlineDeanFixed')
args = parser.parse_args()
root = args.bundle.resolve() / '_internal'
qt = pefile.PE(str(root/'PySide6/Qt6Core.dll'))
for entry in qt.DIRECTORY_ENTRY_IMPORT:
    if entry.dll.decode().lower() != 'icuuc.dll':
        continue
    dependency = root/'icuuc.dll'
    if not dependency.exists():
        dependency = Path('C:/Windows/System32/icuuc.dll')
    exports = {s.name for s in pefile.PE(str(dependency)).DIRECTORY_ENTRY_EXPORT.symbols}
    missing = [i.name.decode() for i in entry.imports if i.name and i.name not in exports]
    print('ICU:', dependency)
    print('Missing Qt-required ICU exports:', missing)
    raise SystemExit(1 if missing else 0)
