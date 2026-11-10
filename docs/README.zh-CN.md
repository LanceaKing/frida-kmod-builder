# Frida 内核模块构建

本仓库通过 GitHub Actions 为 Android arm64 构建 `frida-agent.ko`。
在 **Actions → Build Frida kernel module → Run workflow** 中填写参数即可启动。
构建完成后，在该次运行页面的 **Artifacts** 中下载产物。

## 选择目标内核

先在电脑执行：

```sh
adb shell uname -r
```

将完整输出填入 `kernel_release`。`kernel_family` 可保持 `auto`，也可手动选择对应分支。
标准 GKI 版本中的 `-g提交号-ab构建号` 用于定位源码和 Android CI 产物。
`kernel_ref` 和 `android_ci_build` 可以覆盖自动识别结果。
仓库默认值来自 Frida 官方示例，不代表你的设备版本。

只有 `5.10`、`6.1` 或 Android 版本号不够。模块还依赖完整构建版本、内核配置和符号 CRC。
分支下拉框表示可选目标，不表示所有分支都经过验证。
页大小、CFI 等内核配置直接使用原构建的 `.config`，构建器不会修改这些选项。

## 使用厂商或自定义内核

提供 `kernel_repository`、`kernel_ref`、`prepare_url` 和 `symvers_url`。
后两个 URL 必须同时填写，并且指向同一次内核构建的准备包与 `Module.symvers`。
准备包根目录需要包含 `.config`、`Makefile`、生成的头文件和 x86-64 Linux 构建工具。
只提供内核源码或配置文件不能代替这两个构建产物。

`kernel_clang_url=auto` 从 `.config` 读取 Android Clang 修订号，并从对应 Android 发布分支下载。
若原编译器不在该分支，填入正确的编译器 tar 包 URL。解压后根目录应包含 `bin/clang`。
`system` 使用 LLVM 19，仅适用于兼容该编译器的目标。
Frida agent 部分独立使用 LLVM 19，以满足 soft-float 构建要求。

## 已过期的 Android CI 构建

如果准备包已过期，可提供原始 `Image` 或 `Image.lz4` 的 `kernel_image_url`、同次构建的 `symvers_url`，以及设备解压后配置的 `kernel_config_sha256`，并留空 `prepare_url`。
构建器会核对镜像版本、配置哈希和源码提交，再运行 `olddefconfig` 与 `modules_prepare` 恢复生成文件。
只允许迁移 `CONFIG_UNUSED_KSYMS_WHITELIST` 的文件路径；其他配置变化会使构建失败。

[Pixel 7a Android 13 参数](../presets/pixel-7a-android13-5.10.json)对应构建号 `10208116`。
该版本的官方镜像配置与实测设备配置一致。
Linux 5.10 缺少新版 Frida 的进程线程注入接口，因此该预设选择 `agent_mode=kernel-only`。
连接时使用 `-p 0`。进程线程注入返回 `EOPNOTSUPP`，自动进程 hook 关闭。
该预设还提供同次构建的 `system_map_url`。构建器从原始 `System.map` 计算符号查询函数相对 `_text` 的偏移，模块通过已导出的 `kimage_vaddr` 获取运行时基址。
这解决了 GKI 未导出 kprobe 等函数的问题，不需要手工填写运行时地址，也不会伪造符号 CRC。
调用未导出函数的局部适配函数使用 `__nocfi`，因为旧版 CFI 可能未为这些目标生成跳转表项；内核的 CFI、LTO 和 MODVERSIONS 配置保持启用。

## 调整其他参数

`frida_version` 同时选择源码、GumJS devkit 和 server 的版本。
`rust_toolchain` 选择 Rust 编译器。`module_name` 修改 `.ko` 名称。
`include_server` 决定是否将同版本 Android arm64 server 放入产物。
完整参数表见[英文 README](../README.md#inputs)。

产物包含模块、连接配置、构建来源记录、SHA-256 和安装说明。
失败时可下载 diagnostics 查看日志。
这是公开仓库，只填写可公开的下载地址。
构建会检查 ELF 架构、版本字符串及配置是否变化，但不会在手机上加载模块。
Frida 17.26.2 的 `CONFIG_SYSVIPC` 条件编译修复会随产物一起提供，详见[补丁说明](../patches/README.md)。
安装流程见 [INSTALL.md](INSTALL.md)。

## 构建缓存

Actions 缓存 apt 安装包、内核 Git 对象、下载的内核产物和 Clang 工具链、Frida SDK、Rust 工具链及 Cargo 依赖。
下载缓存按完整 URL 区分，每次复用前检查 SHA-256；文件损坏时重新下载。
环境缓存键包含内核源码、产物参数和 Frida 版本。apt 与 Rust 缓存每周轮换，以纳入依赖更新。
内核生成头文件和打过补丁的 Frida 源码仍会重新生成，配置与 ABI 检查不会跳过。
apt 和源码缓存会在编译前保存，后续编译失败不会丢失已准备好的环境；Rust 与 Cargo 缓存也会在编译失败后保存。
首次运行填充缓存，后续运行可在日志中看到 `Cache restored` 和 `Download cache hit`。GitHub 清理缓存后，工作流会自动重新下载。
