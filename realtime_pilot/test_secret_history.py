"""Verify historical scanning with local disposable Git repositories, no credentials."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class SecretHistoryTests(unittest.TestCase):
    def test_removed_signature_and_shallow_history_are_not_reported_clean(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/check_secrets.py'
        spec = importlib.util.spec_from_file_location('audit_secret_scanner', path)
        scanner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scanner)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            source.mkdir()

            def git(*args):
                return subprocess.check_output(['git', '-C', str(source), *args], stderr=subprocess.DEVNULL)

            def commit():
                git('add', 'fixture.txt')
                git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')

            def scan(root):
                output = io.StringIO()
                with patch.object(scanner, 'ROOT', root), patch.object(sys, 'argv', ['scanner', '--history']), contextlib.redirect_stdout(output):
                    with self.assertRaises(SystemExit) as exit:
                        scanner.main()
                self.assertEqual(exit.exception.code, 1)
                return json.loads(output.getvalue())

            git('init')
            # Deliberately fake pattern, removed from the latest commit.
            (source / 'fixture.txt').write_text('sk-' + 'x' * 30)
            commit()
            (source / 'fixture.txt').write_text('clean current file')
            commit()
            report = scan(source)
            self.assertIn('history_provider_token', [f['rule'] for f in report['findings']])
            shallow = Path(tmp) / 'shallow'
            subprocess.run(['git', 'clone', '--depth', '1', source.as_uri(), str(shallow)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            report = scan(shallow)
            self.assertIn('incomplete_history_shallow_clone', [f['rule'] for f in report['findings']])


if __name__ == '__main__':
    unittest.main()
