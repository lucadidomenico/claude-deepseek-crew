import os, socket, subprocess, time, signal, shutil, tempfile, uuid
import pytest, requests

APP_DIR = os.environ["JUDGE_APP_DIR"]          # prepared copy of the workspace (npm install already done)
PREFIX = os.environ.get("JUDGE_PREFIX", "")    # "/kanban" etc. when judging a module of the combined suite app

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class Server:
    def __init__(self):
        self.port = _free_port()
        self.data_dir = tempfile.mkdtemp(prefix="judge-data-")
        self.proc = None
        self.base = f"http://127.0.0.1:{self.port}"
        self.log = open(os.path.join(os.environ.get("JUDGE_OUT", "/tmp"), f"server{PREFIX.replace('/', '-')}.log"), "ab")
    def start(self):
        env = dict(os.environ, PORT=str(self.port), DATA_DIR=self.data_dir, NODE_ENV="production")
        self.proc = subprocess.Popen(["npm", "start", "--silent"], cwd=APP_DIR, env=env, stdout=self.log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        t0 = time.time()
        while time.time() - t0 < 20:
            if self.proc.poll() is not None: raise RuntimeError("server exited")
            try:
                if requests.get(self.base + PREFIX + "/", timeout=1).status_code < 500: return
                time.sleep(0.25)
            except requests.RequestException: time.sleep(0.25)
        raise RuntimeError("server not ready in 20s")
    def stop(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try: self.proc.wait(5)
            except subprocess.TimeoutExpired: os.killpg(self.proc.pid, signal.SIGKILL); self.proc.wait()
    def restart(self):
        self.stop(); time.sleep(0.3); self.start()

@pytest.fixture(scope="session")
def server():
    s = Server(); s.start(); yield s; s.stop(); shutil.rmtree(s.data_dir, ignore_errors=True)

class Api:
    def __init__(self, server, token=None):
        self.s = server; self.token = token
    def req(self, method, path, json=None, token="__default__", **kw):
        h = kw.pop("headers", {})
        tok = self.token if token == "__default__" else token
        if tok: h["Authorization"] = f"Bearer {tok}"
        return requests.request(method, self.s.base + PREFIX + path, json=json, headers=h, timeout=10, **kw)
    def get(self, p, **kw): return self.req("GET", p, **kw)
    def post(self, p, json=None, **kw): return self.req("POST", p, json=json, **kw)
    def patch(self, p, json=None, **kw): return self.req("PATCH", p, json=json, **kw)
    def put(self, p, json=None, **kw): return self.req("PUT", p, json=json, **kw)
    def delete(self, p, **kw): return self.req("DELETE", p, **kw)

@pytest.fixture
def api(server): return Api(server)

def uniq(prefix="u"): return f"{prefix}{uuid.uuid4().hex[:8]}"
