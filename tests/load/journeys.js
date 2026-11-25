import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';
import { Counter, Rate, Trend } from 'k6/metrics';

const manifest = JSON.parse(open(__ENV.ACCOUNTS));
const users = Number(__ENV.USERS || 10);
const mode = __ENV.MODE || 'realistic';
const base = (__ENV.BASE_URL || '').replace(/\/$/, '');
const probe = __ENV.PROBE_ROLE || '';
if (![1, 10, 20, 30].includes(users) || !['smoke', 'realistic', 'burst'].includes(mode)) {
  throw new Error('Use 10/20/30 users, or one user in smoke mode');
}
if (users === 1 && mode !== 'smoke') throw new Error('One user is only for smoke/baseline');
if (!/^https:\/\/pilah-be-staging\.fly\.dev\/api\/v1$/.test(base) &&
    !/^http:\/\/(localhost|127\.0\.0\.1):\d+\/api\/v1$/.test(base)) {
  throw new Error('Only the exact staging API or local loopback is allowed');
}
if (!manifest.run_id || !manifest.accounts.every(a => a.access_token)) {
  throw new Error('Authenticate the private manifest before testing');
}
if (probe && (!['pengelola', 'nasabah'].includes(probe) || users === 1)) {
  throw new Error('PROBE_ROLE must replace one Pengurus or Nasabah at a matrix level');
}
const staff = users === 1 ? 1 : users * 0.7;
let selected = [
  ...manifest.accounts.filter(a => a.role === 'pengelola').slice(0, staff),
  ...manifest.accounts.filter(a => a.role === 'nasabah').slice(0, users - staff),
];
if (mode === 'smoke' && __ENV.SMOKE_ROLE === 'nasabah') {
  selected = manifest.accounts.filter(a => a.role === 'nasabah').slice(0, 1);
}
const expectedRoleCounts = users === 1
  ? { pengelola: __ENV.SMOKE_ROLE === 'nasabah' ? 0 : 1, nasabah: __ENV.SMOKE_ROLE === 'nasabah' ? 1 : 0 }
  : { pengelola: staff, nasabah: users - staff };
if (mode === 'smoke' && !['pengelola', 'nasabah'].includes(__ENV.SMOKE_ROLE || 'pengelola')) {
  throw new Error('SMOKE_ROLE must be pengelola or nasabah');
}
function assertRoleMix(expected) {
  const actual = { pengelola: 0, nasabah: 0 };
  for (const account of selected) {
    if (!['pengelola', 'nasabah'].includes(account.role)) {
      throw new Error(`Unexpected selected account role: ${account.role}`);
    }
    actual[account.role] += 1;
  }
  if (actual.pengelola !== expected.pengelola || actual.nasabah !== expected.nasabah) {
    throw new Error(`Selected role mix is ${actual.pengelola} Pengurus/${actual.nasabah} Nasabah; expected ${expected.pengelola}/${expected.nasabah}`);
  }
  const accountIds = selected.map(account => account.id);
  if (accountIds.some(id => typeof id !== 'string' || !id) || new Set(accountIds).size !== selected.length) {
    throw new Error('Selected account IDs must be present and unique');
  }
}
assertRoleMix(expectedRoleCounts);
if (probe) {
  const index = selected.map(a => a.role).lastIndexOf(probe);
  if (index < 0) throw new Error(`Cannot reserve probe account: no selected ${probe} account`);
  selected.splice(index, 1);
  expectedRoleCounts[probe] -= 1;
  assertRoleMix(expectedRoleCounts);
}
const vus = selected.length;
const burst = mode === 'burst';
const ordinaryActions = [
  'nasabah_list', 'nasabah_search', 'nasabah_detail', 'prices',
  'jadwal', 'pengurus_history', 'nasabah_home', 'nasabah_balance', 'nasabah_history',
  'transaction_detail', 'nasabah_picker', 'jadwal_calendar',
];
const managerActions = [
  'period_report', 'excel_export', 'setoran_edit', 'setoran_void',
  'pencairan_single_draft', 'pencairan_batch_draft', 'pencairan_confirm', 'pencairan_history',
  'team', 'team_invite', 'team_transfer', 'team_remove', 'team_rejoin',
];
const customerActions = ['nasabah_bank', 'bank_directory', 'pdf_export'];
const draftWrites = new Counter('payout_drafts');
const payoutWrites = new Counter('payout_writes');
const actionLatency = new Trend('action_latency', true);
const failures = new Rate('action_failure');
const samples = new Counter('action_samples');
const writes = new Counter('new_writes');
const journeys = new Counter('completed_journeys');
const integrity = new Counter('integrity_faults');
const throttles = new Counter('login_throttles');
const burstStart = new Trend('burst_start_offset_ms');
const thresholds = { integrity_faults: ['count==0'] };
if (mode === 'realistic') {
  thresholds['action_latency{action:login,phase:steady}'] = ['p(95)<=2000'];
  thresholds['action_failure{action:login,phase:steady}'] = ['rate<0.01'];
  thresholds['action_samples{action:login,phase:steady}'] = ['count>0'];
}
let expectedActions = [...ordinaryActions];
if (selected.some(a => a.role === 'pengelola')) expectedActions.push(...managerActions);
if (selected.some(a => a.role === 'nasabah')) expectedActions.push(...customerActions);
if (users === 1) {
  expectedActions = selected[0].role === 'pengelola'
    ? [...ordinaryActions.filter(action => !['nasabah_home', 'nasabah_balance', 'nasabah_history'].includes(action)), ...managerActions]
    : ['login', 'auth_me', 'jadwal', 'nasabah_home', 'nasabah_balance', 'nasabah_history', 'jadwal_calendar', ...customerActions];
}
for (const action of [...expectedActions, ...(selected.some(a => a.role === 'pengelola') ? ['setoran'] : []), ...(burst ? ['recipient_balance', 'idempotency_replay'] : [])]) {
  const limit = ['setoran', 'idempotency_replay', 'excel_export', 'pdf_export'].includes(action) ? 10000 : 1000;
  // Burst cases intentionally exercise only saves, balance checks and Nasabah reads.
  if (burst && !['setoran', 'auth_me', 'nasabah_home', 'nasabah_balance', 'nasabah_history', 'jadwal', 'jadwal_calendar', 'recipient_balance', 'idempotency_replay'].includes(action)) continue;
  thresholds[`action_latency{action:${action},phase:steady}`] = [`p(95)<=${limit}`];
  thresholds[`action_failure{action:${action},phase:steady}`] = ['rate<0.01'];
  thresholds[`action_samples{action:${action},phase:steady}`] = ['count>0'];
}
let userScenario;
if (mode === 'realistic') {
  userScenario = {
    executor: 'ramping-vus', startVUs: 0,
    stages: [{ duration: '1m', target: vus }, { duration: '5m', target: vus }],
    gracefulStop: '30s',
  };
} else if (burst) {
  userScenario = { executor: 'per-vu-iterations', vus, iterations: 1, maxDuration: '90s' };
} else {
  userScenario = { executor: 'constant-vus', vus, duration: '1m', gracefulStop: '30s' };
}
export const options = {
  scenarios: { users: userScenario },
  thresholds,
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max', 'count'],
  systemTags: ['status', 'method', 'name', 'scenario', 'expected_response'],
  tags: { run_id: __ENV.TRIAL_ID || manifest.run_id, users: String(users), mode },
};

export function setup() {
  const pengurus = manifest.accounts.find(a => a.role === 'pengelola');
  const nasabah = manifest.accounts.find(a => a.role === 'nasabah');
  const endpoints = [
    [pengurus, '/nasabah'], [pengurus, '/nasabah?status=aktif&page_size=100'], [pengurus, '/nasabah?search=Load%20Nasabah%200000'],
    [pengurus, `/nasabah/${manifest.recipient_ids[0]}`], [pengurus, '/jenis-sampah'],
    [pengurus, '/jadwal'], [pengurus, '/aktivitas'],
    [nasabah, '/nasabah/me/beranda'], [nasabah, '/nasabah/me/saldo'],
    [nasabah, '/nasabah/me/riwayat'], [nasabah, '/nasabah/me/bank-sampah'],
    [nasabah, '/bank-sampah'], [pengurus, '/team'],
  ];
  for (const [account, path] of endpoints) {
    const r = http.get(`${base}${path}`, {
      headers: { Authorization: `Bearer ${account.access_token}` },
      tags: { name: 'warmup', phase: 'warmup' }, timeout: '15s', redirects: 0,
    });
    if (r.status !== 200) throw new Error(`Read warm-up failed with HTTP ${r.status}`);
  }
}

function fault(message) {
  integrity.add(1);
  exec.test.abort(message);
}
function phase() {
  if (mode !== 'realistic') return 'steady';
  const elapsed = Date.now() - exec.scenario.startTime;
  if (elapsed < 60000) return 'ramp';
  if (elapsed < 360000) return 'steady';
  return 'drain';
}
function request(account, action, path, payload, key, method) {
  const tags = { action, phase: phase(), role: account.role };
  const params = {
    headers: { Authorization: `Bearer ${account.access_token}`, 'Content-Type': 'application/json' },
    tags: { ...tags, name: action }, timeout: '15s', redirects: 0,
  };
  if (key) params.headers['Idempotency-Key'] = key;
  const response = http.request(method || (payload === undefined ? 'GET' : 'POST'),
    `${base}${path}`, payload === undefined ? null : JSON.stringify(payload), params);
  let body;
  try { body = response.json(); } catch { body = null; }
  const ok = response.status >= 200 && response.status < 300 && (body !== null || response.status === 204);
  actionLatency.add(response.timings.duration, tags);
  samples.add(1, tags);
  failures.add(!ok, tags);
  check(response, { [`${action}: successful response`]: () => ok });
  if (!ok) exec.test.abort(`${action} failed with HTTP ${response.status}; inspect redacted metrics`);
  return { body, status: response.status, response };
}
function requestFile(account, action, path, contentType) {
  const tags = { action, phase: phase(), role: account.role };
  const response = http.get(`${base}${path}`, {
    headers: { Authorization: `Bearer ${account.access_token}` },
    tags: { ...tags, name: action }, timeout: '30s', redirects: 0,
  });
  const ok = response.status === 200 && response.body.length > 0 &&
    response.headers['Content-Type'].includes(contentType) &&
    Boolean(response.headers['Content-Disposition']);
  actionLatency.add(response.timings.duration, tags);
  samples.add(1, tags);
  failures.add(!ok, tags);
  check(response, { [`${action}: valid export`]: () => ok });
  if (!ok) exec.test.abort(`${action} failed with HTTP ${response.status}; inspect redacted metrics`);
  return response;
}
function rows(body) {
  if (Array.isArray(body)) return body;
  return body.results || body.data || [];
}
function list(account, action, path, validate) {
  const body = request(account, action, path).body;
  const values = rows(body);
  if (!Array.isArray(values) || values.length === 0 || !values.every(row => validate(row))) {
    fault(`${action}: empty or incorrectly scoped fixture response`);
  }
  return values;
}
function pause(min = 3, max = 8) {
  if (mode === 'realistic' || mode === 'smoke') sleep(min + Math.random() * (max - min));
}
let verified = false;
let lastLogin = 0;
let managerOperationsDone = false;
let reportExportsDone = false;
let teamOperationsDone = false;

function verifyIdentity(account) {
  const me = request(account, 'auth_me', '/auth/me').body;
  const user = me.user || me;
  if (user.id !== account.id || user.role !== account.role || user.bank_sampah_id !== manifest.bank_id) {
    fault('Account or bank identity differs from manifest');
  }
}

function runBurst(account) {
  const start = exec.scenario.startTime + 15000;
  const wait = (start - Date.now()) / 1000;
  if (wait > 0) sleep(wait);
  if (account.role === 'pengelola') {
    burstStart.add(Date.now() - start);
    let recipient = manifest.recipient_ids[50];
    if (__ENV.CONTENTION !== 'shared') recipient = manifest.recipient_ids[50 + exec.vu.idInTest];
    save(account, recipient);
  } else customer(account);
}

function runPengurus(account) {
  list(account, 'nasabah_list', '/nasabah?page=1', row => manifest.recipient_ids.includes(row.id));
  pause();
  const index = Number.parseInt(crypto.randomUUID().slice(0, 8), 16) % manifest.recipient_ids.length;
  const query = encodeURIComponent(`Load Nasabah ${String(index).padStart(4, '0')}`);
  const found = list(account, 'nasabah_search', `/nasabah?search=${query}`,
    row => row.id === manifest.recipient_ids[index]);
  pause();
  const detail = request(account, 'nasabah_detail', `/nasabah/${found[0].id}`).body;
  if (detail.id !== found[0].id) fault('Incorrect nasabah detail');
  list(account, 'nasabah_picker', '/nasabah?status=aktif&page_size=100', row => manifest.recipient_ids.includes(row.id));
  list(account, 'prices', '/jenis-sampah', row => row.id === manifest.jenis_id);
  pause(15, 30);
  save(account, found[0].id);
  pause();
  list(account, 'jadwal', '/jadwal', row => row.bank_sampah_id === manifest.bank_id || row.lokasi === 'Synthetic load-test location');
  calendar(account);
  pause();
  list(account, 'pengurus_history', '/aktivitas', row => row.tipe === 'setoran' && manifest.recipient_ids.includes(row.data.nasabah_id));
  managerJourneys(account);
  measureLogin(account);
}

function periodQuery() {
  const today = new Date(Date.now() + 7 * 3600000);
  const end = today.toISOString().slice(0, 10);
  const start = new Date(today.getTime() - 365 * 86400000).toISOString().slice(0, 10);
  return `periode=custom&dari_tanggal=${start}&sampai_tanggal=${end}`;
}

function managerJourneys(account) {
  const slot = Math.min(exec.vu.idInTest - 1, manifest.staff_ids.length - 1);
  if (!reportExportsDone) managerReports(account);
  if (!managerOperationsDone) {
    payoutJourneys(account, slot);
    correctionJourneys(account, slot);
    managerOperationsDone = true;
  }
  if (exec.vu.idInTest === 1 && !teamOperationsDone) teamJourney(account);
}

function managerReports(account) {
  const query = periodQuery();
  const report = request(account, 'period_report', `/aktivitas?${query}`).body;
  const reportRows = rows(report);
  if (!report.summary || reportRows.length === 0 ||
      !reportRows.every(row => row.data.bank_sampah_id === manifest.bank_id)) {
    fault('Period report is empty or contains activity outside the fixture bank');
  }
  requestFile(account, 'excel_export', `/transaksi/export?${query}`, 'spreadsheetml');
  reportExportsDone = true;
}

function payoutJourneys(account, slot) {
  const recipient = manifest.recipient_ids[slot];
  const neighbor = manifest.recipient_ids[slot + 1];
  const batch = createBatchDraft(account, recipient, neighbor, slot);
  const single = createSingleDraft(account, recipient, slot);
  confirmPayout(account, single, recipient);
  checkPayoutHistory(account, single.body.id, recipient);
  const drafts = rows(request(account, 'pencairan_batch_draft', '/draft-pencairan?page=1&page_size=100').body);
  const batchDetail = request(account, 'pencairan_batch_draft', `/draft-pencairan/${batch.body.id}`).body;
  if (!drafts.some(row => row.id === batch.body.id) ||
      !batchDetail.items.every(item => manifest.recipient_ids.includes(item.nasabah_id))) {
    fault('Batch draft is missing or contains a member outside the fixture bank');
  }
}

function createBatchDraft(account, recipient, neighbor, slot) {
  const result = request(account, 'pencairan_batch_draft', '/draft-pencairan/batch', {
    nama: `PIL-529 batch ${manifest.run_id} ${slot}`,
    nasabah_ids: [recipient, neighbor],
    metode: 'tunai',
  });
  if (result.status !== 201 || !result.body.items || result.body.items.length !== 2 ||
      !result.body.items.every(item => [recipient, neighbor].includes(item.nasabah_id))) {
    fault('Batch payout draft is not scoped to its selected fixture members');
  }
  draftWrites.add(1);
  return result;
}

function createSingleDraft(account, recipient, slot) {
  const result = request(account, 'pencairan_single_draft', '/draft-pencairan', {
    nama: `PIL-529 single ${manifest.run_id} ${slot}`,
    items: [{ nasabah_id: recipient, nominal: '1', metode: 'tunai' }],
  });
  if (result.status !== 201 || result.body.items.length !== 1 ||
      result.body.items[0].nasabah_id !== recipient) {
    fault('Single payout draft has incorrect membership scope');
  }
  draftWrites.add(1);
  return result;
}

function confirmPayout(account, single, recipient) {
  const confirmed = request(account, 'pencairan_confirm',
    `/draft-pencairan/${single.body.id}/konfirmasi`, {});
  if (confirmed.status !== 200 || confirmed.body.status !== 'dikonfirmasi' ||
      confirmed.body.items.length !== 1 || confirmed.body.items[0].nasabah_id !== recipient) {
    fault('Confirmed payout draft has incorrect status or recipient');
  }
  payoutWrites.add(1);
}

function checkPayoutHistory(account, draftId, recipient) {
  const history = list(account, 'pencairan_history', '/pencairan?page=1&page_size=100',
    row => row.bank_sampah_id === manifest.bank_id);
  const payout = history.find(row => row.draft_id === draftId && row.nasabah_id === recipient);
  if (!payout) fault('Confirmed payout is missing from bank-scoped history');
  const revisions = request(account, 'pencairan_history', `/pencairan/${payout.id}/riwayat`).body;
  if (revisions.pencairan.id !== payout.id ||
      revisions.pencairan.bank_sampah_id !== manifest.bank_id || !Array.isArray(revisions.revisi)) {
    fault('Payout revision history is incorrectly scoped');
  }
}

function correctionJourneys(account, slot) {
  const member = manifest.recipient_ids[slot];
  const deposit = manifest.edit_transaction_ids[slot];
  const edited = request(account, 'setoran_edit', `/transaksi/${deposit}`, {
    alasan: 'PIL-529 synthetic correction',
    catatan: `PIL-529 correction ${manifest.run_id} ${slot}`,
  }, undefined, 'PATCH').body;
  if (edited.id !== deposit || edited.bank_sampah_id !== manifest.bank_id || edited.nasabah_id !== member) {
    fault('Corrected setoran has incorrect fixture identity or bank scope');
  }
  const voidId = manifest.void_transaction_ids[slot];
  const voided = request(account, 'setoran_void', `/transaksi/${voidId}/batalkan`, {
    alasan: 'PIL-529 synthetic void',
  }).body;
  if (voided.id !== voidId || voided.bank_sampah_id !== manifest.bank_id ||
      voided.nasabah_id !== member || voided.status !== 'dibatalkan') {
    fault('Voided setoran has incorrect fixture identity, status or bank scope');
  }
}

function teamJourney(account) {
  const staffIds = manifest.staff_ids;
  const team = request(account, 'team', '/team').body.members;
  if (!Array.isArray(team) || team.length !== staffIds.length ||
      !team.every(member => staffIds.includes(member.id))) {
    fault('Team list contains missing or out-of-fixture members');
  }
  const primary = team.find(member => member.is_primary_pengelola);
  if (!primary || primary.id !== account.id) fault('Team primary identity differs from fixture');
  let invite = request(account, 'team_invite', '/team/invite', {}).body;
  if (!invite.token || !invite.invite_url.endsWith(invite.token) || !invite.expires_at) {
    fault('Team invite response is incomplete');
  }
  const successor = manifest.accounts.find(row => row.id === staffIds[1]);
  const removed = manifest.accounts.find(row => row.id === staffIds[2]);
  let transferred = request(account, 'team_transfer', '/team/transfer', { id: successor.id }).body.members;
  if (!transferred.some(row => row.id === successor.id && row.is_primary_pengelola) ||
      !transferred.some(row => row.id === account.id && !row.is_primary_pengelola)) {
    fault('Team transfer did not move the primary role');
  }
  transferred = request(successor, 'team_transfer', '/team/transfer', { id: account.id }).body.members;
  if (!transferred.some(row => row.id === account.id && row.is_primary_pengelola)) {
    fault('Team transfer back did not restore the fixture owner');
  }
  const removal = request(account, 'team_remove', `/team/${removed.id}`, undefined, undefined, 'DELETE');
  if (removal.status !== 204) fault('Team removal did not return no-content');
  invite = request(account, 'team_invite', '/team/invite', {}).body;
  const joined = request(removed, 'team_rejoin', '/invites/accept', { token: invite.token });
  if (joined.status !== 200 || joined.body.bank_sampah_id !== manifest.bank_id ||
      joined.body.outcome !== 'join_success') {
    fault('Removed fixture manager could not rejoin the same bank via its invite');
  }
  const restored = request(account, 'team', '/team').body.members;
  if (restored.length !== staffIds.length || !restored.some(row => row.id === removed.id) ||
      !restored.some(row => row.id === account.id && row.is_primary_pengelola)) {
    fault('Team state was not restored to the fixture baseline');
  }
}

function measureLogin(account) {
  if (!shouldMeasureLogin(account)) return;
  const response = http.post(`${base}/auth/login`, JSON.stringify({ email: account.email, password: account.password }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login', action: 'login', phase: phase() }, timeout: '15s', redirects: 0 });
  lastLogin = Date.now();
  throttles.add(response.status === 429 ? 1 : 0);
  let body;
  try { body = response.json(); } catch { body = null; }
  const user = body && (body.user || body);
  const ok = response.status === 200 && user.id === account.id && user.role === account.role &&
    user.bank_sampah_id === manifest.bank_id && Boolean(body.access_token);
  actionLatency.add(response.timings.duration, { action: 'login', phase: phase() });
  failures.add(!ok, { action: 'login', phase: phase() });
  samples.add(1, { action: 'login', phase: phase() });
  check(response, { 'login: correct fixture identity': () => ok });
  if (!ok) exec.test.abort(`Login returned HTTP ${response.status} or the wrong fixture identity`);
}

function shouldMeasureLogin(account) {
  if (exec.vu.idInTest !== 1 || lastLogin) return false;
  if (mode === 'smoke') return account.role === 'nasabah';
  return mode === 'realistic' && Date.now() - lastLogin >= 20000;
}

export default function journey() {
  const account = selected[exec.vu.idInTest - 1];
  if (!account) fault('No independent account assigned to this virtual user');
  integrity.add(0);
  if (!verified) {
    verifyIdentity(account);
    verified = true;
  }
  if (burst) {
    runBurst(account);
  } else if (account.role === 'pengelola') {
    runPengurus(account);
  } else customer(account);
  journeys.add(1, { role: account.role, phase: phase() });
  pause();
}
function customer(account) {
  const home = request(account, 'nasabah_home', '/nasabah/me/beranda').body;
  if (home.user.id !== account.id || home.keanggotaan.id !== account.nasabah_id || home.bank_sampah.id !== manifest.bank_id) {
    fault('Nasabah home leaked another account/membership/bank');
  }
  pause();
  const balance = request(account, 'nasabah_balance', '/nasabah/me/saldo').body;
  if (Number(balance.total_saldo) < 25000) fault('Nasabah balance below fixture baseline');
  pause();
  list(account, 'jadwal', '/jadwal', r => r.lokasi === 'Synthetic load-test location');
  calendar(account);
  pause();
  list(account, 'nasabah_history', '/nasabah/me/riwayat', r => typeof r.id === 'string');
  const bank = request(account, 'nasabah_bank', '/nasabah/me/bank-sampah').body;
  if (bank.id !== manifest.bank_id) fault('Nasabah bank detail is outside its fixture membership');
  const directory = rows(request(account, 'bank_directory', '/bank-sampah').body);
  if (!directory.some(row => row.id === manifest.bank_id) ||
      !directory.every(row => typeof row.id === 'string')) {
    fault('Bank directory is empty or malformed');
  }
  if (!reportExportsDone) {
    requestFile(account, 'pdf_export', '/nasabah/me/riwayat/export-pdf', 'application/pdf');
    reportExportsDone = true;
  }
  measureLogin(account);
}
function calendar(account) {
  const local = new Date(Date.now() + 7 * 3600000);
  const year = local.getUTCFullYear();
  const month = local.getUTCMonth();
  const prefix = `${year}-${String(month + 1).padStart(2, '0')}`;
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const body = request(account, 'jadwal_calendar', `/jadwal/calendar-dates?start_date=${prefix}-01&end_date=${prefix}-${lastDay}`).body;
  if (!Array.isArray(body.dates)) fault('Invalid jadwal calendar response');
}

function save(account, recipient) {
  const key = crypto.randomUUID();
  const payload = {
    nasabah_id: recipient, catatan: `PIL-393 ${manifest.run_id}`,
    items: [{ jenis_sampah_id: manifest.jenis_id, berat: '1.000' }],
  };
  const result = request(account, 'setoran', '/transaksi', payload, key);
  const body = result.body;
  if (result.status !== 201 || body.bank_sampah_id !== manifest.bank_id || body.nasabah_id !== recipient ||
      Number(body.total_nilai) !== manifest.price || Number(body.items[0].subtotal) !== manifest.price) {
    fault('Setoran returned incorrect identity, amount or creation status');
  }
  writes.add(1, { phase: phase() });
  if (burst) {
    const replay = request(account, 'idempotency_replay', '/transaksi', payload, key);
    if (replay.status !== 200 || replay.body.id !== body.id) fault('Idempotency replay created a different transaction');
    request(account, 'recipient_balance', `/nasabah/${recipient}/saldo`);
  } else {
    const detail = request(account, 'transaction_detail', `/transaksi/${body.id}`).body;
    if (detail.id !== body.id || detail.nasabah_id !== recipient) fault('Incorrect saved transaction detail');
  }
}
export function handleSummary(data) {
  return { [__ENV.SUMMARY || 'summary.json']: JSON.stringify(data, null, 2) };
}
