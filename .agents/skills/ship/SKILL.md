---
name: ship
description: Create an isolated sibling worktree under the repository parent's <repo>-worktrees directory, implement a requested feature or fix on a prompt-derived feature/<name> or fix/<name> branch, validate it with the repository's own checks, create atomic conventional commits, push the branch, and open a GitHub pull request or GitLab merge request. Use `staging` as the default checkout and PR/MR target unless the user explicitly names another branch. Use ONLY when the user's message starts with the literal word `ship` followed by a prompt. This trigger is mandatory regardless of change size, simplicity, or whether the user explicitly mentions a PR/MR.
argument-hint: "<feature or fix prompt>"
compatibility: Requires git and either gh or glab; run from an existing Git repository.
metadata:
  author: CommandCode
  version: "1.0"
---

# Ship a feature or fix

Execute the complete delivery workflow from an existing repository checkout. Work in a new sibling worktree, never in the main checkout.

## Invocation contract

- This skill is mandatory whenever the user's message starts with the literal word `ship` followed by a prompt, including small, one-file, documentation-only, configuration-only, or otherwise trivial changes.
- Do not reinterpret, downgrade, or bypass this workflow because the requested change seems too small for a branch, commit, push, or PR/MR.
- If the user's message does not start with `ship`, this skill must not be selected solely because the request involves implementation work.

## 1. Establish the repository and request

- Parse the prompt to determine:
  - change kind: `feature` or `fix`; use `fix` for bug, regression, broken behavior, or correction language, otherwise use `feature`;
  - a short kebab-case `<name>` that accurately summarizes the requested change.
- Resolve the baseline and target branches before creating worktrees:
  - default both `baseline_branch` and `target_branch` to `staging`;
  - if the prompt explicitly names another checkout or base branch, use it for `baseline_branch`;
  - if the prompt explicitly names another PR/MR target, use it for `target_branch`;
  - never silently fall back to the remote default branch when the resolved branch is missing.
- If no repository path is given, use the current repository. Resolve its main checkout with `git rev-parse --show-toplevel`. Derive the worktree parent from the main checkout's actual parent directory; do not assume a fixed root such as `~/projects`.
- Inspect `git status --short --branch`, remotes, the default branch, project documentation, contribution instructions, and available scripts before changing anything.
- Do not overwrite, stash, reset, or delete existing work. If the main checkout has uncommitted changes, stop and report that it must be clean before shipping.
- Do not open a PR/MR from `baseline_branch`, `staging`, `main`, `master`, or another protected baseline branch directly.

## 2. Create the sibling worktree

The worktree is a sibling directory next to the main checkout:

```text
<parent>/
├── my-app/
└── my-app-worktrees/
    ├── feature-auth/
    └── fix-navbar/
```

For example, a main checkout at `/work/project-a` uses `/work/project-a-worktrees`, not `/projects/project-a-worktrees`.

- Derive `<repo>` from the main checkout directory name.
- Derive `<parent>` from the main checkout's parent directory.
- Set:
  - worktree root: `<parent>/<repo>-worktrees`;
  - worktree path: `<parent>/<repo>-worktrees/<kind>-<name>`;
  - branch: `<kind>/<name>`.
  - The branch must therefore be `feature/name` or `fix/name`; the worktree directory is `<kind>-<name>`.
- Create the parent directory only when needed, then create the worktree from `origin/<baseline_branch>`:

```bash
repo_root="$(git rev-parse --show-toplevel)"
repo="$(basename "$repo_root")"
parent="$(dirname "$repo_root")"
worktree_root="$parent/${repo}-worktrees"
worktree_path="$worktree_root/<kind>-<name>"
mkdir -p "$worktree_root"
git fetch origin <baseline_branch>
git worktree add -b <kind>/<name> "$worktree_path" origin/<baseline_branch>
if [ -d "$repo_root/.agents" ]; then
  mkdir -p "$worktree_path/.agents"
  cp -a "$repo_root/.agents/." "$worktree_path/.agents/"
  if [ ! -d "$worktree_path/.agents" ]; then
    printf 'Failed to copy local agent instructions into %s\n' "$worktree_path" >&2
    exit 1
  fi
fi
```

- `.agents/` is intentionally gitignored in repositories that use local agent
  instructions and skills, so create the destination and copy its contents
  explicitly after creating the worktree. The `/.` source form includes hidden
  files and avoids relying on Git's treatment of ignored files. Do not omit
  this step or assume `git worktree add` includes ignored files.
- If either the branch or worktree path already exists, stop and ask for a different name. Never reuse or delete it automatically.
- Perform all implementation, tests, commits, pushes, and PR/MR commands from the new worktree.

## 3. Understand and implement

- Read the repository's README, contribution guide, local agent instructions, and the files relevant to the requested behavior.
- Follow existing language, framework, package-manager, formatting, and testing conventions. Do not add unrelated refactors or dependencies.
- Implement the prompt completely, including focused tests for new or changed behavior when the repository has a test convention.
- Keep changes easy to review and separate responsibilities so each commit represents one coherent change.

## 4. Validate

Run the checks documented by the repository first. If none are documented, detect and run applicable checks without inventing project files:

- JavaScript/TypeScript: use the detected package manager from its lockfile; run available `format:check`, `lint`, `typecheck`, and `test` scripts.
- Go: run `gofmt` in check/apply mode according to project convention, then `go vet ./...`, `go test ./...`, and project lint commands when configured.
- Rust: run `cargo fmt --check`, `cargo check`, `cargo test`, and configured clippy checks.
- Python: run configured formatter, linter, type checker, and test commands; prefer project scripts or `pyproject.toml` tooling.
- Other projects: use their documented formatter, linter, build, and test commands.

Fix failures caused by the implementation and rerun the failed checks. Do not bypass hooks or use `--no-verify`. Record the exact successful validation commands for the final response. If a check cannot run because a required tool or service is unavailable, stop before committing and report the blocker.

## 5. Create atomic commits

- Review `git diff`, `git diff --check`, and `git status`.
- Split unrelated changes into multiple commits. Keep each commit single-responsibility; tests for a change belong with that change unless the repository convention clearly separates them.
- Use Conventional Commits with a scope when useful and a space after the colon:
  - `feat(<scope>): add ...`
  - `fix(<scope>): correct ...`
  - `test(<scope>): cover ...`
  - `refactor(<scope>): ...`
  - `docs(<scope>): ...`
- Use imperative summaries, no trailing period, and keep subjects concise. Include a body only when the why is non-obvious, or for breaking, security, migration, or revert context.
- Before each commit, inspect the staged diff and commit only the files for that responsibility. Never amend an existing commit.
- Capture each resulting commit SHA and URL after committing. The commit list must be ordered oldest to newest.

## 6. Push and open the PR/MR

- Confirm the current branch is exactly the new non-default branch, then push only it:

```bash
git push --set-upstream origin <kind>/<name>
```

- Verify `origin/<target_branch>` exists before opening the PR/MR.
- Pass `target_branch` explicitly to the hosting CLI's base/target-branch
  option; do not rely on the repository default.

- Detect the hosting CLI from the remote and installed tools:
  - GitHub remote or `gh` available: use `gh pr create`;
  - GitLab remote or `glab` available: use `glab mr create`;
  - if the required CLI is unavailable, stop after the successful push and report the exact command needed; do not fabricate a link.
- Use `target_branch` as the PR/MR target; it defaults to `staging` unless the prompt explicitly names another target.
- Derive a concise PR/MR title from the prompt and commits. Use the relevant conventional type prefix only when it improves clarity; do not duplicate noisy prefixes.
- Write a focused description containing summary, key changes, and testing. Include the exact validation commands. Use a temporary file in the session scratchpad for multi-line descriptions, not a new project file.
- Create the PR/MR with the CLI and capture its returned URL and title. Do not assign reviewers, enable auto-merge, delete the source branch, or mark draft unless explicitly requested.

## 7. Final response

Return only a compact rich-presence summary using this exact structure:

```text
Implemented: <one-line feature/fix summary>

Commits: <commit 1 link>, <commit 2 link>, so on
MR: <MR/PR link and title>
Validated with: <linter, formatter, typecheck, test, build, etc>
Step to verify changes: <short manual verification steps>
```

- Use `MR:` for both GitHub pull requests and GitLab merge requests.
- Replace `so on` with the complete comma-separated commit links; never leave placeholder text.
- Include the worktree path and branch in the one-line implementation summary only when useful.
- If no MR/PR was created because a required CLI or validation blocker stopped the workflow, state that compactly in the `MR:` line instead of inventing a URL.

## Safety boundaries

- Ask before any destructive operation or any action affecting a shared remote beyond pushing the new branch and opening the requested PR/MR.
- Never force-push, reset hard, delete branches/worktrees, modify the main checkout, skip validation, bypass hooks, or commit secrets.
- Never claim a test, commit, push, or MR/PR succeeded without inspecting its command result.
