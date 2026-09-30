import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from launcher import extraction_target, existing_root, Launcher


class LauncherTest(unittest.TestCase):
    def test_extract_destination_and_region_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            iso = base / 'game with spaces.iso'
            iso.write_bytes(b'iso')
            target = base / 'assets'
            with patch('launcher.identify', return_value={'id': 'pal', 'label': 'PAL'}):
                self.assertEqual(extraction_target(iso, target)[2]['id'], 'pal')
                target.mkdir()
                self.assertEqual(extraction_target(iso, target)[1], target)
                (target / 'keep.txt').write_text('keep')
                with self.assertRaises(ValueError):
                    extraction_target(iso, target)
                self.assertEqual((target / 'keep.txt').read_text(), 'keep')
            with patch('launcher.identify', return_value={'id': 'unknown'}):
                with self.assertRaises(ValueError):
                    extraction_target(iso, base / 'new')

    def test_existing_extraction_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                existing_root(root)
            (root / 'disc').mkdir()
            (root / 'audio').mkdir()
            (root / 'disc/SYSTEM.CNF').write_text('BOOT2 = cdrom0:\\SCUS_976.15;1')
            (root / 'audio/manifest.json').write_text('[]')
            (root / 'manifest.json').write_text(json.dumps({'errors': []}))
            self.assertEqual(existing_root(root), root)
            (root / 'manifest.json').write_text(json.dumps({'errors': ['bad archive']}))
            with self.assertRaises(ValueError):
                existing_root(root)

    def test_subprocess_readiness_and_failure(self):
        app = Launcher.__new__(Launcher)
        events = []
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'viewer fixture.py'
            script.write_text("print('Browse http://127.0.0.1:12345  (Ctrl+C to stop)')")
            app.run([str(script)], Path(directory), lambda *e: events.append(e))
            self.assertIn(('ready', (Path(directory), 'http://127.0.0.1:12345')), events)
            script.write_text('raise SystemExit(1)')
            with self.assertRaises(RuntimeError):
                app.run([str(script)], emit=lambda *e: None)


if __name__ == '__main__':
    unittest.main()
