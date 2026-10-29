'use strict';
// Spreadsheet formula engine: tokenizer (with source positions), parser, evaluator,
// static dependency graph + Tarjan SCC cycle detection, structural rewrites.

const NCOLS = 26, NROWS = 1000;

class ErrV { constructor(code) { this.code = code; } }
const E = {
  DIV: new ErrV('#DIV/0!'), VALUE: new ErrV('#VALUE!'), REF: new ErrV('#REF!'), NAME: new ErrV('#NAME?'),
  NUM: new ErrV('#NUM!'), CYCLE: new ErrV('#CYCLE!'), ERROR: new ErrV('#ERROR!'),
};
const ERR_BY_CODE = {};
for (const k in E) ERR_BY_CODE[E[k].code] = E[k];
const EMPTY = Symbol('empty');
const isErr = (v) => v instanceof ErrV;

const key = (r, c) => r * 32 + c;
const colName = (c) => String.fromCharCode(65 + c);
const refName = (r, c) => colName(c) + r;
const inGrid = (r, c) => Number.isInteger(r) && Number.isInteger(c) && r >= 1 && r <= NROWS && c >= 0 && c < NCOLS;

// Parse a plain cell ref like "b7" (API usage). Returns {r,c} or null.
function parseCellRef(s, allowDollar) {
  if (typeof s !== 'string') return null;
  const m = (allowDollar ? /^\$?([A-Za-z])\$?(\d+)$/ : /^([A-Za-z])(\d+)$/).exec(s);
  if (!m) return null;
  const r = parseInt(m[2], 10), c = m[1].toUpperCase().charCodeAt(0) - 65;
  return inGrid(r, c) ? { r, c } : null;
}

// ---------------------------------------------------------------- tokenizer
const NUM_RE = /(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?/y;
const REF_RE = /(\$?)([A-Za-z]+)(\$?)(\d+)/y;
const IDENT_RE = /[A-Za-z_][A-Za-z0-9_.]*/y;
const ERRLIT_RE = /#(REF!|DIV\/0!|VALUE!|NAME\?|NUM!|CYCLE!|ERROR!)/iy;
const isIdentChar = (ch) => ch !== undefined && /[A-Za-z0-9_.$]/.test(ch);

function nextNonSpace(src, i) {
  while (i < src.length && /\s/.test(src[i])) i++;
  return src[i];
}

// Never throws; unknown characters produce BAD tokens (the parser reports them).
function tokenize(src, offset = 0) {
  const toks = [];
  let i = 0;
  const push = (t, s, e, extra) => toks.push(Object.assign({ t, s: s + offset, e: e + offset }, extra));
  while (i < src.length) {
    const ch = src[i];
    if (/\s/.test(ch)) { i++; continue; }
    if (/[0-9]/.test(ch) || (ch === '.' && /[0-9]/.test(src[i + 1] || ''))) {
      NUM_RE.lastIndex = i; const m = NUM_RE.exec(src);
      push('NUM', i, i + m[0].length, { v: Number(m[0]) }); i += m[0].length; continue;
    }
    if (ch === '"') {
      let j = i + 1, s = '', closed = false;
      while (j < src.length) {
        if (src[j] === '"') { if (src[j + 1] === '"') { s += '"'; j += 2; continue; } closed = true; j++; break; }
        s += src[j++];
      }
      push(closed ? 'STR' : 'BAD', i, j, { v: s }); i = j; continue;
    }
    if (ch === '#') {
      ERRLIT_RE.lastIndex = i; const m = ERRLIT_RE.exec(src);
      if (m) { push('ERR', i, i + m[0].length, { code: m[0].toUpperCase() }); i += m[0].length; continue; }
      push('BAD', i, i + 1); i++; continue;
    }
    if (ch === '$' || /[A-Za-z_]/.test(ch)) {
      REF_RE.lastIndex = i; const m = REF_RE.exec(src);
      if (m && !isIdentChar(src[i + m[0].length]) && nextNonSpace(src, i + m[0].length) !== '(') {
        const letters = m[2].toUpperCase(), row = parseInt(m[4], 10);
        const c = letters.length === 1 ? letters.charCodeAt(0) - 65 : -1;
        push('REF', i, i + m[0].length, { cAbs: m[1] === '$', rAbs: m[3] === '$', c, r: row, valid: inGrid(row, c) });
        i += m[0].length; continue;
      }
      if (ch === '$') { push('BAD', i, i + 1); i++; continue; }
      IDENT_RE.lastIndex = i; const im = IDENT_RE.exec(src);
      push('IDENT', i, i + im[0].length, { name: im[0].toUpperCase() }); i += im[0].length; continue;
    }
    const two = src.slice(i, i + 2);
    if (two === '<=' || two === '>=' || two === '<>') { push(two, i, i + 2); i += 2; continue; }
    if ('<>=+-*/^&(),:'.includes(ch)) { push(ch, i, i + 1); i++; continue; }
    push('BAD', i, i + 1); i++;
  }
  return toks;
}

// ---------------------------------------------------------------- parser
class SyntaxErr extends Error {}

function normRange(a, b) {
  const [cl, cr] = a.c <= b.c ? [a, b] : [b, a];
  const [rt, rb] = a.r <= b.r ? [a, b] : [b, a];
  return { c1: cl.c, c1Abs: cl.cAbs, c2: cr.c, c2Abs: cr.cAbs, r1: rt.r, r1Abs: rt.rAbs, r2: rb.r, r2Abs: rb.rAbs };
}

function parseFormula(body) {
  const toks = tokenize(body);
  let p = 0;
  const peek = () => toks[p];
  const is = (t) => toks[p] && toks[p].t === t;
  const expect = (t) => { if (!is(t)) throw new SyntaxErr(); return toks[p++]; };

  function binLevel(next, ops) {
    return function () {
      let l = next();
      while (toks[p] && ops.includes(toks[p].t)) { const op = toks[p++].t; l = { k: 'bin', op, l, r: next() }; }
      return l;
    };
  }
  function unary() {
    if (is('-') || is('+')) { const op = toks[p++].t; return { k: 'un', op, e: unary() }; }
    return primary();
  }
  const power = binLevel(unary, ['^']);
  const mul = binLevel(power, ['*', '/']);
  const add = binLevel(mul, ['+', '-']);
  const cat = binLevel(add, ['&']);
  const cmp = binLevel(cat, ['=', '<>', '<', '>', '<=', '>=']);

  function primary() {
    const t = peek();
    if (!t) throw new SyntaxErr();
    p++;
    switch (t.t) {
      case 'NUM': return { k: 'num', v: t.v };
      case 'STR': return { k: 'str', v: t.v };
      case 'ERR': return { k: 'err', v: ERR_BY_CODE[t.code] };
      case 'IDENT': {
        if (is('(')) {
          p++;
          const args = [];
          if (is(')')) p++;
          else {
            for (;;) { args.push(cmp()); if (is(',')) { p++; continue; } expect(')'); break; }
          }
          return { k: 'fn', name: t.name, args };
        }
        if (t.name === 'TRUE') return { k: 'bool', v: true };
        if (t.name === 'FALSE') return { k: 'bool', v: false };
        return { k: 'name', name: t.name };
      }
      case 'REF': {
        if (is(':')) {
          p++;
          const b = expect('REF');
          return Object.assign({ k: 'range', valid: t.valid && b.valid }, normRange(t, b));
        }
        return { k: 'ref', r: t.r, c: t.c, valid: t.valid };
      }
      case '(': { const e = cmp(); expect(')'); return e; }
      default: throw new SyntaxErr();
    }
  }

  const ast = cmp();
  if (p !== toks.length) throw new SyntaxErr();
  return ast;
}

// ---------------------------------------------------------------- input interpretation
const NUMBER_INPUT_RE = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

// Returns a cell record {r, c, input, ast|null, value}.
function makeCell(r, c, input) {
  const cell = { r, c, input, ast: null, formula: false, value: EMPTY };
  if (input.startsWith('=')) {
    cell.formula = true;
    try { cell.ast = parseFormula(input.slice(1)); } catch (e) { if (!(e instanceof SyntaxErr)) throw e; cell.ast = null; }
  } else if (NUMBER_INPUT_RE.test(input)) {
    const n = Number(input); cell.value = Number.isFinite(n) ? n : E.NUM;
  } else if (/^(true|false)$/i.test(input)) {
    cell.value = input.toLowerCase() === 'true';
  } else if (input.startsWith("'")) {
    cell.value = input.slice(1);
  } else {
    cell.value = input;
  }
  return cell;
}

// ---------------------------------------------------------------- sheet model
class Sheet {
  constructor(id, name, inputs) {
    this.id = id; this.name = name;
    this.cells = new Map();
    for (const ref in inputs || {}) { const p = parseCellRef(ref); if (p && inputs[ref] !== '') this.cells.set(key(p.r, p.c), makeCell(p.r, p.c, inputs[ref])); }
    this.recalc();
  }
  setInput(r, c, input) {
    if (input === '') this.cells.delete(key(r, c));
    else this.cells.set(key(r, c), makeCell(r, c, input));
  }
  get(r, c) { const cell = this.cells.get(key(r, c)); return cell ? cell.value : EMPTY; }
  inputs() {
    const o = {};
    for (const cell of [...this.cells.values()].sort((a, b) => a.r - b.r || a.c - b.c)) o[refName(cell.r, cell.c)] = cell.input;
    return o;
  }

  // Full recalculation: static dependency graph between formula cells, Tarjan SCC
  // (iterative); SCCs come out dependencies-first, so evaluation order is correct.
  recalc() {
    const formulas = [];
    for (const cell of this.cells.values()) if (cell.formula) formulas.push(cell);
    const index = new Map();
    formulas.forEach((f, i) => index.set(key(f.r, f.c), i));
    const n = formulas.length;
    const adj = formulas.map((f) => {
      const out = new Set();
      const visit = (node) => {
        if (!node) return;
        switch (node.k) {
          case 'ref': if (node.valid) { const j = index.get(key(node.r, node.c)); if (j !== undefined) out.add(j); } break;
          case 'range':
            if (!node.valid) break;
            if ((node.r2 - node.r1 + 1) * (node.c2 - node.c1 + 1) <= n) {
              for (let r = node.r1; r <= node.r2; r++) for (let c = node.c1; c <= node.c2; c++) {
                const j = index.get(key(r, c)); if (j !== undefined) out.add(j);
              }
            } else {
              formulas.forEach((g, j) => { if (g.r >= node.r1 && g.r <= node.r2 && g.c >= node.c1 && g.c <= node.c2) out.add(j); });
            }
            break;
          case 'un': visit(node.e); break;
          case 'bin': visit(node.l); visit(node.r); break;
          case 'fn': node.args.forEach(visit); break;
        }
      };
      visit(f.ast);
      return [...out];
    });

    const idx = new Array(n).fill(-1), low = new Array(n).fill(0), onStack = new Array(n).fill(false);
    const stack = []; let counter = 0;
    for (let s = 0; s < n; s++) {
      if (idx[s] !== -1) continue;
      const work = [[s, 0]];
      idx[s] = low[s] = counter++; stack.push(s); onStack[s] = true;
      while (work.length) {
        const frame = work[work.length - 1];
        const v = frame[0];
        if (frame[1] < adj[v].length) {
          const w = adj[v][frame[1]++];
          if (idx[w] === -1) { idx[w] = low[w] = counter++; stack.push(w); onStack[w] = true; work.push([w, 0]); }
          else if (onStack[w]) low[v] = Math.min(low[v], idx[w]);
          continue;
        }
        work.pop();
        if (work.length) { const u = work[work.length - 1][0]; low[u] = Math.min(low[u], low[v]); }
        if (low[v] === idx[v]) {
          const comp = [];
          let w;
          do { w = stack.pop(); onStack[w] = false; comp.push(w); } while (w !== v);
          const cyclic = comp.length > 1 || adj[v].includes(v);
          for (const j of comp) {
            const cell = formulas[j];
            cell.value = cyclic ? E.CYCLE : this.evalCell(cell);
          }
        }
      }
    }
  }

  evalCell(cell) {
    if (!cell.ast) return E.ERROR;
    const v = this.ev(cell.ast);
    return v === EMPTY ? 0 : v;
  }

  // -------------------------------------------------------------- evaluator
  ev(node) {
    switch (node.k) {
      case 'num': return node.v;
      case 'str': return node.v;
      case 'bool': return node.v;
      case 'err': return node.v;
      case 'name': return E.NAME;
      case 'ref': return node.valid ? this.get(node.r, node.c) : E.REF;
      case 'range': return E.VALUE;
      case 'un': {
        const v = toNum(this.ev(node.e));
        if (isErr(v)) return v;
        return node.op === '-' ? -v : v;
      }
      case 'bin': return this.bin(node);
      case 'fn': return this.call(node);
    }
    throw new Error('bad node');
  }

  bin(node) {
    const op = node.op;
    if (op === '+' || op === '-' || op === '*' || op === '/' || op === '^') {
      const a = toNum(this.ev(node.l)); if (isErr(a)) return a;
      const b = toNum(this.ev(node.r)); if (isErr(b)) return b;
      switch (op) {
        case '+': return fin(a + b);
        case '-': return fin(a - b);
        case '*': return fin(a * b);
        case '/': return b === 0 ? E.DIV : fin(a / b);
        case '^': return fin(Math.pow(a, b));
      }
    }
    const a = this.ev(node.l); if (isErr(a)) return a;
    const b = this.ev(node.r); if (isErr(b)) return b;
    if (op === '&') return toStr(a) + toStr(b);
    return compare(op, a, b);
  }

  // Iterate a range row by row; cb returns a value to stop with, or undefined.
  eachInRange(node, cb) {
    for (let r = node.r1; r <= node.r2; r++) for (let c = node.c1; c <= node.c2; c++) {
      const res = cb(this.get(r, c)); if (res !== undefined) return res;
    }
    return undefined;
  }

  scalar(node) { return node.k === 'range' ? E.VALUE : this.ev(node); }

  call(node) {
    const spec = FUNCS[node.name];
    const args = node.args;
    if (!spec || args.length < spec[0] || args.length > spec[1]) return E.NAME;
    switch (node.name) {
      case 'SUM': case 'AVERAGE': case 'MIN': case 'MAX': case 'COUNT': {
        const isCount = node.name === 'COUNT';
        const nums = [];
        for (const a of args) {
          if (a.k === 'range') {
            if (!a.valid) return E.REF;
            const stop = this.eachInRange(a, (v) => { if (isErr(v)) return v; if (typeof v === 'number') nums.push(v); return undefined; });
            if (stop) return stop;
          } else {
            const v = this.ev(a);
            if (isErr(v)) return v;
            if (isCount) { if (typeof v === 'number') nums.push(v); }
            else { const x = toNum(v); if (isErr(x)) return x; nums.push(x); }
          }
        }
        switch (node.name) {
          case 'COUNT': return nums.length;
          case 'SUM': { let s = 0; for (const x of nums) s += x; return fin(s); }
          case 'AVERAGE': { if (!nums.length) return E.DIV; let s = 0; for (const x of nums) s += x; return fin(s / nums.length); }
          case 'MIN': { if (!nums.length) return 0; let m = Infinity; for (const x of nums) if (x < m) m = x; return m; }
          case 'MAX': { if (!nums.length) return 0; let m = -Infinity; for (const x of nums) if (x > m) m = x; return m; }
        }
        break;
      }
      case 'IF': {
        const cv = this.scalar(args[0]); if (isErr(cv)) return cv;
        const cond = toBool(cv); if (isErr(cond)) return cond;
        if (cond) return this.scalar(args[1]);
        return args.length === 3 ? this.scalar(args[2]) : false;
      }
      case 'ROUND': {
        const x = toNum(this.scalar(args[0])); if (isErr(x)) return x;
        const d = toNum(this.scalar(args[1])); if (isErr(d)) return d;
        return roundHalfAway(x, Math.trunc(d));
      }
      case 'ABS': { const x = toNum(this.scalar(args[0])); return isErr(x) ? x : Math.abs(x); }
      case 'LEN': { const v = this.scalar(args[0]); return isErr(v) ? v : toStr(v).length; }
      case 'CONCAT': {
        let s = '';
        for (const a of args) {
          if (a.k === 'range') {
            if (!a.valid) return E.REF;
            const stop = this.eachInRange(a, (v) => { if (isErr(v)) return v; s += toStr(v); return undefined; });
            if (stop) return stop;
          } else {
            const v = this.ev(a); if (isErr(v)) return v; s += toStr(v);
          }
        }
        return s;
      }
    }
    return E.NAME;
  }
}

const FUNCS = {
  SUM: [1, Infinity], AVERAGE: [1, Infinity], MIN: [1, Infinity], MAX: [1, Infinity], COUNT: [1, Infinity],
  IF: [2, 3], ROUND: [2, 2], ABS: [1, 1], CONCAT: [1, Infinity], LEN: [1, 1],
};

const fin = (x) => (Number.isFinite(x) ? x : E.NUM);

function toNum(v) {
  if (typeof v === 'number') return v;
  if (typeof v === 'boolean') return v ? 1 : 0;
  if (v === EMPTY) return 0;
  if (isErr(v)) return v;
  return E.VALUE; // string
}
function toStr(v) {
  if (typeof v === 'number') return String(v);
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  if (v === EMPTY) return '';
  return v;
}
function toBool(v) {
  if (typeof v === 'boolean') return v;
  if (typeof v === 'number') return v !== 0;
  if (v === EMPTY) return false;
  if (isErr(v)) return v;
  return E.VALUE;
}
function compare(op, a, b) {
  const zero = (x) => (typeof x === 'number' ? 0 : typeof x === 'string' ? '' : false);
  if (a === EMPTY && b === EMPTY) { a = 0; b = 0; }
  else if (a === EMPTY) a = zero(b);
  else if (b === EMPTY) b = zero(a);
  if (typeof a !== typeof b) return E.VALUE;
  if (typeof a === 'string') { a = a.toLowerCase(); b = b.toLowerCase(); }
  switch (op) {
    case '=': return a === b;
    case '<>': return a !== b;
    case '<': return a < b;
    case '>': return a > b;
    case '<=': return a <= b;
    case '>=': return a >= b;
  }
  return E.ERROR;
}
function roundHalfAway(x, d) {
  if (d > 15) return x;
  if (d < -308) return 0;
  const sign = x < 0 ? -1 : 1, ax = Math.abs(x);
  let res;
  if (d >= 0) {
    const f = Math.pow(10, d);
    res = Math.round(Number((ax * f).toPrecision(15))) / f;
  } else {
    const f = Math.pow(10, -d);
    res = Math.round(Number((ax / f).toPrecision(15))) * f;
  }
  return fin(sign * res) === E.NUM ? E.NUM : (sign * res === 0 ? 0 : sign * res);
}

// ---------------------------------------------------------------- formula rewriting
const refText = (c, cAbs, r, rAbs) => (cAbs ? '$' : '') + colName(c) + (rAbs ? '$' : '') + r;
const rangeText = (g) => refText(g.c1, g.c1Abs, g.r1, g.r1Abs) + ':' + refText(g.c2, g.c2Abs, g.r2, g.r2Abs);

// mapRef({c,cAbs,r,rAbs}) -> new same-shaped object, or null for #REF!.
// mapRange(normalized range) -> new range object, or null for #REF!.
// Only in-grid references are considered. If no reference changes, the input is returned untouched;
// otherwise every (in-grid) reference is written canonically and all other text is kept byte-for-byte.
function rewriteFormula(input, mapRef, mapRange) {
  if (!input.startsWith('=')) return input;
  const toks = tokenize(input.slice(1), 1);
  const edits = [];
  let changed = false;
  for (let i = 0; i < toks.length; i++) {
    const t = toks[i];
    if (t.t !== 'REF') continue;
    if (toks[i + 1] && toks[i + 1].t === ':' && toks[i + 2] && toks[i + 2].t === 'REF') {
      const b = toks[i + 2];
      if (t.valid && b.valid) {
        const g = normRange(t, b), ng = mapRange(g);
        if (!ng || ng.r1 !== g.r1 || ng.r2 !== g.r2 || ng.c1 !== g.c1 || ng.c2 !== g.c2) changed = true;
        edits.push({ s: t.s, e: b.e, text: ng ? rangeText(ng) : '#REF!' });
      }
      i += 2; continue;
    }
    if (!t.valid) continue;
    const nr = mapRef({ c: t.c, cAbs: t.cAbs, r: t.r, rAbs: t.rAbs });
    if (!nr || nr.r !== t.r || nr.c !== t.c) changed = true;
    edits.push({ s: t.s, e: t.e, text: nr ? refText(nr.c, nr.cAbs, nr.r, nr.rAbs) : '#REF!' });
  }
  if (!changed) return input;
  let out = '', pos = 0;
  for (const ed of edits) { out += input.slice(pos, ed.s) + ed.text; pos = ed.e; }
  return out + input.slice(pos);
}

function insertRows(sheet, at, count) {
  const mapRow = (r) => (r >= at ? r + count : r);
  const mapRef = (x) => { const r = mapRow(x.r); return r > NROWS ? null : { ...x, r }; };
  const mapRange = (g) => {
    const r1 = mapRow(g.r1); if (r1 > NROWS) return null;
    return { ...g, r1, r2: Math.min(mapRow(g.r2), NROWS) };
  };
  const old = [...sheet.cells.values()];
  sheet.cells = new Map();
  for (const cell of old) {
    const r = mapRow(cell.r);
    if (r > NROWS) continue;
    sheet.setInput(r, cell.c, rewriteFormula(cell.input, mapRef, mapRange));
  }
  sheet.recalc();
}

function deleteRows(sheet, at, count) {
  const end = Math.min(at + count - 1, NROWS);
  const n = end - at + 1;
  const mapRef = (x) => (x.r < at ? x : x.r > end ? { ...x, r: x.r - n } : null);
  const mapRange = (g) => {
    const r1 = g.r1 < at ? g.r1 : g.r1 > end ? g.r1 - n : at;
    const r2 = g.r2 < at ? g.r2 : g.r2 > end ? g.r2 - n : at - 1;
    return r1 > r2 ? null : { ...g, r1, r2 };
  };
  const old = [...sheet.cells.values()];
  sheet.cells = new Map();
  for (const cell of old) {
    if (cell.r >= at && cell.r <= end) continue;
    const r = cell.r > end ? cell.r - n : cell.r;
    sheet.setInput(r, cell.c, rewriteFormula(cell.input, mapRef, mapRange));
  }
  sheet.recalc();
}

// src: {r1,c1,r2,c2}; dst: {r,c}
function copyBlock(sheet, src, dst) {
  const dr = dst.r - src.r1, dc = dst.c - src.c1;
  const mapRef = (x) => {
    const r = x.rAbs ? x.r : x.r + dr, c = x.cAbs ? x.c : x.c + dc;
    return inGrid(r, c) ? { ...x, r, c } : null;
  };
  const mapRange = (g) => {
    const a = mapRef({ c: g.c1, cAbs: g.c1Abs, r: g.r1, rAbs: g.r1Abs });
    const b = mapRef({ c: g.c2, cAbs: g.c2Abs, r: g.r2, rAbs: g.r2Abs });
    return a && b ? normRange(a, b) : null;
  };
  const writes = [];
  for (let r = src.r1; r <= src.r2; r++) for (let c = src.c1; c <= src.c2; c++) {
    const tr = r + dr, tc = c + dc;
    if (!inGrid(tr, tc)) continue;
    const cell = sheet.cells.get(key(r, c));
    writes.push([tr, tc, cell ? rewriteFormula(cell.input, mapRef, mapRange) : '']);
  }
  for (const [r, c, input] of writes) sheet.setInput(r, c, input);
  sheet.recalc();
}

function publicValue(v) {
  if (v === EMPTY) return { value: null, type: 'empty' };
  if (isErr(v)) return { value: v.code, type: 'error' };
  if (typeof v === 'number') return { value: v, type: 'number' };
  if (typeof v === 'boolean') return { value: v, type: 'boolean' };
  return { value: v, type: 'string' };
}

module.exports = {
  NCOLS, NROWS, Sheet, parseCellRef, refName, key, insertRows, deleteRows, copyBlock, publicValue,
  isErr, EMPTY, tokenize, parseFormula, rewriteFormula,
};
