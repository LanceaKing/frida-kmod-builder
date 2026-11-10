# Fork branch and change audit

This candidate uses one source for GKI 5.10 and the upstream kernel paths. It is not approved for merging into `main`.
The core and Java bridge remain separate repositories because they own different failures.

## Branch decision

| Former core branch | Necessary behavior | Separate maintained branch needed? |
| --- | --- | --- |
| `compat/17.26.2-common` | Shared module and injection fixes | No; these form the common source |
| `compat/17.26.2-kernel-only` | PID 0 sessions without process injection | No; `FRIDA_KERNEL_ONLY` selects it |
| `compat/17.26.2-full-5.10` | GKI 5.10 process ABI | No; ARM64 Linux 5.10 selects it automatically |

The candidate retains the old commits in its ancestry, so existing release pins remain reachable.
The repair branch and all official upstream branches are retained. Obsolete downstream branches were removed.
A single source branch does not establish runtime compatibility with other vendor kernels.
The builder accepts Android 12 and Android 13 GKI 5.10 builds without device or patch-level allowlists. Target headers, configuration, and symbols must still match the running kernel.

## Retained changes and reasons

| Change | Failure or dependency | Decision |
| --- | --- | --- |
| SYSVIPC guard | Headers lack `task_struct.sysvsem` when the option is disabled | Retain the matching configuration guard |
| Trimmed GKI export resolution | The pinned kernel retains required functions without module exports | Retain only the opt-in symbol-resolution glue and its CFI call boundaries |
| Linux entrypoint ABI | C calls a zero-argument function but the old Rust declaration takes arguments | Retain the ABI correction |
| Resident agent configuration | The official entrypoint rejects the sample configuration without `agent.type` | Retain the required field |
| Arm64 image-page classification | The KASLR image enters the vmalloc range, whose page lookup cannot handle its block mappings | Retain image classification before vmalloc lookup and allocation/page failure handling |
| Module notifier cleanup | A callback can outlive unloaded module text | Retain unregister after worker shutdown |
| Android TLS capacity | Bionic accesses offset `0x2fa1`, beyond the old scratch region | Retain the Android-only capacity correction |
| Injection connection cleanup | Failed injections leave pending bootstrap listeners or connections | Retain cancellation and close on failed handoff |
| GKI 5.10 thread ABI adapter | 5.10 thread entry, PID detachment, signal/accounting and ARM64 state differ from the generic implementation | Select the 5.10 ABI automatically, detect optional ARM64 fields, and resolve required functions before enabling injection |
| Allocation credentials | Deferred mmap otherwise uses the worker's credentials for LSM checks | Retain scoped credential borrowing for allocation only |
| Hook rollback and callback drain | Partial installation or active callbacks can outlive process-service teardown | Retain checked installation, rollback, readiness state and drain |
| Bridge replacement-frame lifetime | A callback was freed with a waiting caller; ART can still use cloned methods after JavaScript returns | Retain dispatch removal, resource retention and frame drain |
| Bridge inline redirect restoration | The observed jump address equals original instructions read during a live multi-instruction restoration | Retain ART suspension around global patch restoration |

The bridge rows are the script-unload SIGSEGV fixes. The core rows preserve module/injection behavior; they are not presented as the cause of that SIGSEGV.
See [the compatibility evidence](COMPATIBILITY.md), [TLS diagnosis](SERVER-ANDROID13-TLS.md), and [teardown diagnosis](JAVA-TEARDOWN.md).

## Removed redundancy

- Optional `trace_process_ops` parameter and per-operation logs.
- Duplicate generic/5.10 symbol-resolution code and duplicate proc-cache hook bodies.
- The 5.10 adapter's unused `kmem_cache_free` and `signal_cachep` dependencies; its actual cleanup uses `free_signal_struct`.
- The extra map/unmap preflight before hook installation. The actual installation retains its result checks and rollback.
- Branch-based source selection in the builder. Every module mode pins the same core commit.

Different thread-conversion bodies remain where the kernel ABI actually differs. Combining them without ABI evidence would broaden the change rather than remove redundant behavior.
Upstream updates are the source baseline, separate from the downstream fix review.
Published server and tools assets keep their independently validated pins; this source work does not silently replace them.

## Acceptance boundary

Successful compilation and stress tests are regression evidence, not proof that every line is causally necessary or that all interleavings are covered.
The candidate must pass both Pixel modes, the default Android 14 / 6.1 compile, and device lifecycle/teardown probes before review is concluded.
The default 6.1 build does not establish runtime acceptance on a 6.1 device.

## General GKI validation

The kernel ABI workflow compiles full and kernel-only glue against pinned Android 12/13 GKI 5.10 and 5.15, 6.1, 6.6, 6.12, and 6.18 sources. These are compile checks, not device acceptance or complete module-link checks. CFI and LTO are disabled in this header matrix; the exact-target module builds exercise their actual configuration separately.

The 5.10 process path requires the GKI configuration (`CONFIG_SCHED_AUTOGROUP=n`). Optional MTE, seccomp and cgroup helpers are resolved only when configured. The target headers determine whether secondary TLS and SCTLR state are present. Missing required runtime symbols fail initialization instead of using guessed offsets. This does not promise support for arbitrary vendor modifications.

Validation of the new candidate is pending. Previous Pixel results describe earlier source pins.
