#!/usr/bin/env python3
"""Build the upstream Frida arm64 kernel module against a prepared kernel."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
DIST = ROOT / "dist"
DEFAULT_RELEASE = "6.1.145-android14-11-gc1de4747ac59-ab14219743"
DEFAULTS = {
    "frida_version": "17.26.2",
    "kernel_release": DEFAULT_RELEASE,
    "kernel_family": "auto",
    "kernel_repository": "https://android.googlesource.com/kernel/common",
    "kernel_ref": "",
    "android_ci_build": "",
    "android_ci_target": "kernel_aarch64",
    "prepare_url": "",
    "symvers_url": "",
    "kernel_image_url": "",
    "kernel_config_sha256": "",
    "agent_mode": "full",
    "kernel_clang_url": "auto",
    "rust_toolchain": "1.99.1",
    "module_name": "frida-agent",
    "include_server": "true",
}


def run(*args, cwd=ROOT, env=None, capture=False):
    print("+", " ".join(str(x) for x in args), flush=True)
    return subprocess.run(
        [str(x) for x in args], cwd=cwd, env=env, check=True,
        text=True, stdout=subprocess.PIPE if capture else None,
    ).stdout


def require(condition, message):
    if not condition:
        raise ValueError(message)


def https_url(value):
    parsed = urllib.parse.urlsplit(value)
    require(parsed.scheme == "https" and bool(parsed.hostname), "Use an absolute HTTPS URL.")
    require(not parsed.username and not parsed.password, "URLs must not contain credentials.")
    require(not any(c.isspace() for c in value), "URLs must not contain whitespace.")
    return value.rstrip("/")


def configuration(values):
    c = {key: str(values.get(key, default)).strip() for key, default in DEFAULTS.items()}
    require(re.fullmatch(r"\d+\.\d+\.\d+", c["frida_version"]), "Use a Frida release such as 17.26.2.")
    require(re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", c["kernel_release"]), "Enter the complete uname -r output.")
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,48}", c["module_name"]), "Use a module name with letters, digits, _ or -.")
    require(re.fullmatch(r"(?:\d+\.\d+\.\d+|stable|nightly-\d{4}-\d{2}-\d{2})", c["rust_toolchain"]), "Use a Rust version, stable, or a dated nightly.")
    require(c["include_server"] in ("true", "false"), "include_server must be true or false.")
    require(c["agent_mode"] in ("full", "kernel-only"), "agent_mode must be full or kernel-only.")
    https_url(c["kernel_repository"])
    family = re.match(r"(\d+\.\d+)\.\d+-?(android\d+)?", c["kernel_release"])
    require(family is not None, "The kernel release must start with major.minor.patch.")
    detected = f"{family[2]}-{family[1]}" if family[2] else "custom"
    require(c["kernel_family"] in ("auto", "custom", detected), "The selected kernel family does not match kernel_release.")
    c["kernel_family"] = detected if c["kernel_family"] == "auto" else c["kernel_family"]
    commit = re.search(r"-g([0-9a-f]{7,40})(?:-|$)", c["kernel_release"])
    build = re.search(r"-ab(\d+)(?:-|$)", c["kernel_release"])
    c["kernel_ref"] = c["kernel_ref"] or (commit[1] if commit else "")
    c["android_ci_build"] = c["android_ci_build"] or (build[1] if build else "")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./+-]*", c["kernel_ref"]), "Set kernel_ref when uname -r does not contain a Git commit.")
    require(re.fullmatch(r"[A-Za-z0-9_-]+", c["android_ci_target"]), "Invalid Android CI target.")
    require(not c["android_ci_build"] or c["android_ci_build"].isdigit(), "Android CI build must contain digits only.")
    for key in ("prepare_url", "symvers_url", "kernel_image_url"):
        if c[key]:
            https_url(c[key])
    if c["kernel_image_url"]:
        require(not c["prepare_url"] and c["symvers_url"],
                "Image preparation requires symvers_url and an empty prepare_url.")
        require(re.fullmatch(r"[0-9a-f]{64}", c["kernel_config_sha256"]),
                "Image preparation requires the SHA256 of the target kernel configuration.")
    else:
        require(not c["kernel_config_sha256"], "kernel_config_sha256 requires kernel_image_url.")
        require(bool(c["prepare_url"]) == bool(c["symvers_url"]), "Provide both prepare_url and symvers_url, or leave both empty.")
    if not c["prepare_url"] and not c["kernel_image_url"]:
        require(c["android_ci_build"], "Provide an Android CI build or both custom artifact URLs.")
        base = f"https://ci.android.com/builds/submitted/{c['android_ci_build']}/{c['android_ci_target']}/latest/raw"
        c["prepare_url"] = base + "/modules_prepare_outdir.tar.gz"
        c["symvers_url"] = base + f"/{c['android_ci_target']}_Module.symvers"
    if c["kernel_clang_url"] not in ("auto", "system"):
        https_url(c["kernel_clang_url"])
    c["artifact_name"] = f"{c['module_name']}-{c['frida_version']}-{c['kernel_release']}-{c['agent_mode']}"
    return c


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def sha256(path):
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        return digest.hexdigest()


def download(url, path):
    # Android CI's raw URLs support GET. HEAD can incorrectly return 404.
    run("curl", "--fail", "--location", "--retry", "4", "--retry-all-errors",
        "--connect-timeout", "30", "--max-time", "1200", "--output", path, url)
    require(path.stat().st_size > 0, f"Downloaded an empty file: {url}")
    records = WORK / "downloads.json"
    entries = read_json(records) if records.exists() else []
    record = {"url": url, "file": path.name, "sha256": sha256(path)}
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname == "android.googlesource.com" and urllib.parse.parse_qs(parsed.query).get("format") == ["TEXT"]:
        record["transport_sha256"] = record["sha256"]
        path.write_bytes(base64.b64decode(path.read_bytes(), validate=True))
        record["sha256"] = sha256(path)
        record["encoding"] = "base64"
    entries.append(record)
    write_json(records, entries)


def extract(archive, directory):
    directory.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        bundle.extractall(directory, filter="data")


def configure():
    WORK.mkdir(exist_ok=True)
    c = configuration({k: os.environ.get(k.upper(), v) for k, v in DEFAULTS.items()})
    write_json(WORK / "configuration.json", c)
    print(json.dumps(c, indent=2))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as stream:
            stream.write(f"artifact_name={c['artifact_name']}\n")


def git_checkout(repository, ref, destination):
    run("git", "init", destination)
    run("git", "-C", destination, "remote", "add", "origin", repository)
    run("git", "-C", destination, "fetch", "--depth=1", "origin", ref)
    run("git", "-C", destination, "checkout", "--detach", "FETCH_HEAD")
    return run("git", "-C", destination, "rev-parse", "HEAD", capture=True).strip()


def inspect_kernel(directory, expected_release):
    text = (directory / ".config").read_text()
    options = dict(re.findall(r"^(CONFIG_\w+)=(.*)$", text, re.MULTILINE))
    for name in ("ARM64", "MODULES", "KPROBES", "KALLSYMS_ALL"):
        require(options.get(f"CONFIG_{name}") == "y", f"The target requires CONFIG_{name}=y.")
    require(options.get("CONFIG_MODULE_SIG_FORCE") != "y", "The target forces module signatures. This workflow produces unsigned modules.")
    header = (directory / "include/generated/utsrelease.h").read_text()
    match = re.search(r'#define UTS_RELEASE "([^"]+)"', header)
    require(match and match[1] == expected_release, "The prepared kernel release does not match kernel_release. Use artifacts from the exact build.")
    symbols = directory / "Module.symvers"
    require(symbols.is_file() and symbols.stat().st_size > 0, "A nonempty Module.symvers from the target build is required.")
    require(re.search(r"^0x[0-9a-fA-F]+\s+\w+\s+", symbols.read_text(), re.MULTILINE), "Module.symvers does not contain symbol CRC records.")
    return options


def inspect_source(directory, release, commit):
    embedded = re.search(r"-g([0-9a-f]{7,40})(?:-|$)", release)
    require(not embedded or commit.startswith(embedded[1]),
            "The source commit does not match the -g commit in kernel_release.")
    numbers = dict(re.findall(r"^(VERSION|PATCHLEVEL|SUBLEVEL)\s*=\s*(\d+)\s*$",
                              (directory / "Makefile").read_text(), re.MULTILINE))
    version = ".".join(numbers.get(key, "?") for key in ("VERSION", "PATCHLEVEL", "SUBLEVEL"))
    require(re.match(re.escape(version) + r"(?:[-+]|$)", release),
            "The source kernel version does not match kernel_release.")


def config_options(text):
    return dict(re.findall(r"^(CONFIG_\w+)=(.*)$", text, re.MULTILINE))


def verify_config_unchanged(before, after):
    old, new = config_options(before), config_options(after)
    changes = {key: [old.get(key), new.get(key)] for key in old.keys() | new.keys()
               if old.get(key) != new.get(key)}
    require(not changes, f"Kernel preparation changed configuration options: {changes}")


def prepare_compiler(c, options):
    clang_url = c["kernel_clang_url"]
    if clang_url == "auto":
        revision = re.search(r"based on (r[0-9]+[a-z0-9]*)", options.get("CONFIG_CC_VERSION_TEXT", ""))
        android = re.search(r"android\d+", c["kernel_release"])
        require(revision and android, "Cannot infer the Android Clang archive. Set kernel_clang_url explicitly, or use system for LLVM 19.")
        clang_url = ("https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/"
                     f"+archive/refs/heads/{android[0]}-release/clang-{revision[1]}.tar.gz")
    if clang_url != "system":
        download(clang_url, WORK / "kernel-clang.tar.gz")
        extract(WORK / "kernel-clang.tar.gz", WORK / "kernel-clang")
        clang_bin = WORK / "kernel-clang/bin"
        require((clang_bin / "clang").is_file(), "The compiler archive must contain bin/clang at its root.")
    else:
        clang_bin = Path("/usr/lib/llvm-19/bin")
    return clang_url, clang_bin


def prepare_from_image(c, prepared):
    source = WORK / "kernel-source"
    image = WORK / "kernel-image"
    download(c["kernel_image_url"], image)
    env = dict(os.environ, LC_ALL="C")
    original = run("bash", source / "scripts/extract-ikconfig", image, env=env, capture=True)
    require(hashlib.sha256(original.encode()).hexdigest() == c["kernel_config_sha256"],
            "The image's embedded configuration does not match the target configuration SHA256.")
    require(c["kernel_release"].encode() in image.read_bytes() or
            c["kernel_image_url"].split("?")[0].endswith(".lz4"),
            "The kernel image does not contain the expected release string.")
    # Check the banner in an LZ4 image as well as its embedded configuration.
    if c["kernel_image_url"].split("?")[0].endswith(".lz4"):
        run("lz4", "-d", "-f", image, WORK / "kernel-image.raw")
        require(b"Linux version " + c["kernel_release"].encode() + b" " in
                (WORK / "kernel-image.raw").read_bytes(), "The kernel image release does not match kernel_release.")
    (prepared / "original.config").write_text(original)
    clang_url, clang_bin = prepare_compiler(c, config_options(original))
    # Android 5.10 treats LLVM as a boolean and finds these tools through PATH.
    env["PATH"] = str(clang_bin) + os.pathsep + env["PATH"]

    # This old absolute build path is not part of the ABI. Recreate the whitelist
    # from the original exported-symbol table; do not change any kernel feature.
    normalized = original
    relocations = {}
    options = config_options(original)
    key = "CONFIG_UNUSED_KSYMS_WHITELIST"
    if options.get(key, '""') != '""':
        whitelist = prepared / "abi_symbollist.raw"
        symbols = [line.split()[1] for line in (prepared / "Module.symvers").read_text().splitlines() if line.strip()]
        whitelist.write_text("\n".join(sorted(set(symbols))) + "\n")
        value = f'"{whitelist}"'
        normalized = normalized.replace(f"{key}={options[key]}", f"{key}={value}")
        relocations[key] = {"original": options[key], "prepared": value}
    (prepared / ".config").write_text(normalized)
    # The exact source, image banner and config were checked above. Supply the
    # original build's release to kbuild, including its Android CI build suffix.
    make_args = ["make", "-C", source, f"O={prepared}", "ARCH=arm64",
                 f"LLVM={clang_bin}/", "LLVM_IAS=1", "CROSS_COMPILE=aarch64-linux-gnu-",
                 f"KERNELRELEASE={c['kernel_release']}"]
    run(*make_args, "olddefconfig", env=env)
    verify_config_unchanged(normalized, (prepared / ".config").read_text())
    run(*make_args, f"-j{min(os.cpu_count() or 2, 8)}", "modules_prepare", env=env)
    verify_config_unchanged(normalized, (prepared / ".config").read_text())
    return clang_url, clang_bin, {
        "method": "exact-source-and-image", "original_config_sha256": c["kernel_config_sha256"],
        "image_sha256": sha256(image), "config_path_relocations": relocations,
    }


def prepare():
    c = read_json(WORK / "configuration.json")
    prepared = WORK / "kernel-prepared"
    prepared.mkdir(parents=True, exist_ok=True)

    repository = c["kernel_repository"].rstrip("/")
    ref = c["kernel_ref"]
    if urllib.parse.urlsplit(repository).hostname == "android.googlesource.com":
        url = f"{repository}/+/{urllib.parse.quote(ref, safe='/')}?format=JSON"
        with urllib.request.urlopen(url, timeout=60) as response:
            ref = json.loads(response.read().decode()[4:])["commit"]
    kernel_commit = git_checkout(repository, ref, WORK / "kernel-source")
    inspect_source(WORK / "kernel-source", c["kernel_release"], kernel_commit)

    if c["kernel_image_url"]:
        download(c["symvers_url"], prepared / "Module.symvers")
        clang_url, clang_bin, preparation = prepare_from_image(c, prepared)
    else:
        download(c["prepare_url"], WORK / "kernel-prepared.tar.gz")
        extract(WORK / "kernel-prepared.tar.gz", prepared)
        download(c["symvers_url"], prepared / "Module.symvers")
        options = inspect_kernel(prepared, c["kernel_release"])
        clang_url, clang_bin = prepare_compiler(c, options)
        preparation = {"method": "prepared-artifact"}
    options = inspect_kernel(prepared, c["kernel_release"])
    write_json(WORK / "kernel-options.json", options)

    # The prepared Makefile can refer to the original CI workspace.
    # Passing KDIR and KOUT to upstream kbuild rewrites this stub for this runner.
    frida_commit = git_checkout("https://github.com/frida/frida-core.git", c["frida_version"], WORK / "frida-core")
    patches = []
    patch_dir = ROOT / "patches" / c["frida_version"]
    selected_patches = sorted(patch_dir.glob("*.patch"))
    if c["agent_mode"] == "kernel-only":
        mode_patches = sorted((patch_dir / "kernel-only").glob("*.patch"))
        require(mode_patches, "No kernel-only compatibility patch exists for this Frida version.")
        selected_patches += mode_patches
    for patch in selected_patches:
        run("git", "apply", "--check", patch, cwd=WORK / "frida-core")
        run("git", "apply", patch, cwd=WORK / "frida-core")
        patches.append({"path": str(patch.relative_to(ROOT)), "sha256": sha256(patch)})
    run("git", "submodule", "update", "--init", "--recursive", "--depth=1", "releng", cwd=WORK / "frida-core")
    base = f"https://github.com/frida/frida/releases/download/{c['frida_version']}"
    devkit = f"frida-gumjs-devkit-{c['frida_version']}-none-arm64-softfloat_nopic.tar.xz"
    download(f"{base}/{devkit}", WORK / "gumjs-devkit.tar.xz")
    extract(WORK / "gumjs-devkit.tar.xz", WORK / "gumjs-devkit")
    run(sys.executable, "releng/deps.py", "sync", "sdk", "none-arm64-softfloat_nopic", WORK / "sdk", cwd=WORK / "frida-core")

    write_json(WORK / "sources.json", {
        "kernel_commit": kernel_commit, "frida_commit": frida_commit,
        "frida_patches": patches,
        "kernel_preparation": preparation,
        "releng_commit": run("git", "rev-parse", "HEAD", cwd=WORK / "frida-core/releng", capture=True).strip(),
        "kernel_clang_url": clang_url, "kernel_clang_bin": str(clang_bin),
        "kernel_config_sha256": sha256(prepared / ".config"),
        "module_symvers_sha256": sha256(prepared / "Module.symvers"),
        "sdk_libc_sha256": sha256(WORK / "sdk/lib/libc.a"),
        "sdk_deps_file_sha256": sha256(WORK / "frida-core/releng/deps.toml"),
    })


def build():
    c = read_json(WORK / "configuration.json")
    sources = read_json(WORK / "sources.json")
    env = os.environ.copy()
    env.update({"RUSTUP_TOOLCHAIN": c["rust_toolchain"], "LIBCLANG_PATH": "/usr/lib/llvm-19/lib",
                "GUMJS_DEVKIT_DIR": str(WORK / "gumjs-devkit"), "FRIDA_SDK": str(WORK / "sdk"),
                "FRIDA_VERSION": c["frida_version"]})
    run("rustup", "toolchain", "install", c["rust_toolchain"], "--profile", "minimal", "--component", "rust-src", "--target", "aarch64-unknown-none")
    clang_bin = sources["kernel_clang_bin"]
    env["PATH"] = clang_bin + os.pathsep + env["PATH"]
    extra_args = []
    if c["kernel_image_url"]:
        extra_args += [f"KERNELRELEASE={c['kernel_release']}", "LLVM_IAS=1", "CROSS_COMPILE=aarch64-linux-gnu-"]
    if c["agent_mode"] == "kernel-only":
        extra_args += ["EXTRA_CFLAGS=-DFRIDA_KERNEL_ONLY"]
    run("make", "-C", WORK / "frida-core/src/barebone/agent/linux",
        f"-j{min(os.cpu_count() or 2, 8)}", "ARCH=arm64", "BITS=64",
        f"MODULE_NAME={c['module_name']}", f"FRIDA_SDK={WORK / 'sdk'}",
        f"GUMJS_DEVKIT_DIR={WORK / 'gumjs-devkit'}", "AGENT_CC=/usr/bin/clang-19",
        "AGENT_LD=aarch64-linux-gnu-ld", "AGENT_AR=aarch64-linux-gnu-ar",
        "AGENT_NM=aarch64-linux-gnu-nm", "AGENT_OBJCOPY=aarch64-linux-gnu-objcopy",
        f"KDIR={WORK / 'kernel-source'}", f"KOUT={WORK / 'kernel-prepared'}",
        f"LLVM={clang_bin}/", *extra_args, env=env)
    # Recheck after kbuild: configuration regeneration must not change the target ABI.
    inspect_kernel(WORK / "kernel-prepared", c["kernel_release"])
    require(sha256(WORK / "kernel-prepared/.config") == sources["kernel_config_sha256"],
            "kbuild changed the kernel configuration. Use the compiler and artifacts from the original build.")


def package():
    c = read_json(WORK / "configuration.json")
    sources = read_json(WORK / "sources.json")
    DIST.mkdir(exist_ok=True)
    module = DIST / f"{c['module_name']}.ko"
    shutil.copy2(WORK / "frida-core/src/barebone/agent/linux" / module.name, module)
    vermagic = run("modinfo", "-F", "vermagic", module, capture=True).strip()
    require(vermagic.split()[0] == c["kernel_release"], "The output module vermagic does not match kernel_release.")
    elf = run("readelf", "-h", module, capture=True)
    require("AArch64" in elf and "REL (Relocatable file)" in elf, "The output must be an AArch64 relocatable ELF module.")
    shutil.copy2(WORK / "frida-core/src/barebone/agent/etc/linux-kmod.json", DIST / "linux-kmod.json")
    shutil.copy2(ROOT / "docs/INSTALL.md", DIST / "INSTALL.md")
    if c["agent_mode"] == "kernel-only":
        note = ("This is a kernel-session-only build. Connect with `-p 0`.\n"
                "Process thread injection returns EOPNOTSUPP. Automatic process hooks are disabled.\n\n")
        install = DIST / "INSTALL.md"
        install.write_text(note + install.read_text())
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", DIST / "THIRD_PARTY_NOTICES.md")
    shutil.copy2(WORK / "frida-core/COPYING", DIST / "LICENSE.frida-core")
    shutil.copy2(WORK / "kernel-source/COPYING", DIST / "LICENSE.kernel")
    for patch in sources["frida_patches"]:
        path = ROOT / patch["path"]
        shutil.copy2(path, DIST / path.name)
    (DIST / "modinfo.txt").write_text(run("modinfo", module, capture=True))
    if c["include_server"] == "true":
        import lzma
        url = f"https://github.com/frida/frida/releases/download/{c['frida_version']}/frida-server-{c['frida_version']}-android-arm64.xz"
        download(url, WORK / "frida-server.xz")
        with lzma.open(WORK / "frida-server.xz") as stream, (DIST / "frida-server").open("wb") as out:
            shutil.copyfileobj(stream, out)
        (DIST / "frida-server").chmod(0o755)
    provenance = {
        "configuration": c, "sources": sources, "downloads": read_json(WORK / "downloads.json"),
        "vermagic": vermagic,
        "kernel_compiler": run(Path(sources["kernel_clang_bin"]) / "clang", "--version", capture=True).strip(),
        "agent_compiler": run("clang-19", "--version", capture=True).strip(),
        "rust_compiler": run("rustup", "run", c["rust_toolchain"], "rustc", "--version", capture=True).strip(),
        "builder_commit": os.environ.get("GITHUB_SHA", "local"),
        "run_url": f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}",
        "features": {"kernel_session": True, "process_thread_injection": c["agent_mode"] == "full",
                     "automatic_process_hooks": c["agent_mode"] == "full"},
        "validation": {"elf": "AArch64 relocatable", "vermagic": "matched", "device_load_test": "not performed"},
    }
    write_json(DIST / "build-info.json", provenance)
    (DIST / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in sorted(DIST.iterdir()) if p.is_file() and p.name != "SHA256SUMS"))
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as stream:
            stream.write(f"## Built {module.name}\n\nKernel: `{c['kernel_release']}`\n\nFrida: `{c['frida_version']}`\n\n")
            stream.write("Download the artifact from this run. It contains the module, connection configuration, hashes, and build provenance.\n\n")
            stream.write("ELF architecture and vermagic passed. Loading on a device was not tested.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("configure", "prepare", "build", "package"))
    args = parser.parse_args()
    try:
        globals()[args.stage]()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
