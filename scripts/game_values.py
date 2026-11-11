"""Read/write explicitly named local scalar bindings, with engine-frame readback."""
import fcntl
import json
import struct
import time
import uuid


def read_value(api, profile, name):
    field = profile.get('values', {}).get(name)
    if not isinstance(field, dict) or field.get('type') not in ('bool', 'int'):
        raise ValueError('Unknown scalar value binding')
    key = field.get('key')
    layout = profile.get('scalar_tables', {}).get(field['type'], {})
    fields = ('slots_pointer_offset', 'slot_count_offset', 'values_pointer_offset',
              'value_count_offset', 'value_stride', 'value_offset')
    if type(key) is not int or not 0 < key <= 0xffffffff or any(
            type(layout.get(k)) is not int or not 0 <= layout[k] <= 65536 for k in fields):
        raise ValueError('Invalid scalar table binding')
    size = 1 if field['type'] == 'bool' else 4
    if not layout['value_stride'] or layout['value_offset'] + size > layout['value_stride']:
        raise ValueError('Scalar value outside record')
    pointer = profile.get('manager_pointer')
    if type(pointer) is not int or not 0 < pointer < (1 << 39):
        raise ValueError('Invalid scalar manager pointer')

    def read(address, length):
        data = bytes.fromhex(api.read_memory(address, length)['data_hex'])
        if len(data) != length:
            raise RuntimeError('Incomplete scalar memory read')
        return data
    def q(address):
        return struct.unpack('<Q', read(address, 8))[0]
    def u(address):
        return struct.unpack('<I', read(address, 4))[0]

    manager = q(pointer)
    if not manager:
        raise RuntimeError('Scalar manager is not ready')
    table, count = q(manager + layout['slots_pointer_offset']), u(manager + layout['slot_count_offset'])
    values, size_values = q(manager + layout['values_pointer_offset']), u(manager + layout['value_count_offset'])
    if not table or not values or not 1 <= count <= 65536 or not 1 <= size_values <= 65536:
        raise RuntimeError('Scalar table is not ready')
    index = key % count
    for _ in range(min(count, 4096)):
        actual, item = struct.unpack('<II', read(table + index * 8, 8))
        if actual == key:
            if item >= size_values:
                raise RuntimeError('Scalar record outside array')
            raw = read(values + item * layout['value_stride'] + layout['value_offset'], size)
            value = bool(raw[0] & 1) if size == 1 else struct.unpack('<i', raw)[0]
            if q(pointer) != manager or q(manager + layout['slots_pointer_offset']) != table:
                raise RuntimeError('Scalar manager changed during read')
            return value
        if not actual:
            break
        index = (index + 1) % count
    raise RuntimeError('Scalar binding not found')


def write_value(api, name, value, timeout=5):
    if api.info.get('profile_kind') != 'analysis':
        raise ValueError('Scalar writes require a disposable analysis profile')
    profile = json.loads((api.run / 'scene-bindings.json').read_text())
    api.scene_state(api.run / 'scene-bindings.json')
    field = profile.get('values', {}).get(name, {})
    kind = field.get('type')
    if kind == 'bool':
        valid = type(value) is bool
    else:
        valid = kind == 'int' and type(value) is int and -(1 << 31) <= value < (1 << 31)
    if not valid or not profile.get('dispatch', {}).get('scalar_calls'):
        raise ValueError('Invalid scalar value or missing native bindings')
    if type(timeout) not in (int, float) or not 1 <= timeout <= 30:
        raise ValueError('Scalar write timeout must be 1..30 seconds')
    report = dict(name=name, value=value, status='running', readback_verified=False)
    path = api.run / ('value-write-' + uuid.uuid4().hex + '.json')
    sequence = None
    with (api.run / 'scene-load.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another scene operation is running') from None
        try:
            status = api.request('status')
            if status['control'] != 'exclusive' or status['buttons'] or any(status['sticks']):
                raise RuntimeError('Scalar writes require idle exclusive input')
            if status['input_sequence'] != status['applied_sequence'] or status.get('last_present_age_ms') is None or status['last_present_age_ms'] > 1000:
                raise RuntimeError('Scalar writes require acknowledged inputs and fresh frames')
            initial_frame = status['presents']
            event = api.event_state()
            if not event['ready'] or event['active']:
                raise RuntimeError('Finish the active event before changing state')
            report['dispatch_before'] = api.request('guest info')
            if not report['dispatch_before'].get('allowed'):
                raise RuntimeError('Configured guest worker has not polled yet')
            if report['dispatch_before'].get('phase') in ('pending', 'executing'):
                raise RuntimeError('Another guest operation is pending or executing')
            report['before'] = read_value(api, profile, name)
            ack = api.request(f"guest {kind} {field['key']:#x} {int(value)}")
            sequence = ack['sequence']
            report['sequence'] = sequence
            deadline = time.monotonic() + timeout
            matching_frame = None
            while time.monotonic() < deadline:
                status = api.request('status')
                if status['control'] != 'exclusive' or status.get('last_present_age_ms') is None or status['last_present_age_ms'] > 1000:
                    raise RuntimeError('Lost control or fresh frames during scalar write')
                info = api.request('guest info')
                if info['sequence'] != sequence or info['phase'] not in ('pending', 'executing', 'dispatched'):
                    raise RuntimeError('Scalar dispatch was rejected or replaced')
                if info['phase'] == 'dispatched':
                    report['observed'] = read_value(api, profile, name)
                    if report['observed'] == value and status['presents'] >= initial_frame + 2:
                        if matching_frame is None:
                            matching_frame = status['presents']
                        elif status['presents'] > matching_frame:
                            report.update(status='completed', readback_verified=True)
                            return dict(report, evidence=str(path))
                    else:
                        matching_frame = None
                time.sleep(.05)
            raise TimeoutError('Scalar value did not match after dispatch')
        except BaseException as exc:
            report.update(status='failed', error=str(exc))
            if sequence is not None:
                try:
                    report['cancel'] = api.request(f'guest cancel {sequence}')
                except Exception as error:
                    report['cancel_error'] = str(error)
            raise
        finally:
            path.write_text(json.dumps(report, indent=2) + '\n')
