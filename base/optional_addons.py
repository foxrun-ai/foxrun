"""Show optional dependencies. This command installs nothing and reads no keys."""
import csv
from pathlib import Path

REQUIRED = ('id', 'what', 'needs', 'license', 'cost', 'enable', 'available')


def rows(root):
    with (Path(root) / 'config/optional-addons.tsv').open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != list(REQUIRED):
            raise ValueError('optional add-on list has the wrong columns')
        result = list(reader)
    if not result or any(not row[key].strip() for row in result for key in REQUIRED):
        raise ValueError('every optional add-on needs all fields')
    if len({row['id'] for row in result}) != len(result):
        raise ValueError('duplicate optional add-on')
    return result


def show(root):
    print('Optional add-ons: none are installed or enabled by default.')
    for row in rows(root):
        print(row['id'] + ': ' + row['what'])
        print('  Needs: ' + row['needs'])
        print('  License: ' + row['license'] + '. Cost: ' + row['cost'])
        print('  Enable: ' + row['enable'])
        print('  Availability: ' + row['available'])
    return 0
