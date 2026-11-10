# Android 13 server TLS and injection cleanup

This server rebuild targets Frida 17.26.2 and arm64 Apps on the pinned Pixel 7a Android 13 kernel.
TLS means thread-local storage. Bionic uses it for libc state that belongs to one thread.
These patches change the server. They do not change the kernel module or its control protocol.

## Cause and patch

The official server allocates an 8 KiB block for its synthetic TLS layout.
It places the Bionic scratch area at three quarters of that block, leaving 2 KiB.
The target libc reads `bionic_systrace_disabled` at offset `0x2fa1` from the Bionic TLS pointer.
That read falls outside the allocated block and crashes the injected Calculator thread before its agent connects.

`patches/17.26.2/server/0001-android-bionic-tls-capacity.patch` increases the Android TLS block to 64 KiB.
The existing layout then gives each scratch area 16 KiB.
The allocator, range registration, and cleanup share `TLS_SIZE`, so they use the same new size.
The non-Android branch keeps its original size. This is a capacity correction for the observed Android 13 layout, not universal Bionic compatibility.

Concurrent target exit exposed a separate cleanup defect.
The injector starts an asynchronous socket accept before it writes the loader and creates the target thread.
If either operation throws, the accept can remain pending after the attach call returns.
Three device probes each left one abstract Unix listener and one server file descriptor behind.

`patches/17.26.2/server/0002-kernel-injection-connection-cleanup.patch` gives that connection attempt its own cancellation object.
The injector cancels the attempt in `finally`, including when a write, spawn, or connection wait fails.
An accepted connection also closes if its agent handshake fails before ownership transfers to the caller.
The patch preserves the original error and leaves successful agent connections open.

## Source and build

The source is `frida-core` tag `17.26.2`, commit `2a41a960fe9b7fc0ccc85003e4f31f0caeec4d8d`.
Its `releng` submodule pins SDK release `20261106` and requires Android NDK r29.
Use Python 3.10 or newer. The validation build uses Python 3.12 and NDK `29.0.14206865` on macOS arm64.

Run these commands from the builder repository. Use a clean source directory and set the actual NDK path.

```sh
git clone --branch 17.26.2 --depth 1 https://github.com/frida/frida-core.git .work/frida-server-source
git -C .work/frida-server-source submodule update --init --recursive --depth 1
git -C .work/frida-server-source apply ../../patches/17.26.2/server/0001-android-bionic-tls-capacity.patch
git -C .work/frida-server-source apply ../../patches/17.26.2/server/0002-kernel-injection-connection-cleanup.patch
cd .work/frida-server-source
export PYTHON=python3.12
export ANDROID_NDK_ROOT=/path/to/android-ndk-r29
./configure --host=android-arm64 --enable-server --disable-gadget --disable-portal --disable-inject --disable-tests -- -Dcompat=disabled -Dfrida_version=17.26.2
make frida-server
```

The output is `build/server/frida-server`. The build excludes 32-bit and emulated compatibility payloads.
The server keeps protocol version 17.26.2. Identify the custom build by its SHA256 and accompanying source and patch metadata.

## Device acceptance

The current server includes both patches and has SHA256 `77eecc8c7145793cd162bef0cfdca5ce0e044c46782935a51a09c8d91800b813`.
The phone reported version 17.26.2 and the same SHA256.
The generated C source uses 64 KiB for allocation, range registration, and release.
The earlier TLS-only server has SHA256 `e43099154b1532f689fa6929089a506ac5366ef7289f4cb250d7bbc9f33453c6` and contains the connection cleanup defect.

The first TLS-corrected test used a launcher that masked SELinux policy reads.
The TLS crash did not recur, but agent transfer failed with a `tmpfs` memfd access denial and a broken pipe.
That launcher prevented the official server from installing its SELinux types and rules.

The next test started the same server directly as root, with the official SELinux helper enabled.
The live policy hash changed, and the agent memfd had context `u:object_r:frida_memfd:s0`.
Calculator attach, Native and Java hooks, ten attach/unload/detach cycles, spawn, and cancel-before-resume passed.
Invalid and exited PIDs returned `ProcessNotFoundError`. Terminating an attached target delivered `process-terminated` without a crash report.
Module allocation, writes, target thread creation, and agent messages confirmed the official kernel injection route.

The current server adds the connection cleanup patch to the TLS correction. The SELinux helper and injector entrypoints are unchanged.
Extended tests confirm that the pending-listener leak is fixed across 20 target exits and that other Apps reach both hooks.
The later Settings and Calculator unload crashes required a separate [Java bridge lifetime correction](JAVA-TEARDOWN.md).
The final device matrix passed with that bridge patch and this unchanged server binary.
Apply the bridge patch to each script project. Neither server patch changes the Java bridge bundled into user scripts.
Follow the [direct startup commands](INSTALL.md#full-mode-android-app-connection), using port 27043 for Apps and port 27042 for Barebone PID 0.
See the [full-mode acceptance record](PIXEL-5.10-FULL.md) for the kernel regression, policy hashes, resource observations, and remaining scope limits.
