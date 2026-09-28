from pathlib import Path

root = Path(__file__).resolve().parents[1]
for directory in ('config', 'scripts', 'tests', 'docs', '.github', 'apps'):
    for path in (root / directory).rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts or path.name == '.DS_Store':
            continue
        text = path.read_text()
        assert text.endswith('\n'), f'{path}: missing final newline'
        assert all(line == line.rstrip() for line in text.splitlines()), f'{path}: trailing whitespace'
print('Text formatting passed.')
