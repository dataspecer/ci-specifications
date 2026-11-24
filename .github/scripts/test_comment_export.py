"""Check PR comment creation and updates without posting to GitHub."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "comment_export", Path(__file__).with_name("comment-export.py"))
comments = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comments)


class CommentExportTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {
            "RUNNER_TEMP": temporary,
            "SOURCE_REPOSITORY": "dataspecer/dataspecer",
            "PR_NUMBER": "42",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_SHA": "b" * 40,
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "dataspecer/ci-specifications",
            "GITHUB_REF_NAME": "main",
            "GITHUB_EVENT_PATH": str(Path(temporary, "event.json")),
            "SOURCE_COMMIT": "",
            "DOCKER_IMAGE": "ghcr.io/dataspecer/ws:pr-42",
        }))
        Path(temporary, "event.json").write_text(json.dumps({
            "head_commit": {"message": "Update <specifications>\nMore details"},
        }))
        self.clock = self.enterContext(patch.object(comments, "datetime"))
        self.instant = datetime(2026, 11, 24, 13, 5, 9, tzinfo=timezone.utc)
        self.clock.now.side_effect = lambda zone: self.instant.astimezone(zone)
        self.marker = '<!-- specification-exports:dataspecer/ci-exports:pr-42 -->'
        Path(temporary, "export-pr-comment.md").write_text(self.marker + "\nReport\n")
        self.api = self.enterContext(patch.object(comments, "run"))
        self.post = self.enterContext(patch.object(comments.subprocess, "run"))

    def body(self):
        return json.loads(self.post.call_args.kwargs["input"])["body"]

    def test_push_creates_comment_without_application_commit(self):
        self.api.side_effect = [b'{"id": 7}', b'[[]]']
        comments.comment()
        self.assertEqual(self.post.call_args.args[0], [
            "gh", "api", "--method", "POST",
            "repos/dataspecer/dataspecer/issues/42/comments", "--input", "-",
        ])
        self.assertIn("24 November 2026 at 14:05:09 CET (Europe/Prague)", self.body())
        self.assertEqual(self.clock.now.call_args.args[0].key, "Europe/Prague")
        self.assertIn("a commit was pushed to the specifications repository", self.body())
        self.assertIn("<code>dataspecer/ci-specifications</code> (branch <code>main</code>)", self.body())
        self.assertIn(f"[`bbbbbbb`](https://github.com/dataspecer/ci-specifications/commit/{'b' * 40})",
                      self.body())
        self.assertIn("<strong>Update &lt;specifications&gt;</strong>", self.body())
        self.assertNotIn("More details", self.body())
        self.assertFalse(any("/git/commits/" in call.args[-1]
                             for call in self.api.call_args_list))

    def test_push_updates_existing_bot_comment(self):
        self.api.side_effect = [b'{"id": 7}', json.dumps([
            [{"id": 10, "user": {"id": 8}, "body": self.marker}],
            [{"id": 20, "user": {"id": 7}, "body": self.marker}],
        ]).encode()]
        comments.comment()
        self.assertEqual(self.post.call_args.args[0], [
            "gh", "api", "--method", "PATCH",
            "repos/dataspecer/dataspecer/issues/comments/20", "--input", "-",
        ])

    def test_dispatch_still_reports_original_pr_revision(self):
        os.environ["GITHUB_EVENT_NAME"] = "workflow_dispatch"
        os.environ["SOURCE_COMMIT"] = "a" * 40
        self.api.side_effect = [
            json.dumps({"parents": [{"sha": "c" * 40}, {"sha": "d" * 40}]}).encode(),
            b'{"message": "Fix <schema>\\nDetails"}', b'{"id": 7}', b'[[]]',
        ]
        comments.comment()
        self.assertIn(f"[`ddddddd`](https://github.com/dataspecer/dataspecer/commit/{'d' * 40})",
                      self.body())
        self.assertIn("this pull request triggered an application image build", self.body())
        self.assertIn("24 November 2026 at 14:05:09 CET (Europe/Prague)", self.body())
        self.assertIn("Fix &lt;schema&gt;", self.body())
        self.assertNotIn("Details", self.body())
        self.assertNotIn("specifications commit", self.body())

    def test_summer_timestamp_uses_prague_daylight_saving_time(self):
        self.instant = datetime(2026, 7, 1, 22, 5, 9, tzinfo=timezone.utc)
        self.api.side_effect = [b'{"id": 7}', b'[[]]']
        comments.comment()
        self.assertIn("02 July 2026 at 00:05:09 CEST (Europe/Prague)", self.body())


if __name__ == "__main__":
    unittest.main()
