# Request a Discord review or QA check

On an **open pull request**, a repository collaborator with write, maintain,
or admin access can post a new comment:

```text
/request-review
```

or:

```text
/request-qa Please check ID search, pagination, and status filters.
```

Review requests use `DISCORD_REVIEW_WEBHOOK_URL`; QA requests use
`DISCORD_QA_WEBHOOK_URL`. Configure both as repository **Actions secrets** in
Settings → Secrets and variables → Actions. Never put their values in source,
PR descriptions, comments, or workflow logs.

The Discord embed contains the PR title/link, author, requester, source/target
branch, request-comment link, and optional note. Notes are limited to 1,000
characters and Discord mention parsing is disabled, including `@everyone`.
No source files, screenshots, PR bodies, or attachments are sent.

## Activation

GitHub runs `issue_comment` workflows from the repository's **default branch**.
The workflow, handler and tests must therefore reach `main` in both PILAH
repositories before commands work. A workflow present only on `staging` or a
feature branch is not active for PR comments. Promote these files through the
normal reviewed release process; changing the repository default is unnecessary.

## Permissions and failures

- Ordinary issue comments, edited comments, bot comments, closed PRs and
  unrelated commands do not send notifications.
- The handler checks the original comment author's current repository
  permissions through GitHub, rather than trusting comment text or a workflow
  rerunner's identity.
- The notification job checks out the trusted default branch, never a PR's
  branch. Untrusted titles/notes are JSON data and are never shell commands.
- The workflow token has read-only contents and PR permissions. It does not
  assign GitHub reviewers, merge, deploy, or comment back on PRs.
- Discord failures appear in the **Discord review requests** Actions run.
  Missing secrets fail explicitly. Network errors omit webhook URLs.
- Requests are sent once per new comment. Editing a comment does not resend;
  post a new command to request another review. Manually rerunning the workflow
  can resend that request. There is no automatic retry after a delivery failure.
- No Discord role or person is pinged automatically.

## Local validation

```sh
node --test .github/scripts/discord-review-request.test.cjs
```

Tests mock GitHub and Discord. They verify channel routing, original-author
authorization, event/command filtering, closed PRs, missing/malformed secrets,
bounded notes, mention suppression, and sanitized failures. Running them sends
no real Discord notification.
