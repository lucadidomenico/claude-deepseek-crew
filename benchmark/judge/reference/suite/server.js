// Reference for the "suite" app: runs the five module references as child processes and proxies by prefix.
const http = require('node:http'), path = require('node:path'), { spawn } = require('node:child_process'), fs = require('node:fs');
const MODS = ['bookmarks', 'kanban', 'splitter', 'booking', 'sheets'];
const PORT = +process.env.PORT || 3000, DATA = path.resolve(process.env.DATA_DIR || './data');
const kids = {}; let base = 20000 + Math.floor(Math.random() * 20000);
for (const m of MODS) {
  const port = base++; fs.mkdirSync(path.join(DATA, m), { recursive: true });
  const c = spawn(process.execPath, ['server.js'], { cwd: path.join(__dirname, 'mods', m), env: { ...process.env, PORT: String(port), DATA_DIR: path.join(DATA, m) }, stdio: 'inherit' });
  kids[m] = { port, c };
}
const stop = () => { for (const k of Object.values(kids)) k.c.kill('SIGTERM'); process.exit(0); };
process.on('SIGTERM', stop); process.on('SIGINT', stop);
http.createServer((req, res) => {
  const m = req.url.split('/')[1].split('?')[0];
  if (req.url === '/' || req.url === '') { res.writeHead(200, { 'content-type': 'text/html' }); return res.end('<html><body>' + MODS.map(x => `<a href="/${x}/">${x}</a>`).join(' ') + '</body></html>'); }
  if (!kids[m]) { res.writeHead(404, { 'content-type': 'application/json' }); return res.end('{"error":"not found"}'); }
  const p = http.request({ host: '127.0.0.1', port: kids[m].port, method: req.method, path: req.url.slice(m.length + 1) || '/', headers: req.headers }, r => { res.writeHead(r.statusCode, r.headers); r.pipe(res); });
  p.on('error', () => { res.writeHead(502); res.end(); }); req.pipe(p);
}).listen(PORT, () => setTimeout(() => {}, 0));
