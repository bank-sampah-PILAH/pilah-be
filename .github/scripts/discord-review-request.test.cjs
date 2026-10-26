'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { requestDiscordReview } = require('./discord-review-request.cjs');

function fixture(body = '/request-review') {
  const calls = [];
  const f = {
    context: {
      eventName: 'issue_comment', repo: { owner: 'example', repo: 'app' },
      actor: 'workflow-rerunner',
      payload: {
        action: 'created', issue: { number: 42, pull_request: {} },
        comment: { id: 7, body, user: { login: 'requester', type: 'User' },
          html_url: 'https://github.com/example/app/pull/42#issuecomment-7' },
      },
    },
    github: { rest: {
      repos: { getCollaboratorPermissionLevel: async (args) => {
        calls.push({ permission: args }); return { data: { permission: 'write' } };
      } },
      pulls: { get: async () => ({ data: {
        number: 42, state: 'open', title: 'Add search', user: { login: 'author' },
        html_url: 'https://github.com/example/app/pull/42',
        head: { ref: 'feature/search' }, base: { ref: 'staging' },
      } }) },
    } },
    env: {
      DISCORD_REVIEW_WEBHOOK_URL: 'https://discord.com/api/webhooks/123/review-test-token',
      DISCORD_QA_WEBHOOK_URL: 'https://discord.com/api/webhooks/456/qa-test-token',
    },
    core: { info() {}, notice() {} },
    fetchImpl: async (url, options) => { calls.push({ url, options }); return { ok: true }; },
    calls,
  };
  return f;
}

for (const [command, token] of [['review', '123/review'], ['qa', '456/qa']]) {
  test(`/${'request-' + command} uses the selected channel and PR metadata`, async () => {
    const f = fixture(`/request-${command} Please check pagination`);
    assert.deepEqual(await requestDiscordReview(f), { sent: true, kind: command });
    assert.match(f.calls[1].url, new RegExp(token));
    const payload = JSON.parse(f.calls[1].options.body);
    assert.equal(payload.embeds[0].url, 'https://github.com/example/app/pull/42');
    assert.equal(payload.embeds[0].fields.at(-1).value, 'Please check pagination');
    assert.deepEqual(payload.allowed_mentions, { parse: [] });
    assert.equal(f.calls[0].permission.username, 'requester');
  });
}

for (const body of ['hello /request-review', '/request-review-other', '/request-qa-other', '']) {
  test(`ignores non-command ${JSON.stringify(body)}`, async () => {
    const f = fixture(body);
    assert.equal((await requestDiscordReview(f)).sent, false);
    assert.equal(f.calls.length, 0);
  });
}

for (const change of ['issue', 'bot', 'edited', 'wrong-event']) {
  test(`ignores ${change} without checking permissions or sending`, async () => {
    const f = fixture();
    if (change === 'issue') delete f.context.payload.issue.pull_request;
    if (change === 'bot') f.context.payload.comment.user.type = 'Bot';
    if (change === 'edited') f.context.payload.action = 'edited';
    if (change === 'wrong-event') f.context.eventName = 'pull_request';
    assert.equal((await requestDiscordReview(f)).sent, false);
    assert.equal(f.calls.length, 0);
  });
}

for (const permission of ['read', 'triage', 'none']) {
  test(`rejects ${permission} permission even when workflow actor has access`, async () => {
    const f = fixture();
    f.github.rest.repos.getCollaboratorPermissionLevel = async () => ({ data: { permission } });
    assert.equal((await requestDiscordReview(f)).reason, 'insufficient-permission');
    assert.equal(f.calls.length, 0);
  });
}

test('closed PRs never send a request', async () => {
  const f = fixture();
  f.github.rest.pulls.get = async () => ({ data: { state: 'closed' } });
  assert.equal((await requestDiscordReview(f)).reason, 'closed-pr');
  assert.equal(f.calls.filter(c => c.url).length, 0);
});

test('missing secret fails without invoking Discord', async () => {
  const f = fixture(); f.env = {};
  await assert.rejects(requestDiscordReview(f), /Configure the repository Actions secret/);
  assert.equal(f.calls.filter(c => c.url).length, 0);
});

for (const url of ['http://discord.com/api/webhooks/1/token', 'https://attacker.test/api/webhooks/1/token', 'invalid']) {
  test('invalid webhook destination is rejected', async () => {
    const f = fixture(); f.env.DISCORD_REVIEW_WEBHOOK_URL = url;
    await assert.rejects(requestDiscordReview(f), /valid HTTPS Discord webhook URL/);
    assert.equal(f.calls.filter(c => c.url).length, 0);
  });
}

test('Discord errors do not expose the secret response or network URL', async () => {
  const f = fixture();
  f.fetchImpl = async () => { throw new Error(f.env.DISCORD_REVIEW_WEBHOOK_URL); };
  await assert.rejects(requestDiscordReview(f), (error) => {
    assert.doesNotMatch(error.message, /review-test-token/); return true;
  });
  f.fetchImpl = async () => ({ ok: false, status: 429 });
  await assert.rejects(requestDiscordReview(f), /HTTP 429/);
});

test('long untrusted notes are truncated and mass mentions disabled', async () => {
  const f = fixture('/request-qa @everyone\n' + 'x'.repeat(3000));
  await requestDiscordReview(f);
  const payload = JSON.parse(f.calls[1].options.body);
  assert.equal(payload.embeds[0].fields.at(-1).value.length, 1000);
  assert.deepEqual(payload.allowed_mentions.parse, []);
});
