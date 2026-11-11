"""Bounded observations of image-bound UI objects, never an atomic snapshot.

Addresses, object types and screen indices are supplied by local binding files.
No input is sent and no observed byte is interpreted as permission to send input.
"""
import hashlib
import json
from pathlib import Path
import struct


class UIStateChanging(RuntimeError):
    """State bytes changed while the same checked UI object was observed."""


def read_state(api, bindings):
    profile = json.loads(Path(bindings).read_text())
    image = Path(api.info['game']) / 'image.bin'
    if profile.get('schema') != 1 or profile.get('image_sha256') != hashlib.sha256(image.read_bytes()).hexdigest():
        raise ValueError('UI bindings do not match this game image')
    return read_fields(api, profile)


def read_fields(api, profile):
    """Caller must validate the image before repeated observations."""
    def integer(value, low, high):
        return type(value) is int and low <= value <= high

    for key in ('manager_pointer', 'manager_vtable'):
        if not integer(profile.get(key), 1, (1 << 64) - 1):
            raise ValueError('Invalid UI pointer binding')
    for key in ('count_offset', 'table_offset', 'owner_offset', 'state_offset', 'input_state_offset'):
        if not integer(profile.get(key), 0, 65528):
            raise ValueError('Invalid UI offset')
    screens = profile.get('screens')
    if not isinstance(screens, dict) or not 1 <= len(screens) <= 16:
        raise ValueError('Invalid UI screen list')
    for name, spec in screens.items():
        if (not isinstance(name, str) or not name or not isinstance(spec, dict)
                or not integer(spec.get('index'), 0, 511)
                or not integer(spec.get('vtable'), 1, (1 << 64) - 1)):
            raise ValueError('Invalid UI screen binding')

    def read(address, size):
        if not integer(address, 1, (1 << 64) - size):
            raise RuntimeError('Invalid UI read address')
        data = bytes.fromhex(api.read_memory(address, size)['data_hex'])
        if len(data) != size:
            raise RuntimeError('Incomplete UI memory read')
        return data

    def u64(address):
        return struct.unpack('<Q', read(address, 8))[0]

    def header(manager):
        return (u64(manager), struct.unpack('<I', read(manager + profile['count_offset'], 4))[0],
                u64(manager + profile['table_offset']))

    def object_state(pointer, expected, manager):
        if u64(pointer) != expected or u64(pointer + profile['owner_offset']) != manager:
            raise RuntimeError('UI object type or owner changed')
        state = read(pointer + profile['state_offset'], 1)[0]
        input_state = read(pointer + profile['input_state_offset'], 1)[0]
        if u64(pointer) != expected or u64(pointer + profile['owner_offset']) != manager:
            raise RuntimeError('UI object type or owner changed')
        return dict(state=state, input_state=input_state)

    root = profile['manager_pointer']
    manager = u64(root)
    if not manager:
        return dict(available=False, consistent_snapshot=False, screens={})
    initial = header(manager)
    vtable, count, table = initial
    if vtable != profile['manager_vtable'] or not 1 <= count <= 512 or not table:
        raise RuntimeError('UI manager is unavailable or incompatible')
    observations = {}
    pointers = {}
    for name, spec in screens.items():
        if spec['index'] >= count:
            raise RuntimeError('UI screen index outside table')
        pointer = u64(table + spec['index'] * 8)
        pointers[name] = pointer
        observations[name] = object_state(pointer, spec['vtable'], manager) if pointer else None
    # Re-resolve every slot, including absent objects. Repeated observations can
    # detect changes, but cannot exclude an ABA reuse or make the reads atomic.
    for name, spec in screens.items():
        pointer = u64(table + spec['index'] * 8)
        if pointer != pointers[name]:
            raise RuntimeError('UI screen table changed during read')
        if pointer and object_state(pointer, spec['vtable'], manager) != observations[name]:
            raise UIStateChanging('UI state changed during read')
    if header(manager) != initial or u64(root) != manager:
        raise RuntimeError('UI manager changed during read')
    return dict(available=True, consistent_snapshot=False, screens=observations)
