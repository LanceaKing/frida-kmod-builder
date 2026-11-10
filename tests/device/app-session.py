#!/usr/bin/env python3
"""Run a bounded App attach/spawn probe, saving host-side events as JSON.

Use Frida 17.26.2. Kernel trace evidence must be captured separately; successful
hooks alone do not prove which injection backend the server used.
"""
import argparse
import json
from pathlib import Path
import threading
import time
import frida

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--address', default='127.0.0.1:27043')
p.add_argument('--pid', type=int)
p.add_argument('--spawn', action='store_true')
p.add_argument('--cancel-spawn', action='store_true')
p.add_argument('--package', default='com.google.android.calculator')
p.add_argument('--rounds', type=int, default=1)
p.add_argument('--post-detach-seconds', type=float, default=3,
               help='Observe target survival after detach and before killing a spawned target')
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
assert a.spawn or a.cancel_spawn or a.pid, 'Specify a PID or spawn mode'
assert a.post_detach_seconds >= 0
assert frida.__version__ == '17.26.2', frida.__version__
device = frida.get_device_manager().add_remote_device(a.address)
project_root = Path(__file__).resolve().parent
source = frida.Compiler().build('app-hooks.js', project_root=str(project_root))
results = []
try:
    for index in range(a.rounds):
        record = {'round': index + 1, 'started_at': time.time(), 'messages': []}
        results.append(record)
        session = script = None
        pid = a.pid
        resumed = False
        cancel = frida.Cancellable()
        timer = threading.Timer(25, cancel.cancel)
        timer.start()
        try:
            with cancel:
                if a.spawn or a.cancel_spawn:
                    pid = device.spawn([a.package])
                record['pid'] = pid
                session = device.attach(pid)
                script = session.create_script(source)
                script.on('message', lambda message, data: record['messages'].append(
                    {'time': time.time(), 'message': message}))
                script.load()
                if a.cancel_spawn:
                    script.unload()
                    script = None
                    session.detach()
                    session = None
                    device.kill(pid)
                    pid = None
                    record['cancelled_before_resume'] = True
                else:
                    if a.spawn:
                        device.resume(pid)
                        resumed = True
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        kinds = {item['message'].get('payload', {}).get('kind')
                                 for item in record['messages'] if item['message']['type'] == 'send'}
                        if {'native-ready', 'java-ready'} <= kinds:
                            break
                        if cancel.is_cancelled:
                            break
                        time.sleep(0.1)
                    record['counts'] = script.exports_sync.counts()
                    assert record['counts']['native'] > 0 and record['counts']['java'] > 0, record
                record['ok'] = True
        except Exception as error:
            record['ok'] = False
            record['error'] = f'{type(error).__name__}: {error}'
            raise
        finally:
            timer.cancel()
            # Cleanup has its own bound; the operation's timeout may be cancelled.
            cleanup = frida.Cancellable()
            cleanup_timer = threading.Timer(10, cleanup.cancel)
            cleanup_timer.start()
            try:
                with cleanup:
                    if script is not None:
                        script.unload()
                    if session is not None:
                        session.detach()
                    if pid is not None and not a.cancel_spawn:
                        deadline = time.monotonic() + a.post_detach_seconds
                        while time.monotonic() < deadline:
                            assert any(process.pid == pid for process in device.enumerate_processes()), \
                                f'Target {pid} exited after detach'
                            time.sleep(0.1)
                        record['post_detach_alive_seconds'] = a.post_detach_seconds
                    if (a.spawn or a.cancel_spawn) and pid is not None:
                        device.kill(pid)
            except Exception as error:
                record['cleanup_error'] = f'{type(error).__name__}: {error}'
                record['ok'] = False
            finally:
                cleanup_timer.cancel()
                record['finished_at'] = time.time()
                a.output.parent.mkdir(parents=True, exist_ok=True)
                a.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({k: v for k, v in record.items() if k != 'messages'}))
        if not record['ok']:
            raise SystemExit(1)
finally:
    frida.get_device_manager().remove_remote_device(a.address)
