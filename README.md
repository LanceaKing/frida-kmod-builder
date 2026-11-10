# Frida kernel module builder

[中文说明](docs/README.zh-CN.md) · [Run a build](https://github.com/LanceaKing/frida-kmod-builder/actions/workflows/build.yml)

Do not load artifacts from commit `d5f6682` or earlier on the Pixel 7a Android 13 preset.
A device test caused a kernel panic during agent startup.
The builder now removes the conflicting ELF flag. See the [pinned-device acceptance record](docs/PIXEL-5.10-FULL.md) for subsequent validation.
Read the [incident report](docs/PIXEL-5.10-PANIC.md) before using this preset.

Build `frida-agent.ko` for an Android arm64 kernel with GitHub Actions.
Select the kernel family, complete kernel release, Frida version, and source artifacts in the **Run workflow** form.
The workflow builds a [pinned fork](docs/FORKS.md) of the official Frida Barebone Linux agent.

KernelSU can provide the root access needed to load the module.
The module must match the running kernel, including its configuration and symbol versions.
The workflow preserves the supplied kernel configuration and checks the module version string before upload.
A successful build does not establish that the module loads or runs correctly on a device.

## Build a module

1. Read the complete kernel release from your device with `adb shell uname -r`.
2. Open **Actions → Build Frida kernel module → Run workflow**.
3. Set `kernel_release` to the complete output from step 1.
4. Select the kernel family, or keep `auto`.
5. Enter any source overrides required by your kernel.
6. Start the workflow and download the module artifact from the completed run.

The default values use the kernel build in Frida's upstream example.
They are a build example, not a device recommendation.
For a standard Android CI release, the workflow extracts the source commit and build ID from `-gCOMMIT-abBUILD`.
For a vendor kernel, provide its exact source revision and prepared artifacts.

## Inputs

| Input | Purpose |
| --- | --- |
| `kernel_release` | Complete `uname -r` value. Required. |
| `kernel_family` | Consistency check for the Android generation and kernel branch. `auto` detects them. |
| `frida_version` | Version with a committed fork source lock. Currently `17.26.2`; also selects the official GumJS devkit. |
| `kernel_repository` | HTTPS Git URL for the kernel source. Default: Google's `kernel/common`. |
| `kernel_ref` | Exact commit or tag. Empty extracts the commit from `kernel_release`. |
| `android_ci_build` | Android CI build ID. Empty extracts the `-ab` suffix. |
| `android_ci_target` | Android CI target. Default: `kernel_aarch64`. |
| `prepare_url` | Public HTTPS URL for a prepared kernel archive. Set with `symvers_url`. |
| `symvers_url` | Public HTTPS URL for `Module.symvers` from the same build. |
| `kernel_image_url` | Original `Image` or `Image.lz4` URL for rebuilding an expired prepared tree. Set with `symvers_url`; leave `prepare_url` empty. |
| `kernel_config_sha256` | SHA256 of the decompressed device configuration. Required in image preparation mode. |
| `system_map_url` | Original `System.map` for Linux 5.10 GKI builds that trim kprobe exports. Works with prepared artifacts or image preparation. Both modes use the same bootstrap. |
| `agent_mode` | `full` or `kernel-only`. The latter supports PID 0 sessions and disables process injection and automatic process hooks. |
| `kernel_clang_url` | `auto`, `system`, or an HTTPS compiler archive URL. See below. |
| `rust_toolchain` | Rust version or dated nightly for the agent. Default: `1.99.1`. |
| `module_name` | Output name without `.ko`. Default: `frida-agent`. |
| `include_server` | Include the matching Android arm64 `frida-server`. Default: enabled. |

The family list is an input selector, not a list of tested kernels.
Selecting a family does not download a generic replacement kernel.
Changing only the version string cannot make a module compatible with a different build.
Kernel feature and page-size choices come from the supplied `.config` file.

## Kernel artifacts and compilers

A prepared kernel archive contains the configured build tree needed by external modules.
Place `.config`, `Makefile`, `include/generated/utsrelease.h`, and prepared build tools at the archive root.
Supply the original `Module.symvers` separately. It contains symbol version checksums.
The script requires these files even when a kernel uses the same source branch as another build.

The runner is x86-64 Ubuntu 24.04. Prepared tools must run on x86-64 Linux.
The kernel must enable `CONFIG_ARM64`, `CONFIG_MODULES`, `CONFIG_KPROBES`, and `CONFIG_KALLSYMS_ALL`.
This workflow produces unsigned modules. It rejects `CONFIG_MODULE_SIG_FORCE=y`.
Kernel versions, vendor changes, and upstream Frida support can impose further requirements.

The agent uses LLVM 19 and the `none-arm64-softfloat_nopic` SDK selected by Frida's pinned `releng` revision.
The kernel wrapper uses a separate compiler.
With `kernel_clang_url=auto`, the script reads the Android compiler revision from `.config`.
It downloads that compiler from the corresponding `androidN-release` prebuilt branch.
If that branch lacks the revision, supply the exact compiler archive URL yourself.
The archive must contain `bin/clang` at its root.

`kernel_clang_url=system` selects the runner's LLVM 19 for the kernel wrapper too.
Use it only when LLVM 19 is suitable for the target kernel.
The build fails if kbuild changes the supplied `.config` or the output version string differs.
The workflow does not change CFI, page size, module signatures, or symbol-version checks to make a build pass.

When Android CI artifacts have expired, image preparation can restore the generated headers from the exact source, original kernel image, embedded configuration, and original symbol CRC table.
The builder verifies the image banner, configuration hash, and source commit before running `olddefconfig` and `modules_prepare`.
It relocates `CONFIG_UNUSED_KSYMS_WHITELIST` to a runner-local path and rejects any other option change.
Gitiles blob URLs ending in `?format=TEXT` are decoded from base64 automatically.
The [Pixel 7a Android 13 preset](presets/pixel-7a-android13-5.10.json) uses this path for build `10208116`.

The original [kernel-only preset](presets/pixel-7a-android13-5.10.json) remains available for `-p 0` sessions.
It does not install automatic process hooks and returns `EOPNOTSUPP` for process thread creation.
The separate [full preset](presets/pixel-7a-android13-5.10-full.json) adds a compatibility backport for this exact kernel and Frida 17.26.2.
It remains experimental. The pinned device passed the bounded regression matrix with the server patches and the separate [Java bridge teardown patch](docs/JAVA-TEARDOWN.md).
Install the pinned fork bridge in each script project and recompile its Java scripts. The [bundled CLI](docs/FORKS.md) bundles this bridge. The server rebuild alone does not contain it.
The [patched server](docs/SERVER-ANDROID13-TLS.md) corrects TLS capacity and a connection leak during failed injection.
Read the [acceptance record](docs/PIXEL-5.10-FULL.md) before loading it.
Other 5.10 kernels and 32-bit Apps are outside the reviewed scope.
The preset also provides the original `System.map`. The builder derives the offset of `kallsyms_lookup_name` from `_text`; at load time, the exported `kimage_vaddr` supplies the relocated image base.
This handles trimmed GKI exports without adding invented symbol CRCs or requiring a runtime address parameter.
The glue functions that call unexported targets use local `__nocfi` annotations because legacy CFI may omit jump-table entries for those targets. The kernel CFI, LTO, and MODVERSIONS configuration remains enabled.

## Output and installation

The module artifact contains the `.ko`, `linux-kmod.json`, `modinfo.txt`, `build-info.json`, `SHA256SUMS`, and installation instructions.
It also contains `frida-server` when requested.
`build-info.json` records source commits, downloaded file hashes, compiler versions, and the Actions run URL.
The separate diagnostics artifact contains resolved inputs and logs, including on failed runs.
Use public download URLs. Actions inputs and diagnostics are visible in this public repository.

Follow [the installation instructions](docs/INSTALL.md) after downloading the artifact.
The workflow performs no device installation or boot image flashing.
Artifacts expire after 30 days. Diagnostics expire after 14 days.

## Build cache

Actions caches apt package downloads, kernel Git objects, downloaded source artifacts and compiler archives, the Frida SDK, Rust toolchains, and Cargo dependencies.
Each downloaded file is keyed by its full URL and checked against its recorded SHA256 before reuse. Corrupt entries are downloaded again.
The environment cache key includes the kernel source and artifact inputs and the Frida version. Apt and Rust keys also rotate weekly so package updates can enter the cache.
Prepared kernel headers and pinned fork source are rebuilt each run; configuration, source, and output checks still run on a cache hit.
The apt and source caches are saved before compilation, so a later compile failure does not discard a prepared environment. Rust and Cargo caches are also saved after a compile failure.
The first run fills the caches. Later runs show `Cache restored` and `Download cache hit` in the logs. GitHub may evict unused caches; a miss only causes a download.

## Development and sources

Run `python3 -m unittest discover -s tests -v` to exercise input validation and kernel compatibility checks.
The four stages in `scripts/build.py` are `configure`, `prepare`, `build`, and `package`.
Each input also has an uppercase environment variable for local Linux builds.
Temporary files stay in `.work/`, and packaged files stay in `dist/`.

The Actions form takes inspiration from [WildKernels/GKI_KernelSU_SUSFS](https://github.com/WildKernels/GKI_KernelSU_SUSFS).
This repository does not copy its kernel patches or build a replacement kernel.
The build follows [Frida's Linux module instructions](https://github.com/frida/frida-core/blob/17.26.2/src/barebone/agent/linux/README.md).
The builder uses [pinned official forks](docs/FORKS.md). Each artifact records the exact commits in `frida-sources.json`. The [compatibility change index](docs/COMPATIBILITY.md) links every former local patch to its owning fork commit.
Frida and the Linux kernel retain their upstream licenses. See [third-party notices](THIRD_PARTY_NOTICES.md).
