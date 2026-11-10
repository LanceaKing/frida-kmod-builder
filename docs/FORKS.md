# Pinned Frida forks

The builder uses forks of the official Frida repositories. The [source lock](../sources/frida-17.26.2.json) records full commits, upstream bases, and release checksums. Builds reject versions without a source lock. Branch updates do not change a pinned build.

The [Frida superproject](https://github.com/LanceaKing/frida) changes only the core and tools submodule URLs and commits. Clone it with `--recurse-submodules` to obtain the fixed full-mode source tree. It is based on official Frida 17.26.2.

The [core fork](https://github.com/LanceaKing/frida-core) preserves the existing compatibility fixes as separate commits. Its `common`, `full-5.10`, and `kernel-only` profiles match the corresponding legacy patch chains exactly, including both server fixes. The builder selects the full 5.10 profile only for the pinned Pixel kernel; other full builds use common. Kernel-only builds use their separate profile.

The [Java bridge fork](https://github.com/LanceaKing/frida-java-bridge) contains the tested script-unload correction against bridge 7.0.13. Only `index.js`, `lib/android.js`, and `lib/class-factory.js` change. The first fork commit matches the prior accepted patch byte for byte. A ten-line follow-up suspends ART while restoring global inline patches, fixing a second race found during migration. See [the root cause and scope](JAVA-TEARDOWN.md).

The [tools fork](https://github.com/LanceaKing/frida-tools) changes only the bridge dependency and its lock entry. The standard CLI bundles the fixed bridge. The server entrypoints, SELinux helper, client protocol, and CLI commands remain unchanged. Official GumJS devkits and SDK dependencies remain pinned by the existing release and releng files.

Local files under `patches/` are historical evidence. Builds and fresh npm installs no longer apply them. Module bundles include `frida-sources.json`; `build-info.json` records the selected core commit and source-lock hash. Both Pixel presets include the fork server by default. Packaging verifies the compressed server and the extracted binary before replacing its output file.

## Server and CLI release

The [fork release](https://github.com/LanceaKing/frida/releases/tag/17.26.2-pixel-5.10.2) provides the Android arm64 server, the tools wheel, and the source lock. The server retains protocol version 17.26.2. Its SHA256 is `6b3a0a1fef0599a5fd762d49db6a982e146b0ac8cc5008d841fd69d6dc7552cf`. The build uses NDK r29, Python 3.12, and the [documented server configuration](SERVER-ANDROID13-TLS.md#source-and-build). It excludes 32-bit and emulated compatibility payloads.

Install the tools wheel in an isolated environment with the matching client:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'frida==17.26.2' 'https://github.com/LanceaKing/frida/releases/download/17.26.2-pixel-5.10.2/frida_tools-14.13.1.dev3-py3-none-any.whl#sha256=c8daeb940b86a28581ca5888611e2f13f0001b8d83a3687ef5f94aed02111a3e'
frida --version
```

Verify the wheel SHA256 against `tools.wheel_sha256` in the source lock when downloading it separately. Its development version identifies the fork commit after the upstream tools release. Keep this environment pinned; a normal tools upgrade can replace the bundled bridge. Script projects that compile their own bridge must also use the [pinned npm dependency](JAVA-TEARDOWN.md#install-the-fork-bridge).

## Migration validation

Git tree comparison confirmed all three core profiles reproduce the old patch chains exactly. The initial fresh npm install reproduced the three previously tested Java bridge files. Migration then exposed an additional ART inline-patch restoration race; the follow-up commit is documented in [the teardown report](JAVA-TEARDOWN.md#inline-art-patch-restoration-race). The tools bridge bundle and wheel built successfully, and all 33 builder tests passed, including rejection of moving source refs and archive or binary checksum mismatches.

The final source lock passed the [full build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42827336519) and [kernel-only build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42827343307), including server checksum validation and module ABI checks.

Both downloaded fork modules passed normal unload/load and a Barebone PID 0 script. Their SHA256 values match the final CI artifacts exactly: full `b3bd71cae80fcdcb2f30dfbf9eea56e21c7aa4d1db88beac138c32ecd19f73d7`, kernel-only `991cf94fa1b9db95004b418aa717310f9f032dd9fbf8be1ae88b97fc8a218efb`. The fork CLI loaded its bundled Java bridge, installed a Java hook, unloaded it, and left Settings alive. A clean fork install also passed 30 application attach cycles, two spawns, two cancellations, 20 target-exit races with 20 recovery injections, and invalid/exited-PID and process-termination checks.

The initial concurrent race probe rejected a listener belonging to another active injection. The accepted 20-race run was serialized, and every round ended with zero pending bootstrap listeners. Prior acceptance remains scoped to the pinned Pixel 7a Android 13 arm64 device. This migration does not establish compatibility with other ART or kernel versions.

The final fork full module, server, and pinned bridge passed 50 concurrent hook unloads with Java stack walking and 10 Settings spawns. Another 20 Settings spawns passed with the same final bridge before the module switch. Both module binaries match the final CI outputs. The boot ID and SELinux policy hash stayed unchanged; enforcement remained enabled. No new tombstone or kernel fault appeared after the inline-restoration fix.

Raw local test records are retained under `.work/forks/final/`. The earlier failing preview is marked superseded; use release `17.26.2-pixel-5.10.2`.
