# History rewrite, 2026-10-21

Every commit SHA in this repository changed on 2026-10-21. If you hold a clone
from before that date, re-sync it (below). Don't push old commits back: that
puts the removed material back in public history.

## Why

The repo is public and the owner wants it to stay public. Older history
contained material that shouldn't be public:

1. Links to private AI coding sessions, carried in `Claude-Session:` trailer
   lines in commit messages.

Nothing else changed. Every commit keeps its real message content, files,
`Co-Authored-By` lines, authors and dates. The tree of every commit is
byte-identical before and after the rewrite.

## How

- Tool: `git filter-repo` (a40bce548d2c).
- `--message-callback`: drops lines that are only a session link, a
  `Claude-Session:` trailer or a "Generated with" trailer, and collapses the
  blank lines that leaves behind.
- Scope: all branches and all tags. The annotated tag was rewritten and its
  release still attaches to the same tag name.
- A full pre-rewrite mirror and bundle are kept privately by the owner, off
  GitHub.
- After the push, a fresh clone had 0 session links across `git log --all`,
  every blob in every commit, and every tag.

## Re-syncing an old clone

```sh
git fetch origin --prune --force '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*'
git reset --keep origin/<your-branch>   # per branch that has no local-only work
```

For a branch with local-only commits, rebase those commits onto the new
branch (`git rebase --onto origin/<branch> <old-base> <branch>`) or re-clone.

## What still holds the old commits

GitHub keeps old commits reachable through the read-only `refs/pull/*` refs
of past pull requests, and through its caches, so an old SHA URL may still
open. A purge request to GitHub Support covers that. The rewrite can't reach
it.

## Branch and tag map (old -> new)

| ref | old | new |
|---|---|---|
| `heads/main` | `f1b3e70259bc` | `c7ee713aec29` |
| `tags/v1.0.0` | `53ea63a216ef` | `106616d39c41` |
