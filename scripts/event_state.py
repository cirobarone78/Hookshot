"""Bounded event lifecycle reads using an owner-supplied, image-bound layout."""
import struct


def read_event_state(api, layout):
    keys = ('active_offset', 'count_offset', 'items_offset', 'index_offset', 'name_offset')
    if not isinstance(layout, dict) or any(type(layout.get(k)) is not int or not 0 <= layout[k] <= 65536 for k in keys):
        raise ValueError('Invalid event-state layout')
    pointer = layout.get('manager_pointer')
    if type(pointer) is not int or not 0 < pointer < (1 << 39):
        raise ValueError('Invalid event manager pointer')

    def read(address, size):
        data = bytes.fromhex(api.read_memory(address, size)['data_hex'])
        if len(data) != size:
            raise RuntimeError('Incomplete event-state read')
        return data
    def u64(address):
        return struct.unpack('<Q', read(address, 8))[0]
    def u32(address):
        return struct.unpack('<I', read(address, 4))[0]

    manager = u64(pointer)
    if not manager:
        return dict(ready=False, active=None, name=None, consistent_snapshot=False)
    root = u64(manager + layout['active_offset'])
    name = None
    if root:
        count, index = u32(root + layout['count_offset']), u32(root + layout['index_offset'])
        items = u64(root + layout['items_offset'])
        if count > 256:
            raise RuntimeError('Invalid event stack size')
        # Setup/teardown may have a live root without a current entry. It is busy.
        if items and index < count:
            entry = u64(items + index * 8)
            if entry:
                text = u64(entry + layout['name_offset'])
                if text:
                    raw = read(text, 64)
                    if b'\0' not in raw:
                        raise RuntimeError('Unterminated event name')
                    name = raw.split(b'\0', 1)[0].decode('utf-8')
    if u64(pointer) != manager or u64(manager + layout['active_offset']) != root:
        raise RuntimeError('Event changed during read; retry')
    return dict(ready=True, active=bool(root), root=root, name=name, consistent_snapshot=False)
