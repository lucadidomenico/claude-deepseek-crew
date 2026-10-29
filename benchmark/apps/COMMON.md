## Technical contract (mandatory, the app is graded automatically against it)

- Runtime: **Node.js 22**. Any npm packages are allowed (pure-JS or with prebuilt binaries). Node 22 also ships `node:sqlite`.
- The project root must contain `package.json`. The grader runs `npm install` and then `npm start`.
- The server must listen on the port given by the `PORT` environment variable (default 3000) on `127.0.0.1` or `0.0.0.0`.
- All persistent data must be stored **inside the directory given by the `DATA_DIR` environment variable** (default `./data`; create it if missing). Data must survive a server restart.
- The server must be ready to accept requests within 15 seconds of `npm start`.
- JSON API: request and response bodies are JSON (`Content-Type: application/json`), except where stated otherwise.
- Errors: respond with the status code given in the spec and a JSON body `{"error": "<human readable message>"}`.
- IDs are integers assigned by the server, starting from 1 for each resource type.
- Timestamps are ISO 8601 strings in UTC (e.g. `2026-10-28T18:00:00.000Z`).
- Unknown routes → 404.
- `GET /` must serve a usable HTML page (a simple single-page UI that uses the API is enough; no build step).
- Do not rely on any external network service at runtime.
