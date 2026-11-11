# Two source forks and one builder

Current builds use one default feature set. The dual-mode runs below are historical validation records; kernel-only mode has been removed.

This repository maintains the source lock, dependency files, build scripts, and releases.
The [branch and change audit](FORK-AUDIT.md) records the candidate scope; no fork changes have been merged into main. Only two source forks are required.
The [core fork](https://github.com/LanceaKing/frida-core) contains kernel compatibility, TLS, and injection cleanup fixes.
The [Java bridge fork](https://github.com/LanceaKing/frida-java-bridge) contains the script-unload fixes.
The [compatibility index](COMPATIBILITY.md) links every former patch to its owning commit.

The builder uses one core commit from [the source lock](../sources/frida-17.26.2.json) for all target kernels.
ARM64 Linux 5.10 automatically selects the GKI process ABI; optional ARM64 fields are detected from the target headers.
Other kernel families retain the upstream process ABI. Each module must be rebuilt against the exact target kernel configuration and symbols; a shared source branch does not make module binaries portable.
It builds tools from a fixed [official frida-tools commit](https://github.com/frida/frida-tools/commit/6bbae44a5df871524619337130471871ccc386dd).
Only `bridges/package.json` and `bridges/package-lock.json` are replaced with the copies in `sources/tools-17.26.2/`.
The build rejects unrelated dependency changes. A build-local npm wrapper maps the upstream helpers' `npm install` calls to `npm ci`.
The official tools program files stay unchanged. The CLI bundles the pinned bridge and keeps its official commands.
The server keeps its official entrypoint and SELinux helper. Official GumJS devkits and SDK dependencies remain unchanged.

The former top-level Frida and tools forks were deleted after the replacement release assets were published and verified in this builder repository.
Use the new release URLs below. Old URLs in earlier source-lock revisions are historical and no longer supported.

## Build and publish

Use Python 3.12, Node.js 26.9.0, npm 11.19.1, and uv 0.13.0 for the tools build.
Python build dependencies are pinned in `sources/tools-17.26.2/build-constraints.txt`.
Run from this repository:

```sh
python3.12 scripts/build_tools.py --output dist/release
export ANDROID_NDK_ROOT=/path/to/android-ndk-29.0.14206865
python3.12 scripts/build_server.py --output dist/release
```

The server script needs a clean build directory. Its default source checkout is `.work/server-source`.
It uses the independent `server.core_commit` pin and records the compiler configuration in `server-build.json`.
Source maintenance on fork `main` does not silently upgrade published server or tools binaries.
The tools script uses a fresh temporary checkout and writes `tools-build.json` with source and dependency hashes.
The server excludes 32-bit and emulated compatibility payloads. Its protocol version remains 17.26.2.

Build modules through the single existing Actions workflow. The default build includes GKI 5.10 compatibility and process injection. The workflow resolves target artifacts automatically.
Publish the server, tools wheel, both modules, their build records, the source lock, and checksums in this repository's release.
Update the source-lock hashes before publishing. Download the assets again and check their hashes before accepting a release.
Module packaging checks the compressed server and extracted binary hashes before replacing its output file.

## Install the bundled CLI

The [unified bridge release](https://github.com/LanceaKing/frida-kmod-builder/releases/tag/17.26.2-unified.1) contains the updated tools wheel and its provenance. The independently pinned server and earlier exact-target modules remain in the [previous builder release](https://github.com/LanceaKing/frida-kmod-builder/releases/tag/17.26.2-pixel-5.10.3). Build modules for other kernels through Actions; the old release name does not select a source compatibility path.
Install the wheel with the matching Frida client in an isolated environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'frida==17.26.2' 'https://github.com/LanceaKing/frida-kmod-builder/releases/download/17.26.2-unified.1/frida_tools-14.13.1.dev7-py3-none-any.whl#sha256=676d320ae08961771d75135f9f31c07998adc6d96369f46fbbcba426e9ed45bc'
frida --version
```

For historical releases, only the full `.ko` corresponds to the current feature set. New builds have no mode selector. Copy the module matching your target kernel as `frida-agent.ko`.
Check the original asset hashes before renaming. Decompress the server archive and name its output `frida-server`.
Then follow [the installation guide](INSTALL.md). Actions module bundles already use these filenames.

The wheel version distinguishes this dependency bundle from the official tools package.
Keep the environment pinned. A normal tools upgrade can replace its bundled bridge.
Script projects that compile their own bridge must use the [pinned npm dependency](JAVA-TEARDOWN.md#install-the-fork-bridge).

## Previous fork migration validation

Git tree comparison confirmed all three core profiles reproduce the old patch chains exactly. The initial fresh npm install reproduced the three previously tested Java bridge files. Migration then exposed an additional ART inline-patch restoration race; the follow-up commit is documented in [the teardown report](JAVA-TEARDOWN.md#inline-art-patch-restoration-race). The tools bridge bundle and wheel built successfully, and all 33 builder tests passed, including rejection of moving source refs and archive or binary checksum mismatches.

The final source lock passed the [full build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42827336519) and [kernel-only build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42827343307), including server checksum validation and module ABI checks.

Both downloaded fork modules passed normal unload/load and a Barebone PID 0 script. Their SHA256 values match the final CI artifacts exactly: full `b3bd71cae80fcdcb2f30dfbf9eea56e21c7aa4d1db88beac138c32ecd19f73d7`, kernel-only `991cf94fa1b9db95004b418aa717310f9f032dd9fbf8be1ae88b97fc8a218efb`. The bundled CLI loaded its bundled Java bridge, installed a Java hook, unloaded it, and left Settings alive. A clean fork install also passed 30 application attach cycles, two spawns, two cancellations, 20 target-exit races with 20 recovery injections, and invalid/exited-PID and process-termination checks.

The initial concurrent race probe rejected a listener belonging to another active injection. The accepted 20-race run was serialized, and every round ended with zero pending bootstrap listeners. Prior acceptance remains scoped to the pinned Pixel 7a Android 13 arm64 device. This migration does not establish compatibility with other ART or kernel versions.

The final fork full module, server, and pinned bridge passed 50 concurrent hook unloads with Java stack walking and 10 Settings spawns. Another 20 Settings spawns passed with the same final bridge before the module switch. Both module binaries match the final CI outputs. The boot ID and SELinux policy hash stayed unchanged; enforcement remained enabled. No new tombstone or kernel fault appeared after the inline-restoration fix.

Raw local test records are retained under `.work/forks/final/`. The earlier preview failed the inline-restoration test. Current installs use the builder release linked above.

## Two-fork consolidation acceptance

The consolidated build uses the same core and Java bridge commits as the previous acceptance.
The tools wheel comes from official source with only the two bridge dependency files replaced.
All CLI program files and Java bridge bytes match the previously tested wheel. Only package metadata and nested ZIP timestamps differ.
The independent [tools CI build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42858274353) produced matching bridge and dependency-file hashes.
All 36 local tests passed.

The rebuilt server has SHA256 `b6674025881fe799baadd3a6ab4c89091bc6d52a86e43e698c4fb625726200ee`.
The [full build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42859031582) and [kernel-only build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42859039209) passed with the new source lock and release URLs.
Both modules match the published and device-tested bytes. Their build records are included in the release.
All release assets were downloaded again and checked against `SHA256SUMS`.

The new server and tools bundle passed 50 concurrent unloads with Java stack walking, 20 Settings spawns, and 34 sessions across three Apps.
They also passed 20 target-exit races with recovery after each, invalid/exited PID checks, process-termination notifications, and a standard CLI Java hook.
Both module modes passed normal unload/load and PID 0 sessions with the new server.
No new tombstone, kernel fault, reboot, or SELinux policy change occurred. Enforcement stayed enabled and trace logging was restored.
Raw local records are under `.work/two-forks/device/`.
