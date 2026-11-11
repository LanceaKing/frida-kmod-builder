"""Discover exact kernel artifacts and compilers in official Android archives."""
import json
import re
import time
import urllib.error
import urllib.request

BOOT_ARTIFACTS = "https://android.googlesource.com/platform/prebuilts/boot-artifacts"
CLANG = "https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86"


def gitiles(url, missing_ok=False):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.loads(response.read()[4:])
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            delay = error.headers.get("Retry-After", "")
            time.sleep(int(delay) if delay.isdigit() else 2 ** (attempt + 1))


def branch_tips(repository, pattern):
    refs = gitiles(repository + "/+refs/heads?format=JSON")
    return sorted({value["value"] for name, value in refs.items() if re.search(pattern, name)})


def kernel_archive(release, kernel_commit, build_id):
    """Match official build metadata, then leave full image validation to the builder."""
    version = re.match(r"\d+\.\d+", release)[0]
    pending = branch_tips(BOOT_ARTIFACTS, r"(?:^|-)" + re.escape(version) + r"(?:-|$)")
    seen = set()
    for commit in pending:
        if commit in seen:
            continue
        if len(seen) >= 1024:
            break
        seen.add(commit)
        info = gitiles(f"{BOOT_ARTIFACTS}/+/{commit}?format=JSON")
        message = info["message"]
        build_matches = re.search(r"\bab/" + re.escape(build_id) + r"\b", message)
        source_matches = any(kernel_commit.startswith(sha) for sha in re.findall(r"\b[0-9a-f]{12,40}\b", message))
        if build_matches and source_matches:
            tree = gitiles(f"{BOOT_ARTIFACTS}/+/{commit}/kernel/?format=JSON", missing_ok=True)
            names = {e["name"] for e in tree["entries"]} if tree else set()
            image = next((name for name in ("Image.lz4", "Image") if name in names), None)
            required = {"vmlinux.symvers"} | ({"System.map"} if version == "5.10" else set())
            if image and required <= names:
                print(f"Resolved Android kernel build {build_id} to archive {commit}.", flush=True)
                base = f"{BOOT_ARTIFACTS}/+/{commit}/kernel/"
                return {"prepare_url": "", "kernel_image_url": base + image + "?format=TEXT",
                        "symvers_url": base + "vmlinux.symvers?format=TEXT",
                        "system_map_url": base + "System.map?format=TEXT" if version == "5.10" else "",
                        "artifact_source": "android-prebuilts", "artifact_commit": commit}
        pending.extend(parent for parent in info["parents"] if parent not in seen)
    raise ValueError("No exact archived kernel build found. Provide original artifact URLs and the configuration SHA256.")


def clang_archive(android, revision):
    # Resolve branch tips to commits before checking paths or downloading archives.
    tips = branch_tips(CLANG, r"(?:^|-)" + re.escape(android) + r"(?:-|$)")
    for commit in tips:
        tree = gitiles(f"{CLANG}/+/{commit}/clang-{revision}/?format=JSON", missing_ok=True)
        if tree is not None:
            print(f"Resolved Android Clang {revision} to archive {commit}.", flush=True)
            return f"{CLANG}/+archive/{commit}/clang-{revision}.tar.gz"
    raise ValueError(f"Cannot locate Android Clang {revision}. Provide kernel_clang_url from the original build.")
