"""Offline tests: all Git remotes and generated files live in one temporary tree."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_skill.py"
SPEC = importlib.util.spec_from_file_location("sync_skill", SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        default_parent = Path(__file__).resolve().parents[3]
        parent = Path(os.environ.get("XIUMI_SYNC_TEST_TMPDIR", str(default_parent))).resolve()
        self.assertTrue(parent.is_dir(), "Test temporary parent must already exist")
        self.temporary = tempfile.TemporaryDirectory(prefix="_sync_skill_test_", dir=parent)
        self.base = Path(self.temporary.name).resolve()
        self.assertEqual(self.base.parent, parent)
        self.addCleanup(self.temporary.cleanup)
        self.source = self.base / "source"
        self.install = self.base / "install"
        self.source.mkdir()
        self.install.mkdir()
        self.state_path = self.base / "baseline.json"
        self.config_path = self.install / ".sync.local.json"
        self.config = {
            "source": str(self.source), "install": str(self.install),
            "git_dir": str(self.base / "publisher.git"),
            "repo_url": str(self.base / "remote.git"), "branch": "main",
            "baseline": str(self.state_path), "authorized_publish": True,
        }
        for relative in sync.PUBLIC_FILES + sync.OPTIONAL_PUBLIC_FILES:
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(("initial " + relative + "\n").encode())
        self.state = {"version": 1, "install": {}, "remote_commit": None}
        for relative in sync.RUNTIME_FILES:
            data = (self.source / relative).read_bytes()
            target = self.install / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            self.state["install"][relative] = sync.digest(data)
        self.write_configuration()

    def write_configuration(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")

    def run_sync(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = sync.main(["--config", str(self.config_path), *arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def snapshot(self):
        return {
            path.relative_to(self.base).as_posix(): path.read_bytes()
            for path in self.base.rglob("*") if path.is_file()
        }

    def command(self, *arguments, cwd=None):
        return subprocess.check_output(["git", *arguments], cwd=cwd, stderr=subprocess.PIPE)

    def prepare_remote(self):
        self.command("init", "--bare", "--initial-branch=main", self.config["repo_url"])
        self.command("init", "--bare", self.config["git_dir"])
        self.seed = self.base / "seed"
        self.seed.mkdir()
        self.command("init", "--initial-branch=main", str(self.seed))
        for relative in sync.PUBLIC_FILES + sync.OPTIONAL_PUBLIC_FILES:
            path = self.seed / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.source / relative).read_bytes())
        self.command("add", "--all", cwd=self.seed)
        self.command("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid",
                     "commit", "-m", "Initial public files", cwd=self.seed)
        self.command("push", self.config["repo_url"], "main", cwd=self.seed)
        self.state["remote_commit"] = self.remote_head()
        self.write_configuration()

    def remote_head(self):
        return self.command("--git-dir=" + self.config["repo_url"], "rev-parse", "main").decode().strip()

    def test_dry_run_changes_nothing_and_default_config_is_local(self):
        (self.source / "SKILL.md").write_bytes(b"changed source\n")
        before = self.snapshot()
        code, output, error = self.run_sync()
        self.assertEqual(code, 0, error)
        self.assertIn('"action": "copy"', output)
        self.assertEqual(before, self.snapshot())
        # Running a copy of the real script finds this installation's config.
        copied_script = self.install / "scripts/sync_skill.py"
        copied_script.write_bytes(SCRIPT.read_bytes())
        self.state["install"]["scripts/sync_skill.py"] = sync.digest(copied_script.read_bytes())
        self.write_configuration()
        completed = subprocess.run(
            [sys.executable, "-B", str(copied_script), "--check"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_apply_is_idempotent_and_preserves_private_files(self):
        (self.source / "references/ui-workflow.md").write_bytes(b"new verified steps\r\n")
        (self.source / "private-photo.jpg").write_bytes(b"private")
        (self.source / ".sync.local.json").write_text("private config", encoding="utf-8")
        local_note = self.install / "local-note.txt"
        local_note.write_text("keep", encoding="utf-8")
        first = self.run_sync("--apply")
        self.assertEqual(first[0], 0, first[2])
        before = self.snapshot()
        second = self.run_sync("--apply")
        self.assertEqual(second[0], 0, second[2])
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.install / "private-photo.jpg").exists())
        self.assertEqual(local_note.read_text(), "keep")
        self.assertEqual(json.loads(self.config_path.read_text()), self.config)
        for relative in sync.RUNTIME_FILES:
            self.assertEqual((self.source / relative).read_bytes(), (self.install / relative).read_bytes())

    def test_install_only_or_bilateral_change_is_not_overwritten(self):
        for source_changed in (False, True):
            with self.subTest(source_changed=source_changed):
                (self.install / "SKILL.md").write_bytes(b"local installation edits\n")
                if source_changed:
                    (self.source / "SKILL.md").write_bytes(b"different source edits\n")
                before = self.snapshot()
                code, output, _ = self.run_sync("--apply")
                self.assertEqual(code, 2)
                self.assertIn("Installation changed", output)
                self.assertEqual(before, self.snapshot())

    def test_missing_baseline_is_not_assumed_safe(self):
        self.state["install"].pop("scripts/sync_skill.py")
        self.write_configuration()
        before = self.snapshot()
        code, output, _ = self.run_sync("--apply")
        self.assertEqual(code, 2)
        self.assertIn("initialize this entry explicitly", output)
        self.assertEqual(before, self.snapshot())

    def test_explicit_null_baseline_installs_new_runtime_file(self):
        path = self.install / "scripts/sync_skill.py"
        path.unlink()
        self.state["install"]["scripts/sync_skill.py"] = None
        self.write_configuration()
        result = self.run_sync("--apply")
        self.assertEqual(result[0], 0, result[2])
        self.assertEqual(path.read_bytes(), (self.source / "scripts/sync_skill.py").read_bytes())

    def test_remote_conflict_is_rejected_before_local_copy(self):
        self.prepare_remote()
        (self.seed / "README.md").write_text("remote edit\n", encoding="utf-8")
        self.command("add", "README.md", cwd=self.seed)
        self.command("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid",
                     "commit", "-m", "Other contributor", cwd=self.seed)
        self.command("push", self.config["repo_url"], "main", cwd=self.seed)
        remote_before = self.remote_head()
        installed_before = (self.install / "SKILL.md").read_bytes()
        state_before = self.state_path.read_bytes()
        (self.source / "SKILL.md").write_bytes(b"new source\n")
        code, _, error = self.run_sync("--push")
        self.assertEqual(code, 2)
        self.assertIn("Remote branch differs", error)
        self.assertEqual(self.remote_head(), remote_before)
        self.assertEqual((self.install / "SKILL.md").read_bytes(), installed_before)
        self.assertEqual(self.state_path.read_bytes(), state_before)

    def test_publish_consent_must_be_boolean_true(self):
        self.prepare_remote()
        original = self.remote_head()
        for value in (False, None, "true", 1):
            with self.subTest(value=value):
                if value is None:
                    self.config.pop("authorized_publish", None)
                else:
                    self.config["authorized_publish"] = value
                self.write_configuration()
                before = self.snapshot()
                code, _, error = self.run_sync("--push")
                self.assertEqual(code, 2)
                self.assertIn("authorized_publish", error)
                self.assertEqual(original, self.remote_head())
                self.assertEqual(before, self.snapshot())

    def test_proxy_is_validated_and_scoped_to_each_git_process(self):
        environment_before = dict(os.environ)
        completed = subprocess.CompletedProcess([], 0, stdout=b"true\n", stderr=b"")
        for proxy in (None, "http://127.0.0.1:12345", "https://proxy.example.invalid:443"):
            with self.subTest(proxy=proxy):
                if proxy is None:
                    self.config.pop("git_proxy", None)
                else:
                    self.config["git_proxy"] = proxy
                self.write_configuration()
                config = sync.load_config(self.config_path)
                files_before = self.snapshot()
                with patch.object(sync.subprocess, "run", return_value=completed) as run:
                    self.assertEqual(sync.git(config, "rev-parse", "--is-bare-repository"), b"true\n")
                command = run.call_args.args[0]
                self.assertEqual(command[-2:], ["rev-parse", "--is-bare-repository"])
                self.assertNotIn("config", command)  # No persistent git config command.
                if proxy is None:
                    self.assertNotIn("-c", command)
                    self.assertFalse(any(value.startswith("http.proxy=") for value in command))
                else:
                    self.assertEqual(command[2:4], ["-c", "http.proxy=" + proxy])
                child_environment = environment_before.copy()
                child_environment["GIT_TERMINAL_PROMPT"] = "0"
                self.assertEqual(run.call_args.kwargs["env"], child_environment)
                self.assertEqual(dict(os.environ), environment_before)
                self.assertEqual(self.snapshot(), files_before)
        for proxy in ("socks5://127.0.0.1:12345", "http://user@localhost", "https://user:pass@localhost", "http://localhost:bad"):
            with self.subTest(invalid_proxy=proxy):
                self.config["git_proxy"] = proxy
                self.write_configuration()
                with self.assertRaises(sync.SyncError):
                    sync.load_config(self.config_path)

    def test_three_way_sync_uses_only_public_tree_and_is_idempotent(self):
        self.prepare_remote()
        before_commit = self.remote_head()
        (self.source / "private-photo.jpg").write_bytes(b"private image")
        (self.source / ".sync.local.json").write_text("private config", encoding="utf-8")
        (self.source / "SKILL.md").write_bytes(b"public update\r\n")
        code, output, error = self.run_sync("--push")
        self.assertEqual(code, 0, error)
        commit = json.loads(output)["published_commit"]
        self.assertNotEqual(commit, before_commit)
        self.assertEqual(commit, self.remote_head())
        parent = self.command("--git-dir=" + self.config["repo_url"], "rev-parse", commit + "^").decode().strip()
        self.assertEqual(parent, before_commit)
        names = self.command("--git-dir=" + self.config["repo_url"], "ls-tree", "-r", "--name-only", "-z", commit)
        self.assertEqual(set(filter(None, names.decode().split("\0"))), set(sync.PUBLIC_FILES + sync.OPTIONAL_PUBLIC_FILES))
        for relative in sync.PUBLIC_FILES + sync.OPTIONAL_PUBLIC_FILES:
            published = self.command("--git-dir=" + self.config["repo_url"], "show", commit + ":" + relative)
            self.assertEqual(published, (self.source / relative).read_bytes())
        for relative in sync.RUNTIME_FILES:
            self.assertEqual((self.source / relative).read_bytes(), (self.install / relative).read_bytes())
        self.assertEqual(json.loads(self.state_path.read_text())["remote_commit"], commit)
        again = self.run_sync("--push")
        self.assertEqual(again[0], 0, again[2])
        self.assertEqual(commit, self.remote_head())


if __name__ == "__main__":
    unittest.main()
