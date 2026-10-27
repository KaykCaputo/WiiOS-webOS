import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = json.loads((ROOT / 'appinfo.json').read_text())['version']
for name in ('package.json', 'package-lock.json'):
    path = ROOT / name
    value = json.loads(path.read_text())
    value['version'] = version
    if name == 'package-lock.json':
        value['packages']['']['version'] = version
    path.write_text(json.dumps(value, indent=2) + '\n')
