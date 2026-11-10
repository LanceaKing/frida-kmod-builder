# Pixel 7a full-mode acceptance record

Status: **experimental; device acceptance is incomplete**. Do not label this preset as fully supported.

The scope is arm64 Apps, Frida 17.26.2, and kernel `5.10.157-android13-4-00003-g776d0a76f6aa-ab10208116` from source `776d0a76f6aa7c5a92c60afbe886a8e786953199`.
The backport keeps the official prctl ABI and the official Android server binary.
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
The revised candidate has not been loaded on the device.
The device must first recover from the initial worker that did not finish initialization. A reboot can remove runtime KernelSU root, so recovery requires coordination with the device owner.

| Acceptance stage | Result |
| --- | --- |
| Shared and mode-specific patches apply | Passed for both modes |
| Offline builds | Passed for both revisions and modes |
| CRC, vermagic, CFI and writable sections | Passed for both revisions and modes |
| First full startup | Failed before service readiness; artifact rejected |
| Revised full startup | Not tested |
| Alloc/read/write/free and user-thread probe | Prepared, not run |
| Calculator Native and Java hooks | Prepared, not run |
| Spawn and cancellation | Prepared, not run |
| Ten attach/unload/detach cycles | Not run |
| Invalid PID, exit race, restart and reconnect | Not run |
| Kernel injection trace plus agent connection | Not established |
| Minimal kernel JS session | Not run |

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
