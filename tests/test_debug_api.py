"""Exercise the real Linux Unix-socket API against authored frame times and input polls."""
import json
import importlib.util
import os
import argparse
from pathlib import Path
import socket
import sys
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor

RUN_ALL_ARGS = ["--cc", "gcc"]

RUN_ALL_SKIP = {'windows': 'Linux runtime API and Unix session isolation'}

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hookshot-api-test-') as tmp:
        exe = Path(tmp) / 'fixture'
        subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-pthread',
                        '-I' + str(ROOT / 'host'), str(ROOT / 'host/hos_debug.c'),
                        str(ROOT / 'tests/debug_api_fixture.c'), '-o', str(exe)], check=True)
        name = 'hookshot-test-' + uuid.uuid4().hex
        env = {k: v for k, v in os.environ.items() if not k.startswith('HOS_DEBUG_')}
        env['HOS_DEBUG_SOCKET'] = name
        proc = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
        try:
            assert proc.stdout.readline().strip() == 'ready'

            def host(command):
                proc.stdin.write(command + '\n')
                proc.stdin.flush()
                return proc.stdout.readline().strip()

            def request(command):
                with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as s:
                    s.settimeout(2)
                    s.connect('\0' + name)
                    s.sendall(command.encode() if isinstance(command, str) else command)
                    return json.loads(s.recv(4096))

            s = request('status')
            assert s['pid'] == proc.pid and s['fps'] is None and s['last_present_age_ms'] is None
            assert s['control'] == 'player' and s['input_polls'] == 0
            assert not request('input 1 0 0 0 0 200')['ok']
            assert not request('memory info')['ready']
            assert not request('memory read 0x0 4')['ok']
            window = json.loads(host('memory-ready'))
            memory = request('memory info')
            assert memory == dict(ok=True, ready=True, guest_size=hex(window['size']), image_base='0x100',
                                  image_end='0x800', max_read_bytes=256, writable=False, consistent_snapshot=False)
            read = request('memory read 0x1 256')
            assert read['address'] == '0x1' and read['length'] == 256 and not read['consistent_snapshot']
            assert bytes.fromhex(read['data_hex']) == bytes(range(1, 256)) + b'\0'
            assert request(f'memory read {window["size"] - 1:#x} 1')['data_hex'] == 'ff'
            # Exact bounds, protected/unmapped pages and partial kernel reads fail without faulting the process.
            for address, length in [(window['size'], 1), (window['size'] - 1, 2), (window['page'], 1),
                                    (window['page'] - 1, 2), (0xfffffffffffffff0, 32)]:
                response = request(f'memory read {address:#x} {length}')
                assert response['ok'] is False and 'data_hex' not in response
            host('memory-unmap')
            assert not request(f'memory read {window["page"] * 2:#x} 8')['ok']
            host('memory-change')
            assert request('memory read 0x0 32')['data_hex'] == 'a5' * 32
            host('frame')
            for _ in range(120):
                host('advance 10000000')
                host('frame')
            s = request('status')
            assert s['presents'] == 121 and s['sample_intervals'] == 120 and s['fps'] == 100
            assert s['frame_ms_mean'] == s['frame_ms_max'] == s['frame_ms_p95'] == 10
            host('advance 2000000000')
            stale = request('status')
            assert stale['last_present_age_ms'] == 2000 and stale['presents'] == 121
            host('frame')
            slow = request('status')
            assert slow['frame_ms_max'] == 2000 and slow['frame_ms_p95'] == 10 and slow['fps'] < 40
            assert slow['frames_over_50ms'] == slow['frames_over_100ms'] == 1
            assert request('control exclusive')['ok']
            press = request('input 32769 -20000 12345 300 0 200')
            host('advance 5000000000')  # No Npad poll during a long load: hold remains pending.
            assert request('status')['applied_sequence'] != press['sequence']
            p = json.loads(host('poll'))
            assert p == dict(mode=1, buttons=32769, sticks=[-20000, 12345, 300, 0])
            assert request('status')['applied_sequence'] == press['sequence']
            host('advance 199000000')
            assert json.loads(host('poll'))['buttons'] == 32769
            host('advance 1000000')
            assert json.loads(host('poll'))['buttons'] == 0
            canceled = request('input 1 123 0 0 0 60000')
            assert request(f'cancel {canceled["sequence"]}')["canceled"]
            assert request('status')['input_sequence'] != request('status')['applied_sequence']
            assert json.loads(host('poll'))['buttons'] == 0
            assert request('status')['input_sequence'] == request('status')['applied_sequence']
            for command in ('control shared', 'control exclusive'):
                assert request(command)['ok']
                assert request('input 1 0 0 0 0 60000')['ok']
                assert json.loads(host('poll'))['buttons'] == 1
                assert request('control player')['injected_input_cleared']
                assert json.loads(host('poll'))['buttons'] == 0
            assert not request('guest string 0x11 66697874757265')['ok']
            assert host('guest-poll') == '0'
            assert request('guest info')['thread'] == 'fixture-thread'
            request('control exclusive')
            call = request('guest string 0x11 66697874757265')
            assert call['phase'] == 'pending'
            assert not request('guest string 0x11 66697874757265')['ok']
            assert host('guest-other') == '0'  # Wrong thread cannot consume the request.
            assert request('guest info')['phase'] == 'pending'
            assert host('guest-poll') == '1'
            assert request('guest info')['phase'] == 'dispatched'
            assert host('guest-poll') == '1'  # Exactly once.
            call = request('guest string 0x11 66697874757265')
            assert not request(f'guest cancel {call["sequence"] + 1}')['canceled']
            assert request(f'guest cancel {call["sequence"]}')['canceled']
            assert host('guest-poll') == '1'
            request('guest string 0x11 66697874757265')
            host('advance 2000000000')
            assert request('guest info')['phase'] == 'canceled'
            assert host('guest-poll') == '1'
            request('guest string 0x11 66697874757265')
            request('control player')
            request('control exclusive')
            assert host('guest-poll') == '1'  # Handoff permanently cancels, even if switched back.
            request('guest string 0x12 -')
            assert host('guest-poll') == '1'
            assert request('guest info')['phase'] == 'rejected'
            assert request('guest info')['rejection_reason'] == 'adapter_rejected'
            request('guest event ' + 'reject'.encode().hex())
            assert request('guest info')['rejection_reason'] is None
            assert host('guest-poll') == '1'
            rejected = request('guest info')
            assert rejected['phase'] == 'rejected'
            assert rejected['rejection_reason'] == 'event_helper_returned_false'
            assert host('guest-poll') == '1'  # Rejected helpers are never retried.
            request('guest event 66697874757265')
            assert request('guest info')['dispatched_thread'] == ''
            assert request('guest info')['rejection_reason'] is None
            assert host('guest-poll') == '2'
            assert request('guest info')['phase'] == 'dispatched'
            assert request('guest info')['dispatched_thread'] == 'fixture-thread'
            assert request('guest info')['rejection_reason'] is None
            assert host('guest-poll') == '2'
            for kind in ('bool', 'int'):
                assert request(f'guest {kind} 0x11 1')['ok']
                host('guest-poll')
                assert request('guest info')['phase'] == 'dispatched'
            request('guest event 66697874757265 0x1234 0x2a')
            assert host('guest-poll') == '3'
            assert request('guest info')['phase'] == 'dispatched'
            request('guest event 66697874757265')
            assert host('guest-poll') == '4'  # Context is cleared for the next plain request.
            for command in ('guest bool 0x11 2', 'guest bool 0x11 -1', 'guest int 0x11 2147483648',
                            'guest int 0x11 -2147483649', 'guest int 0x11 1x', 'guest int 0 1',
                            'guest event 66697874757265 0 1',
                            'guest event 66697874757265 0x8000000000 1',
                            'guest event 66697874757265 0x1234 0x100000000',
                            'guest event 66697874757265 0x1234',
                            'guest event 66697874757265 -1 1'):
                assert not request(command)['ok'], command
            host('busy')
            queued = request('guest event 66697874757265')
            for _ in range(3):
                assert host('guest-poll') == '4'
                pending = request('guest info')
                assert pending['sequence'] == queued['sequence']
                assert pending['phase'] == 'pending'
                assert pending['pending_reason'] == 'awaiting_readiness'
                assert pending['rejection_reason'] is None
            host('ready')
            assert host('guest-poll') == '5'
            assert request('guest info')['phase'] == 'dispatched'
            assert request('guest info')['pending_reason'] is None
            assert host('guest-poll') == '5'
            host('busy')
            request('guest event 66697874757265')
            assert request('guest info')['pending_reason'] is None
            host('guest-poll')
            host('advance 1999999999')
            host('guest-poll')
            assert request('guest info')['phase'] == 'pending'
            host('advance 1')
            host('ready')
            assert host('guest-poll') == '5'
            assert request('guest info')['phase'] == 'canceled'
            host('busy')
            queued = request('guest event 66697874757265')
            host('guest-poll')
            assert request(f'guest cancel {queued["sequence"]}')['canceled']
            host('ready')
            assert host('guest-poll') == '5'
            host('busy')
            request('guest event 66697874757265')
            host('guest-poll')
            request('control player')
            request('control exclusive')
            host('ready')
            assert host('guest-poll') == '5'
            assert request('guest info')['phase'] == 'canceled'
            request('guest event 66697874757265')
            host('guest-block')
            assert request('guest info')['phase'] == 'executing'
            request('control player')
            request('control exclusive')
            assert host('guest-unblock') == '5'
            assert request('guest info')['phase'] == 'canceled'
            assert host('guest-poll') == '5'
            request('guest event 66697874757265')
            host('guest-block')
            host('advance 2000000000')
            assert host('guest-unblock') == '5'
            assert request('guest info')['phase'] == 'canceled'
            host('busy')
            request('guest event 66697874757265 wait 4000')
            host('guest-poll')
            host('advance 2000000000')
            host('guest-poll')
            assert request('guest info')['phase'] == 'pending'
            host('advance 1999999999')
            host('guest-poll')
            assert request('guest info')['phase'] == 'pending'
            host('advance 1')
            host('ready')
            assert host('guest-poll') == '5'
            assert request('guest info')['phase'] == 'canceled'
            request('guest event 66697874757265 0x1234 0x2a wait 4000')
            host('advance 3000000000')
            assert host('guest-poll') == '6'
            assert request('guest info')['phase'] == 'dispatched'
            assert host('guest-poll') == '6'
            sequence = request('guest info')['sequence']
            for invalid in ('1999', '10001', '-1', '4000x', '4000 extra'):
                assert not request('guest event 66697874757265 wait ' + invalid)['ok']
                assert request('guest info')['sequence'] == sequence
            request('control player')
            malformed = ['', 'wat', 'status extra', 'control invalid', 'input 65536 0 0 0 0 200',
                         'guest event -', 'guest event 00', 'guest event abc',
                         'guest string 0x0 01', 'guest string 0x100000000 01',
                         'guest string 0x11 00', 'guest string 0x11 abc', 'guest string 0x11 zz',
                         'guest string 0x11 ' + '01' * 64,
                         'input 1 32768 0 0 0 200', 'input 1 0 0 0 0 0', 'input 1 0 0 0 0 60001',
                         'input 99999999999999999999999999999 0 0 0 0 10', 'input 1x 0 0 0 0 10',
                         'input 1 0 0 0 0 10 trailing', b'status\0hidden', 'x' * 2048,
                         'memory info extra', 'memory write 0x0 ff', 'memory read -1 4', 'memory read +0x1 4',
                         'memory read 0x 4', 'memory read 0x10000000000000000 4', 'memory read 0x1garbage 4',
                         'memory read 0x0 0', 'memory read 0x0 257', 'memory read 0x0 -1', 'memory read 0x0 1e2']
            for command in malformed:
                # A zero-length seqpacket is received as EOF and gets an explicit error.
                assert request(command)['ok'] is False, command
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as idle:
                idle.connect('\0' + name)
                assert request('status')['ok']  # An idle client cannot block the server indefinitely.
            assert request('status')['control'] == 'player'
            # The shipped Python client uses this exact server and rejects a mismatched session peer.
            spec = importlib.util.spec_from_file_location('analysis_api', ROOT / 'scripts/analysis_api.py')
            adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapter)
            session = Path(tmp) / 'session.json'
            info = dict(pid=proc.pid, process_start_ticks=adapter.process_stamp(proc.pid), debug_socket=name,
                        headless=False, start_minimized=True, audio_enabled=False)
            session.write_text(json.dumps(info))
            (Path(tmp) / 'game.log').write_text('')
            (Path(tmp) / 'shots').mkdir()
            api = adapter.HookshotAPI(session)
            assert api.status()['runtime_api_available'] and api.status()['telemetry_source'] == 'native present hook'
            assert api.memory_info()['ready']
            assert api.read_memory(0, 8)['data_hex'] == 'a5' * 8
            for address, length in [(-1, 1), (1 << 64, 1), (0, 0), (0, 257), (True, 8), (0, 1.5)]:
                try:
                    api.read_memory(address, length)
                    raise AssertionError('invalid memory read accepted')
                except ValueError:
                    pass
            cli = subprocess.run([sys.executable, str(ROOT / 'scripts/analysis_api.py'), 'read-memory', str(session),
                                  '0x0', '8'], capture_output=True, text=True, check=True)
            assert json.loads(cli.stdout)['data_hex'] == 'a5' * 8
            api.control('exclusive')
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(api.press, 'A+LRIGHT', 200)
                for _ in range(1000):
                    host('poll')
                    if future.done():
                        break
                assert future.result(timeout=2)['applied']
            assert api.status()['buttons'] == 1 and api.status()['sticks'] == [32767, 0, 0, 0]
            try:
                api.input(1, milliseconds=200, timeout=0)
                raise AssertionError('unpolled command did not time out')
            except adapter.InputPollTimeout as exc:
                assert exc.input_canceled is True
                assert type(exc.input_sequence) is int
                assert api.status()['input_sequence'] == exc.input_sequence + 1
            assert json.loads(host('poll'))['buttons'] == 0
            api.control('player')
            try:
                api.press('A')
                raise AssertionError('player input lock ignored')
            except RuntimeError:
                pass
            original_pid, original_stamp = api.info['pid'], api.info['process_start_ticks']
            api.info['pid'] = os.getpid()
            api.info['process_start_ticks'] = adapter.process_stamp(os.getpid())
            try:
                api.request('status')
                raise AssertionError('mismatched socket peer accepted')
            except RuntimeError as error:
                assert 'peer does not match' in str(error)
            api.info['pid'], api.info['process_start_ticks'] = original_pid, original_stamp
            # Preserve the existing session-log path for old running binaries.
            del api.info['debug_socket']
            assert api.status()['telemetry_source'] == 'renderer log'
        finally:
            proc.stdin.close()
            proc.wait(timeout=3)
        assert proc.returncode == 0
    print('PASS: native API timing, input/handoff, bounded memory reads, guard/unmapped pages and malformed/idle clients')


if __name__ == '__main__':
    main()
