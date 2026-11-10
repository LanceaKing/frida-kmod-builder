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
