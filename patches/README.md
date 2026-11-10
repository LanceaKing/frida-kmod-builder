# Frida compatibility patches

The builder applies patches only from the directory for the selected Frida version.
Each patch must pass `git apply --check` against that version.
The artifact includes the applied patches, and `build-info.json` records their hashes.

Frida 17.26.2 accesses `task_struct.sysvsem` without testing `CONFIG_SYSVIPC`.
Android GKI build `14219743` disables this option, and its `task_struct` has no such member.
`0001-guard-sysvipc-context.patch` uses the same conditional compilation guard as the kernel header.
It retains the original semaphore code when the option is enabled.
It does not change the target kernel configuration.

The patch modifies Frida source and retains its upstream license.
New Frida releases receive no patch unless a corresponding directory exists here.

The separate `frida-java-bridge/7.0.13/` patch controls Java callback lifetime during script unload on the pinned Android 13 device.
Apply it to the script project's npm dependency, then recompile the scripts.
The kernel builder and server patches do not apply it. See the [teardown instructions and regression test](../docs/JAVA-TEARDOWN.md).

With `agent_mode=kernel-only`, the builder also applies `17.26.2/kernel-only/0002-kernel-session-only.patch` and defines `FRIDA_KERNEL_ONLY`.
This excludes process thread creation and reparenting, which use newer fields and interfaces absent from Android 13 Linux 5.10.
Thread injection returns `-EOPNOTSUPP`. The automatic process-hook installer returns without creating a worker or installing hooks.
Kernel sessions through `/dev/frida` remain enabled. This patch does not change the kernel configuration.

`0003-gki-trimmed-exports.patch` is active only when the builder defines `FRIDA_GKI_TRIMMED_EXPORTS` from a supplied original `System.map`.
Android 13 build 10208116 retains several functions in its image but omits them from its export table.
The patch locates `kallsyms_lookup_name` relative to the exported `kimage_vaddr`, then resolves the FIFO input, reverse symbol lookup, and module notifier functions by name.
The existing ARM64 kernel source defines `kimage_vaddr` as a relocated pointer to `_text`.
Selected glue functions use `__nocfi` for calls to unexported functions that lack legacy CFI jump-table entries, and for the module event callback into the Rust agent.
The build still enables CFI and LTO and checks the original CRCs for every imported export. No runtime address parameter or device setting change is needed.

`0004-linux-entrypoint-abi.patch` aligns the Linux Rust entry point with the C wrapper's zero-argument declaration.
The Rust function obtains the module range through the existing `kernel::own_range()` wrapper.
The macOS entry point keeps its arguments. This corrects a separate ABI defect, not the observed read-only-memory panic.

The builder also removes `SHF_GNU_RETAIN` from the prelinked agent before kbuild links the C wrapper.
This linker flag overlaps Linux's internal `SHF_RO_AFTER_INIT` flag.
The final module must contain no such flags on writable sections, and `.bss` must remain writable, allocated, and NOBITS.
Native kbuild can retain read-only `.text`. The loader classifies code before its read-only-after-init class, so this remains safe.
The kernel still applies its own protections to `.data..ro_after_init` and `__jump_table` during loading.

`0005-resident-agent-config.patch` adds the required `agent.type` value, `resident`, to the upstream Linux module configuration.
Frida 17.26.2 selects the agent configuration class using this field.
Without it, the supplied example fails with `Config for 'agent' is invalid` before opening `/dev/frida`.

`0006-arm64-image-pages.patch` checks the known arm64 kernel image range before the vmalloc range.
Android 5.10 can place its randomized image inside the range accepted by `is_vmalloc_addr()`.
`vmalloc_to_page()` cannot handle the image's block mappings. The patch uses `__pa_symbol()` for image pages and rejects allocation or page lookup failures before `vmap()`.
Both modes use this fix.

`0007-unregister-module-notifier.patch` removes the module event callback during unload.
The exit path first waits for the agent worker to stop, so startup cannot register another callback after cleanup.
It then calls the existing synchronous unregister function before the loader frees the module.
This also covers a worker that stops after an initialization failure.
Both modes use this fix. It does not change CFI enforcement.

`full-5.10/0006-linux-5.10-process-injection.patch` is selected only for the pinned Pixel 7a kernel and Frida 17.26.2.
It uses the 5.10 `kernel_thread` entry convention, then prepares EL0 registers, stack, TLS, user address access, PAC/MTE state, credentials, seccomp state, namespaces, and thread-group membership before returning to userspace.
It uses two-argument `detach_pid`, omits `free_pids` and the absent `quick_threads` field, transfers the user/process accounting, and uses the target kernel's signal cleanup helper.
The creator owns the spawn context until the child completes setup. Failure paths release the target task and mm references.
The target's exec lock excludes an address-space replacement during setup. Exit checks and reference acquisition run under the tasklist, task, and sighand locks.

The full patch checks required symbols, preflights hook page mappings, checks all seven replacement results, and reverts installed hooks on failure.
It exposes the official prctl service only after initialization succeeds. Shutdown closes that service, reverts hooks, waits for active Gum callbacks, and drains the process worker.
`trace_process_ops=1` logs operation names, target PID, result and created TID. It is off by default and does not log memory contents.
The ordinary Android server uses this service for App injection. The Barebone protocol remains unchanged.
Runtime acceptance is tracked separately from compiled features in `build-info.json`.

`17.26.2/server/0001-android-bionic-tls-capacity.patch` applies only to a separate Android server build.
It increases the synthetic TLS block to 64 KiB, so the existing layout reserves 16 KiB for Bionic state.
The target libc accesses offset `0x2fa1` in that area, beyond the original 2 KiB capacity.
The kernel-module builder does not select this server patch.
See the [server build and validation record](../docs/SERVER-ANDROID13-TLS.md) for App tests using the official startup policy helper.

`17.26.2/server/0002-kernel-injection-connection-cleanup.patch` follows the TLS patch in the server build.
It cancels each pending accept/handshake when its injection attempt ends and closes connections whose handshake failed.
Concurrent target-exit probes exposed the missing cleanup as a leaked abstract Unix listener after each failed injection.
The kernel-module builder does not select this patch. The official policy helper, entrypoints, and prctl ABI remain unchanged.
