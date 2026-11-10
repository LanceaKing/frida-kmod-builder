# Android 13 server TLS correction

This server rebuild targets Frida 17.26.2 and arm64 Apps on the pinned Pixel 7a Android 13 kernel.
TLS means thread-local storage. Bionic uses it for libc state that belongs to one thread.
This patch changes the Android server. It does not change the kernel module or its control protocol.

## Cause and patch

The official server allocates an 8 KiB block for its synthetic TLS layout.
It places the Bionic scratch area at three quarters of that block, leaving 2 KiB.
The target libc reads `bionic_systrace_disabled` at offset `0x2fa1` from the Bionic TLS pointer.
That read falls outside the allocated block and crashes the injected Calculator thread before its agent connects.

`patches/17.26.2/server/0001-android-bionic-tls-capacity.patch` increases the Android TLS block to 64 KiB.
The existing layout then gives each scratch area 16 KiB.
The allocator, range registration, and cleanup share `TLS_SIZE`, so they use the same new size.
The non-Android branch keeps its original size. This is a capacity correction for the observed Android 13 layout, not universal Bionic compatibility.

## Source and build

The source is `frida-core` tag `17.26.2`, commit `2a41a960fe9b7fc0ccc85003e4f31f0caeec4d8d`.
Its `releng` submodule pins SDK release `20261106` and requires Android NDK r29.
Use Python 3.10 or newer. The validation build uses Python 3.12 and NDK `29.0.14206865` on macOS arm64.

Run these commands from the builder repository. Use a clean source directory and set the actual NDK path.

```sh
git clone --branch 17.26.2 --depth 1 https://github.com/frida/frida-core.git .work/frida-server-source
git -C .work/frida-server-source submodule update --init --recursive --depth 1
git -C .work/frida-server-source apply ../../patches/17.26.2/server/0001-android-bionic-tls-capacity.patch
cd .work/frida-server-source
export PYTHON=python3.12
export ANDROID_NDK_ROOT=/path/to/android-ndk-r29
./configure --host=android-arm64 --enable-server --disable-gadget --disable-portal --disable-inject --disable-tests -- -Dcompat=disabled -Dfrida_version=17.26.2
make frida-server
```

The output is `build/server/frida-server`. The build excludes 32-bit and emulated compatibility payloads.
The server keeps protocol version 17.26.2. Identify the custom build by its SHA256 and accompanying source and patch metadata.

## Device acceptance

The server built successfully with SHA256 `e43099154b1532f689fa6929089a506ac5366ef7289f4cb250d7bbc9f33453c6`.
The phone reported version 17.26.2 and the same SHA256.
The generated C source uses 64 KiB for allocation, range registration, and release.

Calculator attach no longer reproduced the earlier Bionic TLS crash. The process remained alive after the failed attach.
The loader reached agent file transfer, where SELinux denied `read write` on `memfd:frida-agent-64.so`.
The file had type `tmpfs`, and the target thread retained the Calculator App's `untrusted_app` context.
The host reported `TransportError: error sending data: Broken pipe`.
Agent startup, Native hooks, Java hooks, and App spawn remain unaccepted.

The rebuilt server also passed a minimal Barebone kernel JavaScript session on port 27042.
No new kernel warning, Oops, panic, device reboot, or Calculator crash appeared in this validation.
Root remained available. Global SELinux stayed Enforcing, and the policy hash stayed unchanged.
The failed App test server stopped normally, and the disposable Calculator process was terminated.
The rebuilt Barebone server remained running.

The TLS change does not grant App access to the agent file.
The existing requirement to preserve SELinux policy still applies. No policy or file-label changes formed part of this validation.
Use port 27043 for App tests and keep the existing Barebone server on port 27042.
Use the existing `server-no-policy` launcher to preserve the device's current SELinux policy.
Capture module operation records, created thread IDs, and agent messages for each successful App test.
Record the results in the [full-mode acceptance record](PIXEL-5.10-FULL.md).
