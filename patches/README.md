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
