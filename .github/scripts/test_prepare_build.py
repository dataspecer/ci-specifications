"""Regression checks for push target discovery and matrix preparation."""
from contextlib import chdir
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "prepare_build", Path(__file__).with_name("prepare-build.py"))
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class PrepareBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(chdir(temporary))
        for name in ("first", "second"):
            Path("specifications", name).mkdir(parents=True)
        Path("event.json").write_text("{}")
        self.enterContext(patch.dict(os.environ, {
            "GITHUB_EVENT_PATH": str(Path("event.json").resolve()),
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_OUTPUT": str(Path("output").resolve()),
            "DOCKER_IMAGE_REPOSITORY": "ghcr.io/dataspecer/ws",
            "PUSH_DOCKER_TAGS": '["branch-main","latest"]',
        }))
        self.api = self.enterContext(patch.object(prepare.subprocess, "check_output"))
        self.api.return_value = b"[[]]"
        self.images = {}
        self.inspected = []
        self.enterContext(patch.object(prepare.subprocess, "run", side_effect=self.run_command))

    def run_command(self, args, **kwargs):
        if args[0] == "git":
            return subprocess.CompletedProcess(args, 0)
        self.assertEqual(args[:3], ["docker", "manifest", "inspect"])
        self.inspected.append(args[3])
        error = self.images[args[3].rsplit(":", 1)[1]]
        return subprocess.CompletedProcess(args, 1 if error else 0, stderr=error)

    def output(self):
        return {key: json.loads(value) for key, value in
                (line.split("=", 1) for line in Path("output").read_text().splitlines())}

    def test_published_draft_and_ready_prs_across_pages(self):
        self.api.return_value = json.dumps([
            [{"number": 1, "draft": True}, {"number": 2, "draft": False}],
            [{"number": 3, "draft": True}, {"number": 4, "draft": False}],
        ]).encode()
        self.images = {"pr-1": "", "pr-2": "", "pr-3": "manifest unknown",
                       "pr-4": "no such manifest: ghcr.io/dataspecer/ws:pr-4"}
        prepare.main()
        self.api.assert_called_once_with([
            "gh", "api", "--paginate", "--slurp",
            "repos/dataspecer/dataspecer/pulls?state=open&per_page=100",
        ])
        output = self.output()
        tags = [target["tag"] for target in output["tags"]["include"]]
        self.assertEqual(tags, ["branch-main", "latest", "pr-1", "pr-2"])
        self.assertEqual([target["pr_number"] for target in output["tags"]["include"]],
                         ["", "", "1", "2"])
        self.assertEqual(output["comments"]["include"], output["tags"]["include"][2:])
        self.assertTrue(output["has_comments"])
        builds = output["builds"]["include"]
        self.assertEqual(len(builds), 8)
        self.assertEqual({(b["tag"], b["specification"]) for b in builds},
                         {(tag, name) for tag in tags for name in ("first", "second")})
        self.assertTrue(all(b["image"] == f"ghcr.io/dataspecer/ws:{b['tag']}" for b in builds))
        self.assertEqual(len(self.inspected), 4)

    def test_no_open_prs_keeps_base_tags(self):
        prepare.main()
        self.assertEqual(len(self.output()["builds"]["include"]), 4)
        self.assertEqual(self.output()["comments"], {"include": []})
        self.assertFalse(self.output()["has_comments"])
        self.assertEqual(self.inspected, [])

    def test_all_pr_images_missing_keeps_base_tags(self):
        self.api.return_value = b'[[{"number": 1}]]'
        self.images = {"pr-1": "MANIFEST_UNKNOWN: manifest unknown"}
        prepare.main()
        self.assertEqual([t["tag"] for t in self.output()["tags"]["include"]],
                         ["branch-main", "latest"])
        self.assertFalse(self.output()["has_comments"])

    def test_registry_errors_fail_before_matrix_output(self):
        self.api.return_value = b'[[{"number": 1}]]'
        for error in ("unauthorized", "toomanyrequests", "connection timed out"):
            with self.subTest(error=error):
                self.images = {"pr-1": error}
                with self.assertRaisesRegex(RuntimeError, error):
                    prepare.main()
                self.assertFalse(Path("output").exists())

    def test_api_errors_fail_before_matrix_output(self):
        self.api.side_effect = subprocess.CalledProcessError(1, "gh")
        with self.assertRaises(subprocess.CalledProcessError):
            prepare.main()
        self.assertEqual(self.inspected, [])
        self.assertFalse(Path("output").exists())

    def test_dispatch_uses_only_supplied_image(self):
        os.environ["GITHUB_EVENT_NAME"] = "workflow_dispatch"
        target = {"tag": "pr-42", "image": "ghcr.io/dataspecer/ws@sha256:" + "a" * 64,
                  "pr_number": ""}
        Path("event.json").write_text(json.dumps({"inputs": {
            "docker_tag": target["tag"], "docker_image": target["image"],
        }}))
        prepare.main()
        self.assertEqual(self.output()["tags"]["include"], [target])
        self.assertFalse(self.output()["has_comments"])
        self.assertEqual(len(self.output()["builds"]["include"]), 2)
        self.api.assert_not_called()
        self.assertEqual(self.inspected, [])

    def test_pr_dispatch_passes_comment_metadata(self):
        os.environ["GITHUB_EVENT_NAME"] = "workflow_dispatch"
        Path("event.json").write_text(json.dumps({"inputs": {
            "docker_tag": "pr-42", "docker_image": "ghcr.io/dataspecer/ws:pr-42",
            "pr_number": "42",
        }}))
        prepare.main()
        self.assertEqual(self.output()["tags"]["include"][0]["pr_number"], "42")
        self.assertEqual(self.output()["comments"], self.output()["tags"])
        self.assertTrue(self.output()["has_comments"])
        self.api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
