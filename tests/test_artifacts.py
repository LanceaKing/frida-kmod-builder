import io
import json
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import artifacts


class ArchiveDiscoveryTests(unittest.TestCase):
    release = "5.10.240-android13-4-gabcdef123456-ab12345"
    source = "abcdef123456" + "0" * 28

    def test_filters_and_deduplicates_branch_tips(self):
        refs = {"device-a-5.10-release": {"value": "a"},
                "device-b-5.10-release": {"value": "a"},
                "device-c-5.15-release": {"value": "b"}}
        with mock.patch.object(artifacts, "gitiles", return_value=refs):
            self.assertEqual(artifacts.branch_tips("https://example.com", r"(?:^|-)5\.10(?:-|$)"), ["a"])

    def test_matches_build_and_source_in_history_and_pins_urls(self):
        replies = [
            {"message": "Update ab/123450 SHA abcdef123456", "parents": ["parent"]},
            {"message": "Update ab/12345 SHA fedcba654321", "parents": ["parent"]},
            {"message": "Update ab/12345 SHA abcdef123456", "parents": []},
            {"entries": [{"name": n} for n in ("Image.lz4", "vmlinux.symvers", "System.map")]},
        ]
        with mock.patch.object(artifacts, "branch_tips", return_value=["tip-a", "tip-b"]), \
             mock.patch.object(artifacts, "gitiles", side_effect=replies) as get:
            result = artifacts.kernel_archive(self.release, self.source, "12345")
        self.assertEqual(get.call_count, 4)
        self.assertEqual(result["artifact_commit"], "parent")
        for key in ("kernel_image_url", "symvers_url", "system_map_url"):
            self.assertIn("/+/parent/kernel/", result[key])

    def test_missing_exact_build_or_required_files_fails(self):
        for message, names in (("Unrelated build", []),
                               ("Update ab/12345 SHA abcdef123456", ["Image.lz4", "vmlinux.symvers"])):
            replies = [{"message": message, "parents": []}, {"entries": [{"name": n} for n in names]}]
            with self.subTest(message=message), \
                 mock.patch.object(artifacts, "branch_tips", return_value=["tip"]), \
                 mock.patch.object(artifacts, "gitiles", side_effect=replies):
                with self.assertRaisesRegex(ValueError, "No exact archived"):
                    artifacts.kernel_archive(self.release, self.source, "12345")

    def test_newer_kernel_accepts_uncompressed_image_without_system_map(self):
        replies = [{"message": "Update ab/12345 SHA abcdef123456", "parents": []},
                   {"entries": [{"name": n} for n in ("Image", "vmlinux.symvers")]}]
        with mock.patch.object(artifacts, "branch_tips", return_value=["tip"]), \
             mock.patch.object(artifacts, "gitiles", side_effect=replies):
            result = artifacts.kernel_archive("6.1.99-android14-gabcdef123456-ab12345", self.source, "12345")
        self.assertTrue(result["kernel_image_url"].endswith("/Image?format=TEXT"))
        self.assertEqual(result["system_map_url"], "")

    def test_compiler_discovery_requires_the_exact_revision(self):
        replies = [{"android13-release": {"value": "a"},
                    "android-gki-5.10-android13": {"value": "b"},
                    "android14-release": {"value": "c"}}, None, {"entries": []}]
        with mock.patch.object(artifacts, "gitiles", side_effect=replies) as get:
            result = artifacts.clang_archive("android13", "r450784e")
        self.assertEqual(result, artifacts.CLANG + "/+archive/b/clang-r450784e.tar.gz")
        self.assertTrue(all("/clang-r450784e/" in c.args[0] for c in get.call_args_list[1:]))
        with mock.patch.object(artifacts, "branch_tips", return_value=[]):
            with self.assertRaisesRegex(ValueError, "Cannot locate"):
                artifacts.clang_archive("android13", "r450784e")


class GitilesTests(unittest.TestCase):
    def test_only_missing_objects_are_optional(self):
        for code in (404, 403):
            error = urllib.error.HTTPError("https://example.com", code, "error", {}, None)
            with self.subTest(code=code), mock.patch.object(artifacts.urllib.request, "urlopen", side_effect=error):
                if code == 404:
                    self.assertIsNone(artifacts.gitiles("https://example.com", missing_ok=True))
                else:
                    with self.assertRaises(urllib.error.HTTPError):
                        artifacts.gitiles("https://example.com", missing_ok=True)

    def test_rate_limit_retry_preserves_json_response(self):
        error = urllib.error.HTTPError("https://example.com", 429, "limited", {"Retry-After": "3"}, None)
        response = io.BytesIO(b")]}'\n" + json.dumps({"commit": "abc"}).encode())
        with mock.patch.object(artifacts.urllib.request, "urlopen", side_effect=[error, response]), \
             mock.patch.object(artifacts.time, "sleep") as sleep:
            self.assertEqual(artifacts.gitiles("https://example.com"), {"commit": "abc"})
        sleep.assert_called_once_with(3)
