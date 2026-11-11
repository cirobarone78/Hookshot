"""Find a unique live event starter using a local, image-bound actor-table layout.

These are live reads, not a snapshot. The native dispatcher rechecks holder and
actor identity on the game thread before attaching the original ActorLink.
"""
import math
import struct


def find_actor(api, layout, selector):
    keys = ('pool_offset', 'slot_count', 'stride', 'holder_actor_offset', 'holder_id_offset',
            'actor_id_offset', 'actor_holder_offset', 'actor_name_pointer_offset', 'actor_position_offset')
    if not isinstance(layout, dict) or any(type(layout.get(k)) is not int or not 0 <= layout[k] <= 65536 for k in keys):
        raise ValueError('Invalid actor table layout')
    if not 1 <= layout['slot_count'] <= 4096 or not 16 <= layout['stride'] <= 512:
        raise ValueError('Invalid actor table bounds')
    if layout['holder_actor_offset'] + 8 > layout['stride'] or layout['holder_id_offset'] + 4 > layout['stride']:
        raise ValueError('Actor holder fields outside slot')
    pointer = layout.get('manager_pointer')
    if type(pointer) is not int or not 0 < pointer < (1 << 39):
        raise ValueError('Invalid actor manager pointer')
    if not isinstance(selector, dict):
        raise ValueError('Invalid actor selector')
    name, position = selector.get('name'), selector.get('position')
    if not isinstance(name, str) or not name or '\0' in name or len(name.encode()) > 63:
        raise ValueError('Invalid actor name')
    if not isinstance(position, list) or len(position) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in position):
        raise ValueError('Actor selector needs three finite position coordinates')

    def read(address, length):
        raw = bytes.fromhex(api.read_memory(address, length)['data_hex'])
        if len(raw) != length:
            raise RuntimeError('Incomplete actor read')
        return raw
    def u64(address):
        return struct.unpack('<Q', read(address, 8))[0]
    def u32(address):
        return struct.unpack('<I', read(address, 4))[0]

    manager = u64(pointer)
    if not manager:
        raise RuntimeError('Actor manager is not ready')
    matches = []
    for index in range(layout['slot_count']):
        holder = manager + layout['pool_offset'] + index * layout['stride']
        actor = u64(holder + layout['holder_actor_offset'])
        if not actor or actor >= (1 << 39) - 65536:
            continue
        try:
            identity = u32(holder + layout['holder_id_offset'])
            if u64(actor + layout['actor_holder_offset']) != holder or u32(actor + layout['actor_id_offset']) != identity:
                continue
            raw = read(u64(actor + layout['actor_name_pointer_offset']), 64)
            if b'\0' not in raw or raw.split(b'\0', 1)[0] != name.encode():
                continue
            actual = struct.unpack('<3f', read(actor + layout['actor_position_offset'], 12))
            if not all(math.isfinite(a) and abs(a - b) <= .1 for a, b in zip(actual, position)):
                continue
            if u64(holder + layout['holder_actor_offset']) == actor and u32(holder + layout['holder_id_offset']) == identity:
                matches.append(dict(actor=actor, actor_id=identity, holder=holder, position=actual))
        except (RuntimeError, OSError):
            # An actor may disappear between reads. Never reuse its candidate.
            continue
    if u64(pointer) != manager:
        raise RuntimeError('Actor manager changed during lookup')
    if len(matches) != 1:
        raise RuntimeError(f'Expected one matching event starter, found {len(matches)}')
    return matches[0]
