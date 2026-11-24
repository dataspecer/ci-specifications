"""Exercise comparison fetching against a local export repository."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


WORKSPACE = Path(__file__).resolve().parents[2]


class CompareExportsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.remote = self.root / "exports.git"
        self.source = self.root / "source"
        self.source.mkdir()
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "0",
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
            "EXPORT_TOKEN": "test-token",
            "EXPORT_REPOSITORY": "test/exports",
            "DOCKER_TAG": "pr-42", "BASE_EXPORT_TAG": "branch-main",
            "RUNNER_TEMP": str(self.root),
            "GITHUB_WORKSPACE": str(WORKSPACE),
            "GITHUB_SERVER_URL": "https://github.com",
        }
        self.git("init", "--bare", "--quiet", str(self.remote))
        self.git("init", "--quiet", str(self.source))
        self.git("config", "--global", f"url.{self.remote.as_uri()}.insteadOf",
                 "https://github.com/test/exports.git")
        self.git("remote", "add", "origin", str(self.remote))

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.source, env=self.env,
                                       stderr=subprocess.PIPE)

    def publish(self, tag, content, image=None):
        self.git("checkout", "--orphan", tag)
        (self.source / "export.txt").write_text(content)
        self.git("add", "export.txt")
        message = f"{tag}\n\nDocker image: {image or 'ghcr.io/dataspecer/ws:' + tag}"
        self.git("commit", "--quiet", "-m", message)
        self.git("push", "origin", tag)

    def compare(self, check=True):
        result = subprocess.run(["bash", str(WORKSPACE / ".github/scripts/compare-exports.sh")],
                                env=self.env, capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
            return (self.root / "export-pr-comment.md").read_text()
        return result

    def test_comparison_uses_baseline_published_after_pr(self):
        self.publish("branch-main", "old baseline")
        self.publish("pr-42", "new exports")
        self.git("checkout", "branch-main")
        (self.source / "export.txt").write_text("new exports")
        self.git("add", "export.txt")
        self.git("commit", "--quiet", "-m", "Publish updated baseline after PR",
                 "-m", "Docker image: ghcr.io/dataspecer/ws:branch-main")
        self.git("push", "origin", "branch-main")
        body = self.compare()
        self.assertIn("The exported files are identical", body)
        self.assertIn("compare/branch-main..pr-42", body)

    def test_different_published_snapshots(self):
        self.publish("branch-main", "baseline")
        self.publish("pr-42", "changed exports")
        self.assertIn("0 added, 0 removed, and 1 modified", self.compare())

    def test_missing_baseline_is_reported(self):
        self.publish("pr-42", "exports")
        body = self.compare()
        self.assertIn("Comparison unavailable", body)
        self.assertIn("Base branch tag <code>branch-main</code>: unavailable", body)
        self.assertIn("PR tag <code>pr-42</code>: <code>ghcr.io/dataspecer/ws:pr-42</code>", body)

    def test_both_images_come_from_compared_snapshots(self):
        self.env["BASE_EXPORT_TAG"] = "branch-feature-x"
        base_image = "ghcr.io/dataspecer/ws@sha256:" + "a" * 64
        pr_image = "ghcr.io/dataspecer/ws@sha256:" + "b" * 64
        self.publish("branch-feature-x", "baseline", base_image)
        self.publish("pr-42", "exports", pr_image)
        # The current workflow's image can differ from the fetched snapshot.
        self.env["DOCKER_IMAGE"] = "ghcr.io/dataspecer/ws:pr-42"
        body = self.compare()
        self.assertIn(f"PR tag <code>pr-42</code>: <code>{pr_image}</code>", body)
        self.assertIn(f"Base branch tag <code>branch-feature-x</code>: <code>{base_image}</code>", body)

    def test_legacy_snapshot_without_image_metadata(self):
        self.publish("branch-main", "baseline")
        self.git("commit", "--amend", "--quiet", "-m", "Legacy export")
        self.git("push", "--force", "origin", "branch-main")
        self.publish("pr-42", "exports")
        self.assertIn("Base branch tag <code>branch-main</code>: not recorded in this export",
                      self.compare())

    def test_missing_pr_snapshot_fails_without_report(self):
        self.publish("branch-main", "exports")
        self.assertNotEqual(self.compare(check=False).returncode, 0)
        self.assertFalse((self.root / "export-pr-comment.md").exists())


if __name__ == "__main__":
    unittest.main()
