'use strict';

async function requestDiscordReview({ github, context, core, fetchImpl = fetch, env = process.env }) {
  const { issue, comment, action } = context.payload;
  if (context.eventName !== 'issue_comment' || action !== 'created' ||
      !issue?.pull_request || !comment || comment.user?.type !== 'User') {
    return { sent: false, reason: 'not-human-pr-comment' };
  }
  const command = comment.body.trim().match(/^\/request-(review|qa)(?:\s+([\s\S]*))?$/);
  if (!command) return { sent: false, reason: 'not-command' };

  const requester = comment.user.login;
  const { owner, repo } = context.repo;
  const permission = await github.rest.repos.getCollaboratorPermissionLevel({
    owner, repo, username: requester,
  });
  if (!['admin', 'maintain', 'write'].includes(permission.data.permission)) {
    core.notice('Discord request ignored: the comment author needs repository write access.');
    return { sent: false, reason: 'insufficient-permission' };
  }

  const { data: pr } = await github.rest.pulls.get({ owner, repo, pull_number: issue.number });
  if (pr.state !== 'open') return { sent: false, reason: 'closed-pr' };
  const kind = command[1];
  const secretName = kind === 'review' ? 'DISCORD_REVIEW_WEBHOOK_URL' : 'DISCORD_QA_WEBHOOK_URL';
  const secret = env[secretName];
  if (!secret) throw new Error(`Configure the repository Actions secret ${secretName}.`);
  let webhook;
  try {
    webhook = new URL(secret);
    if (webhook.protocol !== 'https:' || !['discord.com', 'discordapp.com'].includes(webhook.hostname) ||
        webhook.port || webhook.username || webhook.password ||
        !/^\/api\/webhooks\/\d+\/[^/]+$/.test(webhook.pathname)) throw new Error();
  } catch {
    throw new Error(`The ${secretName} secret must be a valid HTTPS Discord webhook URL.`);
  }
  webhook.searchParams.set('wait', 'true');

  const label = kind === 'review' ? 'Code review' : 'QA';
  const payload = {
    allowed_mentions: { parse: [] },
    embeds: [{
      title: `${label} requested: ${owner}/${repo} #${pr.number}`.slice(0, 256),
      url: pr.html_url,
      description: pr.title.slice(0, 1000),
      color: kind === 'review' ? 3447003 : 15844367,
      fields: [
        { name: 'Requested by', value: requester.slice(0, 100), inline: true },
        { name: 'Author', value: pr.user.login.slice(0, 100), inline: true },
        { name: 'Branch', value: `${pr.head.ref} → ${pr.base.ref}`.slice(0, 1024) },
        { name: 'Request comment', value: comment.html_url },
        ...(command[2]?.trim() ? [{ name: 'Note', value: command[2].trim().slice(0, 1000) }] : []),
      ],
      footer: { text: `GitHub comment ${comment.id}` },
    }],
  };

  let response;
  try {
    response = await fetchImpl(webhook.toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    // Network exception messages can contain the credential-bearing URL.
    throw new Error('Discord delivery failed or timed out. Check network access and the configured secret.');
  }
  if (!response.ok) throw new Error(`Discord delivery failed (HTTP ${response.status}).`);
  core.info(`${label} request delivered for ${owner}/${repo}#${pr.number}.`);
  return { sent: true, kind };
}

module.exports = { requestDiscordReview };
