"""Read-only verification of the dated patch; historical manifests stay intact."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / 'SERVICE_PATCH_20261107.json').read_text(encoding='utf-8'))
    failures = []
    for entry in manifest['files']:
        relative = entry['path']
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            failures.append({'path': relative, 'reason': 'missing or unsafe path'})
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry['after_sha256']:
            failures.append({'path': relative, 'reason': 'changed after patch snapshot'})
    print(json.dumps({'pass': not failures, 'checked_files': len(manifest['files']),
                      'manifest': 'SERVICE_PATCH_20261107.json', 'failures': failures},
                     ensure_ascii=True, indent=2))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
