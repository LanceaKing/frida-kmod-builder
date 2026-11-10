# Pixel 7a full-mode acceptance record

Status: **experimental; device acceptance is incomplete**. Do not label this preset as fully supported.

Revision `0bae5f8` passes the process probe, normal module reload, and a minimal kernel JavaScript session on the target device.
The rebuilt server fixes the observed synthetic Bionic TLS capacity error.
Calculator injection now stops at a SELinux denial for the agent memfd. Native hooks, Java hooks, and App spawn remain unaccepted.

The scope is arm64 Apps, Frida 17.26.2, and kernel `5.10.157-android13-4-00003-g776d0a76f6aa-ab10208116` from source `776d0a76f6aa7c5a92c60afbe886a8e786953199`.
The backport keeps the official prctl ABI. The latest device test uses a server with the scoped Android TLS patch.
Barebone port 27042 serves kernel sessions. Android port 27043 serves App sessions through `KernelInjectSession`.

## Build and first device attempt

Commit `8c30d73` built both modes. The full bundle passed all 84 symbol CRC checks, all 83 undefined import checks, vermagic, the legacy CFI check-function check, and writable-section checks.
The kernel-only rebuild passed 62 CRC and 61 import checks and was byte-identical to the previously loaded module.
Both builds reused the apt, source/download, SDK, and Rust caches. Apt downloaded 0 bytes.

- [First full build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42788272165)
- [Kernel-only comparison](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42788271823)

The old Barebone server retained `/dev/frida` after SIGTERM. Its PID and file descriptor were identified, the server was terminated, and the module reference count fell to zero.
Normal `rmmod` then completed. No forced module removal was used.

The first full artifact has SHA256 `6398af1ae7bf0b17f92567bb4c681ddeb23d9fab0ba28293078b580890c824a3`.
**Do not load this artifact.** `insmod` returned success, but hook installation emitted warnings in `vmalloc_to_page` and `vmap_pte_range` and did not finish.
The process PING returned EINVAL, `/dev/frida` was absent, and the agent worker remained running.
No process injection or App hook was attempted. The observed boot ID did not change and root remained available.
The captured log contains warnings, not an observed panic or reboot.

The source classified the randomized kernel image as vmalloc memory. The image uses block mappings that this kernel's `vmalloc_to_page` cannot translate.
The shared image-page patch now checks the kernel image first. The full-mode installer also checks every hook page before starting a Gum patch transaction.

## Revised candidate

Commit `8ccfe4e` adds the image-page fix, mapping preflight, request-entry trace records, and disposable device probes.

- [Revised full build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42789593517)
- [Revised kernel-only build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42789595267)

Both revised bundles also passed their CRC, undefined-import, vermagic, CFI and writable-section checks.
The full module SHA256 is `a7cece6a30d139431299d00125fe074a2b8e22ac901c290fa19a4bf92638004c`.
The kernel-only module SHA256 is `cc7d3f88c49f8354ab093fe13872f2a554ebb8b769460533d72c2d7f220d6d02`.
After a reboot and root recovery, this candidate loaded successfully and passed the disposable process probe.
Calculator attach then failed during executable memory allocation. SELinux denied `execmem` for the process worker's `kernel` domain.
Revision `f42fc3c` carries the authorized caller's credentials through deferred allocation. It leaves thread creation under the worker's normal credentials.

Loading that revision after a normal unload caused a kernel panic in the module notification chain's CFI check.
The new module did not reach initialization. The old exit path stopped its worker but left its module notification callback registered.
That missing cleanup supports a stale-callback explanation. The crash alone does not identify every pointer involved.

## Current device results: 2026-11-10

Revision `0bae5f8` adds synchronous notification cleanup after the agent worker stops. Both modes include this patch.

- [Full build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42794839390)
- [Kernel-only build](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42794845423)

The full module SHA256 is `463bc642565654c1919e64c351435382ca77533c25cbd2881007c89df3bb3e5a`.
The kernel-only module SHA256 is `3c6a643b65da09b775b861601b771c48c0d6721227db6661bbc01df64599fabf`.
Full mode passed 84 symbol CRC and 83 undefined-import checks. Kernel-only mode passed 62 CRC and 61 import checks.
Both retained the legacy CFI check function and the required writable section flags.

The full module completed three loads and two normal unloads in one boot.
The second unload followed process probes, an App injection attempt, and a kernel JavaScript session.
Both servers stopped with SIGTERM. The module reference count reached zero before each unload.
No forced module removal, kernel warning, Oops, panic, or device reboot occurred during these tests.

The disposable target ran as UID 2000. Its injected thread reported the correct PID, TID, UID, and supplied TLS pointer.
Allocation, read/write, thread exit, and mapping release passed.
The target-exit probe returned `ESRCH` when thread creation followed target termination.
An invalid PID produced failed allocations and no new thread. This allocation API returns zero, not an errno, for that case.

The kernel session at port 27042 loaded `send({kind: 'kernel-ready', value: 6 * 7})` and received the expected value, 42.
Script unload and session detach completed. The same test passed after module reload and server restart.
These are two minimal kernel sessions, not a general kernel instrumentation stress test.

Root remained available. The device remained globally Enforcing, and the SELinux policy SHA256 stayed unchanged.
The audit log contained `checkpoint_restore` events with `permissive=1` for the existing KernelSU domain.
These observations establish policy preservation, not stock-policy equivalence or enforcement in every domain.

## App injection blocker

The unchanged Frida 17.26.2 Android server reached allocation, writes, and thread creation in the module.
The Calculator thread adopted UID 10187, but it crashed before the agent connected back.
The crash was a userspace SIGSEGV in `ScopedTrace::ScopedTrace`, called by `pthread_create`. It was not a kernel panic.

The official [`synthesize_tls()` implementation](https://github.com/frida/frida-core/blob/17.26.2/src/linux/kernel-injector.vala#L306) allocates an 8 KiB block.
It places the Bionic scratch area at three quarters of the block, leaving 2 KiB.
The device's `libc.so` reads the Bionic TLS pointer from `TPIDR_EL0 - 8`, then reads a byte at offset `0x2fa1`.
The captured pointer plus that offset exactly matches the reported fault address.
This read falls outside the synthetic TLS allocation.

The faulting code uses `bionic_systrace_disabled`, a field in Android 13's `bionic_tls` structure.
The device binary provides the decisive offset evidence. The matching source layout is supporting evidence.
The probe's successful syscall-only thread does not establish a valid Bionic pthread environment.

This failure occurred with the unchanged official server. The next test used the rebuilt server described below.

## Rebuilt server: TLS corrected, policy blocker remains

The [Android server patch](SERVER-ANDROID13-TLS.md) increases the total synthetic TLS allocation to 64 KiB.
The existing quarter-block layout then reserves 16 KiB for Bionic state.
The server SHA256 is `e43099154b1532f689fa6929089a506ac5366ef7289f4cb250d7bbc9f33453c6`.
The device reported the same hash and version 17.26.2.

The Calculator test reached module allocation, writes, and thread creation with App UID 10187.
The earlier TLS crash did not recur, and Calculator remained alive.
The next operation failed when SELinux rejected `read write` access to the agent memfd, which retained file type `tmpfs`.
The host reported `TransportError: error sending data: Broken pipe` before agent startup or script execution.
This is a separate blocker from TLS capacity. The existing mapper path also transfers this file descriptor.

The rebuilt server passed the minimal kernel JavaScript test on port 27042.
No additional kernel warning, Oops, panic, or device reboot occurred. Root, global Enforcing state, and the policy hash stayed unchanged.
The App test server stopped normally. The disposable Calculator process was terminated to release the failed injection's mappings.
The rebuilt Barebone server remained running. No SELinux policy or file-label changes formed part of this test.

| Acceptance stage | Result |
| --- | --- |
| Shared and mode-specific patches apply | Passed for both modes |
| Offline builds | Passed for both revisions and modes |
| CRC, vermagic, CFI and writable sections | Passed for current full and kernel-only bundles |
| First full startup | Failed before service readiness; artifact rejected |
| Current full startup and normal reload | Three loads and two unloads passed |
| Alloc/read/write/free and user-thread probe | Passed |
| Rebuilt server TLS capacity | Built and verified; original crash did not recur |
| Calculator Native and Java hooks | Blocked by SELinux agent-memfd denial before script execution |
| Spawn and cancellation | Not run after attach failed |
| Ten attach/unload/detach cycles | Not run |
| Invalid PID and target exit before spawn | Passed; concurrent exit race remains untested |
| Kernel server restart and reconnect | Passed |
| Kernel injection trace plus agent connection | Operations and target thread observed; agent connection failed |
| Minimal kernel JS session | Passed before/after reload and with the rebuilt server |

`features` in build-info describes compiled code. `device_validation` records actual observations. A successful build must not set device acceptance to passed.

## Reproducible probes

`tests/device/process-probe.c` implements the official prctl structures. Run its target as the ordinary shell user and its controller as root.
It checks allocation, read/write, a remote thread with a supplied stack and TLS, its reported PID/TID/UID/TLS, thread exit, and mapping release.
The thread uses only syscalls, so the test does not pretend that an arbitrary TLS block is a valid Bionic pthread.
The host must compare the reported UID with the target's UID and inspect `/proc/PID/task/TID/status` during the two-second pause.

`tests/device/app-session.py` uses the pinned Frida Python client and compiles `app-hooks.js` with `frida-java-bridge` 7.0.13.
Install its Java bridge with `npm ci --prefix tests/device`.
The hooks report original `getpid()` and `System.identityHashCode()` results and preserve those results.
The runner supports attach, spawn, cancel-before-resume, and repeated sessions, with bounded operations and cleanup.
These scripts are prepared test tools, not evidence of successful injection.

The unmodified Android server attempts to modify SELinux policy at startup.
`server-no-policy.c` masks policy reads in a private mount namespace so the official policy helper returns before any write.
The launcher was tested independently: its policy view was empty, the global policy SHA256 was unchanged, and the device remained Enforcing.
This verifies preservation of the current policy; it does not claim that the current policy is the stock policy.
