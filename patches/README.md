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
