"""Read scene strings through a local, image-bound table layout.

Binding addresses and field hashes are derived locally and never distributed.
Reads use the host's bounded memory API; they are not an atomic game snapshot.
"""
import hashlib
import json
from pathlib import Path
import struct


def read_state(api, bindings):
    profile = json.loads(Path(bindings).read_text())
    validate_profile(api, profile)
    return read_fields(api, profile)


def validate_profile(api, profile):
    """Validate the exact in-memory binding profile before a polling transaction."""
    image = Path(api.info['game']) / 'image.bin'
    if profile.get('schema') != 1 or profile.get('image_sha256') != hashlib.sha256(image.read_bytes()).hexdigest():
        raise ValueError('Scene bindings do not match this game image')


def read_fields(api, profile):
    """Internal polling reader; caller must validate the image-bound profile first."""
    layout, fields = profile['string_table'], profile['fields']
    if not isinstance(fields, dict) or not 1 <= len(fields) <= 16:
        raise ValueError('Invalid scene field list')
    required = ('slots_pointer_offset', 'slot_count_offset', 'values_pointer_offset',
                'value_count_offset', 'value_stride', 'string_pointer_offset', 'string_capacity')
    if any(type(layout.get(k)) is not int or not 0 <= layout[k] <= 65536 for k in required):
        raise ValueError('Invalid scene table layout')
    if not 1 <= layout['string_capacity'] <= 256 or not layout['value_stride']:
        raise ValueError('Invalid scene string capacity or record stride')
    if layout['string_pointer_offset'] + 8 > layout['value_stride']:
        raise ValueError('String pointer outside scene record')
    if any(type(h) is not int or not 0 < h <= 0xffffffff for h in fields.values()):
        raise ValueError('Invalid scene field hash')
    pointer = profile['manager_pointer']
    if type(pointer) is not int or pointer <= 0:
        raise ValueError('Invalid scene manager pointer')

    def read(address, length):
        raw = bytes.fromhex(api.read_memory(address, length)['data_hex'])
        if len(raw) != length:
            raise RuntimeError('Incomplete scene memory read')
        return raw

    def u64(address):
        return struct.unpack('<Q', read(address, 8))[0]

    def u32(address):
        return struct.unpack('<I', read(address, 4))[0]

    manager = u64(pointer)
    if not manager:
        return dict(ready=False, consistent_snapshot=False, fields={})
    table = u64(manager + layout['slots_pointer_offset'])
    slots = u32(manager + layout['slot_count_offset'])
    values = u64(manager + layout['values_pointer_offset'])
    count = u32(manager + layout['value_count_offset'])
    if not table or not values or not 1 <= slots <= 65536 or not 1 <= count <= 65536:
        raise RuntimeError('Scene table is not ready or its layout is incompatible')
    result = {}
    for name, key in fields.items():
        index = key % slots
        for _ in range(min(slots, 4096)):
            actual, item = struct.unpack('<II', read(table + index * 8, 8))
            if actual == key:
                if item >= count:
                    raise RuntimeError('Scene table record outside value array')
                address = u64(values + item * layout['value_stride'] + layout['string_pointer_offset'])
                if not address:
                    raise RuntimeError('Missing scene string storage')
                raw = read(address, layout['string_capacity'])
                if b'\0' not in raw:
                    raise RuntimeError('Scene string has no terminator')
                result[name] = raw.split(b'\0', 1)[0].decode('utf-8')
                break
            if not actual:
                raise RuntimeError(f'Scene field not found: {name}')
            index = (index + 1) % slots
        else:
            raise RuntimeError('Scene table probe limit exceeded')
    if u64(pointer) != manager or u64(manager + layout['slots_pointer_offset']) != table:
        raise RuntimeError('Scene manager changed during read; retry')
    return dict(ready=True, consistent_snapshot=False, fields=result)
