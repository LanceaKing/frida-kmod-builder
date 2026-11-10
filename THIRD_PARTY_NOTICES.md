# Third-party components

The scripts download pinned forks and upstream dependencies during each build.
Fork changes retain the upstream licenses; see [source provenance](docs/FORKS.md).
This repository does not include their source or binary files.
The license for this repository applies only to its original scripts and documentation.

- [Frida Core](https://github.com/frida/frida-core): wxWindows Library Licence 3.1 terms in the upstream repository.
- [Frida Gum](https://github.com/frida/frida-gum): wxWindows Library Licence 3.1 terms in the upstream repository.
- [Frida Java bridge](https://github.com/frida-packages/frida-java-bridge): LGPL-2.0 with the wxWindows exception, as declared by package 7.0.13. The bridge patch retains those terms.
- [Linux](https://android.googlesource.com/kernel/common): GPL-2.0 and per-file terms in the selected source tree.
- [Android Clang prebuilts](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86): upstream LLVM and bundled component notices.
- [Frida SDK dependencies](https://github.com/frida/releng): each dependency retains its upstream license.

Build artifacts retain all applicable upstream license obligations.
Source revisions and download locations are recorded in `build-info.json`.
