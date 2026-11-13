#!/usr/bin/env python3
"""Render an export snapshot report, or create/update its PR comment."""

import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote


def run(*args):
    return subprocess.check_output(args)


def report(baseline):
    env = os.environ
    server = env['GITHUB_SERVER_URL']
    repository = env['EXPORT_REPOSITORY']
    tag = env['DOCKER_TAG']
    marker = f'<!-- specification-exports:{repository}:{tag} -->'
    head = run('git', 'rev-parse', 'HEAD').decode().strip()
    base_tag = env['BASE_EXPORT_TAG']
    compare = f'{server}/{repository}/compare/{quote(base_tag, safe="")}..{quote(tag, safe="")}'
    introduction = ('Hello, I am just a small bot 🥺. I exported all our test specifications using '
                    'Dataspecer from this pull request (the code here, merged with the base branch)')
    if baseline:
        introduction += ' and compared them to the base branch. Here is the result:'
    else:
        introduction += '. I could not compare them to the base branch yet. Here is the result:'
    lines = [marker, introduction, '']
    if baseline:
        base = run('git', 'rev-parse', baseline).decode().strip()
        # Direct tree comparison works even when the branches have unrelated histories.
        entries = run('git', 'diff', '--no-renames', '--name-status', '-z', base, head).split(b'\0')[:-1]
        statuses = [entries[i].decode() for i in range(0, len(entries), 2)]
        if statuses:
            added = statuses.count('A')
            removed = statuses.count('D')
            # File type changes count as modifications in the concise summary.
            modified = len(statuses) - added - removed
            lines += [f'⚠️ There are some changes: **{added} added, {removed} removed, '
                      f'and {modified} modified files**. You should check them before merging this PR.', '']
        else:
            lines += ['✅ Everything is intact! The exported files are identical to the base branch.', '']
    else:
        lines += ['⚠️ Comparison unavailable: the base branch exports have not been published yet.', '']
    lines += [f'[Compare with the base branch]({compare})', '']
    Path(env['RUNNER_TEMP'], 'export-pr-comment.md').write_text('\n'.join(lines))


def pull_request():
    env = os.environ
    repository, number = env['SOURCE_REPOSITORY'], env['PR_NUMBER']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid SOURCE_REPOSITORY')
    if not re.fullmatch(r'[1-9][0-9]*', number):
        raise ValueError('Invalid pull request number')
    return repository, number


def resolve_base():
    repository, number = pull_request()
    pr = json.loads(run('gh', 'api', f'repos/{repository}/pulls/{number}'))
    # Match docker/metadata-action branch tag sanitization in the source workflow.
    tag = re.sub(r'[^a-zA-Z0-9_.-]+', '-', f"branch-{pr['base']['ref']}")
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'tag={tag}\n')


def comment():
    env = os.environ
    repository, number = pull_request()
    commit = env['SOURCE_COMMIT']
    if not re.fullmatch(r'[0-9a-fA-F]{40}', commit):
        raise ValueError('Invalid SOURCE_COMMIT; expected a full commit SHA')
    source = json.loads(run('gh', 'api', f'repos/{repository}/git/commits/{commit}'))
    # A PR build merge has the base first and the original PR head second.
    # Resolve the dispatched revision, since the PR may have advanced meanwhile.
    if len(source['parents']) == 2:
        commit = source['parents'][1]['sha']
        source = json.loads(run('gh', 'api', f'repos/{repository}/git/commits/{commit}'))
    body = Path(env['RUNNER_TEMP'], 'export-pr-comment.md').read_text()
    title = source['message'].split('\n', 1)[0]
    body += (f'\nThis message was generated from commit <code>{commit[:7]}</code>: '
             f'<strong>{html.escape(title)}</strong>.\n')
    marker = body.splitlines()[0]
    author = json.loads(run('gh', 'api', 'user'))['id']
    pages = json.loads(run('gh', 'api', '--paginate', '--slurp',
                          f'repos/{repository}/issues/{number}/comments?per_page=100'))
    matches = [c for page in pages for c in page if c['user']['id'] == author
               and marker in (c.get('body') or '')]
    endpoint = (f"repos/{repository}/issues/comments/{matches[-1]['id']}" if matches
                else f'repos/{repository}/issues/{number}/comments')
    subprocess.run(['gh', 'api', '--method', 'PATCH' if matches else 'POST', endpoint,
                    '--input', '-'], input=json.dumps({'body': body}).encode(),
                   stdout=subprocess.DEVNULL, check=True)


if __name__ == '__main__':
    if sys.argv[1] == 'report':
        report(sys.argv[2] if len(sys.argv) > 2 else None)
    elif sys.argv[1] == 'base':
        resolve_base()
    else:
        comment()
