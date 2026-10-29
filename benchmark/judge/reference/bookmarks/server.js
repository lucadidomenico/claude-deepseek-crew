'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const PORT = Number(process.env.PORT) || 3000;
const DATA_DIR = path.resolve(process.env.DATA_DIR || './data');
const DB_FILE = path.join(DATA_DIR, 'bookmarks.json');
fs.mkdirSync(DATA_DIR, { recursive: true });

let db = { nextId: 1, bookmarks: [] };
try { db = JSON.parse(fs.readFileSync(DB_FILE, 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }

function save() {
  const tmp = DB_FILE + '.' + process.pid + '.tmp';
  const fd = fs.openSync(tmp, 'w');
  fs.writeSync(fd, JSON.stringify(db));
  fs.fsyncSync(fd); fs.closeSync(fd);
  fs.renameSync(tmp, DB_FILE);
}

class HttpError extends Error { constructor(s, m) { super(m); this.status = s; } }
const bad = (m) => new HttpError(400, m);

function send(res, status, body, headers = {}) {
  if (status === 204) { res.writeHead(204, headers); return res.end(); }
  const data = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(data), ...headers });
  res.end(data);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []; let size = 0;
    req.on('data', (c) => { size += c.length; if (size > 1e6) { reject(new HttpError(413, 'Body too large')); req.destroy(); } else chunks.push(c); });
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (!raw.trim()) return reject(bad('Request body must be a JSON object'));
      let v; try { v = JSON.parse(raw); } catch { return reject(bad('Invalid JSON')); }
      if (v === null || typeof v !== 'object' || Array.isArray(v)) return reject(bad('Request body must be a JSON object'));
      resolve(v);
    });
    req.on('error', reject);
  });
}

function vUrl(u) {
  if (typeof u !== 'string') throw bad('url is required and must be a string');
  if (!/^https?:\/\//.test(u)) throw bad('url must start with http:// or https://');
  if (u.length > 2000) throw bad('url must be at most 2000 characters');
  return u;
}
function vTitle(t) {
  if (typeof t !== 'string') throw bad('title is required and must be a string');
  const s = t.trim();
  if (!s) throw bad('title must not be empty');
  if (s.length > 200) throw bad('title must be at most 200 characters');
  return s;
}
function vTags(tags) {
  if (!Array.isArray(tags)) throw bad('tags must be an array of strings');
  const set = new Set();
  for (const t of tags) {
    if (typeof t !== 'string') throw bad('tags must be an array of strings');
    const s = t.trim().toLowerCase();
    if (s.length > 30) throw bad('each tag must be at most 30 characters');
    if (s) set.add(s);
  }
  if (set.size > 10) throw bad('at most 10 tags allowed');
  return [...set].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}
function urlTaken(url, exceptId) { return db.bookmarks.some((b) => b.url === url && b.id !== exceptId); }

function parseIntParam(v, name, def, min, max) {
  if (v === null) return def;
  if (!/^\d+$/.test(v)) throw bad(`${name} must be a non-negative integer`);
  const n = Number(v);
  if (n < min || (max !== undefined && n > max)) throw bad(`${name} out of range`);
  return n;
}

const byCreatedDesc = (a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : b.id - a.id);

function csvField(v) {
  const s = String(v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

let lastTs = 0;
function nowIso() { let t = Date.now(); if (t <= lastTs) t = lastTs + 1; lastTs = t; return new Date(t).toISOString(); }

const HTML = fs.readFileSync(path.join(__dirname, 'index.html'));

async function handle(req, res) {
  const u = new URL(req.url, 'http://localhost');
  const p = u.pathname.replace(/\/+$/, '') || '/';
  const m = req.method;

  if (p === '/' && (m === 'GET' || m === 'HEAD')) {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Content-Length': HTML.length });
    return res.end(m === 'HEAD' ? undefined : HTML);
  }

  if (p === '/api/bookmarks') {
    if (m === 'POST') {
      const body = await readBody(req);
      const url = vUrl(body.url);
      const title = vTitle(body.title);
      const tags = body.tags === undefined ? [] : vTags(body.tags);
      if (urlTaken(url)) throw new HttpError(409, 'A bookmark with this url already exists');
      const ts = nowIso();
      const bm = { id: db.nextId++, url, title, tags, createdAt: ts, updatedAt: ts };
      db.bookmarks.push(bm); save();
      return send(res, 201, bm);
    }
    if (m === 'GET') {
      const sp = u.searchParams;
      const limit = parseIntParam(sp.get('limit'), 'limit', 50, 1, 100);
      const offset = parseIntParam(sp.get('offset'), 'offset', 0, 0);
      let list = db.bookmarks.slice();
      const tag = sp.get('tag');
      if (tag !== null && tag.trim() !== '') { const t = tag.trim().toLowerCase(); list = list.filter((b) => b.tags.includes(t)); }
      const q = sp.get('q');
      if (q !== null && q !== '') { const ql = q.toLowerCase(); list = list.filter((b) => b.title.toLowerCase().includes(ql) || b.url.toLowerCase().includes(ql)); }
      list.sort(byCreatedDesc);
      return send(res, 200, list.slice(offset, offset + limit), { 'X-Total-Count': String(list.length), 'Access-Control-Expose-Headers': 'X-Total-Count' });
    }
    throw new HttpError(405, 'Method not allowed');
  }

  const mm = p.match(/^\/api\/bookmarks\/([^/]+)$/);
  if (mm) {
    const id = /^\d+$/.test(mm[1]) ? Number(mm[1]) : NaN;
    const idx = db.bookmarks.findIndex((b) => b.id === id);
    if (m === 'GET') { if (idx < 0) throw new HttpError(404, 'Bookmark not found'); return send(res, 200, db.bookmarks[idx]); }
    if (m === 'DELETE') { if (idx < 0) throw new HttpError(404, 'Bookmark not found'); db.bookmarks.splice(idx, 1); save(); return send(res, 204); }
    if (m === 'PATCH') {
      if (idx < 0) throw new HttpError(404, 'Bookmark not found');
      const body = await readBody(req);
      const cur = db.bookmarks[idx];
      const upd = {};
      if ('url' in body) upd.url = vUrl(body.url);
      if ('title' in body) upd.title = vTitle(body.title);
      if ('tags' in body) upd.tags = vTags(body.tags);
      if (upd.url !== undefined && urlTaken(upd.url, cur.id)) throw new HttpError(409, 'A bookmark with this url already exists');
      Object.assign(cur, upd, { updatedAt: nowIso() }); save();
      return send(res, 200, cur);
    }
    throw new HttpError(405, 'Method not allowed');
  }

  if (p === '/api/tags' && m === 'GET') {
    const counts = new Map();
    for (const b of db.bookmarks) for (const t of b.tags) counts.set(t, (counts.get(t) || 0) + 1);
    const out = [...counts].map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => b.count - a.count || (a.tag < b.tag ? -1 : a.tag > b.tag ? 1 : 0));
    return send(res, 200, out);
  }

  if (p === '/api/export' && m === 'GET') {
    const rows = ['id,url,title,tags,createdAt'];
    for (const b of db.bookmarks.slice().sort((a, b) => a.id - b.id))
      rows.push([b.id, b.url, b.title, b.tags.join('|'), b.createdAt].map(csvField).join(','));
    const data = rows.join('\r\n') + '\r\n';
    res.writeHead(200, { 'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': 'attachment; filename="bookmarks.csv"', 'Content-Length': Buffer.byteLength(data) });
    return res.end(data);
  }

  throw new HttpError(404, 'Not found');
}

http.createServer((req, res) => {
  handle(req, res).catch((e) => {
    if (res.headersSent) return res.end();
    if (e instanceof HttpError) return send(res, e.status, { error: e.message });
    console.error(e); send(res, 500, { error: 'Internal server error' });
  });
}).listen(PORT, '0.0.0.0', () => console.log(`Bookmarks listening on ${PORT}, data in ${DATA_DIR}`));
