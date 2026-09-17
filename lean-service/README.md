# lean-service

Standalone Lean 4 + Mathlib typechecker, deployed separately from the main
app because loading Mathlib's environment needs real RAM (2-4GB+) that a
free web-service instance doesn't have. The main app's `scripts/lean.py`
calls this over HTTP.

## API

- `GET /health` — liveness check.
- `POST /check` `{"code": "<lean source>"}` -> `{"ok": bool, "output": str}`.
  Send `Authorization: Bearer <LEAN_SERVICE_TOKEN>` if a token is configured.

## Deploying on an Oracle Cloud Always-Free VM

1. Create an OCI account (free tier, no ongoing cost) and provision an
   **Ampere A1** compute instance (the Always-Free shape: up to 4 OCPU /
   24GB RAM, genuinely free forever) running Ubuntu.
2. Open the instance's security list / network security group for the port
   you'll run this on (e.g. 8000) — either directly, or behind a reverse
   proxy (Caddy/nginx) terminating TLS on 443. If you already run Dokploy
   elsewhere, this can just be another app on it instead.
3. Install Docker on the VM:
   ```
   curl -fsSL https://get.docker.com | sh
   ```
4. Copy this `lean-service/` folder to the VM (`scp` or `git clone` the repo
   there) and build + run:
   ```
   docker build -t lean-service .
   docker run -d --name lean-service --restart unless-stopped \
     -p 8000:8000 \
     -e LEAN_SERVICE_TOKEN=<pick-a-random-secret> \
     lean-service
   ```
   The first build downloads Mathlib's precompiled cache (several GB) — expect
   it to take a while depending on the VM's network.
5. Point the main app at it: set `LEAN_SERVICE_URL=http://<vm-ip>:8000` (or
   `https://...` if behind a reverse proxy) and `LEAN_SERVICE_TOKEN` to the
   same secret, in `app/.env` (local) or the host's env vars (deployed).
6. Verify: `curl http://<vm-ip>:8000/health`.
