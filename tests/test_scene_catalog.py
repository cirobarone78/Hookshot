"""Authored metadata only: binary bounds, catalogue identity and entrance ambiguity."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import scene_catalog as catalog
import byml


def fixture(endian='<'):
    order = 'little' if endian == '<' else 'big'
    data = bytearray((b'YB' if endian == '<' else b'BY') + struct.pack(endian + 'HIII', 7, 16, 0, 32))
    data += b'\xc2' + (1).to_bytes(3, order) + struct.pack(endian + 'II', 12, 14) + b'a\0\0\0'
    data += b'\xc1' + (1).to_bytes(3, order) + b'\0\0\0\xd1' + struct.pack(endian + 'i', -123)
    return data


class BinaryTests(unittest.TestCase):
    def test_byte_orders(self):
        for order in ('<', '>'):
            self.assertEqual(byml.loads(fixture(order)), {'a': -123})

    def test_every_truncation(self):
        data = fixture()
        for end in range(len(data)):
            with self.assertRaises(ValueError, msg=str(end)):
                byml.loads(data[:end])

    def test_cycle_and_unknown_types(self):
        for kind in (0xc1, 0xa1):
            data = fixture()
            data[39] = kind
            struct.pack_into('<I', data, 40, 32)
            with self.assertRaises(ValueError):
                byml.loads(data)

    def test_bad_string_and_index(self):
        for offset, value in ((29, 65), (36, 1)):
            data = fixture()
            data[offset] = value
            with self.assertRaises(ValueError):
                byml.loads(data)

    def test_array_and_null(self):
        data = fixture()[:32]
        data += b'\xc0\x02\0\0\xd0\xff\0\0' + struct.pack('<II', 1, 0)
        self.assertEqual(byml.loads(data), [True, None])


class CatalogTests(unittest.TestCase):
    def test_catalog_and_api(self):
        with tempfile.TemporaryDirectory() as temp:
            game = Path(temp)
            romfs = game / 'romfs'
            (romfs / 'RSDB').mkdir(parents=True)
            (romfs / 'Banc/Test').mkdir(parents=True)
            database = romfs / 'RSDB/GameBancInfo.Test.rstbl.byml.zs'
            database.touch()
            layer = romfs / 'Banc/Test/Map_Dynamic.bcett.byml.zs'
            layer.touch()
            image = game / 'image.bin'
            image.write_bytes(b'authored image fixture')
            rows = [{'__RowId': 'test-map', 'BancMain': 'Work/Banc/Scene/Test/Map.bcett.json'}]
            documents = {database: rows, layer: {'Actors': [
                {'Gyaml': 'StartPos', 'Name': 'shared', 'Hash': 1},
                {'Gyaml': 'StartPos', 'Name': 'shared', 'Hash': 2},
                {'Gyaml': 'StartPos', 'Name': 'unique', 'Hash': 3},
                {'Gyaml': 'Other', 'Name': 'ignored'}]}}
            result = catalog.build_catalog(romfs, image, documents.__getitem__)
            scene = result['scenes'][0]
            self.assertEqual([s['unique_name'] for s in scene['entrances']], [False, False, True])
            self.assertEqual(len(scene['missing_sources']), 1)
            self.assertFalse(scene['runtime_load_verified'])
            path = game / 'catalog.json'
            path.write_text(json.dumps(result))
            self.assertEqual(catalog.read_catalog(path, image), result)
            if sys.platform == 'linux':
                spec = importlib.util.spec_from_file_location('scene_test_api', ROOT / 'scripts/analysis_api.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                session = game / 'session.json'
                session.write_text(json.dumps({'game': str(game)}))
                api = module.HookshotAPI(session)
                self.assertEqual(api.scenes(path, 'test-map'), result)
                with self.assertRaises(ValueError):
                    api.scenes(path, 'missing')
            image.write_bytes(b'different image')
            with self.assertRaises(ValueError):
                catalog.read_catalog(path, image)
            rows[0]['BancMain'] = 'Work/Banc/Scene/../../escape.bcett.json'
            with self.assertRaises(ValueError):
                catalog.build_catalog(romfs, image, documents.__getitem__)


if __name__ == '__main__':
    unittest.main()
