'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const PORT = parseInt(process.env.PORT || '3000', 10);
const DATA_DIR = path.resolve(process.env.DATA_DIR || './data');
const DB_FILE = path.join(DATA_DIR, 'db.json');
fs.mkdirSync(DATA_DIR, { recursive: true });

let db = { seq: { users: 0, groups: 0, expenses: 0, payments: 0 }, users: [], tokens: {}, groups: [], expenses: [], payments: [] };
if (fs.existsSync(DB_FILE)) db = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
function save() {
  const tmp = DB_FILE + '.' + process.pid + '.tmp';
  const fd = fs.openSync(tmp, 'w');
  fs.writeSync(fd, JSON.stringify(db));
  fs.fsyncSync(fd); fs.closeSync(fd);
  fs.renameSync(tmp, DB_FILE);
}
const nextId = (k) => ++db.seq[k];
const now = () => new Date().toISOString();

class HttpError extends Error { constructor(s, m) { super(m); this.status = s; } }
const bad = (m) => { throw new HttpError(400, m); };

function hashPassword(pw) {
  const salt = crypto.randomBytes(16);
  return 'scrypt$' + salt.toString('hex') + '$' + crypto.scryptSync(pw, salt, 64).toString('hex');
}
function verifyPassword(pw, stored) {
  const [, s, h] = stored.split('$');
  const a = crypto.scryptSync(pw, Buffer.from(s, 'hex'), 64), b = Buffer.from(h, 'hex');
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

const pubUser = (u) => ({ id: u.id, email: u.email, name: u.name });
const userById = (id) => db.users.find((u) => u.id === id);
const isInt = (v) => typeof v === 'number' && Number.isInteger(v);
const isNonEmptyStr = (v, max) => typeof v === 'string' && v.trim().length > 0 && v.trim().length <= max;

function groupView(g) {
  return { id: g.id, name: g.name, createdBy: g.createdBy, createdAt: g.createdAt,
    members: [...g.memberIds].sort((a, b) => a - b).map((id) => pubUser(userById(id))) };
}

function isRealDate(s) {
  if (typeof s !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const [y, m, d] = s.split('-').map(Number);
  if (m < 1 || m > 12 || d < 1) return false;
  const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  const dim = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
  return d <= dim;
}

// Largest remainder. raws: array of numbers (amount*w/total); returns integer shares summing to amount.
function largestRemainder(amount, weights, total, exactInts) {
  const n = weights.length;
  let floors, fracs;
  if (exactInts) {
    // exact integer arithmetic with BigInt; fractional part compared as remainder/total
    const A = BigInt(amount), T = BigInt(total);
    floors = weights.map((w) => Number((A * BigInt(w)) / T));
    fracs = weights.map((w) => Number((A * BigInt(w)) % T) / Number(T));
    // compare fractions exactly via remainders (same denominator)
    const rems = weights.map((w) => (A * BigInt(w)) % T);
    fracs = rems;
  } else {
    const raws = weights.map((w) => (amount * w) / total);
    floors = raws.map((r) => Math.floor(r + 1e-9));
    fracs = raws.map((r, i) => { const f = r - floors[i]; return f < 1e-9 ? 0 : f; });
  }
  const shares = floors.slice();
  let missing = amount - shares.reduce((a, b) => a + b, 0);
  const idx = [...Array(n).keys()];
  const cmp = exactInts
    ? (a, b) => (fracs[a] > fracs[b] ? -1 : fracs[a] < fracs[b] ? 1 : a - b)
    : (a, b) => (Math.abs(fracs[a] - fracs[b]) < 1e-9 ? a - b : fracs[b] - fracs[a]);
  const order = idx.sort(cmp);
  for (let k = 0; missing > 0; k = (k + 1) % n) { shares[order[k]]++; missing--; }
  // Safety (percent within tolerance may overshoot): remove from smallest fractions, last listed first
  for (let k = n - 1; missing < 0; k = (k - 1 + n) % n) { if (shares[order[k]] > 0) { shares[order[k]]--; missing++; } }
  return shares;
}

function computeShares(amount, type, parts) {
  const n = parts.length;
  if (type === 'equal') {
    const base = Math.floor(amount / n), rem = amount % n;
    return parts.map((p, i) => base + (i < rem ? 1 : 0));
  }
  const vals = parts.map((p) => p.value);
  if (type === 'exact') {
    if (!vals.every((v) => isInt(v) && v >= 0)) bad('exact values must be integers >= 0');
    if (vals.reduce((a, b) => a + b, 0) !== amount) bad('exact values must sum to amountCents');
    return vals.slice();
  }
  if (type === 'percent') {
    if (!vals.every((v) => v >= 0)) bad('percent values must be >= 0');
    const sum = vals.reduce((a, b) => a + b, 0);
    if (Math.abs(sum - 100) > 0.001 + 1e-12) bad('percent values must sum to 100');
    return largestRemainder(amount, vals, 100, false);
  }
  if (type === 'shares') {
    if (!vals.every((v) => isInt(v) && v >= 0)) bad('shares values must be integers >= 0');
    const total = vals.reduce((a, b) => a + b, 0);
    if (total <= 0) bad('total shares must be > 0');
    return largestRemainder(amount, vals, total, true);
  }
}

function balancesOf(g) {
  const bal = new Map(g.memberIds.map((id) => [id, 0]));
  const add = (id, v) => bal.set(id, (bal.get(id) || 0) + v);
  for (const e of db.expenses) if (e.groupId === g.id) {
    add(e.paidBy, e.amountCents);
    for (const s of e.shares) add(s.userId, -s.amountCents);
  }
  for (const p of db.payments) if (p.groupId === g.id) { add(p.fromUserId, p.amountCents); add(p.toUserId, -p.amountCents); }
  return [...g.memberIds].sort((a, b) => a - b).map((id) => ({ userId: id, name: userById(id).name, balanceCents: bal.get(id) }));
}

function settlementsOf(g) {
  const bals = balancesOf(g).map((b) => ({ id: b.userId, v: b.balanceCents }));
  let debtors = bals.filter((b) => b.v < 0), creditors = bals.filter((b) => b.v > 0);
  const out = [];
  const pick = (arr, key) => arr.reduce((best, x) => (best === null || key(x) > key(best) || (key(x) === key(best) && x.id < best.id) ? x : best), null);
  while (debtors.length && creditors.length) {
    const d = pick(debtors, (x) => -x.v), c = pick(creditors, (x) => x.v);
    const amt = Math.min(-d.v, c.v);
    out.push({ fromUserId: d.id, toUserId: c.id, amountCents: amt });
    d.v += amt; c.v -= amt;
    debtors = debtors.filter((x) => x.v !== 0); creditors = creditors.filter((x) => x.v !== 0);
  }
  return out;
}

const csvField = (v) => { const s = String(v); return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };

function send(res, status, body, type = 'application/json') {
  if (status === 204) { res.writeHead(204); return res.end(); }
  const data = type === 'application/json' ? JSON.stringify(body) : body;
  res.writeHead(status, { 'Content-Type': type + '; charset=utf-8', 'Content-Length': Buffer.byteLength(data) });
  res.end(data);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (!raw.trim()) return resolve({});
      try { const v = JSON.parse(raw); if (v === null || typeof v !== 'object' || Array.isArray(v)) return reject(new HttpError(400, 'body must be a JSON object')); resolve(v); }
      catch { reject(new HttpError(400, 'invalid JSON')); }
    });
    req.on('error', reject);
  });
}

const INDEX = fs.readFileSync(path.join(__dirname, 'public', 'index.html'));

async function handle(req, res) {
  const url = new URL(req.url, 'http://x');
  const p = url.pathname.replace(/\/+$/, '') || '/';
  const m = req.method;

  if (p === '/' && m === 'GET') { res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); return res.end(INDEX); }
  if (!p.startsWith('/api/') && p !== '/api') throw new HttpError(404, 'not found');

  if (p === '/api/auth/register' && m === 'POST') {
    const b = await readBody(req);
    if (typeof b.email !== 'string' || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(b.email.trim())) bad('invalid email');
    if (typeof b.password !== 'string' || b.password.length < 8) bad('password must be at least 8 characters');
    if (!isNonEmptyStr(b.name, 50)) bad('name must be 1-50 characters');
    const email = b.email.trim().toLowerCase();
    if (db.users.some((u) => u.email === email)) throw new HttpError(409, 'email already registered');
    const u = { id: nextId('users'), email, name: b.name.trim(), passwordHash: hashPassword(b.password), createdAt: now() };
    db.users.push(u); save();
    return send(res, 201, pubUser(u));
  }
  if (p === '/api/auth/login' && m === 'POST') {
    const b = await readBody(req);
    const email = typeof b.email === 'string' ? b.email.trim().toLowerCase() : null;
    const u = email && db.users.find((x) => x.email === email);
    if (!u || typeof b.password !== 'string' || !verifyPassword(b.password, u.passwordHash)) throw new HttpError(401, 'invalid credentials');
    const token = crypto.randomBytes(32).toString('hex');
    db.tokens[token] = u.id; save();
    return send(res, 200, { token, user: pubUser(u) });
  }

  // auth
  const auth = req.headers.authorization || '';
  const mt = /^Bearer\s+(\S+)$/i.exec(auth);
  const uid = mt && db.tokens[mt[1]];
  const me = uid && userById(uid);
  if (!me) throw new HttpError(401, 'unauthorized');

  if (p === '/api/groups') {
    if (m === 'POST') {
      const b = await readBody(req);
      if (!isNonEmptyStr(b.name, 100)) bad('name must be 1-100 characters');
      const g = { id: nextId('groups'), name: b.name.trim(), createdBy: me.id, createdAt: now(), memberIds: [me.id] };
      db.groups.push(g); save();
      return send(res, 201, groupView(g));
    }
    if (m === 'GET') return send(res, 200, db.groups.filter((g) => g.memberIds.includes(me.id)).sort((a, b) => a.id - b.id).map(groupView));
    throw new HttpError(404, 'not found');
  }

  const gm = /^\/api\/groups\/([^/]+)(\/.*)?$/.exec(p);
  if (!gm) throw new HttpError(404, 'not found');
  const sub = gm[2] || '';
  const routes = [
    ['GET', /^$/], ['POST', /^\/members$/], ['POST', /^\/expenses$/], ['GET', /^\/expenses$/],
    ['DELETE', /^\/expenses\/[^/]+$/], ['POST', /^\/payments$/], ['GET', /^\/payments$/],
    ['GET', /^\/balances$/], ['GET', /^\/settlements$/], ['GET', /^\/export\.csv$/],
  ];
  if (!routes.some(([mm, re]) => mm === m && re.test(sub))) throw new HttpError(404, 'not found');
  const gid = /^\d+$/.test(gm[1]) ? Number(gm[1]) : NaN;
  const g = db.groups.find((x) => x.id === gid);
  if (!g) throw new HttpError(404, 'group not found');
  if (!g.memberIds.includes(me.id)) throw new HttpError(403, 'not a member of this group');

  if (sub === '' ) return send(res, 200, groupView(g));

  if (sub === '/members') {
    const b = await readBody(req);
    if (typeof b.email !== 'string' || !b.email.trim()) bad('email required');
    const u = db.users.find((x) => x.email === b.email.trim().toLowerCase());
    if (!u) throw new HttpError(404, 'user not found');
    if (g.memberIds.includes(u.id)) throw new HttpError(409, 'already a member');
    g.memberIds.push(u.id); save();
    return send(res, 201, groupView(g));
  }

  if (sub === '/expenses' && m === 'POST') {
    const b = await readBody(req);
    if (!isNonEmptyStr(b.description, 200)) bad('description must be 1-200 characters');
    if (!isInt(b.amountCents) || b.amountCents < 1) bad('amountCents must be an integer >= 1');
    if (!isInt(b.paidBy) || !g.memberIds.includes(b.paidBy)) bad('paidBy must be a group member');
    if (!isRealDate(b.date)) bad('date must be a valid YYYY-MM-DD date');
    const sp = b.split;
    if (!sp || typeof sp !== 'object' || Array.isArray(sp)) bad('split required');
    if (!['equal', 'exact', 'percent', 'shares'].includes(sp.type)) bad('invalid split type');
    if (!Array.isArray(sp.participants) || sp.participants.length === 0) bad('participants must be a non-empty array');
    const seen = new Set();
    for (const pt of sp.participants) {
      if (!pt || typeof pt !== 'object' || !isInt(pt.userId) || !g.memberIds.includes(pt.userId)) bad('every participant must be a group member');
      if (seen.has(pt.userId)) bad('duplicate participant');
      seen.add(pt.userId);
      if (sp.type !== 'equal' && (typeof pt.value !== 'number' || !Number.isFinite(pt.value))) bad('value required');
    }
    const shares = computeShares(b.amountCents, sp.type, sp.participants);
    const e = {
      id: nextId('expenses'), groupId: g.id, description: b.description.trim(), amountCents: b.amountCents,
      paidBy: b.paidBy, date: b.date, createdBy: me.id, createdAt: now(),
      split: { type: sp.type, participants: sp.participants },
      shares: sp.participants.map((pt, i) => ({ userId: pt.userId, amountCents: shares[i] })),
    };
    db.expenses.push(e); save();
    return send(res, 201, e);
  }
  if (sub === '/expenses' && m === 'GET') {
    return send(res, 200, db.expenses.filter((e) => e.groupId === g.id)
      .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.id - a.id)));
  }
  if (sub.startsWith('/expenses/')) {
    const s = sub.slice(10);
    const eid = /^\d+$/.test(s) ? Number(s) : NaN;
    const i = db.expenses.findIndex((e) => e.id === eid && e.groupId === g.id);
    if (i < 0) throw new HttpError(404, 'expense not found');
    db.expenses.splice(i, 1); save();
    return send(res, 204);
  }
  if (sub === '/payments' && m === 'POST') {
    const b = await readBody(req);
    if (!isInt(b.fromUserId) || !g.memberIds.includes(b.fromUserId)) bad('fromUserId must be a member');
    if (!isInt(b.toUserId) || !g.memberIds.includes(b.toUserId)) bad('toUserId must be a member');
    if (b.fromUserId === b.toUserId) bad('fromUserId and toUserId must differ');
    if (!isInt(b.amountCents) || b.amountCents < 1) bad('amountCents must be an integer >= 1');
    const pay = { id: nextId('payments'), groupId: g.id, fromUserId: b.fromUserId, toUserId: b.toUserId, amountCents: b.amountCents, createdAt: now() };
    db.payments.push(pay); save();
    return send(res, 201, pay);
  }
  if (sub === '/payments') return send(res, 200, db.payments.filter((x) => x.groupId === g.id).sort((a, b) => a.id - b.id));
  if (sub === '/balances') return send(res, 200, balancesOf(g));
  if (sub === '/settlements') return send(res, 200, settlementsOf(g));
  if (sub === '/export.csv') {
    const rows = db.expenses.filter((e) => e.groupId === g.id)
      .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.id - b.id))
      .map((e) => [e.date, e.description, userById(e.paidBy).name, e.amountCents].map(csvField).join(','));
    return send(res, 200, ['date,description,paidBy,amountCents', ...rows].join('\r\n') + '\r\n', 'text/csv');
  }
  throw new HttpError(404, 'not found');
}

http.createServer((req, res) => {
  handle(req, res).catch((err) => {
    if (err instanceof HttpError) return send(res, err.status, { error: err.message });
    console.error(err); send(res, 500, { error: 'internal error' });
  });
}).listen(PORT, '0.0.0.0', () => console.log(`splitter listening on ${PORT}, data in ${DATA_DIR}`));
