import importlib.util
from pathlib import Path
import tempfile
import struct
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("builder", Path(__file__).parents[1] / "scripts/build.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def elf_fixture(bss_flags=3, extra_name=None):
    entries = [("", 0, 0), (".shstrtab", 3, 0), (".text", 1, 0x200006), (".bss", 8, bss_flags)]
    if extra_name:
        entries.append((extra_name, 1, 3))
    names = b"\0" + b"".join(name.encode() + b"\0" for name, _, _ in entries[1:])
    table_offset = (64 + len(names) + 7) & ~7
    blob = bytearray(table_offset + 64 * len(entries))
    struct.pack_into("<16sHHIQQQIHHHHHH", blob, 0,
                     b"\x7fELF\x02\x01\x01", 1, 183, 1, 0, 0, table_offset,
                     0, 64, 0, 0, 64, len(entries), 1)
    blob[64:64 + len(names)] = names
    for i, (name, kind, flags) in enumerate(entries):
        payload_offset = 64 if kind == 3 else 0
        payload_size = len(names) if kind == 3 else (4096 if kind == 8 else 0)
        struct.pack_into("<IIQQQQIIQQ", blob, table_offset + i * 64,
                         names.index(name.encode() + b"\0"), kind, flags, 0,
                         payload_offset, payload_size, 0, 0, 8, 0)
    return bytes(blob)


class ModuleSectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "agent.o"

    def test_strips_only_retain_and_preserves_nobits(self):
        before = elf_fixture(0x200003)
        self.path.write_bytes(before)
        changes = builder.strip_agent_retain(self.path)
        self.assertEqual([c["section"] for c in changes], [".text", ".bss"])
        after = self.path.read_bytes()
        expected = bytearray(before)
        for section in builder.elf_sections(before):
            if section["flags"] & 0x200000:
                struct.pack_into("<Q", expected, section["flags_offset"], section["flags"] & ~0x200000)
        self.assertEqual(after, expected)
        self.assertEqual(builder.inspect_module_sections(self.path)["bss"], "writable allocated NOBITS")
        self.assertEqual(builder.strip_agent_retain(self.path), [])

    def test_rejects_the_panic_causing_bss_flag(self):
        self.path.write_bytes(elf_fixture(0x200003))
        with self.assertRaisesRegex(ValueError, "Unsafe SHF_GNU_RETAIN.*bss"):
            builder.inspect_module_sections(self.path)

    def test_allows_native_retained_read_only_code(self):
        self.path.write_bytes(elf_fixture(3))
        result = builder.inspect_module_sections(self.path)
        self.assertEqual(result["writable_gnu_retain"], "absent")
        self.assertEqual(result["retained_read_only_sections"], [".text"])

    def test_never_modifies_kernel_owned_sections(self):
        for name in (".modinfo", ".data..ro_after_init", "__jump_table"):
            before = elf_fixture(0x200003, name)
            self.path.write_bytes(before)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "prelinked agent"):
                builder.strip_agent_retain(self.path)
            self.assertEqual(self.path.read_bytes(), before)

    def test_rejects_invalid_section_tables(self):
        for blob in (b"", bytes(64), elf_fixture()[:100]):
            with self.subTest(size=len(blob)), self.assertRaises(ValueError):
                builder.elf_sections(blob)


class ForkServerTests(unittest.TestCase):
    def test_checks_archive_and_binary_before_replacing_output(self):
        import hashlib
        import lzma
        good = b"tested fork server"
        archive = lzma.compress(good)
        digest = lambda value: hashlib.sha256(value).hexdigest()
        for corrupt_archive, corrupt_binary in [(False, False), (True, False), (False, True)]:
            with self.subTest(archive=corrupt_archive, binary=corrupt_binary), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                output = root / "frida-server"
                output.write_bytes(b"previous")
                server = {"url": "https://example.com/server.xz", "sha256": digest(archive),
                          "binary_sha256": digest(b"wrong" if corrupt_binary else good)}
                def fetch(url, destination):
                    destination.write_bytes(b"corrupt" if corrupt_archive else archive)
                with mock.patch.object(builder, "WORK", root), \
                     mock.patch.object(builder, "frida_source", return_value={"server": server}), \
                     mock.patch.object(builder, "download", side_effect=fetch):
                    if corrupt_archive or corrupt_binary:
                        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                            builder.fetch_server({}, output)
                        self.assertEqual(output.read_bytes(), b"previous")
                    else:
                        builder.fetch_server({}, output)
                        self.assertEqual(output.read_bytes(), good)
                        self.assertEqual(output.stat().st_mode & 0o777, 0o755)


class ConfigurationTests(unittest.TestCase):
    def test_infers_exact_android_build(self):
        result = builder.configuration({})
        self.assertEqual(result["kernel_ref"], "c1de4747ac59")
        self.assertEqual(result["android_ci_build"], "14219743")
        self.assertEqual(result["kernel_family"], "android14-6.1")
        self.assertIn("14219743/kernel_aarch64/latest/raw/", result["prepare_url"])

    def test_custom_kernel_requires_both_artifacts(self):
        with self.assertRaisesRegex(ValueError, "both"):
            builder.configuration({"prepare_url": "https://example.com/prepared.tar.gz"})

    def test_custom_kernel_accepts_explicit_sources(self):
        result = builder.configuration({
            "kernel_release": "5.10.157-vendor", "kernel_family": "custom",
            "agent_mode": "kernel-only",
            "kernel_ref": "vendor-tag", "prepare_url": "https://example.com/prepared.tar.gz",
            "symvers_url": "https://example.com/Module.symvers", "kernel_clang_url": "system",
        })
        self.assertEqual(result["android_ci_build"], "")
        self.assertEqual(result["kernel_ref"], "vendor-tag")

    def test_fork_profiles_keep_pixel_modes_separate(self):
        configs = [builder.configuration(builder.read_json(builder.ROOT / "presets" / name))
                   for name in ("pixel-7a-android13-5.10.json", "pixel-7a-android13-5.10-full.json")]
        sources = [builder.frida_source(c) for c in configs]
        self.assertEqual([s["profile"] for s in sources], ["kernel-only", "full-5.10"])
        self.assertNotEqual(sources[0]["commit"], sources[1]["commit"])
        self.assertEqual(sources[0]["repository"], sources[1]["repository"])
        self.assertEqual(builder.frida_source(builder.configuration({}))["profile"], "common")
        for source in sources:
            self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")
            self.assertIn("LanceaKing/frida-core", source["repository"])

    def test_fork_source_rejects_unpinned_revision(self):
        c = builder.configuration({})
        lock = builder.read_json(builder.ROOT / "sources/frida-17.26.2.json")
        lock["core"]["profiles"]["common"] = "main"
        with mock.patch.object(builder, "read_json", return_value=lock):
            with self.assertRaisesRegex(ValueError, "full commit SHA"):
                builder.frida_source(c)

    def test_missing_fork_version_has_no_upstream_fallback(self):
        c = builder.configuration({"frida_version": "99.0.0"})
        with self.assertRaisesRegex(ValueError, "No pinned fork"):
            builder.frida_source(c)

    def test_full_510_rejects_unreviewed_targets(self):
        preset = builder.read_json(builder.ROOT / "presets/pixel-7a-android13-5.10-full.json")
        for change in ({"kernel_release": "5.10.157-android13-4-g1234567-ab999"},
                       {"kernel_ref": "main"}, {"frida_version": "17.26.3"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "limited"):
                builder.configuration({**preset, **change})

    def test_rejects_wrong_family(self):
        with self.assertRaisesRegex(ValueError, "family"):
            builder.configuration({"kernel_family": "android13-5.10"})

    def test_image_preparation_requires_config_hash_and_symbols(self):
        values = {"kernel_image_url": "https://example.com/Image.lz4"}
        with self.assertRaisesRegex(ValueError, "symvers_url"):
            builder.configuration(values)
        values["symvers_url"] = "https://example.com/vmlinux.symvers"
        with self.assertRaisesRegex(ValueError, "SHA256"):
            builder.configuration(values)
        values["kernel_config_sha256"] = "a" * 64
        result = builder.configuration(values)
        self.assertEqual(result["prepare_url"], "")

    def test_kernel_only_mode_is_explicit(self):
        result = builder.configuration({"agent_mode": "kernel-only"})
        self.assertTrue(result["artifact_name"].endswith("-kernel-only"))
        with self.assertRaisesRegex(ValueError, "agent_mode"):
            builder.configuration({"agent_mode": "partial"})

    def test_image_and_prepared_archive_are_mutually_exclusive(self):
        with self.assertRaisesRegex(ValueError, "empty prepare_url"):
            builder.configuration({"kernel_image_url": "https://example.com/Image",
                                   "prepare_url": "https://example.com/tree.tar.gz",
                                   "symvers_url": "https://example.com/Module.symvers"})


class ConfigPreservationTests(unittest.TestCase):
    def test_ignores_header_and_disabled_option_formatting(self):
        builder.verify_config_unchanged("# old\nCONFIG_CFI_CLANG=y\n# CONFIG_FOO is not set\n",
                                        "# new\nCONFIG_CFI_CLANG=y\n")

    def test_rejects_abi_changes(self):
        for key in ("CFI_CLANG", "LTO_CLANG_FULL", "MODVERSIONS", "ARM64_4K_PAGES"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                builder.verify_config_unchanged(f"CONFIG_{key}=y\n", f"# CONFIG_{key} is not set\n")

    def test_rejects_shell_payloads_and_options(self):
        for key, value in (("module_name", "a;id"), ("kernel_ref", "--upload-pack=id"),
                           ("kernel_release", "6.1.0$(id)"), ("rust_toolchain", "stable\nid")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                builder.configuration({key: value})

    def test_rejects_credentials_and_local_urls(self):
        for value in ("file:///tmp/source", "https://token@example.com/source", "http://example.com/source"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                builder.configuration({"kernel_repository": value})


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        (self.path / "include/generated").mkdir(parents=True)
        (self.path / "include/generated/utsrelease.h").write_text(f'#define UTS_RELEASE "{builder.DEFAULT_RELEASE}"\n')
        (self.path / ".config").write_text("CONFIG_ARM64=y\nCONFIG_MODULES=y\nCONFIG_KPROBES=y\nCONFIG_KALLSYMS_ALL=y\n")
        (self.path / "Module.symvers").write_text("0x12345678\tmodule_layout\tvmlinux\tEXPORT_SYMBOL\n")

    def test_accepts_matching_build(self):
        self.assertEqual(builder.inspect_kernel(self.path, builder.DEFAULT_RELEASE)["CONFIG_MODULES"], "y")

    def test_rejects_other_build_on_same_branch(self):
        with self.assertRaisesRegex(ValueError, "release"):
            builder.inspect_kernel(self.path, builder.DEFAULT_RELEASE.replace("14219743", "14219744"))

    def test_rejects_unsigned_module_on_signature_enforcing_kernel(self):
        with (self.path / ".config").open("a") as stream:
            stream.write("CONFIG_MODULE_SIG_FORCE=y\n")
        with self.assertRaisesRegex(ValueError, "signatures"):
            builder.inspect_kernel(self.path, builder.DEFAULT_RELEASE)

    def test_rejects_missing_probe_support(self):
        p = self.path / ".config"
        p.write_text(p.read_text().replace("CONFIG_KPROBES=y", "# CONFIG_KPROBES is not set"))
        with self.assertRaisesRegex(ValueError, "KPROBES"):
            builder.inspect_kernel(self.path, builder.DEFAULT_RELEASE)

    def test_rejects_html_in_place_of_symvers(self):
        (self.path / "Module.symvers").write_text("<html>Sign in</html>")
        with self.assertRaisesRegex(ValueError, "CRC"):
            builder.inspect_kernel(self.path, builder.DEFAULT_RELEASE)


class SymbolBootstrapTests(unittest.TestCase):
    def setUp(self):
        names = ["_text", "kallsyms_lookup_name", "kallsyms_on_each_symbol", "__kfifo_from_user",
                 "sprint_symbol_no_offset", "register_module_notifier", "unregister_module_notifier"]
        self.map = "\n".join(f"{0xffffffc008000000 + i * 0x1000:016x} T {name}" for i, name in enumerate(names))
        self.symvers = "0xb2ead97c\tkimage_vaddr\tvmlinux\tEXPORT_SYMBOL\n"

    def test_requires_exported_runtime_image_base(self):
        self.assertEqual(builder.kallsyms_offset(self.map, self.symvers), 0x1000)
        with self.assertRaisesRegex(ValueError, "export kimage_vaddr"):
            builder.kallsyms_offset(self.map, "")

    def test_rejects_missing_symbol_and_impossible_offset(self):
        with self.assertRaisesRegex(ValueError, "lacks required symbol"):
            builder.kallsyms_offset(self.map.replace("kallsyms_lookup_name", "unrelated"), self.symvers)
        with self.assertRaisesRegex(ValueError, "Invalid kallsyms offset"):
            builder.kallsyms_offset(self.map.replace("ffffffc008001000", "ffffffc008001001"), self.symvers)


class DownloadCacheTests(unittest.TestCase):
    def test_reuses_verified_bytes_and_refetches_corrupt_cache(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(builder, "WORK", Path(directory)):
            def fake_download(*args):
                Path(args[args.index("--output") + 1]).write_bytes(b"original artifact")
            destination = Path(directory) / "artifact"
            with mock.patch.object(builder, "run", side_effect=fake_download) as fetch:
                builder.download("https://example.com/original", destination)
                destination.unlink()
                builder.download("https://example.com/original", destination)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(destination.read_bytes(), b"original artifact")
                record = builder.read_json(Path(directory) / "downloads.json")[-1]
                self.assertTrue(record["cache_hit"])
                cached = next(p for p in (Path(directory) / "download-cache").iterdir() if p.suffix == "")
                cached.write_bytes(b"corrupted")
                builder.download("https://example.com/original", destination)
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(destination.read_bytes(), b"original artifact")

    def test_distinguishes_urls_with_the_same_output_name(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(builder, "WORK", Path(directory)):
            def fake_download(*args):
                Path(args[args.index("--output") + 1]).write_bytes(args[-1].encode())
            destination = Path(directory) / "artifact"
            with mock.patch.object(builder, "run", side_effect=fake_download) as fetch:
                for name in ("one", "two", "one"):
                    url = "https://example.com/" + name
                    builder.download(url, destination)
                    self.assertEqual(destination.read_text(), url)
                self.assertEqual(fetch.call_count, 2)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        (self.path / "Makefile").write_text("VERSION = 6\nPATCHLEVEL = 1\nSUBLEVEL = 145\n")

    def test_matching_source(self):
        builder.inspect_source(self.path, builder.DEFAULT_RELEASE, "c1de4747ac591582dce61ce3143a25cccdef3442")

    def test_wrong_source_commit(self):
        with self.assertRaisesRegex(ValueError, "commit"):
            builder.inspect_source(self.path, builder.DEFAULT_RELEASE, "a" * 40)

    def test_wrong_source_version(self):
        with self.assertRaisesRegex(ValueError, "version"):
            builder.inspect_source(self.path, "6.1.146-vendor", "a" * 40)


if __name__ == "__main__":
    unittest.main()
