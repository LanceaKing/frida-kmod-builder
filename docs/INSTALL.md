# Load the Frida kernel module

Do not reload the original Pixel 7a Android 13 artifact after a panic.
Builds from `d5f6682` and earlier contain an ELF flag that can make mutable memory read-only.
The revised build removes that flag, but runtime validation remains incomplete.
Read the [incident report](https://github.com/LanceaKing/frida-kmod-builder/blob/main/docs/PIXEL-5.10-PANIC.md) first.

Use a rooted Android arm64 device with the exact kernel recorded in `build-info.json`.
KernelSU can provide root access, including in its runtime jailbreak mode.
The root profile must permit module loading and access to `/dev/frida`.
A completed Actions build does not prove that this module works on your device.

## Load and connect

Run these commands on the computer connected to the device.
Replace `frida-agent.ko` if you selected a different module name.
If the artifact does not include `frida-server`, obtain the matching Android arm64 release from Frida.

```sh
shasum -a 256 -c SHA256SUMS
adb shell uname -r
adb shell su -c id
adb push frida-agent.ko frida-server linux-kmod.json /data/local/tmp/
adb shell su -c 'chmod 755 /data/local/tmp/frida-server'
adb shell su -c 'insmod /data/local/tmp/frida-agent.ko'
adb shell su -c 'ls -l /dev/frida'
adb shell su -c 'dmesg | tail -n 60'
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
adb shell su -c 'FRIDA_BAREBONE_CONFIG=/data/local/tmp/linux-kmod.json /data/local/tmp/frida-server --device=barebone -l 127.0.0.1:27042'
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
adb shell su -c 'rmmod frida-agent'
adb forward --remove tcp:27042
```

A full reboot removes a manually loaded module.
KernelSU jailbreak mode can also require reactivation after a full reboot.
For upstream details, read the [Frida Linux module guide](https://github.com/frida/frida-core/blob/17.26.2/src/barebone/agent/linux/README.md).
