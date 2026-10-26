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
if (probe) {
  const index = selected.map(a => a.role).lastIndexOf(probe);
  selected.splice(index, 1);
}
const vus = selected.length;
const burst = mode === 'burst';
const ordinaryActions = [
  'nasabah_list', 'nasabah_search', 'nasabah_detail', 'prices',
  'jadwal', 'pengurus_history', 'nasabah_home', 'nasabah_balance', 'nasabah_history',
  'transaction_detail', 'nasabah_picker', 'jadwal_calendar',
];
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
let expectedActions = ordinaryActions;
if (users === 1) {
  const pengurusSmoke = selected[0].role === 'pengelola';
  expectedActions = ordinaryActions.filter(action => {
    if (pengurusSmoke) return !action.startsWith('nasabah_h') && action !== 'nasabah_balance';
    return ['auth_me', 'jadwal', 'nasabah_home', 'nasabah_balance', 'nasabah_history', 'jadwal_calendar'].includes(action);
  });
}
for (const action of [...expectedActions, ...(selected.some(a => a.role === 'pengelola') ? ['setoran'] : []), ...(burst ? ['recipient_balance', 'idempotency_replay'] : [])]) {
  const limit = ['setoran', 'idempotency_replay'].includes(action) ? 2000 : 1000;
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
    [nasabah, '/nasabah/me/riwayat'],
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
function request(account, action, path, payload, key) {
  const tags = { action, phase: phase(), role: account.role };
  const params = {
    headers: { Authorization: `Bearer ${account.access_token}`, 'Content-Type': 'application/json' },
    tags: { ...tags, name: action }, timeout: '15s', redirects: 0,
  };
  if (key) params.headers['Idempotency-Key'] = key;
  const response = payload === undefined ? http.get(`${base}${path}`, params) :
    http.post(`${base}${path}`, JSON.stringify(payload), params);
  let body;
  try { body = response.json(); } catch (_) { body = null; }
  const ok = response.status >= 200 && response.status < 300 && body !== null;
  actionLatency.add(response.timings.duration, tags);
  samples.add(1, tags);
  failures.add(!ok, tags);
  check(response, { [`${action}: successful response`]: () => ok });
  if (!ok) exec.test.abort(`${action} failed with HTTP ${response.status}; inspect redacted metrics`);
  return { body, status: response.status };
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
let recipientIndex = 0;

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
  const index = recipientIndex++ % manifest.recipient_ids.length;
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
  measureLogin(account);
}

function measureLogin(account) {
  if (mode !== 'realistic' || exec.vu.idInTest !== 1 || Date.now() - lastLogin < 20000) return;
  const response = http.post(`${base}/auth/login`, JSON.stringify({ email: account.email, password: account.password }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login', action: 'login', phase: phase() }, timeout: '15s', redirects: 0 });
  lastLogin = Date.now();
  throttles.add(response.status === 429 ? 1 : 0);
  actionLatency.add(response.timings.duration, { action: 'login', phase: phase() });
  failures.add(response.status !== 200, { action: 'login', phase: phase() });
  samples.add(1, { action: 'login', phase: phase() });
  if (response.status !== 200) exec.test.abort(`Permitted login returned HTTP ${response.status}`);
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
