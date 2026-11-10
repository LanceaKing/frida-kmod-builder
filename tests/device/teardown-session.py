#!/usr/bin/env python3
"""Unload Java hooks while four independent Java threads continue calling them."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import threading
import time
import uuid

import frida

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--serial', required=True)
p.add_argument('--address', default='127.0.0.1:27043')
p.add_argument('--package', default='com.google.android.calculator')
p.add_argument('--activity', default='com.google.android.calculator/com.android.calculator2.Calculator')
p.add_argument('--dex', type=Path, required=True)
p.add_argument('--rounds', type=int, default=50)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
assert a.rounds > 0
assert frida.__version__ == '17.26.2', frida.__version__


def shell(command):
    return subprocess.run(
        ['adb', '-s', a.serial, 'shell', 'su -c ' + shlex.quote(command)],
        capture_output=True, text=True, timeout=20, check=True).stdout.strip()


boot = shell('cat /proc/sys/kernel/random/boot_id')
source = frida.Compiler().build('teardown-hooks.js', project_root=str(Path(__file__).resolve().parent))
dex = list(a.dex.read_bytes())
device = frida.get_device_manager().add_remote_device(a.address)
results = []
try:
    for index in range(a.rounds):
        assert shell('cat /proc/sys/kernel/random/boot_id') == boot, 'Device rebooted'
        assert shell('getenforce') == 'Enforcing'
        shell('am force-stop ' + shlex.quote(a.package))
        launched = shell('am start -W -n ' + shlex.quote(a.activity))
        assert 'Status: ok' in launched, launched
        pid = int(shell('pidof ' + shlex.quote(a.package)))
        record = {'round': index + 1, 'pid': pid, 'started_at': time.time(), 'messages': []}
        results.append(record)
        session = script = None
        cancel = frida.Cancellable()
        timer = threading.Timer(30, cancel.cancel)
        timer.start()
        try:
            with cancel:
                session = device.attach(pid)
                script = session.create_script(source)
                script.on('message', lambda message, data: record['messages'].append(message))
                script.load()
                paths = script.exports_sync.prepare(dex, uuid.uuid4().hex)
                record['paths'] = paths
                script.exports_sync.start()
                deadline = time.monotonic() + 1.5
                while True:
                    before = script.exports_sync.counts()
                    if before['hits'] > 10 and int(before['calls']) > 0:
                        break
                    assert time.monotonic() < deadline, before
                    time.sleep(0.01)
                assert before['alive'] > 0 and int(before['failures']) == 0, before
                record['before'] = before
                record['unload_start'] = time.time()
                script.unload()
                script = None
                record['unload_end'] = time.time()
                session.detach()
                session = None
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    shell(f'test -d /proc/{pid}')
                    time.sleep(0.1)
                result = json.loads(shell('cat ' + shlex.quote(paths['output'])))
                record['workload_result'] = result
                assert result['failures'] == 0 and result['calls'] > int(before['calls']), result
                assert not any(m['type'] == 'error' for m in record['messages']), record['messages']
                shell('rm ' + ' '.join(shlex.quote(paths[k]) for k in ('path', 'output')))
                record['ok'] = True
        except Exception as error:
            record['ok'] = False
            record['error'] = f'{type(error).__name__}: {error}'
        finally:
            timer.cancel()
            cleanup = frida.Cancellable()
            cleanup_timer = threading.Timer(10, cleanup.cancel)
            cleanup_timer.start()
            try:
                with cleanup:
                    if script is not None:
                        script.unload()
                    if session is not None:
                        session.detach()
            except Exception as error:
                record['ok'] = False
                record['cleanup_error'] = f'{type(error).__name__}: {error}'
            finally:
                cleanup_timer.cancel()
            record['finished_at'] = time.time()
            a.output.parent.mkdir(parents=True, exist_ok=True)
            a.output.write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps({k: v for k, v in record.items() if k != 'messages'}), flush=True)
        if not record['ok']:
            raise SystemExit(1)
finally:
    frida.get_device_manager().remove_remote_device(a.address)
