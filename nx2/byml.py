"""Bounded reader for binary YAML metadata. Contains no title-specific data.

Only the node types used by the local scene catalogue are supported. Unknown
types, cycles, duplicate keys and out-of-range offsets are errors, not omissions.
"""
import math
import struct


def loads(data):
    if len(data) < 16 or data[:2] not in (b'YB', b'BY'):
        raise ValueError('Invalid BYML header')
    endian = '<' if data[:2] == b'YB' else '>'
    order = 'little' if endian == '<' else 'big'

    def span(offset, length):
        if offset < 0 or length < 0 or offset + length > len(data):
            raise ValueError('BYML range outside file')
        return data[offset:offset + length]

    def number(offset, fmt):
        return struct.unpack(endian + fmt, span(offset, struct.calcsize(fmt)))[0]

    if not 2 <= number(2, 'H') <= 7:
        raise ValueError('Unsupported BYML version')

    def header(offset, kind):
        raw = span(offset, 4)
        if raw[0] != kind:
            raise ValueError('Unexpected BYML node type')
        return int.from_bytes(raw[1:], order)

    def table(offset):
        if not offset:
            return []
        count = header(offset, 0xc2)
        span(offset + 4, (count + 1) * 4)
        offsets = [number(offset + 4 + i * 4, 'I') for i in range(count + 1)]
        if offsets[0] < 4 + 4 * (count + 1):
            raise ValueError('BYML string overlaps table')
        result = []
        for start, end in zip(offsets, offsets[1:]):
            raw = span(offset + start, end - start)
            if not raw or raw[-1] != 0 or b'\0' in raw[:-1]:
                raise ValueError('Invalid BYML string terminator')
            result.append(raw[:-1].decode('utf-8'))
        return result

    keys, strings = table(number(4, 'I')), table(number(8, 'I'))
    active = set()
    budget = 2_000_000

    def indexed(values, index):
        if index >= len(values):
            raise ValueError('BYML string index outside table')
        return values[index]

    def value(kind, offset, depth):
        if kind in (0xc0, 0xc1):
            return node(number(offset, 'I'), depth + 1)
        if kind == 0xa0:
            return indexed(strings, number(offset, 'I'))
        if kind == 0xd0:
            v = number(offset, 'I')
            if v not in (0, 1):
                raise ValueError('Invalid BYML boolean')
            return bool(v)
        formats = {0xd1: 'i', 0xd2: 'f', 0xd3: 'I', 0xd4: 'q', 0xd5: 'Q', 0xd6: 'd'}
        if kind in formats:
            v = number(number(offset, 'I') if kind >= 0xd4 else offset, formats[kind])
            if isinstance(v, float) and not math.isfinite(v):
                raise ValueError('Non-finite BYML number')
            return v
        if kind == 0xff:
            return None
        raise ValueError(f'Unsupported BYML value type {kind:#x}')

    def node(offset, depth):
        nonlocal budget
        if depth > 64 or offset in active:
            raise ValueError('BYML cycle or excessive nesting')
        kind = span(offset, 1)[0]
        count = header(offset, kind)
        budget -= count + 1
        if budget < 0:
            raise ValueError('BYML node budget exceeded')
        active.add(offset)
        try:
            if kind == 0xc0:
                types = span(offset + 4, count)
                start = (offset + 4 + count + 3) & ~3
                span(start, count * 4)
                return [value(t, start + i * 4, depth) for i, t in enumerate(types)]
            if kind == 0xc1:
                span(offset + 4, count * 8)
                result = {}
                for p in range(offset + 4, offset + 4 + count * 8, 8):
                    key = indexed(keys, int.from_bytes(span(p, 3), order))
                    if key in result:
                        raise ValueError('Duplicate BYML key')
                    result[key] = value(data[p + 3], p + 4, depth)
                return result
            raise ValueError(f'Unsupported BYML container {kind:#x}')
        finally:
            active.remove(offset)

    root = number(12, 'I')
    return node(root, 0) if root else None
