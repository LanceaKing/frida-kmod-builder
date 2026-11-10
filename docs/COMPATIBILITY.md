# Frida fork compatibility changes

All compatibility changes live in the official-repository forks. The builder selects fixed commits from the [source lock](../sources/frida-17.26.2.json).
The old patch files remain available in Git history. Builds and npm installs use the fork sources directly.
Artifacts include `frida-sources.json`. `build-info.json` records the selected core commit and source-lock hash.

Before removing the 11 local patch files, each patch was applied to its corresponding fork commit's parent.
Every resulting Git tree matched that fork commit exactly. These historical commits remain reachable from the unified core history. The current module modes share one pinned core commit.

| Change | Scope | Fork commit |
| --- | --- | --- |
| SYSVIPC guard | All core profiles | [`050d2e6`](https://github.com/LanceaKing/frida-core/commit/050d2e6009bca27102185969ca6d829e9686c3fc) |
| Trimmed GKI exports | All core profiles | [`ca8a410`](https://github.com/LanceaKing/frida-core/commit/ca8a410dd134a42acb7c3dc53320080f2dc7b4df) |
| Linux entrypoint ABI | All core profiles | [`42f1e2c`](https://github.com/LanceaKing/frida-core/commit/42f1e2c7c86a3c6f7d73228e3b0667dd62ece2d0) |
| Resident agent configuration | All core profiles | [`ffe5a54`](https://github.com/LanceaKing/frida-core/commit/ffe5a5433067aa91b7dfe949630f4dd9c204b01c) |
| Arm64 image pages | All core profiles | [`321ae17`](https://github.com/LanceaKing/frida-core/commit/321ae177e51ba71aa2697849d9f48e0459b22d65) |
| Module notifier cleanup | All core profiles | [`2420e9e`](https://github.com/LanceaKing/frida-core/commit/2420e9e6f52c5e36ceaae6b6307a7b0093964e57) |
| Linux 5.10 process injection | full-5.10 | [`32e5a83`](https://github.com/LanceaKing/frida-core/commit/32e5a832a5fd837456f6341f53ec075925683925) |
| Kernel-only mode | kernel-only | [`7a888d5`](https://github.com/LanceaKing/frida-core/commit/7a888d58a69b0141969762483af214c3ac43c2ff) |
| Android Bionic TLS capacity | All core profiles | [`9861f45`](https://github.com/LanceaKing/frida-core/commit/9861f4546a5bd42369416da1efb4d021878e35e0) |
| Injection connection cleanup | All core profiles | [`fdc9da5`](https://github.com/LanceaKing/frida-core/commit/fdc9da5ab29ac5bbe32c8b68ff7d3cc43c3ae230) |
| Java replacement-frame drain | Java bridge | [`70b66c7`](https://github.com/LanceaKing/frida-java-bridge/commit/70b66c7a60902b4f5c83f7a9f5e55c9c952bbf4e) |

The bridge also includes the later [ART inline-patch restoration fix](JAVA-TEARDOWN.md#inline-art-patch-restoration-race).
The source lock includes that follow-up. See [fork provenance and validation](FORKS.md) for the tested artifacts.

## Compatibility behavior

Frida 17.26.2 accesses `task_struct.sysvsem` without testing `CONFIG_SYSVIPC`.
Android GKI build `14219743` disables this option, and its `task_struct` has no such member.
[SYSVIPC guard](https://github.com/LanceaKing/frida-core/commit/050d2e6009bca27102185969ca6d829e9686c3fc) uses the same conditional compilation guard as the kernel header.
It retains the original semaphore code when the option is enabled.
It does not change the target kernel configuration.

The patch modifies Frida source and retains its upstream license.
New Frida releases require an explicit source lock; builds never fall back to unpatched upstream sources.

The separate [Java replacement-frame drain](https://github.com/LanceaKing/frida-java-bridge/commit/70b66c7a60902b4f5c83f7a9f5e55c9c952bbf4e) change controls Java callback lifetime during script unload on the pinned Android 13 device.
Install the pinned fork bridge in the script project, then recompile the scripts.
The kernel builder and server patches do not apply it. See the [teardown instructions and regression test](JAVA-TEARDOWN.md).

The shared core source includes [Kernel-only mode](https://github.com/LanceaKing/frida-core/commit/7a888d58a69b0141969762483af214c3ac43c2ff) and defines `FRIDA_KERNEL_ONLY`.
This excludes process thread creation and reparenting, which use newer fields and interfaces absent from Android 13 Linux 5.10.
Thread injection returns `-EOPNOTSUPP`. The automatic process-hook installer returns without creating a worker or installing hooks.
Kernel sessions through `/dev/frida` remain enabled. This patch does not change the kernel configuration.

[Trimmed GKI exports](https://github.com/LanceaKing/frida-core/commit/ca8a410dd134a42acb7c3dc53320080f2dc7b4df) is active only when the builder defines `FRIDA_GKI_TRIMMED_EXPORTS` from a supplied original `System.map`.
Android 13 build 10208116 retains several functions in its image but omits them from its export table.
The patch locates `kallsyms_lookup_name` relative to the exported `kimage_vaddr`, then resolves the FIFO input, reverse symbol lookup, and module notifier functions by name.
The existing ARM64 kernel source defines `kimage_vaddr` as a relocated pointer to `_text`.
Selected glue functions use `__nocfi` for calls to unexported functions that lack legacy CFI jump-table entries, and for the module event callback into the Rust agent.
The build still enables CFI and LTO and checks the original CRCs for every imported export. No runtime address parameter or device setting change is needed.

[Linux entrypoint ABI](https://github.com/LanceaKing/frida-core/commit/42f1e2c7c86a3c6f7d73228e3b0667dd62ece2d0) aligns the Linux Rust entry point with the C wrapper's zero-argument declaration.
The Rust function obtains the module range through the existing `kernel::own_range()` wrapper.
The macOS entry point keeps its arguments. This corrects a separate ABI defect, not the observed read-only-memory panic.

The builder also removes `SHF_GNU_RETAIN` from the prelinked agent before kbuild links the C wrapper.
This linker flag overlaps Linux's internal `SHF_RO_AFTER_INIT` flag.
The final module must contain no such flags on writable sections, and `.bss` must remain writable, allocated, and NOBITS.
Native kbuild can retain read-only `.text`. The loader classifies code before its read-only-after-init class, so this remains safe.
The kernel still applies its own protections to `.data..ro_after_init` and `__jump_table` during loading.

[Resident agent configuration](https://github.com/LanceaKing/frida-core/commit/ffe5a5433067aa91b7dfe949630f4dd9c204b01c) adds the required `agent.type` value, `resident`, to the upstream Linux module configuration.
Frida 17.26.2 selects the agent configuration class using this field.
Without it, the supplied example fails with `Config for 'agent' is invalid` before opening `/dev/frida`.

[Arm64 image pages](https://github.com/LanceaKing/frida-core/commit/321ae177e51ba71aa2697849d9f48e0459b22d65) checks the known arm64 kernel image range before the vmalloc range.
Android 5.10 can place its randomized image inside the range accepted by `is_vmalloc_addr()`.
`vmalloc_to_page()` cannot handle the image's block mappings. The patch uses `__pa_symbol()` for image pages and rejects allocation or page lookup failures before `vmap()`.
Both modes use this fix.

[Module notifier cleanup](https://github.com/LanceaKing/frida-core/commit/2420e9e6f52c5e36ceaae6b6307a7b0093964e57) removes the module event callback during unload.
The exit path first waits for the agent worker to stop, so startup cannot register another callback after cleanup.
It then calls the existing synchronous unregister function before the loader frees the module.
This also covers a worker that stops after an initialization failure.
Both modes use this fix. It does not change CFI enforcement.

[Linux 5.10 process injection](https://github.com/LanceaKing/frida-core/commit/32e5a832a5fd837456f6341f53ec075925683925) is selected only for the pinned Pixel 7a kernel and Frida 17.26.2.
It uses the 5.10 `kernel_thread` entry convention, then prepares EL0 registers, stack, TLS, user address access, PAC/MTE state, credentials, seccomp state, namespaces, and thread-group membership before returning to userspace.
It uses two-argument `detach_pid`, omits `free_pids` and the absent `quick_threads` field, transfers the user/process accounting, and uses the target kernel's signal cleanup helper.
The creator owns the spawn context until the child completes setup. Failure paths release the target task and mm references.
The target's exec lock excludes an address-space replacement during setup. Exit checks and reference acquisition run under the tasklist, task, and sighand locks.

The current candidate checks required symbols, checks all seven replacement results, and reverts installed hooks on failure. The redundant hook-page preflight has been removed.
It exposes the official prctl service only after initialization succeeds. Shutdown closes that service, reverts hooks, waits for active Gum callbacks, and drains the process worker.
The unified source omits the optional `trace_process_ops` diagnostic parameter. Older stage-triggered race records refer to the previous tested source.
The ordinary Android server uses this service for App injection. The Barebone protocol remains unchanged.
Runtime acceptance is tracked separately from compiled features in `build-info.json`.

[Android Bionic TLS capacity](https://github.com/LanceaKing/frida-core/commit/9861f4546a5bd42369416da1efb4d021878e35e0) applies only to a separate Android server build.
It increases the synthetic TLS block to 64 KiB, so the existing layout reserves 16 KiB for Bionic state.
The target libc accesses offset `0x2fa1` in that area, beyond the original 2 KiB capacity.
This change affects the Android server, not the kernel module.
See the [server build and validation record](SERVER-ANDROID13-TLS.md) for App tests using the official startup policy helper.

[Injection connection cleanup](https://github.com/LanceaKing/frida-core/commit/fdc9da5ab29ac5bbe32c8b68ff7d3cc43c3ae230) follows the TLS patch in the server build.
It cancels each pending accept/handshake when its injection attempt ends and closes connections whose handshake failed.
Concurrent target-exit probes exposed the missing cleanup as a leaked abstract Unix listener after each failed injection.
This change affects the Android server, not the kernel module. The official policy helper, entrypoints, and prctl ABI remain unchanged.
