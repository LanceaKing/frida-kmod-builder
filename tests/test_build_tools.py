import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('build_tools', Path(__file__).parents[1] / 'scripts/build_tools.py')
tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tools)


class DependencyOverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'source'
        self.overlay = Path(self.tmp.name) / 'overlay'
        (self.source / 'bridges').mkdir(parents=True)
        self.overlay.mkdir()
        self.url = 'https://example.com/bridge.tar.gz'
        original = {'name': 'bridges', 'dependencies': {'frida-java-bridge': '7.0.13', 'other': '1.0.0'}}
        original_lock = {'packages': {'': copy.deepcopy(original),
                        'node_modules/frida-java-bridge': {'resolved': 'https://example.com/original', 'integrity': 'sha512-old'},
                        'node_modules/other': {'version': '1.0.0'}}}
        self.selected = copy.deepcopy(original)
        self.selected['dependencies']['frida-java-bridge'] = self.url
        self.lock = copy.deepcopy(original_lock)
        self.lock['packages']['']['dependencies']['frida-java-bridge'] = self.url
        self.lock['packages']['node_modules/frida-java-bridge'] = {'resolved': self.url, 'integrity': 'sha512-new'}
        for name, data in [('package.json', original), ('package-lock.json', original_lock)]:
            (self.source / 'bridges' / name).write_text(json.dumps(data))

    def apply(self):
        for name, data in [('package.json', self.selected), ('package-lock.json', self.lock)]:
            (self.overlay / name).write_text(json.dumps(data))
        tools.configure_dependencies(self.source, self.overlay, self.url)

    def test_accepts_only_bridge_overlay(self):
        self.apply()
        self.assertEqual(json.loads((self.source / 'bridges/package.json').read_text()), self.selected)

    def test_rejects_unrelated_manifest_or_lock_changes(self):
        self.selected['dependencies']['other'] = '2.0.0'
        with self.assertRaisesRegex(ValueError, 'only the Java bridge'):
            self.apply()
        self.selected['dependencies']['other'] = '1.0.0'
        self.lock['packages']['node_modules/other']['version'] = '2.0.0'
        with self.assertRaisesRegex(ValueError, 'only the Java bridge'):
            self.apply()

    def test_rejects_wrong_archive_or_missing_integrity(self):
        entry = self.lock['packages']['node_modules/frida-java-bridge']
        entry['resolved'] = 'https://example.com/unpinned'
        with self.assertRaisesRegex(ValueError, 'locked URL and integrity'):
            self.apply()
        entry['resolved'] = self.url
        entry['integrity'] = ''
        with self.assertRaisesRegex(ValueError, 'locked URL and integrity'):
            self.apply()
