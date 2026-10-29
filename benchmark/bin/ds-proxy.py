#!/usr/bin/env python3
"""Logging reverse proxy: localhost -> https://api.deepseek.com/anthropic.
Logs every request (model, path) and the usage from every response into a JSONL file.
Lets us (1) prove which model/endpoint the worker uses, (2) compute real DeepSeek cost."""
import http.server, json, os, sys, time, urllib.request, urllib.error, threading
UP = "https://api.deepseek.com/anthropic"
LOG = os.environ.get("DS_PROXY_LOG", "ds-proxy.jsonl")
lock = threading.Lock()
def log(rec):
    with lock, open(LOG, "a") as f: f.write(json.dumps(rec) + "\n")
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _do(self, method):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else None
        model = None; tools = []
        try:
            j = json.loads(body); model = j.get("model")
            tools = [t.get("type") or t.get("name") for t in j.get("tools", [])]
        except Exception: pass
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "accept-encoding", "connection")}
        tag = os.environ.get("DS_TAG") or self.headers.get("x-ds-tag")
        req = urllib.request.Request(UP + self.path, data=body, method=method, headers=hdrs)
        t0 = time.time(); usage = {}; resp_model = None; status = None; server_tools = 0
        try:
            r = urllib.request.urlopen(req, timeout=900); status = r.status
            self.send_response(r.status)
            ctype = r.headers.get("content-type", "")
            for k, v in r.headers.items():
                if k.lower() not in ("transfer-encoding", "content-length", "connection", "content-encoding"): self.send_header(k, v)
            if "event-stream" in ctype:
                self.send_header("transfer-encoding", "chunked"); self.end_headers()
                buf = b""
                for chunk in iter(lambda: r.read1(65536), b""):
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk)); self.wfile.flush()
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.startswith(b"data:"):
                            try: ev = json.loads(line[5:])
                            except Exception: continue
                            if ev.get("type") == "message_start":
                                m = ev["message"]; resp_model = m.get("model"); usage.update(m.get("usage") or {})
                            elif ev.get("type") == "message_delta": usage.update(ev.get("usage") or {})
                            elif ev.get("type") == "content_block_start" and (ev.get("content_block") or {}).get("type") == "server_tool_use": server_tools += 1
                self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
            else:
                data = r.read(); self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
                try: j2 = json.loads(data); resp_model = j2.get("model"); usage = j2.get("usage") or {}
                except Exception: pass
        except urllib.error.HTTPError as e:
            status = e.code; data = e.read()
            self.send_response(e.code); self.send_header("content-type", e.headers.get("content-type", "application/json"))
            self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
            usage = {"error": data[:500].decode("utf8", "replace")}
        log({"ts": t0, "dur": round(time.time() - t0, 2), "tag": tag, "method": method, "path": self.path, "status": status,
             "req_model": model, "resp_model": resp_model, "usage": usage, "server_tool_uses": server_tools,
             "server_tools_offered": [t for t in tools if t and ("web" in str(t))]})
    def do_POST(self): self._do("POST")
    def do_GET(self): self._do("GET")
class S(http.server.ThreadingHTTPServer): daemon_threads = True
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    S(("127.0.0.1", port), H).serve_forever()
