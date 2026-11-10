# Pixel 7a full-mode acceptance record

Status: **experimental; bounded regression passed on the pinned device with the server and Java bridge patches**.

Revision `0bae5f8` passes the process probe, normal module reload, and a minimal kernel JavaScript session on the target device.
The rebuilt server fixes the observed synthetic Bionic TLS capacity error.
Direct server startup restores official SELinux initialization. The separate [Java bridge patch](JAVA-TEARDOWN.md) corrects premature callback release during script unload.
Install the pinned fork bridge in the script project and recompile its Java scripts. The server rebuild does not include this client-side dependency correction.

The scope is arm64 Apps, Frida 17.26.2, and kernel `5.10.157-android13-4-00003-g776d0a76f6aa-ab10208116` from source `776d0a76f6aa7c5a92c60afbe886a8e786953199`.
The backport keeps the official prctl ABI. The historical matrix below uses the TLS and connection-cleanup server patches plus the first Java bridge correction. The [fork migration](FORKS.md) adds the ART inline-patch restoration fix and records the new validation.
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

## Earlier App injection blocker: stock server TLS

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

## Earlier rebuilt-server test: policy initialization disabled

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

## Official startup: App tests passed

The next test removed `server-no-policy` and started the same TLS-corrected server directly as root.
No additional server source patch, kernel module change, or custom SELinux rule was needed.
The official startup helper loaded its policy, and the injector labeled the agent memfd `u:object_r:frida_memfd:s0`.
The policy SHA256 changed from `c22b30cb8408cc79f1284610de6ce1f2b463d2fd1d58c56cd9026eb439100e46` to `57a2b0de542ff73c270e465fcb2b64025cba064c98e86f942e431ae1ad002e4f`.
The hash stayed at the latter value after both servers restarted directly.

The first Calculator attach used PID 20314 and created bootstrap TID 20454 with UID 10187.
Module allocation, write, and spawn records preceded the agent's Native and Java messages.
Both hooks preserved the original return values. Ten further attach/script-unload/detach cycles all passed.
The module recorded 33 allocations and 33 successful frees for these eleven sessions, with one new bootstrap thread per session.
Across the ten-cycle batch, server RSS changed from 173384 to 173392 KiB and its FD count stayed at 58.
Calculator RSS changed from 203408 to 203360 KiB, its FD count fell from 126 to 122, and no mapping name contained `frida` after detach.
These bounded observations do not establish absence of all memory leaks.

Spawn/resume passed both hooks. Cancel-before-resume unloaded the script, detached, and terminated the disposable target.
Neither spawned process remained after cleanup.
For those two targets and the active-session termination test, the final deferred region release returned `ESRCH` after the process had exited.
The kernel had already released each terminated process's address space; the earlier stack and TLS frees returned zero.
Invalid and exited PIDs returned `ProcessNotFoundError`.
Terminating a target with an active session delivered `process-terminated` without a crash report.
An App restart and a normal Android server restart were followed by another successful attach and both hooks.
The official Barebone entrypoint also passed the PID 0 JavaScript test, returning 42, then unloaded and detached.

Boot ID stayed `8a6ae5b1-6a98-4f06-8200-04dca2757ec9`, root remained available, and every enforcing-state snapshot reported Enforcing.
No new kernel warning, Oops, panic, device reboot, or Calculator crash appeared in the captured logs.
The audit log still contained socket `setopt` and `/proc/PID/maps` `ioctl` denials for the App, plus permissive `checkpoint_restore` events in the existing KernelSU domain.
These did not fail the probes; no extra rules were added for them.
The App retained its `untrusted_app` context. Global Enforcing does not imply that every domain is enforcing.

Both direct servers remained listening: Barebone on 27042 and ordinary Android on 27043, bound to device loopback and forwarded through ADB.
No client session remained. The module reference count was one because the Barebone server held `/dev/frida`.
This test did not reload the module; the three-load/two-unload result above remains the module lifecycle evidence.
At this stage, concurrent target exit and other Apps were untested. The extended tests below supersede that acceptance status.

Raw device logs, policy snapshots, host events, and the summary are stored locally in `.work/official-entry-validation-20261110/`.
The distributable server bundle includes `device-validation.json`; policy binaries and device logs are not committed.

## Extended Apps and concurrent target exit

The extended matrix covered Clock (`untrusted_app`), Settings (`system_app`), and DocumentsUI (`priv_app`).
Each completed ten attach/script-unload/detach cycles with Native and Java callbacks.
Clock and Settings also completed spawn/resume and cancel-before-resume probes.
DocumentsUI used its document-picker activity because it has no launcher activity.
These initial probes checked callbacks and cleanup API results, but did not observe the process after detach.

The exit probe uses `exit-on-injection.c` to watch the module's operation records in `/dev/kmsg`.
It verifies the target package and uses a pidfd to send SIGKILL without a PID-reuse hazard.
The four trigger events are allocation, write, spawn, and target-thread readiness.
They select scheduling windows, not exact kernel instructions or every possible interleaving.

The first three failed injections each left a pending abstract Unix listener in the server.
The server FD count grew by three after the clients disconnected.
The [connection-cleanup patch](SERVER-ANDROID13-TLS.md) cancels the per-attempt accept/handshake and closes connections whose handshake failed.
The rebuilt server SHA256 is `77eecc8c7145793cd162bef0cfdca5ce0e044c46782935a51a09c8d91800b813`.
Both server patches apply in order and exactly match the built source. The module and official policy helper are unchanged.

The corrected server completed five exits at each trigger, for 20 attempts.
Ten calls returned `NotSupportedError`, four returned `TransportError`, and six reached the existing connection timeout.
All returned within 10.84 seconds without external cancellation. No pending listener remained after any attempt.
The server FD count before each call stayed at 60. Each attempt was followed by a new target and successful Native/Java callbacks.
The test records device-side signal markers because ADB output and RPC errors can arrive at the host in different orders.

The final crash-log review invalidated full acceptance despite those successful API results.
Settings spawn PID 24997 reported SIGSEGV. Calculator recovery PIDs 27544, 29324, and 30356 also crashed after hook unload.
The Calculator tombstones all enter the old Java `identityHashCode()` callback from ART's generic JNI trampoline.
They resolve to `gum_quick_value_from_ffi()` at agent offset `0xe81188`, called by `gum_quick_native_callback_invoke()`.
The faulting instruction reads an invalid FFI field-type pointer. At that stage, callback lifetime and stale method dispatch were unresolved.
This is not the earlier Bionic TLS fault, and it is not a kernel panic.

The App runner now observes survival for three seconds after detach, before terminating a spawned target, and exits nonzero on cleanup failure.
Ten fresh Calculator runs without the module and ten after restoring it passed this stronger check.
Those bounded controls did not reproduce the crash. They do not explain or resolve the recorded failures, or establish which backend caused them.
The readiness gate therefore remained failed at that stage. The final teardown regression below supersedes that status.

The control experiment used normal module removal and restored the same artifact afterward.
This brings same-boot lifecycle evidence to four loads and three normal unloads, with no forced unload or kernel fault.
The restored module and corrected server passed the minimal PID 0 JavaScript session.
Root, boot ID, global Enforcing state, and the post-official-startup policy hash stayed unchanged.
Both direct servers are running again on loopback ports 27042 and 27043. No probe client remains attached.

Evidence is stored locally in `.work/extended-validation-20261110/`, including the pre-fix leak, corrected tests, controls, and three Calculator tombstones.
The crash and device logs are not committed. Other kernels, 32-bit Apps, exhaustive interleavings, and long-duration stress remain outside the tested scope.

## Final Java teardown regression

A diagnostic build later caught a `NativeCallback` release while a caller waited for the JavaScript lock.
The [bridge lifetime patch and reproduction record](JAVA-TEARDOWN.md) document the failure and the two-stage cleanup.
The patch retains replacement callbacks and cloned ART methods until no ART frame references them.
The official server entrypoints, SELinux helper, kernel module, and prctl protocol remain unchanged.

The final non-diagnostic matrix passed 50 concurrent unloads, 40 repeated attach sessions, 42 spawns, and three cancellations before resume.
It also passed 20 injection/exit races and 20 fresh-process recoveries, each with the stronger post-detach survival check.
The maximum failed-injection duration was 10.48 seconds. No bootstrap listener remained after any attempt.
Invalid/exited PID handling, target termination, and the Barebone PID 0 session passed.

The final crash-buffer and tombstone comparison found no new crash.
The kernel log contained no new warning, Oops, or panic. Root, boot ID, global Enforcing state, and the policy hash remained unchanged.
Both direct server entrypoints remained running with the existing server SHA256 `77eecc8c7145793cd162bef0cfdca5ce0e044c46782935a51a09c8d91800b813`.
Evidence and source hashes are in `.work/teardown-acceptance-20261110/summary.json` and `provenance.json`.
Earlier diagnostic and interrupted candidate runs are excluded from this final count.
Standalone hook removal in a running script, other ART builds, 32-bit Apps, and exhaustive interleavings remain outside this result.

| Acceptance stage | Result |
| --- | --- |
| Shared and mode-specific patches apply | Passed for both modes |
| Offline builds | Passed for both revisions and modes |
| CRC, vermagic, CFI and writable sections | Passed for current full and kernel-only bundles |
| First full startup | Failed before service readiness; artifact rejected |
| Current full startup and normal reload | Four loads and three normal unloads passed |
| Alloc/read/write/free and user-thread probe | Passed |
| Rebuilt server TLS capacity | Built and verified; original crash did not recur |
| Native and Java hooks in four Apps | Passed with the bridge patch and post-detach survival checks |
| Spawn and cancellation | 42 spawns and three cancellations passed with the bridge patch |
| Ten attach/unload/detach cycles | Passed in each of four Apps, with survival checks |
| Concurrent injection/exit | Final 20 bounded aborts and fresh-process recoveries passed without a new crash |
| Concurrent Java hook unload | Final 50 four-thread rounds passed |
| Invalid PID and target exit | Process probes and active-session termination passed |
| Server restart and reconnect | Passed for kernel and App entrypoints |
| Kernel injection trace plus agent connection | Matching allocation, write, bootstrap TID, and script messages observed |
| Minimal kernel JS session | Passed before/after reload, with the rebuilt server, and with direct official startup |

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
It also observes target survival after detach. Capture crash logs for the tested PIDs, including after the runner returns.
The results above come from these probes; the scripts alone do not establish successful injection.

Compile `tests/device/exit-on-injection.c` with an Android arm64 NDK compiler and push it to `/data/local/tmp/exit-on-injection`.
Run `tests/device/app-exit-race.py` with the device serial, disposable target PID, package, server PID, trigger stage, and output path.
The module must have `trace_process_ops=1`. The probe kills only the specified target and records kernel signal markers and server resources.
An operation result in its JSON does not accept post-detach recovery by itself. Keep the crash-log and survival checks as separate gates.

The earlier `server-no-policy.c` launcher masked policy reads in a private mount namespace.
It preserved the current policy but prevented official agent-file setup. The launcher has been removed.
Use the [direct official startup commands](INSTALL.md#full-mode-android-app-connection) for both server entrypoints.

## Fork source migration

The current builder uses pinned official forks. See [fork provenance and validation](FORKS.md).
The earlier binary hashes and test results above remain historical evidence for their recorded builds.
