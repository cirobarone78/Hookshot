#!/usr/bin/env python3
"""Build a local scene/entrance catalogue from the owner's extracted metadata.

Output is derived game data: keep it in ignored work/. This inventories assets;
it does not establish that a scene can be loaded in the current runtime state.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'nx2'))
import byml


def entrances(document):
    result = []
    for actor in document.get('Actors', []):
        if actor.get('Gyaml') != 'StartPos' or not actor.get('Name'):
            continue
        result.append(dict(name=actor['Name'], actor_id=str(actor['Hash']),
                           position=actor.get('Translate'), rotation=actor.get('Rotate', [0, 0, 0])))
    return result


def build_catalog(romfs, image, read):
    """read(path) decodes one metadata document; injected for game-free tests."""
    romfs = Path(romfs).resolve()
    databases = sorted((romfs / 'RSDB').glob('GameBancInfo.*.rstbl.byml.zs'))
    if len(databases) != 1:
        raise ValueError('Expected exactly one scene database; refusing an ambiguous revision')
    rows = read(databases[0])
    if not isinstance(rows, list):
        raise ValueError('Scene database must be an array')
    scenes, seen = [], set()
    for row in rows:
        name, source = row['__RowId'], row['BancMain']
        if name in seen:
            raise ValueError('Duplicate scene identifier')
        seen.add(name)
        prefix, suffix = 'Work/Banc/Scene/', '.bcett.json'
        if not source.startswith(prefix) or not source.endswith(suffix):
            raise ValueError('Unsupported scene resource path')
        relative = Path(source[len(prefix):-len(suffix)])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Scene resource escapes the catalogue root')
        starts, sources, missing = [], [], []
        for layer in ('Static', 'Dynamic'):
            path = romfs / 'Banc' / f'{relative}_{layer}.bcett.byml.zs'
            if not path.is_file():
                missing.append(str(path.relative_to(romfs)))
                continue
            sources.append(str(path.relative_to(romfs)))
            for start in entrances(read(path)):
                starts.append(dict(start, source=sources[-1]))
        counts = Counter(s['name'] for s in starts)
        for start in starts:
            start['unique_name'] = counts[start['name']] == 1
        scenes.append(dict(id=name, sources=sources, missing_sources=missing,
                           entrances=starts, runtime_load_verified=False))
    return dict(schema=1, image_sha256=hashlib.sha256(Path(image).read_bytes()).hexdigest(),
                database=str(databases[0].relative_to(romfs)), scenes=sorted(scenes, key=lambda s: s['id']))


def read_catalog(path, image):
    result = json.loads(Path(path).read_text())
    if result.get('schema') != 1 or not isinstance(result.get('scenes'), list):
        raise ValueError('Unsupported scene catalogue schema')
    if hashlib.sha256(Path(image).read_bytes()).hexdigest() != result.get('image_sha256'):
        raise ValueError('Scene catalogue belongs to a different game image')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, default=ROOT / 'work/native-game')
    parser.add_argument('--out', type=Path, default=ROOT / 'work/scene-api/catalog.json')
    args = parser.parse_args()
    import zstandard
    from shader_census import dictionaries, unpack
    romfs = args.game / 'romfs'
    dicts = dictionaries(romfs, zstandard)
    result = build_catalog(romfs, args.game / 'image.bin',
                           lambda path: byml.loads(unpack(path.read_bytes(), dicts, zstandard)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + '.tmp')
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(args.out)
    print(json.dumps(dict(catalog=str(args.out), scenes=len(result['scenes']),
                         entrances=sum(len(s['entrances']) for s in result['scenes']))))


if __name__ == '__main__':
    main()
