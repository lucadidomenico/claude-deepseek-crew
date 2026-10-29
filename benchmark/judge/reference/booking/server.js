'use strict';
const http = require('node:http');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const PORT = Number(process.env.PORT) || 3000;
const DATA_DIR = path.resolve(process.env.DATA_DIR || './data');
const DB_FILE = path.join(DATA_DIR, 'db.json');
fs.mkdirSync(DATA_DIR, { recursive: true });

let db = { users: [], rooms: [], bookings: [], tokens: {}, seq: { user: 0, room: 0, booking: 0, series: 0 } };
if (fs.existsSync(DB_FILE)) db = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
function save() {
  const tmp = DB_FILE + '.' + process.pid + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(db));
  fs.renameSync(tmp, DB_FILE);
}

// ---------- helpers ----------
class HttpError extends Error { constructor(s, m, extra) { super(m); this.status = s; this.extra = extra; } }
const bad = (m) => { throw new HttpError(400, m); };
function send(res, status, body) {
  if (status === 204) { res.writeHead(204); return res.end(); }
  const s = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(s) });
  res.end(s);
}
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const iso = (ms) => new Date(ms).toISOString();

function hashPw(pw) {
  const salt = crypto.randomBytes(16);
  return salt.toString('hex') + ':' + crypto.scryptSync(pw, salt, 64).toString('hex');
}
function checkPw(pw, stored) {
  const [s, h] = stored.split(':');
  const a = crypto.scryptSync(pw, Buffer.from(s, 'hex'), 64), b = Buffer.from(h, 'hex');
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
const pubUser = (u) => ({ id: u.id, email: u.email, name: u.name, role: u.role });

// ---------- time zones ----------
const dtfCache = new Map();
function dtf(tz) {
  let f = dtfCache.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit',
      day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    dtfCache.set(tz, f);
  }
  return f;
}
function validTz(tz) {
  if (typeof tz !== 'string' || !tz) return false;
  try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); return true; } catch { return false; }
}
// UTC ms -> local wall parts
function localParts(ms, tz) {
  const p = {};
  for (const { type, value } of dtf(tz).formatToParts(new Date(ms))) p[type] = value;
  return { y: +p.year, mo: +p.month, d: +p.day, h: +p.hour % 24, mi: +p.minute, s: +p.second };
}
function offsetAt(ms, tz) { // local - utc, ms
  const p = localParts(ms, tz);
  return Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s) - Math.floor(ms / 1000) * 1000;
}
// local wall (y,mo,d, minutes-of-day) -> UTC ms; returns null if the wall time does not exist (DST gap)
function localToUtc(y, mo, d, mins, tz) {
  const wall = Date.UTC(y, mo - 1, d, 0, mins);
  const cands = new Set();
  for (const guess of [wall - offsetAt(wall, tz), wall - offsetAt(wall - 864e5, tz), wall - offsetAt(wall + 864e5, tz)]) {
    const t = wall - offsetAt(guess, tz);
    if (t + offsetAt(t, tz) === wall) cands.add(t);
  }
  if (!cands.size) return null;
  return Math.min(...cands); // ambiguous (DST fold): earlier instant
}
const ymdStr = (p) => `${String(p.y).padStart(4, '0')}-${String(p.mo).padStart(2, '0')}-${String(p.d).padStart(2, '0')}`;

// ---------- parsing ----------
const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|z|[+-]\d{2}:\d{2})$/;
function daysIn(y, m) { return new Date(Date.UTC(y, m, 0)).getUTCDate(); }
function parseIso(s) { // returns {ms, sec, frac} or null
  if (typeof s !== 'string') return null;
  const m = ISO_RE.exec(s);
  if (!m) return null;
  const [y, mo, d, h, mi] = [+m[1], +m[2], +m[3], +m[4], +m[5]];
  const sec = m[6] ? +m[6] : 0;
  const fracStr = m[7] || '';
  if (mo < 1 || mo > 12 || d < 1 || d > daysIn(y, mo) || h > 23 || mi > 59 || sec > 59) return null;
  let off = 0;
  if (m[8] !== 'Z' && m[8] !== 'z') {
    const oh = +m[8].slice(1, 3), om = +m[8].slice(4, 6);
    if (oh > 23 || om > 59) return null;
    off = (m[8][0] === '+' ? 1 : -1) * (oh * 60 + om) * 60000;
  }
  const fracMs = fracStr ? Math.floor(Number('0.' + fracStr) * 1000) : 0;
  return { ms: Date.UTC(y, mo - 1, d, h, mi, sec, fracMs) - off, exact: sec === 0 && !/[1-9]/.test(fracStr) };
}
const HM_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;
const hmToMin = (s) => { const m = HM_RE.exec(s); return m ? +m[1] * 60 + +m[2] : null; };
const minToHm = (n) => `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}`;
function parseDate(s) {
  const m = typeof s === 'string' && /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return null;
  const y = +m[1], mo = +m[2], d = +m[3];
  if (mo < 1 || mo > 12 || d < 1 || d > daysIn(y, mo)) return null;
  return { y, mo, d };
}

// ---------- domain ----------
const overlaps = (aS, aE, bS, bE) => aS < bE && bS < aE;
function roomBookings(roomId) { return db.bookings.filter((b) => b.roomId === roomId); }
function sortByStart(arr) { return arr.sort((a, b) => Date.parse(a.start) - Date.parse(b.start) || a.id - b.id); }

// validates occurrence; returns nothing or throws 400
function checkOccurrence(room, sMs, eMs, now) {
  if (!(eMs > sMs)) bad('end must be after start');
  const dur = (eMs - sMs) / 60000;
  if (dur < 15 || dur > 240) bad('duration must be between 15 minutes and 4 hours');
  const ls = localParts(sMs, room.timezone), le = localParts(eMs, room.timezone);
  if (ls.mi % 15 || le.mi % 15 || ls.s || le.s || sMs % 60000 || eMs % 60000) bad('start and end must be on 15-minute boundaries');
  if (ymdStr(ls) !== ymdStr(le)) bad('booking must start and end on the same local day');
  const open = hmToMin(room.openTime), close = hmToMin(room.closeTime);
  if (ls.h * 60 + ls.mi < open || le.h * 60 + le.mi > close) bad('booking outside opening hours');
  if (!(sMs > now)) bad('start must be in the future');
}

// ---------- routes ----------
function auth(req) {
  const h = req.headers.authorization || '';
  const m = /^Bearer\s+(\S+)$/i.exec(h);
  const uid = m && db.tokens[m[1]];
  const u = uid && db.users.find((x) => x.id === uid);
  if (!u) throw new HttpError(401, 'authentication required');
  return u;
}
function getRoom(id) {
  const r = /^\d+$/.test(id) ? db.rooms.find((x) => x.id === Number(id)) : null;
  if (!r) throw new HttpError(404, 'room not found');
  return r;
}
function getBooking(id) {
  const b = /^\d+$/.test(id) ? db.bookings.find((x) => x.id === Number(id)) : null;
  if (!b) throw new HttpError(404, 'booking not found');
  return b;
}
const requireAdmin = (u) => { if (u.role !== 'admin') throw new HttpError(403, 'admin only'); };
const INVALID_JSON = Symbol('invalid');
const requireBody = (b) => { if (b === INVALID_JSON) bad('invalid JSON'); if (!isObj(b)) bad('JSON object body required'); return b; };

async function handle(req, res, url, body) {
  const p = url.pathname, method = req.method, q = url.searchParams;
  let m;
  if (p === '/' && method === 'GET') {
    const html = fs.readFileSync(path.join(__dirname, 'index.html'));
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return res.end(html);
  }
  if (p === '/api/auth/register' && method === 'POST') {
    const b = requireBody(body);
    if (typeof b.email !== 'string' || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(b.email.trim())) bad('invalid email');
    if (typeof b.password !== 'string' || b.password.length < 8) bad('password must be at least 8 characters');
    if (typeof b.name !== 'string' || !b.name.trim() || b.name.trim().length > 50) bad('invalid name');
    const email = b.email.trim().toLowerCase();
    if (db.users.some((u) => u.email === email)) throw new HttpError(409, 'email already registered');
    const u = { id: ++db.seq.user, email, name: b.name.trim(), role: db.users.length === 0 ? 'admin' : 'member', password: hashPw(b.password) };
    db.users.push(u); save();
    return send(res, 201, pubUser(u));
  }
  if (p === '/api/auth/login' && method === 'POST') {
    const b = requireBody(body);
    const email = typeof b.email === 'string' ? b.email.trim().toLowerCase() : null;
    const u = email && db.users.find((x) => x.email === email);
    if (!u || typeof b.password !== 'string' || !checkPw(b.password, u.password)) throw new HttpError(401, 'invalid credentials');
    const token = crypto.randomBytes(32).toString('hex');
    db.tokens[token] = u.id; save();
    return send(res, 200, { token, user: pubUser(u) });
  }
  if (!p.startsWith('/api/')) throw new HttpError(404, 'not found');

  // route matching first so unknown routes are 404 even without auth? Auth applies to all /api/* -> check route existence after auth.
  const user = auth(req);
  const now = Date.now();

  if (p === '/api/rooms') {
    if (method === 'GET') return send(res, 200, [...db.rooms].sort((a, b) => a.id - b.id));
    if (method === 'POST') {
      requireAdmin(user);
      const b = requireBody(body);
      if (typeof b.name !== 'string' || !b.name.trim() || b.name.trim().length > 100) bad('invalid name');
      if (!validTz(b.timezone)) bad('invalid timezone');
      const o = typeof b.openTime === 'string' ? hmToMin(b.openTime) : null;
      const c = typeof b.closeTime === 'string' ? hmToMin(b.closeTime) : null;
      if (o === null || c === null || o % 15 || c % 15 || !(o < c)) bad('invalid opening hours');
      const name = b.name.trim();
      if (db.rooms.some((r) => r.name.toLowerCase() === name.toLowerCase())) throw new HttpError(409, 'room name already exists');
      const r = { id: ++db.seq.room, name, timezone: b.timezone, openTime: b.openTime, closeTime: b.closeTime, createdAt: iso(now) };
      db.rooms.push(r); save();
      return send(res, 201, r);
    }
    throw new HttpError(404, 'not found');
  }
  if ((m = /^\/api\/rooms\/([^/]+)$/.exec(p))) {
    if (method === 'GET') return send(res, 200, getRoom(m[1]));
    if (method === 'DELETE') {
      requireAdmin(user);
      const r = getRoom(m[1]);
      db.rooms = db.rooms.filter((x) => x.id !== r.id);
      db.bookings = db.bookings.filter((x) => x.roomId !== r.id);
      save();
      return send(res, 204);
    }
    throw new HttpError(404, 'not found');
  }
  if ((m = /^\/api\/rooms\/([^/]+)\/bookings$/.exec(p))) {
    const room = getRoom(m[1]);
    if (method === 'GET') {
      let from = -Infinity, to = Infinity;
      for (const [k, set] of [['from', (v) => (from = v)], ['to', (v) => (to = v)]]) {
        if (q.has(k)) {
          const v = q.get(k);
          const pi = parseIso(v); const pd = parseDate(v);
          let ms = pi ? pi.ms : pd ? Date.UTC(pd.y, pd.mo - 1, pd.d) : NaN;
          if (!Number.isFinite(ms)) bad(`invalid ${k}`);
          set(ms);
        }
      }
      if (from > to) bad('from must not be after to');
      return send(res, 200, sortByStart(roomBookings(room.id).filter((b) => overlaps(Date.parse(b.start), Date.parse(b.end), from, to))));
    }
    if (method === 'POST') {
      const b = requireBody(body);
      if (typeof b.title !== 'string' || !b.title.trim() || b.title.trim().length > 100) bad('invalid title');
      const ps = parseIso(b.start), pe = parseIso(b.end);
      if (!ps || !pe) bad('start and end must be ISO 8601 date-times with offset');
      if (!ps.exact || !pe.exact) bad('start and end must be on 15-minute boundaries');
      let freq = null, count = 1;
      if (b.recurrence !== undefined && b.recurrence !== null) {
        const rc = b.recurrence;
        if (!isObj(rc) || (rc.freq !== 'daily' && rc.freq !== 'weekly') || !Number.isInteger(rc.count) || rc.count < 1 || rc.count > 52) bad('invalid recurrence');
        freq = rc.freq; count = rc.count;
      }
      checkOccurrence(room, ps.ms, pe.ms, now);
      const tz = room.timezone;
      const ls = localParts(ps.ms, tz), le = localParts(pe.ms, tz);
      const sMin = ls.h * 60 + ls.mi, eMin = le.h * 60 + le.mi;
      const occ = [];
      for (let i = 0; i < count; i++) {
        if (i === 0) { occ.push([ps.ms, pe.ms]); continue; }
        const step = i * (freq === 'daily' ? 1 : 7);
        const day = new Date(Date.UTC(ls.y, ls.mo - 1, ls.d + step));
        const [y, mo, d] = [day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate()];
        const s = localToUtc(y, mo, d, sMin, tz), e = localToUtc(y, mo, d, eMin, tz);
        if (s === null || e === null) bad(`occurrence on ${ymdStr({ y, mo, d })} falls in a non-existent local time`);
        checkOccurrence(room, s, e, now);
        occ.push([s, e]);
      }
      const existing = roomBookings(room.id).map((x) => [Date.parse(x.start), Date.parse(x.end)]);
      const conflicts = occ.filter(([s, e]) => existing.some(([xs, xe]) => overlaps(s, e, xs, xe))).map(([s]) => iso(s));
      if (conflicts.length) throw new HttpError(409, 'booking conflicts with existing bookings', { conflicts });
      const seriesId = freq ? ++db.seq.series : null;
      const created = occ.map(([s, e]) => ({ id: ++db.seq.booking, roomId: room.id, userId: user.id, title: b.title.trim(), start: iso(s), end: iso(e), seriesId }));
      db.bookings.push(...created); save();
      return send(res, 201, created);
    }
    throw new HttpError(404, 'not found');
  }
  if ((m = /^\/api\/rooms\/([^/]+)\/availability$/.exec(p)) && method === 'GET') {
    const room = getRoom(m[1]);
    const date = parseDate(q.get('date'));
    if (!date) bad('invalid date');
    const ds = q.get('duration');
    const dur = ds !== null && /^\d+$/.test(ds) ? Number(ds) : NaN;
    if (!(dur >= 15 && dur <= 240 && dur % 15 === 0)) bad('invalid duration');
    const tz = room.timezone, open = hmToMin(room.openTime), close = hmToMin(room.closeTime);
    const existing = roomBookings(room.id).map((x) => [Date.parse(x.start), Date.parse(x.end)]);
    const slots = [];
    for (let t = open; t + dur <= close; t += 15) {
      const s = localToUtc(date.y, date.mo, date.d, t, tz), e = localToUtc(date.y, date.mo, date.d, t + dur, tz);
      if (s === null || e === null || !(e > s) || !(s > now)) continue;
      if (existing.some(([xs, xe]) => overlaps(s, e, xs, xe))) continue;
      slots.push(minToHm(t));
    }
    return send(res, 200, { date: q.get('date'), timezone: tz, slots });
  }
  if ((m = /^\/api\/bookings\/([^/]+)$/.exec(p))) {
    if (method === 'GET') return send(res, 200, getBooking(m[1]));
    if (method === 'DELETE') {
      const bk = getBooking(m[1]);
      if (bk.userId !== user.id && user.role !== 'admin') throw new HttpError(403, 'forbidden');
      const scope = q.has('scope') ? q.get('scope') : 'single';
      if (scope !== 'single' && scope !== 'series') bad('invalid scope');
      if (scope === 'series' && bk.seriesId !== null) {
        const st = Date.parse(bk.start);
        db.bookings = db.bookings.filter((x) => !(x.seriesId === bk.seriesId && Date.parse(x.start) >= st));
      } else db.bookings = db.bookings.filter((x) => x.id !== bk.id);
      save();
      return send(res, 204);
    }
    throw new HttpError(404, 'not found');
  }
  if (p === '/api/me/bookings' && method === 'GET') return send(res, 200, sortByStart(db.bookings.filter((b) => b.userId === user.id)));
  throw new HttpError(404, 'not found');
}

const server = http.createServer((req, res) => {
  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', async () => {
    try {
      const url = new URL(req.url, 'http://localhost');
      let body;
      const raw = Buffer.concat(chunks).toString('utf8');
      if (raw.trim()) { try { body = JSON.parse(raw); } catch { body = INVALID_JSON; } }
      await handle(req, res, url, body);
    } catch (e) {
      if (e instanceof HttpError) send(res, e.status, { error: e.message, ...(e.extra || {}) });
      else { console.error(e); send(res, 500, { error: 'internal error' }); }
    }
  });
});
server.listen(PORT, '0.0.0.0', () => console.log(`booking listening on ${PORT}, data in ${DATA_DIR}`));
