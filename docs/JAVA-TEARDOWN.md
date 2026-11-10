# Java hook teardown on Android 13

The teardown patch targets `frida-java-bridge` 7.0.13 on the pinned Android 13 arm64 device.
It leaves Frida's server entrypoint, SELinux helper, kernel module, and injection protocol unchanged.
Frida 17 loads this Java bridge from the script project. Rebuilding the server alone does not apply this patch to user scripts.

## Failure and lifetime correction

The original script removes Java method replacements during its weak-reference cleanup.
It can then release a `NativeCallback` while a target thread waits to acquire the JavaScript lock.
The callback takes its JavaScript reference only after it acquires that lock.
A diagnostic build reproduced the invalid release in Settings and in a four-thread Calculator workload.
The diagnostic reported `freeing NativeCallback ... with 1 waiting calls`.

Other Settings crashes occurred in ART's JNI return path.
ART still needs the cloned replacement method after its JavaScript callback returns.
Waiting only for JavaScript callbacks does not cover that native return path.

The patch separates method removal from resource release.
It retains the replacement callbacks and cloned methods, removes their dispatch entries, and pins the script against destruction.
It then suspends ART threads and walks their stacks under the ART thread-list lock.
The native walk retains the JavaScript lock throughout the inspection.
If a frame still references a replacement, it resumes the threads and repeats the inspection later.
It releases the resources and unpins the script only after those frames disappear.
The timer schedules another inspection. A fixed elapsed delay never authorizes resource release.

This patch covers script unload. It does not change standalone assignments to `method.implementation = null` during a running script.
The new inspection uses private ART exports. Other Android versions and architectures need separate validation.
The existing JVM and Dalvik disposal paths remain unchanged.

The thread-list lock requirement comes from [ART's `ThreadList::ForEach` declaration](https://android.googlesource.com/platform/art/+/refs/tags/android-13.0.0_r75/runtime/thread_list.h#140).
The inspection reads each frame's method through [ART's `StackVisitor::GetMethod`](https://android.googlesource.com/platform/art/+/refs/tags/android-13.0.0_r75/runtime/stack.cc#104).

## Inline ART patch restoration race

Fork migration testing exposed another unload race on 2026-11-10. Settings PID 9897 exited with SIGSEGV after script unload. Its `x8` jump target was `0x90003408540006c0`; the fault address had the top byte removed. These eight bytes exactly match the original instructions at `libart.so` offsets `0x395650` and `0x395654`, inside `StackVisitor::WalkStack` on the tested ART build (`289d75599f6112d5757113220599e90b`).

The arm64 inline redirect stores its trampoline address at that location. Restoring the original multi-instruction region while a managed thread executes the redirect can make the thread load instruction bytes as its branch address. Draining replacement JNI frames does not protect unrelated stack walks.

The fork wraps global patch restoration in ART `SuspendAll` / `ResumeAll`. It restores the redirects and releases their trampolines while managed threads are suspended. The existing non-ART path is unchanged. This is a ten-line addition to `lib/android.js`; it preserves the earlier replacement-frame drain.

## Install the fork bridge

Run these commands from the builder repository on the host:

```sh
npm ci --prefix tests/device
```

For a separate script project, pin the fork commit and keep its lock file:

```sh
npm install --save-exact https://codeload.github.com/LanceaKing/frida-java-bridge/tar.gz/1245d0bbd84f68f3337e9f7a82316cef8d42294d
```

Recompile that project's scripts after installation. Clean installs retain the fix.
The [fork tools wheel](FORKS.md) also bundles this bridge for the standard CLI.
Keep the [official server startup](INSTALL.md#full-mode-android-app-connection).

## Reproduce the concurrent unload test

`TeardownWorkload.java` runs four Java threads independently of the Frida script.
They repeatedly call `System.identityHashCode` through reflection and compare its return value with the original value.
They also capture Java stack traces to exercise ART inline redirects during unload.
The host unloads the hook while those threads run, observes process survival, and reads their final result.
A unique output path prevents a previous run from supplying a false success.
The runner fails on a JavaScript error, a changed return value, an early process exit, or a cleanup timeout.

Build the fixture with a JDK and Android SDK build-tools. Set `ANDROID_SDK_ROOT` to the installed SDK directory.
The device run used build-tools 36.1.0 and a Java 8 target.
Run these commands from the builder repository:

```sh
mkdir -p .work/teardown/classes .work/teardown/dex
javac --release 8 -d .work/teardown/classes tests/device/TeardownWorkload.java
"$ANDROID_SDK_ROOT/build-tools/36.1.0/d8" --min-api 26 --output .work/teardown/dex .work/teardown/classes/re/frida/test/*.class
uv run --no-project --with frida==17.26.2 python tests/device/teardown-session.py \
  --serial DEVICE_SERIAL --dex .work/teardown/dex/classes.dex \
  --rounds 50 --output .work/teardown/results.json
```

The runner restarts Calculator before each round. Use `--package` and `--activity` to select another test App.
It requires the existing root connection and an enforcing device. It stops if the boot ID changes.
Capture the crash log, tombstones, kernel log, policy hash, and server resources separately before and after the matrix.

## Validation status

The unpatched diagnostic build failed on Settings spawn round 7 and concurrent Calculator round 39.
A separate instrumented Settings run identified the callback address and caught its release with a waiting caller.
The initial candidate passed 30 Settings spawns. That run preceded the added thread-list lock and is preliminary evidence only.
The final patch passed the following matrix on 2026-11-10 with the non-diagnostic server:

| Probe | Passed |
| --- | --- |
| Four-thread concurrent Java hook unload | 50 rounds, correct return values, and survival after unload |
| Repeated Native/Java attach and detach | 40 sessions across Calculator, Clock, Settings, and DocumentsUI |
| Spawn, resume, hook unload, and survival | 42 sessions, including 30 consecutive Settings and 10 Calculator spawns |
| Cancel before resume | Calculator, Clock, and Settings |
| Exit during kernel injection | Five attempts at each of four stages, with 20 successful fresh-process recoveries |
| Invalid PID, exited PID, and active target termination | Expected errors and detach event |
| Barebone PID 0 JavaScript | Expected result, unload, and detach |

All ordinary detach checks observed survival for three seconds.
The 20 interrupted injections returned within 10.48 seconds without external cancellation.
They returned 15 `NotSupportedError`, three `ProcessNotRespondingError`, and two `TransportError` results.
No bootstrap listener remained after any attempt. Server FD counts before attempts varied from 65 to 74.

The final audit found no new crash-buffer records, changed tombstones, kernel warnings, Oops, panic, or reboot.
Root, global Enforcing state, the boot ID, and the policy hash remained unchanged.
Both official server entrypoints remained available. The diagnostic server was stopped before the final matrix.
The deployed server SHA256 remained `77eecc8c7145793cd162bef0cfdca5ce0e044c46782935a51a09c8d91800b813`.

The patch applies to a clean bridge 7.0.13 package and reproduces all three tested source files exactly.
The 30 repository tests, Python and JavaScript syntax checks, Java fixture compilation, Android C syntax check, and workflow lint passed locally.
CI installs the pinned fork bridge from the lock file and checks its JavaScript syntax.
These results cover the stated device and script-unload path. They do not establish every possible interleaving or compatibility with another ART build.

Local diagnosis evidence is in `.work/teardown-investigation-20261110/`.
Candidate evidence is in `.work/teardown-candidate-20261110/`.
Final acceptance evidence is in `.work/teardown-acceptance-20261110/`.
The repository excludes device logs and binaries.

## Fork follow-up acceptance

The [fork migration record](FORKS.md) supersedes the earlier acceptance for current installs. The ten-line inline-restoration correction passed 50 concurrent unloads with Java stack walking on the fork full module and 30 Settings spawns using the final pinned bridge, including 10 on that module. No new tombstone appeared after the fix. The server entrypoints and SELinux helper remain unchanged.
