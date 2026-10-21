# History rewrite, 2026-10-21

The history of this repository was rewritten on 2026-10-21 with
`git filter-repo`, to remove links, paths and third-party data that shouldn't
be public. Commit SHAs changed. The current tree is unchanged.

## If you hold a clone from before 2026-10-21

**Never push from it.** Pushing old history puts the removed material back.

Re-clone, or reset each branch that has no local-only work:

```sh
git fetch origin --prune --force '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*'
git reset --keep origin/<your-branch>
```

Move any local-only work onto the new history with `git cherry-pick`, then
delete the old branches.

## Records

The old-to-new SHA map and the rewrite record are kept privately in the
Barry vault, not in this repository.
