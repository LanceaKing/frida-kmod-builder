#!/usr/bin/env python3
"""Build official frida-tools with the pinned Java bridge dependency."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.check_output([str(a) for a in args], text=True, **kwargs).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configure_dependencies(source, overlay, bridge):
    original = json.loads((source / 'bridges/package.json').read_text())
    selected = json.loads((overlay / 'package.json').read_text())
    expected = copy.deepcopy(original)
    expected['dependencies']['frida-java-bridge'] = bridge
    if selected != expected:
        raise ValueError('The tools overlay must change only the Java bridge dependency.')
    original_lock = json.loads((source / 'bridges/package-lock.json').read_text())
    selected_lock = json.loads((overlay / 'package-lock.json').read_text())
    entry = selected_lock['packages']['node_modules/frida-java-bridge']
    if entry.get('resolved') != bridge or not entry.get('integrity', '').startswith('sha512-'):
        raise ValueError('The bridge archive must have a locked URL and integrity hash.')
    expected_lock = copy.deepcopy(original_lock)
    expected_lock['packages']['']['dependencies']['frida-java-bridge'] = bridge
    expected_lock['packages']['node_modules/frida-java-bridge'] = entry
    if selected_lock != expected_lock:
        raise ValueError('The tools lock must change only the Java bridge dependency.')
    for name in ('package.json', 'package-lock.json'):
        shutil.copy2(overlay / name, source / 'bridges' / name)


def build(lock_path, output):
    lock = json.loads(lock_path.read_text())
    tools = lock['tools']
    if tools['repository'] != 'https://github.com/frida/frida-tools.git':
        raise ValueError('Tools must come from the official upstream repository.')
    commit = tools['commit']
    if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Tools require a full commit SHA.')
    output.mkdir(parents=True, exist_ok=True)
    work = ROOT / '.work/tools-build'
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as directory:
        source = Path(directory) / 'source'
        source.mkdir()
        run('git', 'init', source)
        run('git', '-C', source, 'fetch', '--depth=1', tools['repository'], commit)
        run('git', '-C', source, 'checkout', '--detach', 'FETCH_HEAD')
        if run('git', '-C', source, 'rev-parse', 'HEAD') != commit:
            raise ValueError('Fetched tools commit differs from source lock.')
        run('git', '-C', source, 'submodule', 'update', '--init', '--recursive', '--depth=1')
        overlay = ROOT / tools['dependencies']
        configure_dependencies(source, overlay, lock['java_bridge']['archive'])
        # Upstream build helpers invoke npm install. Keep their source unchanged,
        # but use npm ci in this build process so every bundle uses its lock file.
        npm = shutil.which('npm')
        if npm is None:
            raise RuntimeError('npm is required.')
        shim = Path(directory) / 'bin'
        shim.mkdir()
        wrapper = shim / 'npm'
        wrapper.write_text(f'#!{sys.executable}\nimport os, sys\n'
                           'args = sys.argv[1:]\n'
                           'if args == ["install"]: args = ["ci"]\n'
                           f'os.execv({npm!r}, [{npm!r}, *args])\n')
        wrapper.chmod(0o755)
        epoch = run('git', '-C', source, 'show', '-s', '--format=%ct', 'HEAD')
        env = dict(os.environ, FRIDA_VERSION=tools['version'], SOURCE_DATE_EPOCH=epoch,
                   PYTHONHASHSEED='0', PATH=str(shim) + os.pathsep + os.environ['PATH'])
        wheels = Path(directory) / 'wheels'
        subprocess.run(['uv', 'build', '--wheel', str(source), '--python', sys.executable, '--out-dir', str(wheels),
                        '--build-constraints', str(overlay / 'build-constraints.txt')], env=env, check=True)
        wheel, = wheels.glob('*.whl')
        if wheel.name != tools['wheel_url'].rsplit('/', 1)[1]:
            raise ValueError('Built wheel filename differs from source lock.')
        changed = run('git', '-C', source, 'diff', '--name-only').splitlines()
        if sorted(changed) != ['bridges/package-lock.json', 'bridges/package.json']:
            raise ValueError(f'Unexpected tools source changes: {changed}')
        with zipfile.ZipFile(wheel) as archive:
            bridge_hash = hashlib.sha256(archive.read('frida_tools/bridges/java.js')).hexdigest()
        shutil.copy2(wheel, output / wheel.name)
        record = {'tools_repository': tools['repository'], 'tools_commit': commit,
                  'bridge_commit': lock['java_bridge']['commit'], 'version': tools['version'],
                  'dependency_files': {n: digest(overlay / n) for n in
                                       ('package.json', 'package-lock.json', 'build-constraints.txt')},
                  'changed_source_files': changed, 'source_date_epoch': epoch,
                  'node': run('node', '--version'), 'npm': run(npm, '--version'),
                  'uv': run('uv', '--version'), 'python': sys.version,
                  'wheel': wheel.name, 'wheel_sha256': digest(wheel), 'java_bundle_sha256': bridge_hash}
        (output / 'tools-build.json').write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-lock', type=Path, default=ROOT / 'sources/frida-17.26.2.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/tools')
    args = parser.parse_args()
    build(args.source_lock.resolve(), args.output.resolve())
