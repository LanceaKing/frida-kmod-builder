#!/usr/bin/env python3
"""Terminate a disposable App at a kernel injection event and record the result.

Requires exit-on-injection on the device and trace_process_ops=1. The watcher
uses a pidfd and verifies the process name before sending SIGKILL. Inspect the
saved kernel logs and server resource counts before accepting the full batch.
"""
import argparse
import json
from pathlib import Path
import queue
import re
import shlex
import subprocess
import threading
import time

import frida

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--serial', required=True)
p.add_argument('--address', default='127.0.0.1:27043')
p.add_argument('--pid', type=int, required=True)
p.add_argument('--package', required=True)
p.add_argument('--stage', choices=['alloc', 'write', 'spawn', 'thread-ready'], required=True)
p.add_argument('--watcher', default='/data/local/tmp/exit-on-injection')
p.add_argument('--server-pid', type=int, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
assert frida.__version__ == '17.26.2', frida.__version__
record = {'pid': a.pid, 'package': a.package, 'stage': a.stage, 'events': []}


def shell(command):
    return subprocess.run(['adb', '-s', a.serial, 'shell', 'su -c ' + shlex.quote(command)],
                          capture_output=True, text=True, timeout=20)


def resources():
    r = shell(f'ls /proc/{a.server_pid}/fd | wc -l; '
              f'grep -E "VmRSS|Threads" /proc/{a.server_pid}/status')
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    sockets = shell('cat /proc/net/unix')
    assert sockets.returncode == 0, sockets.stderr
    return {
        'fd_count': int(lines[0]),
        'status': lines[1:],
        'bootstrap_listeners': re.findall(r'@/frida-[0-9a-f-]{36}\b', sockets.stdout),
    }


events = queue.Queue()
watcher = session = None
device = frida.get_device_manager().add_remote_device(a.address)
cancel = frida.Cancellable()
timer = threading.Timer(20, cancel.cancel)
try:
    record['resources_before'] = resources()
    command = shlex.join([a.watcher, str(a.pid), a.package, a.stage])
    watcher = subprocess.Popen(['adb', '-s', a.serial, 'shell', 'su -c ' + shlex.quote(command)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def consume():
        for line in watcher.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                event = {'kind': 'invalid-output', 'text': line}
            event['received_host_ns'] = time.monotonic_ns()
            record['events'].append(event)
            events.put(event)

    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    ready = events.get(timeout=5)
    assert ready['kind'] == 'ready' and ready['pid'] == a.pid, ready
    timer.start()
    record['attach_started_ns'] = time.monotonic_ns()
    detached = threading.Event()

    def on_detached(reason, crash):
        record['detached'] = {'reason': reason, 'crash': str(crash) if crash else None}
        detached.set()

    try:
        with cancel:
            session = device.attach(a.pid)
            record['attach_result'] = 'attached'
            session.on('detached', on_detached)
    except Exception as error:
        record['attach_result'] = type(error).__name__
        record['attach_error'] = str(error)
    finally:
        record['attach_finished_ns'] = time.monotonic_ns()
        timer.cancel()
    watcher.wait(timeout=8)
    reader.join(timeout=2)
    record['watcher_stderr'] = watcher.stderr.read()
    assert watcher.returncode == 0, record
    killed = next(e for e in record['events'] if e['kind'] == 'kill')
    exited = next(e for e in record['events'] if e['kind'] == 'exit')
    assert killed['result'] == 0 and exited['exited'], record
    assert shell('test -d /proc/' + str(a.pid)).returncode != 0, record
    assert not cancel.is_cancelled, 'Attach needed external cancellation'
    assert record['attach_result'] in {
        'attached', 'ProcessNotFoundError', 'NotSupportedError',
        'TransportError', 'ProcessNotRespondingError'
    }, record
    if session is not None:
        assert detached.wait(5) or session.is_detached, record
        assert record.get('detached', {}).get('crash') is None, record
    record['duration_ms'] = (record['attach_finished_ns'] - record['attach_started_ns']) / 1e6
    record['kill_received_during_attach'] = (
        record['attach_started_ns'] <= killed['received_host_ns'] <= record['attach_finished_ns'])
    record['resources_after'] = resources()
    deadline = time.monotonic() + 2
    while record['resources_after']['bootstrap_listeners'] and time.monotonic() < deadline:
        time.sleep(0.1)
        record['resources_after'] = resources()
    assert not record['resources_after']['bootstrap_listeners'], 'Pending injection socket leaked'
    # ADB watcher output and the Frida RPC use separate connections. Receipt
    # order is diagnostic only when attach fails after the traced target kill.
    # If attach succeeds, require evidence that the kill overlapped the call.
    if record['attach_result'] == 'attached':
        assert record['kill_received_during_attach'], 'Attach completed before the observed kill'
    record['race_evidence'] = 'kernel injection trigger, pidfd kill, target exit, bounded attach result'
    record['operation_ok'] = True
except Exception as error:
    record['operation_ok'] = False
    record['error'] = f'{type(error).__name__}: {error}'
    raise
finally:
    timer.cancel()
    if watcher is not None and watcher.poll() is None:
        watcher.terminate()
        watcher.wait(timeout=5)
    if session is not None and not session.is_detached:
        cleanup = frida.Cancellable()
        cleanup_timer = threading.Timer(5, cleanup.cancel)
        cleanup_timer.start()
        try:
            with cleanup:
                session.detach()
        except Exception as error:
            record['operation_ok'] = False
            record['cleanup_error'] = f'{type(error).__name__}: {error}'
        finally:
            cleanup_timer.cancel()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record), flush=True)
    frida.get_device_manager().remove_remote_device(a.address)
if not record['operation_ok']:
    raise SystemExit(1)
