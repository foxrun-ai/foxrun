"""Module install manifests are the sole authority for pack shipping."""
import csv
import json
from pathlib import Path


def manifest_path(root, name):
    root = Path(root)
    pack = root / 'modules' / name
    return (pack if pack.is_dir() else root / name) / 'install.json'


def ships(manifest):
    return manifest.get('ships') is not False


def shipped_names(root, names):
    root = Path(root)
    product_paths = None
    for manifest in (root / 'product-manifest.tsv', root / 'base/product-manifest.tsv'):
        if manifest.is_file():
            with manifest.open(newline='') as stream:
                product_paths = {row['path'] for row in csv.DictReader(stream, delimiter='\t')}
            break
    result = []
    for name in names:
        path = manifest_path(root, name)
        # Wiki is built in. Local packs cannot join an installed core sample.
        if name == 'wiki' or (path.is_file() and
                (product_paths is None or path.relative_to(root).as_posix() in product_paths) and
                ships(json.loads(path.read_text()))):
            result.append(name)
    return result
