---
name: lgtm
description: Merge an approved GitHub pull request, delete its merged remote branch, and remove its clean linked worktree. Use when the user says LGTM, approve and merge, merge this PR, or asks to clean up a merged worktree.
argument-hint: "[PR URL, number, or branch]"
compatibility: Requires git and the GitHub CLI (gh); run from the PR's linked worktree.
metadata:
  author: CommandCode
  version: "1.0"
---

# Merge and clean up a pull request

Run this workflow from the feature worktree created by `ship`. It is GitHub-only and must never remove the main checkout.

## 1. Identify and validate the target

- Resolve the repository root, current branch, current worktree path, Git common directory, and default branch:

  ```bash
  git rev-parse --show-toplevel
  git branch --show-current
  git status --short --branch
  git rev-parse --path-format=absolute --git-common-dir
  gh repo view --json nameWithOwner,defaultBranchRef
  ```

- Require a named branch, PR URL/number, or a current non-default branch. If the target is ambiguous, stop and ask; never guess among multiple PRs.
- Resolve the PR with `gh pr view <target> --json number,title,state,isDraft,mergeStateStatus,reviewDecision,statusCheckRollup,headRefName,headRefOid,baseRefName,url`.
- Run `gh pr checks <number> --required` and stop if any required check is failing or pending. Also stop for `CHANGES_REQUESTED`, `REVIEW_REQUIRED`, a draft PR, or a dirty, blocked, conflicted, or unknown merge state.
- Require the PR head branch to equal the current branch when running from a worktree. Never merge a different branch accidentally.
- Stop if the current worktree has uncommitted or untracked files. Never discard user work.
- Compute the primary checkout from the absolute Git common directory and require the current worktree path to be `<parent>/<repo>-worktrees/<entry>`. Never remove any other path.

## 2. Merge on GitHub

- Use the repository's documented merge policy. If no policy is documented and the user did not specify a method, use squash merge:

  ```bash
  gh pr merge <number> --squash --match-head-commit <head-sha>
  ```

- Use `--merge` or `--rebase` only when explicitly requested or required by repository policy. Do not use auto-merge, force-push, or bypass flags.
- Inspect the command result, then verify the PR is merged:

  ```bash
  gh pr view <number> --json state,mergedAt,headRefName,url
  ```

- Only after confirmed `MERGED`, delete the remote head branch. Use an explicit remote deletion rather than `--delete-branch`, because the local branch is still checked out in the worktree:

  ```bash
  git push origin --delete <head-branch>
  ```

  Verify the remote branch no longer exists with `git ls-remote --heads origin <head-branch>`. If deletion reports that the branch is already absent, treat it as successful only when this verification is empty; otherwise stop before removing the worktree.

## 3. Remove the linked worktree

- Run cleanup from the primary checkout, not from the worktree being removed:

  ```bash
  git -C <primary-checkout> worktree remove <worktree-path>
  ```

- Do not use `--force`. If removal refuses because the worktree is dirty or otherwise unsafe, stop and report the exact blocker.
- After removal, run `git -C <primary-checkout> worktree prune` and verify the worktree path is gone. Leave the local branch reference in place unless the user explicitly asks to delete it; remote branch deletion and worktree removal are the required cleanup.

## 4. Report

Return a concise result containing:

- PR URL and merge method
- merge confirmation and remote branch deletion result
- removed worktree path and branch
- any cleanup that was not performed

Never claim merge, branch deletion, or worktree removal succeeded without inspecting each command result.

## Safety boundaries

- Treat an explicit `LGTM` for a uniquely identified PR as authorization to merge and clean up that PR; ask for confirmation if the target, branch, or worktree is ambiguous.
- Never merge from the default branch, remove the primary checkout, use force deletion, bypass required checks, or delete a branch before the PR is confirmed merged.
