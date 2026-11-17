"""Task commitments must precede plans and cannot silently change source facts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .task_commitment import committed_tasks
from .task_context import frozen_tasks
from . import test_daily_problem as fixtures


class TaskCommitmentTests(unittest.TestCase):
    def test_fresh_commitment_exists_before_caller_and_restores_environment(self):
        case, reference, _ = fixtures.NativeDailyTests().fixture()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            root = Path(temp) / "tasks"
            with committed_tasks([case], ["2007-07-18"], reference, root, "a"*64):
                self.assertTrue((root / "MANIFEST.json").is_file())
                task = frozen_tasks(case, "2007-07-18", reference)
                self.assertTrue(task["A_and_B_share_tasks"])
                self.assertFalse(json.loads((root / "MANIFEST.json").read_text())["plans_generated"])
            self.assertNotIn("EB_FROZEN_TASK_ROOT", os.environ)

    def test_inherited_task_change_is_rejected_before_planning(self):
        case, reference, _ = fixtures.NativeDailyTests().fixture()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            with committed_tasks([case], ["2007-07-18"], reference, Path(temp)/"tasks", "a"*64):
                changed = copy.deepcopy(case)
                changed["household"]["comfort"]["preferred_cooling_c"] = [22, 24]
                with self.assertRaisesRegex(ValueError, "FROZEN_TASK_IDENTITY_MISMATCH"):
                    with committed_tasks([changed], ["2007-07-18"], reference, Path(temp)/"unused", "a"*64):
                        self.fail("planning may not start")

    def test_exception_does_not_leak_a_task_root_into_next_batch(self):
        case, reference, _ = fixtures.NativeDailyTests().fixture()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "caller failure"):
                with committed_tasks([case], ["2007-07-18"], reference, Path(temp)/"tasks", "a"*64):
                    raise RuntimeError("caller failure")
            self.assertNotIn("EB_FROZEN_TASK_ROOT", os.environ)

    def test_task_files_are_not_overwritten(self):
        case, reference, _ = fixtures.NativeDailyTests().fixture()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            root = Path(temp) / "tasks"
            with committed_tasks([case], ["2007-07-18"], reference, root, "a"*64):
                before = (root / "MANIFEST.json").read_bytes()
            with self.assertRaises(FileExistsError):
                with committed_tasks([case], ["2007-07-18"], reference, root, "a"*64):
                    self.fail("existing output may not be reused")
            self.assertEqual(before, (root / "MANIFEST.json").read_bytes())
