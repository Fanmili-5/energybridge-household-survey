import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from runtime_config import load_model_environment


class RuntimeConfigTests(unittest.TestCase):
    def test_no_implicit_parent_secret_discovery(self):
        with patch.dict(os.environ,{},clear=True):
            load_model_environment()
            self.assertEqual(os.environ['PYTHON_DOTENV_DISABLED'],'1')
            self.assertNotIn('LLM_API_KEY',os.environ)

    def test_explicit_file_does_not_override_process_or_load_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.env';path.write_text('LLM_MODEL=fixture-model\nLLM_API_KEY=fixture-not-a-key\nEB_API_SLOTS=99\nPATH=bad\n')
            with patch.dict(os.environ,{'EB_PILOT_ENV_FILE':str(path),'LLM_API_KEY':'process-fixture'},clear=True):
                load_model_environment()
                self.assertEqual(os.environ['LLM_API_KEY'],'process-fixture')
                self.assertEqual(os.environ['LLM_MODEL'],'fixture-model')
                self.assertNotIn('EB_API_SLOTS',os.environ)
                self.assertNotIn('PATH',os.environ)
