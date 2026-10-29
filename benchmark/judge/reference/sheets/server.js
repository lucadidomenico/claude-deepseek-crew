'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const eng = require('./engine');

const PORT = parseInt(process.env.PORT || '3000', 10);
const DATA_DIR = path.resolve(process.env.DATA_DIR || './data');
const DB_FILE = path.join(DATA_DIR, 'db.json');
fs.mkdirSync(DATA_DIR, { recursive: true });

let seq = 0;
const sheets = new Map(); // id -> eng.Sheet
if (fs.existsSync(DB_FILE)) {
  const db = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
  seq = db.seq || 0;
  for (const s of db.sheets || []) sheets.set(s.id, new eng.Sheet(s.id, s.name, s.cells));
}
function save() {
  const db = { seq, sheets: [...sheets.values()].map((s) => ({ id: s.id, name: s.name, cells: s.inputs() })) };
  const tmp = DB_FILE + '.' + process.pid + '.tmp';
  const fd = fs.openSync(tmp, 'w');
  fs.writeSync(fd, JSON.stringify(db));
  fs.fsyncSync(fd); fs.closeSync(fd);
  fs.renameSync(tmp, DB_FILE);
}

class HttpError extends Error { constructor(s, m) { super(m); this.status = s; } }
const bad = (m) => { throw new HttpError(400, m); };
const notFound = (m) => { throw new HttpError(404, m || 'not found'); };

function send(res, status, body, type) {
  if (body === undefined) { res.writeHead(status); return res.end(); }
  const data = type ? body : JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': type || 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(data) });
  res.end(data);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (!raw.trim()) return resolve(undefined);
      try { resolve(JSON.parse(raw)); } catch { reject(new HttpError(400, 'invalid JSON body')); }
    });
    req.on('error', reject);
  });
}
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isInt = (v) => typeof v === 'number' && Number.isInteger(v);

function cellView(sheet, r, c) {
  const cell = sheet.cells.get(eng.key(r, c));
  return Object.assign({ input: cell ? cell.input : '' }, eng.publicValue(cell ? cell.value : eng.EMPTY));
}
function sheetView(sheet) {
  const cells = {};
  for (const cell of [...sheet.cells.values()].sort((a, b) => a.r - b.r || a.c - b.c)) {
    cells[eng.refName(cell.r, cell.c)] = Object.assign({ input: cell.input }, eng.publicValue(cell.value));
  }
  return { id: sheet.id, name: sheet.name, cells };
}
const validInput = (v) => typeof v === 'string' && v.length <= 1000;

function csvField(s) { return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }
function exportCsv(sheet) {
  let maxR = 0, maxC = -1;
  for (const cell of sheet.cells.values()) { if (cell.r > maxR) maxR = cell.r; if (cell.c > maxC) maxC = cell.c; }
  let out = '';
  for (let r = 1; r <= maxR; r++) {
    const row = [];
    for (let c = 0; c <= maxC; c++) {
      const v = sheet.get(r, c);
      let s;
      if (v === eng.EMPTY) s = '';
      else if (eng.isErr(v)) s = v.code;
      else if (typeof v === 'boolean') s = v ? 'TRUE' : 'FALSE';
      else s = String(v);
      row.push(csvField(s));
    }
    out += row.join(',') + '\r\n';
  }
  return out;
}

const INDEX_HTML = fs.readFileSync(path.join(__dirname, 'public', 'index.html'));

async function handle(req, res) {
  const url = new URL(req.url, 'http://x');
  let parts;
  try { parts = url.pathname.split('/').filter(Boolean).map(decodeURIComponent); } catch { notFound(); }
  const m = req.method;

  if (parts.length === 0 && (m === 'GET' || m === 'HEAD')) {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Content-Length': INDEX_HTML.length });
    return res.end(m === 'HEAD' ? undefined : INDEX_HTML);
  }
  if (parts[0] !== 'api' || parts[1] !== 'sheets') notFound();

  if (parts.length === 2) {
    if (m === 'GET') return send(res, 200, [...sheets.values()].sort((a, b) => a.id - b.id).map((s) => ({ id: s.id, name: s.name })));
    if (m === 'POST') {
      const body = await readBody(req);
      if (!isObj(body) || typeof body.name !== 'string') bad('name is required');
      const name = body.name.trim();
      if (!name || name.length > 100) bad('name must be 1-100 characters');
      const s = new eng.Sheet(++seq, name, {});
      sheets.set(s.id, s); save();
      return send(res, 201, { id: s.id, name: s.name });
    }
    notFound();
  }

  if (!/^\d+$/.test(parts[2])) notFound('sheet not found');
  const sheet = sheets.get(parseInt(parts[2], 10));
  const route = parts.slice(3).join('/');
  const known = ['', 'cells', 'rows/insert', 'rows/delete', 'copy', 'export.csv'];
  const isCellRoute = parts.length === 5 && parts[3] === 'cells';
  if (!known.includes(route) && !isCellRoute) notFound();
  if (!sheet) notFound('sheet not found');

  if (route === '') {
    if (m === 'GET') return send(res, 200, sheetView(sheet));
    if (m === 'DELETE') { sheets.delete(sheet.id); save(); return send(res, 204); }
    notFound();
  }

  if (isCellRoute) {
    if (m !== 'GET' && m !== 'PUT') notFound();
    const p = eng.parseCellRef(parts[4]);
    if (!p) bad('invalid cell reference');
    const ref = eng.refName(p.r, p.c);
    if (m === 'PUT') {
      const body = await readBody(req);
      if (!isObj(body) || !validInput(body.input)) bad('input must be a string of at most 1000 characters');
      sheet.setInput(p.r, p.c, body.input);
      sheet.recalc(); save();
    }
    return send(res, 200, Object.assign({ ref }, cellView(sheet, p.r, p.c)));
  }

  if (route === 'export.csv') {
    if (m !== 'GET') notFound();
    return send(res, 200, exportCsv(sheet), 'text/csv; charset=utf-8');
  }

  if (m !== 'POST') notFound();
  const body = await readBody(req);
  if (!isObj(body)) bad('JSON object body required');

  if (route === 'cells') {
    if (!isObj(body.cells)) bad('cells must be an object');
    const writes = [];
    for (const k of Object.keys(body.cells)) {
      const p = eng.parseCellRef(k);
      if (!p) bad('invalid cell reference: ' + k);
      if (!validInput(body.cells[k])) bad('invalid input for ' + k);
      writes.push([p, body.cells[k]]);
    }
    for (const [p, input] of writes) sheet.setInput(p.r, p.c, input);
    sheet.recalc(); save();
    const cells = {};
    for (const [p] of writes) cells[eng.refName(p.r, p.c)] = cellView(sheet, p.r, p.c);
    return send(res, 200, { cells });
  }

  if (route === 'rows/insert' || route === 'rows/delete') {
    const { at, count } = body;
    if (!isInt(at) || at < 1 || at > eng.NROWS) bad('at must be an integer between 1 and 1000');
    if (!isInt(count) || count < 1) bad('count must be a positive integer');
    if (route === 'rows/insert') eng.insertRows(sheet, at, count); else eng.deleteRows(sheet, at, count);
    save();
    return send(res, 200, { ok: true });
  }

  if (route === 'copy') {
    if (typeof body.from !== 'string' || typeof body.to !== 'string') bad('from and to are required');
    const fp = body.from.split(':');
    if (fp.length > 2) bad('invalid from');
    const a = eng.parseCellRef(fp[0], true), b = fp.length === 2 ? eng.parseCellRef(fp[1], true) : a;
    if (!a || !b) bad('invalid from');
    const to = eng.parseCellRef(body.to, true);
    if (!to) bad('invalid to');
    eng.copyBlock(sheet, { r1: Math.min(a.r, b.r), r2: Math.max(a.r, b.r), c1: Math.min(a.c, b.c), c2: Math.max(a.c, b.c) }, to);
    save();
    return send(res, 200, { ok: true });
  }
  notFound();
}

http.createServer((req, res) => {
  handle(req, res).catch((err) => {
    if (err instanceof HttpError) return send(res, err.status, { error: err.message });
    console.error(err); send(res, 500, { error: 'internal error' });
  });
}).listen(PORT, '0.0.0.0', () => console.log(`sheets listening on ${PORT}, data in ${DATA_DIR}`));
