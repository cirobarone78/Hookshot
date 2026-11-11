"""Bounded file bridge for the optional external layer's native settings page.

Only this adapter thread invokes shmctl or persists preferences. The renderer
exchanges complete integer-valued snapshots without knowing the external ABI.
"""
import json
import os
from pathlib import Path
import stat
import threading

LIMIT = 4096
MAX_SEQUENCE = (1 << 64) - 1


class Stopped(Exception):
    pass


def read_small(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('Control input must be a regular file')
        data = os.read(fd, LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError('Control input exceeds its limit')
        return data.decode('ascii')
    finally:
        os.close(fd)


def fields(text):
    values = {}
    for line in text.splitlines():
        if not line or '=' not in line:
            raise ValueError('Malformed control field')
        key, value = line.split('=', 1)
        if key in values or not key or not value or not value.lstrip('-').isdigit():
            raise ValueError('Duplicate or noninteger control field')
        values[key] = int(value)
    return values


def atomic_text(path, text):
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='ascii') as stream:
        stream.write(text)
    os.replace(temporary, path)


class ControlBridge:
    def __init__(self, session, settings, validate, directory, *, defaults):
        self.session, self.settings, self.validate = session, settings, validate
        if set(defaults) != set(settings):
            raise ValueError('Defaults must cover every external setting')
        self.defaults = {key: validate(key, value) for key, value in defaults.items()}
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700)
        self.values = {key: int(bounds[0] * (100 if bounds[2] is float else 1))
                       for key, bounds in settings.items()}
        self.actual = {}
        self.ack = self.available = self.helper_state = self.model_up = self.error = 0
        self.poll_sequence = 0
        self.seen = {}
        self.stop = threading.Event()
        self.thread = None

    def _call(self, *args):
        if self.stop.is_set():
            raise Stopped()
        return self.session.control(*args)

    def _refresh(self):
        current = self._call('settings')
        updated, actual = {}, {}
        for key, (_, _, kind) in self.settings.items():
            value = self.validate(key, current[key])
            actual[key] = value
            updated[key] = round(value * (100 if kind is float else 1))
        status = self._call('status')
        self.values = updated
        self.actual = actual
        self.helper_state = int(status.get('helper_state', 0))
        self.model_up = int(bool(status.get('model_up', 0)))
        self.available = int(self.helper_state == 4)

    def _publish(self):
        state = dict(protocol=1, ack=self.ack, available=self.available,
                     helper_state=self.helper_state, model_up=self.model_up, error=self.error)
        state.update(self.values)
        atomic_text(self.directory / 'state', ''.join(f'{key}={value}\n' for key, value in state.items()))

    def _changed(self, name):
        path = self.directory / name
        try:
            info = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return False
        stamp = (info.st_ino, info.st_mtime_ns, info.st_size)
        if self.seen.get(name) == stamp:
            return False
        self.seen[name] = stamp
        return True

    def _request(self):
        text = read_small(self.directory / 'request')
        sequences = [line[len('sequence='):] for line in text.splitlines() if line.startswith('sequence=')]
        sequence = int(sequences[0]) if len(sequences) == 1 and sequences[0].isdecimal() else 0
        if not 1 <= sequence <= MAX_SEQUENCE or sequence <= self.ack:
            return False
        # Acknowledge a rejected complete request too, so native pending controls
        # can revert to the published actual state instead of waiting forever.
        self.ack = sequence
        request = fields(text)
        reset = request.get('reset')
        expected = {'protocol', 'sequence', *self.settings}
        if reset is not None:
            expected.add('reset')
        if set(request) != expected or request['protocol'] != 1 or reset not in (None, 1):
            raise ValueError('Unsupported or incomplete control request')
        desired = {}
        for key, (_, _, kind) in self.settings.items():
            desired[key] = self.validate(key, request[key] / (100 if kind is float else 1))
        if reset is not None and desired != self.defaults:
            raise ValueError('Reset requires the complete factory settings snapshot')
        self._refresh()
        if not self.available:
            raise RuntimeError('External helper is unavailable')
        for key, value in desired.items():
            scale = 100 if self.settings[key][2] is float else 1
            # Reset is exact, including sub-cent values that the menu rounds
            # for display. Ordinary edits still preserve untouched precision.
            if reset is not None or round(value * scale) != self.values[key]:
                self._call('set', key, str(value))
        # Read actual settings again; failed partial application is reported, not
        # mistaken for an atomic external-ABI update or persisted as complete.
        self._refresh()
        path = Path(self.session.info.get('preferences_path', Path(self.session.info['base']) / 'preferences.json'))
        # Keep untouched settings at their original precision even though the
        # native page represents adjustable float values in hundredths.
        atomic_text(path, json.dumps(self.actual, indent=2) + '\n')
        self.error = 0
        return True

    def process_once(self):
        changed = False
        try:
            if self._changed('request'):
                changed = self._request()
            if self._changed('poll'):
                nonce = read_small(self.directory / 'poll').strip()
                if not nonce.isdecimal() or not 1 <= int(nonce) <= MAX_SEQUENCE:
                    raise ValueError('Invalid control poll')
                if int(nonce) > self.poll_sequence:
                    self.poll_sequence = int(nonce)
                    self._refresh()
                    changed = True
        except Stopped:
            return
        except Exception:
            # Includes bounded subprocess failures. Refresh any partial external
            # application without persisting it as a completed full request.
            self.error = 1
            changed = True
            try:
                self._refresh()
            except Exception:
                self.available = 0
        if changed:
            self._publish()

    def _work(self):
        while not self.stop.wait(.1):
            self.process_once()

    def start(self):
        try:
            self._refresh()
        except Exception:
            self.available = 0
            self.error = 1
        self._publish()
        self.thread = threading.Thread(target=self._work, name='dlss5-controls', daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.stop.set()
        if self.thread is not None:
            # Each shmctl call has a five-second timeout, and _call checks stop
            # between commands. No new command may start during helper teardown.
            self.thread.join(timeout=6)
            if self.thread.is_alive():
                raise RuntimeError('External settings bridge did not stop')
        self.available = 0
        self._publish()
