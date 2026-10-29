'use strict';
const http = require('node:http');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const PORT = Number(process.env.PORT) || 3000;
const DATA_DIR = path.resolve(process.env.DATA_DIR || './data');
const DB_FILE = path.join(DATA_DIR, 'db.json');
fs.mkdirSync(DATA_DIR, { recursive: true });

// ---------- storage ----------
let db = { seq: { user: 0, board: 0, card: 0 }, users: [], boards: [], cards: [], tokens: {} };
if (fs.existsSync(DB_FILE)) db = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
function save() {
  const tmp = DB_FILE + '.' + process.pid + '.tmp';
  const fd = fs.openSync(tmp, 'w');
  fs.writeSync(fd, JSON.stringify(db));
  fs.fsyncSync(fd);
  fs.closeSync(fd);
  fs.renameSync(tmp, DB_FILE);
}
const nextId = (k) => ++db.seq[k];
const now = () => new Date().toISOString();
const sha = (s) => crypto.createHash('sha256').update(s).digest('hex');

function hashPassword(pw) {
  const salt = crypto.randomBytes(16);
  const h = crypto.scryptSync(pw, salt, 64);
  return 'scrypt$' + salt.toString('hex') + '$' + h.toString('hex');
}
function verifyPassword(pw, stored) {
  const [, s, h] = stored.split('$');
  const calc = crypto.scryptSync(pw, Buffer.from(s, 'hex'), 64);
  return crypto.timingSafeEqual(calc, Buffer.from(h, 'hex'));
}

// ---------- helpers ----------
class HttpError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
const fail = (status, msg) => { throw new HttpError(status, msg); };
function send(res, status, body) {
  if (body === undefined) { res.writeHead(status); return res.end(); }
  const data = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(data) });
  res.end(data);
}
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []; let size = 0;
    req.on('data', (c) => { size += c.length; if (size > 1e6) { reject(new HttpError(413, 'Body too large')); req.destroy(); } else chunks.push(c); });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}
async function jsonBody(req) {
  const raw = await readBody(req);
  if (!raw.trim()) return {};
  let v;
  try { v = JSON.parse(raw); } catch { fail(400, 'Invalid JSON body'); }
  if (v === null || typeof v !== 'object' || Array.isArray(v)) fail(400, 'Body must be a JSON object');
  return v;
}
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const COLUMNS = ['todo', 'doing', 'done'];

const pubUser = (u) => ({ id: u.id, email: u.email });
const pubBoard = (b) => ({ id: b.id, name: b.name, ownerId: b.ownerId, wipLimit: b.wipLimit, createdAt: b.createdAt });
const pubCard = (c) => ({ id: c.id, boardId: c.boardId, title: c.title, description: c.description, column: c.column,
  position: c.position, createdBy: c.createdBy, createdAt: c.createdAt, updatedAt: c.updatedAt });
function membersOf(b) {
  const ids = new Set([b.ownerId, ...b.memberIds]);
  return db.users.filter((u) => ids.has(u.id)).sort((a, b2) => a.id - b2.id).map(pubUser);
}
function canAccess(b, uid) { return b.ownerId === uid || b.memberIds.includes(uid); }
function parseId(s) { return /^[1-9]\d*$/.test(s) ? Number(s) : null; }
function getBoard(idStr, user, ownerOnly) {
  const id = parseId(idStr);
  const b = id && db.boards.find((x) => x.id === id);
  if (!b) fail(404, 'Board not found');
  if (!canAccess(b, user.id)) fail(403, 'No access to this board');
  if (ownerOnly && b.ownerId !== user.id) fail(403, 'Only the board owner can do this');
  return b;
}
function getCard(idStr, user) {
  const id = parseId(idStr);
  const c = id && db.cards.find((x) => x.id === id);
  if (!c) fail(404, 'Card not found');
  const b = db.boards.find((x) => x.id === c.boardId);
  if (!canAccess(b, user.id)) fail(403, 'No access to this card');
  return { c, b };
}
function columnCards(boardId, column, excludeId) {
  return db.cards.filter((x) => x.boardId === boardId && x.column === column && x.id !== excludeId)
    .sort((a, b) => a.position - b.position);
}
function reindex(list) { list.forEach((c, i) => { c.position = i; }); }
function validName(v, max) { return typeof v === 'string' && v.trim().length > 0 && v.trim().length <= max; }
function validWip(v) { return v === null || (Number.isInteger(v) && v >= 1); }

function authUser(req) {
  const h = req.headers.authorization || '';
  const m = /^Bearer\s+(\S+)$/i.exec(h);
  if (!m) fail(401, 'Missing or invalid token');
  const uid = db.tokens[sha(m[1])];
  const u = uid && db.users.find((x) => x.id === uid);
  if (!u) fail(401, 'Missing or invalid token');
  return { user: u, tokenKey: sha(m[1]) };
}

// ---------- routes ----------
const routes = [];
const route = (method, pattern, handler, auth = true) => {
  const keys = [];
  const re = new RegExp('^' + pattern.replace(/:(\w+)/g, (_, k) => { keys.push(k); return '([^/]+)'; }) + '/?$');
  routes.push({ method, re, keys, handler, auth });
};

route('POST', '/api/auth/register', async (req) => {
  const b = await jsonBody(req);
  if (typeof b.email !== 'string' || !EMAIL_RE.test(b.email.trim())) fail(400, 'Invalid email');
  if (typeof b.password !== 'string' || b.password.length < 8) fail(400, 'Password must be at least 8 characters');
  const email = b.email.trim().toLowerCase();
  if (db.users.some((u) => u.email === email)) fail(409, 'Email already registered');
  const u = { id: nextId('user'), email, passwordHash: hashPassword(b.password), createdAt: now() };
  db.users.push(u); save();
  return [201, pubUser(u)];
}, false);

route('POST', '/api/auth/login', async (req) => {
  const b = await jsonBody(req);
  if (typeof b.email !== 'string' || typeof b.password !== 'string') fail(401, 'Invalid credentials');
  const u = db.users.find((x) => x.email === b.email.trim().toLowerCase());
  if (!u || !verifyPassword(b.password, u.passwordHash)) fail(401, 'Invalid credentials');
  const token = crypto.randomBytes(32).toString('hex');
  db.tokens[sha(token)] = u.id; save();
  return [200, { token, user: pubUser(u) }];
}, false);

route('POST', '/api/auth/logout', async (req, p, ctx) => { delete db.tokens[ctx.tokenKey]; save(); return [204]; });
route('GET', '/api/me', async (req, p, ctx) => [200, pubUser(ctx.user)]);

route('POST', '/api/boards', async (req, p, { user }) => {
  const b = await jsonBody(req);
  if (!validName(b.name, 100)) fail(400, 'name is required (max 100 chars)');
  const wip = has(b, 'wipLimit') ? b.wipLimit : null;
  if (!validWip(wip)) fail(400, 'wipLimit must be an integer >= 1 or null');
  const board = { id: nextId('board'), name: b.name.trim(), ownerId: user.id, wipLimit: wip, createdAt: now(), memberIds: [] };
  db.boards.push(board); save();
  return [201, pubBoard(board)];
});
route('GET', '/api/boards', async (req, p, { user }) =>
  [200, db.boards.filter((b) => canAccess(b, user.id)).sort((a, b) => a.id - b.id).map(pubBoard)]);
route('GET', '/api/boards/:id', async (req, p, { user }) => {
  const b = getBoard(p.id, user);
  return [200, { ...pubBoard(b), members: membersOf(b) }];
});
route('PATCH', '/api/boards/:id', async (req, p, { user }) => {
  const b = getBoard(p.id, user, true);
  const body = await jsonBody(req);
  if (has(body, 'name') && !validName(body.name, 100)) fail(400, 'name must be non-empty (max 100 chars)');
  if (has(body, 'wipLimit') && !validWip(body.wipLimit)) fail(400, 'wipLimit must be an integer >= 1 or null');
  if (has(body, 'name')) b.name = body.name.trim();
  if (has(body, 'wipLimit')) b.wipLimit = body.wipLimit;
  save();
  return [200, pubBoard(b)];
});
route('DELETE', '/api/boards/:id', async (req, p, { user }) => {
  const b = getBoard(p.id, user, true);
  db.boards = db.boards.filter((x) => x !== b);
  db.cards = db.cards.filter((c) => c.boardId !== b.id);
  save(); return [204];
});
route('POST', '/api/boards/:id/members', async (req, p, { user }) => {
  const b = getBoard(p.id, user, true);
  const body = await jsonBody(req);
  if (typeof body.email !== 'string' || !body.email.trim()) fail(400, 'email is required');
  const u = db.users.find((x) => x.email === body.email.trim().toLowerCase());
  if (!u) fail(404, 'User not found');
  if (u.id === b.ownerId || b.memberIds.includes(u.id)) fail(409, 'User already has access');
  b.memberIds.push(u.id); save();
  return [201, membersOf(b)];
});
route('DELETE', '/api/boards/:id/members/:userId', async (req, p, { user }) => {
  const b = getBoard(p.id, user, true);
  const uid = parseId(p.userId);
  if (uid === b.ownerId) fail(400, 'The owner cannot be removed');
  if (!uid || !b.memberIds.includes(uid)) fail(404, 'Member not found');
  b.memberIds = b.memberIds.filter((x) => x !== uid); save();
  return [204];
});

route('POST', '/api/boards/:id/cards', async (req, p, { user }) => {
  const b = getBoard(p.id, user);
  const body = await jsonBody(req);
  if (!validName(body.title, 200)) fail(400, 'title is required (max 200 chars)');
  if (has(body, 'description') && typeof body.description !== 'string') fail(400, 'description must be a string');
  const column = has(body, 'column') ? body.column : 'todo';
  if (!COLUMNS.includes(column)) fail(400, 'Invalid column');
  const list = columnCards(b.id, column);
  if (column === 'doing' && b.wipLimit !== null && list.length + 1 > b.wipLimit) fail(409, 'WIP limit reached');
  const t = now();
  const c = { id: nextId('card'), boardId: b.id, title: body.title.trim(), description: body.description ?? '',
    column, position: list.length, createdBy: user.id, createdAt: t, updatedAt: t };
  db.cards.push(c); save();
  return [201, pubCard(c)];
});
route('GET', '/api/boards/:id/cards', async (req, p, { user }) => {
  const b = getBoard(p.id, user);
  const out = {};
  for (const col of COLUMNS) out[col] = columnCards(b.id, col).map(pubCard);
  return [200, out];
});
route('PATCH', '/api/cards/:id', async (req, p, { user }) => {
  const { c, b } = getCard(p.id, user);
  const body = await jsonBody(req);
  if (has(body, 'title') && !validName(body.title, 200)) fail(400, 'title must be non-empty (max 200 chars)');
  if (has(body, 'description') && typeof body.description !== 'string') fail(400, 'description must be a string');
  if (has(body, 'column') && !COLUMNS.includes(body.column)) fail(400, 'Invalid column');
  if (has(body, 'position') && !Number.isInteger(body.position)) fail(400, 'position must be an integer');
  const target = has(body, 'column') ? body.column : c.column;
  const moving = target !== c.column;
  const others = columnCards(b.id, target, c.id);
  if (moving && target === 'doing' && b.wipLimit !== null && others.length + 1 > b.wipLimit) fail(409, 'WIP limit reached');
  if (has(body, 'title')) c.title = body.title.trim();
  if (has(body, 'description')) c.description = body.description;
  if (moving || has(body, 'position')) {
    let pos = has(body, 'position') ? body.position : others.length;
    pos = Math.max(0, Math.min(others.length, pos));
    const source = c.column;
    others.splice(pos, 0, c);
    c.column = target;
    reindex(others);
    if (moving) reindex(columnCards(b.id, source));
  }
  c.updatedAt = now(); save();
  return [200, pubCard(c)];
});
route('DELETE', '/api/cards/:id', async (req, p, { user }) => {
  const { c } = getCard(p.id, user);
  db.cards = db.cards.filter((x) => x !== c);
  reindex(columnCards(c.boardId, c.column));
  save(); return [204];
});

const INDEX = fs.readFileSync(path.join(__dirname, 'index.html'));

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://x');
    const pathname = url.pathname;
    if (req.method === 'GET' && (pathname === '/' || pathname === '/index.html')) {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); return res.end(INDEX);
    }
    let matchedPath = false;
    for (const r of routes) {
      const m = r.re.exec(pathname);
      if (!m) continue;
      matchedPath = true;
      if (r.method !== req.method) continue;
      const params = {}; r.keys.forEach((k, i) => { params[k] = decodeURIComponent(m[i + 1]); });
      const ctx = r.auth ? authUser(req) : {};
      const [status, body] = await r.handler(req, params, ctx);
      return send(res, status, body);
    }
    if (matchedPath) {
      // known path, wrong method: still require auth on /api/*, then 404 (unknown route)
      if (pathname.startsWith('/api/') && !pathname.startsWith('/api/auth/')) authUser(req);
      fail(404, 'Not found');
    }
    if (pathname.startsWith('/api/') && !pathname.startsWith('/api/auth/')) authUser(req);
    fail(404, 'Not found');
  } catch (e) {
    if (e instanceof HttpError) return send(res, e.status, { error: e.message });
    console.error(e);
    send(res, 500, { error: 'Internal server error' });
  }
});
server.listen(PORT, '0.0.0.0', () => console.log(`Kanban listening on ${PORT}, data in ${DATA_DIR}`));
