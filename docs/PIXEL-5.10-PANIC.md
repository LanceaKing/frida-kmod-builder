# Pixel 7a Linux 5.10 startup panic

Do not reload artifacts built from `d5f6682` or earlier on this target.
The revised build removes the identified flag conflict.
A later device check confirmed that the module remained loaded and the server opened `/dev/frida`.
Later full-mode revision `0bae5f8` passed a minimal kernel JavaScript session and normal reload.
See the [full-mode acceptance record](PIXEL-5.10-FULL.md) for that result and later App tests with the TLS-corrected server.
Compilation, matching symbol CRCs, and matching vermagic do not establish runtime compatibility.

## Observed failure

The target ran `5.10.157-android13-4-00003-g776d0a76f6aa-ab10208116` with KernelSU runtime jailbreak root.
After `insmod`, Frida started its kernel thread and reported `listening on /dev/frida`.
About one second later, the kernel reported a write to read-only memory and panicked.
The device restarted. The temporary root session ended, and `su` became unavailable.

The retained bugreport contained these relevant fields:

```text
Unable to handle kernel write to read-only memory
ESR = 0x9600004f
WnR = 1
pc : frida_kmod_wake+0x24/0x7c [frida_agent]
lr : g_main_context_iteration+0x3c/0x48 [frida_agent]
Code: ... (b828013f)
```

The instruction `b828013f` is `stadd w8, [x9]`.
Its target register matched the fault address. In the preserved artifact, this instruction increments `frida_wake_seq` in `.bss`.
The preserved local artifact had SHA256 `aa2d4740a10f23b51ed822a5275116fed4958e2beb0cd695caaa2a9f0b176a2d`.
The file retrieved from the phone after reboot contained only zeros, so its bytes cannot establish the exact loaded artifact hash.
Raw device logs remain local and are not part of this public report.

## Cause and correction

The preserved module's `.bss` had ELF flags `0x200003`.
Bit `0x200000` means `SHF_GNU_RETAIN` to the toolchain and `SHF_RO_AFTER_INIT` to this kernel.
The prelinked agent retained `.bss.__lock___libc_recursive_mutex`, a C library lock section.
Kbuild merged it into the module's combined `.bss` and carried the retention bit into that section.
The kernel classified the section as read-only after initialization. The agent then attempted to change its wake counter.
The observed fault, instruction, timing, and target kernel's loader code support this cause.

The target defines the flag in [include/uapi/linux/elf.h](https://android.googlesource.com/kernel/common/+/776d0a76f6aa7c5a92c60afbe886a8e786953199/include/uapi/linux/elf.h).
Its [module loader](https://android.googlesource.com/kernel/common/+/776d0a76f6aa7c5a92c60afbe886a8e786953199/kernel/module.c) classifies flagged sections and protects them after initialization.
The target enables `CONFIG_STRICT_MODULE_RWX=y`.

The builder now clears only `SHF_GNU_RETAIN`, after the agent prelink and before kbuild adds kernel sections.
It preserves all section data, types, sizes, alignment, relocations, and other flags.
The prelink uses no garbage collection. The final kbuild link retains the selected sections without this userspace retention flag.
The builder refuses to apply this operation to an object that contains kernel-owned sections.
Packaging rejects remaining retention flags on writable sections and requires a writable NOBITS `.bss`.
Native kbuild also retains read-only `.text`. The loader classifies executable and read-only sections before its read-only-after-init class.
The validator permits that case and records those sections without changing them.
The correction preserves kernel configuration, CFI, and normal kernel protections for sections that become read-only after initialization.

A separate patch aligns the Linux Rust entry point with its C declaration.
The entry point now obtains the module range through the existing kernel wrapper, instead of reading arguments that the caller never supplied.
This ABI mismatch did not explain the observed wake-counter write fault.

## Validation limits

Regression tests reproduce the conflicting flags and require the old artifact to fail the new section check.
All 28 local tests passed, and [Actions run 42780176775](https://github.com/LanceaKing/frida-kmod-builder/actions/runs/42780176775) built revision `f513722` successfully.
The revised module has SHA256 `ddfece51db48aee0b9b4b5b8e0e107239e355b1384a9a7757d437e515edd72a0` and `.bss` flags `0x3`.
Offline validation matched the target vermagic, all 62 symbol CRC records, all 61 imported symbols, and bundle hashes.
The legacy CFI check function remained present. The apt, source, download, and Rust caches were reused.
The revised artifact still requires further device validation before normal use.
No repeat module load, root reactivation, reboot, or boot-image change formed part of this investigation.
KernelSU runtime jailbreak root must be reactivated through the previously used method after a full reboot.

## Follow-up connection configuration

After the user loaded the revised module, the server rejected the bundled JSON with `Config for 'agent' is invalid`.
The upstream 17.26.2 example omitted `agent.type`, which its parser requires.
Adding `"type": "resident"` let the server start, open `/dev/frida`, and listen on `127.0.0.1:27042`.
The device retained the same boot ID and root access during this check. No module reload was needed.
The build now applies a configuration patch so future bundles include the required field.
