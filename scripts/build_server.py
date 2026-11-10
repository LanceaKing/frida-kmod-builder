#!/usr/bin/env python3
"""Build the pinned Android arm64 server with its official entrypoint."""
import argparse
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys
import build as builder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-lock', type=Path, default=builder.ROOT / 'sources/frida-17.26.2.json')
    parser.add_argument('--source-dir', type=Path, default=builder.WORK / 'server-source')
    parser.add_argument('--output', type=Path, default=builder.DIST / 'server')
    args = parser.parse_args()
    lock = builder.read_json(args.source_lock)
    ndk = Path(os.environ['ANDROID_NDK_ROOT']).resolve()
    properties = (ndk / 'source.properties').read_text()
    builder.require('Pkg.Revision = 29.0.14206865' in properties, 'Use Android NDK 29.0.14206865.')
    source = args.source_dir.resolve()
    source.parent.mkdir(parents=True, exist_ok=True)
    commit = lock['server']['core_commit']
    builder.require(commit in lock['core']['profiles'].values(), 'Server commit must be a pinned core profile.')
    actual = builder.git_checkout(lock['core']['repository'], commit, source)
    builder.require(actual == commit, 'Fetched core differs from source lock.')
    builder.run('git', '-C', source, 'submodule', 'update', '--init', '--recursive', '--depth=1', 'releng')
    env = dict(os.environ, PYTHON=sys.executable, ANDROID_NDK_ROOT=str(ndk))
    configure = ['./configure', '--host=android-arm64', '--enable-server', '--disable-gadget',
                 '--disable-portal', '--disable-inject', '--disable-tests', '--',
                 '-Dcompat=disabled', '-Dfrida_version=' + lock['version']]
    builder.run(*configure, cwd=source, env=env)
    builder.run('make', '-j8', 'frida-server', cwd=source, env=env)
    builder.run('git', '-C', source, 'diff', '--exit-code')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    binary = output / 'frida-server'
    shutil.copy2(source / 'build/server/frida-server', binary)
    archive = output / f"frida-server-{lock['version']}-android-arm64.xz"
    with binary.open('rb') as src, lzma.open(archive, 'wb', preset=6) as dst:
        shutil.copyfileobj(src, dst)
    record = {'core_repository': lock['core']['repository'], 'core_commit': commit,
              'configure': configure, 'ndk': '29.0.14206865', 'python': sys.version,
              'releng_commit': builder.run('git', '-C', source / 'releng', 'rev-parse', 'HEAD', capture=True).strip(),
              'binary_sha256': builder.sha256(binary), 'archive': archive.name,
              'archive_sha256': builder.sha256(archive)}
    builder.write_json(output / 'server-build.json', record)
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
