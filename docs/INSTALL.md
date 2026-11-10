# Load the Frida kernel module

Do not reload the original Pixel 7a Android 13 artifact after a panic.
Builds from `d5f6682` and earlier contain an ELF flag that can make mutable memory read-only.
The revised build removes that flag. Later full-mode tests passed on the pinned device.
Read the [incident report](PIXEL-5.10-PANIC.md) and [current acceptance record](PIXEL-5.10-FULL.md) first.

Use a rooted Android arm64 device with the exact kernel recorded in `build-info.json`.
KernelSU can provide root access, including in its runtime jailbreak mode.
The root profile must permit module loading and access to `/dev/frida`.
A completed Actions build does not prove that this module works on your device.

## Load and connect

Run these commands on the computer connected to the device.
Replace `frida-agent.ko` if you selected a different module name.
If the artifact does not include `frida-server`, obtain the pinned [fork release](FORKS.md) and verify both server hashes in `frida-sources.json`.
The Pixel presets include this server by default.

```sh
shasum -a 256 -c SHA256SUMS
adb shell uname -r
adb shell su -c id
adb push frida-agent.ko frida-server linux-kmod.json /data/local/tmp/
adb shell "su -c 'chmod 755 /data/local/tmp/frida-server'"
adb shell "su -c 'insmod /data/local/tmp/frida-agent.ko'"
adb shell "su -c 'ls -l /dev/frida'"
adb shell "su -c 'dmesg | tail -n 60'"
```

The agent reports `frida: listening on /dev/frida` when it is ready.
The connection configuration must include `agent.type`:

```json
{
  "agent": {
    "type": "resident",
    "transport": {
      "type": "device",
      "path": "/dev/frida"
    }
  }
}
```

If the server reports `Config for 'agent' is invalid`, replace the older JSON with this configuration.
This configuration change does not require reloading the module.
Start the server in the foreground and keep that terminal open:

```sh
adb shell "su -c 'FRIDA_BAREBONE_CONFIG=/data/local/tmp/linux-kmod.json /data/local/tmp/frida-server --device=barebone -l 127.0.0.1:27042'"
```

Open a second terminal on the computer. Use a Frida client with the matching Frida version:

```sh
adb forward tcp:27042 tcp:27042
frida -H 127.0.0.1:27042 -p 0
```

The server exposes the kernel session through the local ADB connection.
If module loading fails, read the kernel log before changing inputs.
If the device reboots, stop loading the module and collect the retained crash log with `adb bugreport`.
If access to `/dev/frida` fails, inspect the server's SELinux domain and denial messages.

## Stop the session

Close the Frida client and stop the server before unloading the module.
Replace the module name below if you selected a custom name.
The commands operate on the running kernel and do not install a boot image.

```sh
adb shell "su -c 'rmmod frida-agent'"
adb forward --remove tcp:27042
```

A full reboot removes a manually loaded module.
KernelSU jailbreak mode can also require reactivation after a full reboot.
For upstream details, read the [Frida Linux module guide](https://github.com/frida/frida-core/blob/17.26.2/src/barebone/agent/linux/README.md).

## Full mode: Android App connection

The Pixel 7a full preset is experimental. Check [its acceptance record](PIXEL-5.10-FULL.md) first.
Revision `0bae5f8` passes a minimal kernel session and normal reload on the pinned device.
The unchanged Frida 17.26.2 server crashes during App attach because its synthetic Bionic TLS area is too small.
The [rebuilt Android server](SERVER-ANDROID13-TLS.md) corrects that capacity error.
With official server startup, Native/Java callbacks and bounded injection tests work on this device.
Install the [pinned fork bridge](JAVA-TEARDOWN.md) in the script project and recompile its Java scripts.
For the standard `frida` CLI, install the [fork tools wheel](FORKS.md), which bundles that bridge.
The pinned device passed the bounded teardown and injection regression matrix with that bridge patch.
Unpatched script bundles still have the observed callback lifetime defect.
Use the current server with both the TLS and connection-cleanup patches described in its build record.
Barebone remains on port 27042 for `-p 0`. App injection uses a second, ordinary Android server on port 27043.
Both use the Android arm64 server for Frida 17.26.2. The fork migration uses the fixed server recorded in [the source lock](../sources/frida-17.26.2.json).

Start the server directly as root. Its official Android startup code patches the live SELinux policy, including in Barebone mode.
It creates `frida_file` and `frida_memfd` and adds the access rules used by its injector.
The injector then labels the agent file or memfd. No extra policy patch or manual file relabeling is needed for this tested device.
The earlier `server-no-policy` launcher prevented this setup and caused the agent-file denial. It has been removed.
The official helper can temporarily disable enforcement and make the shell domain permissive if its first policy write fails.
Record the policy hash and global enforcing state before and after startup. Stopping the server does not undo the live policy change.

Start each server in a separate terminal:

```sh
adb shell "su -c 'FRIDA_BAREBONE_CONFIG=/data/local/tmp/linux-kmod.json /data/local/tmp/frida-server --device=barebone -l 127.0.0.1:27042'"
adb shell "su -c '/data/local/tmp/frida-server -l 127.0.0.1:27043'"
adb forward tcp:27042 tcp:27042
adb forward tcp:27043 tcp:27043
frida -H 127.0.0.1:27042 -p 0
frida -H 127.0.0.1:27043 -p APP_PID
```

For diagnosis, load the full module with `trace_process_ops=1`.
A valid kernel-injection result needs matching module operation records, a created target TID, and an agent connection followed by script messages.
A successful App hook by itself is not proof: the Android backend can use its normal fallback when the module's PING is unavailable.

Before replacing a module, unload scripts, detach clients, stop both servers, and check `/sys/module/frida_agent/refcnt`.
Use normal `rmmod frida_agent`. If a reference remains, find its owner. Do not force removal.
If initialization is stuck, preserve its log and recover the device before another load.
If a panic occurs, preserve crash evidence and stop repeated loading.
