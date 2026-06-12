# AGENTS.md — set up Presto Cockpit end to end

This is a precise, do‑this‑then‑that runbook for an **AI agent** (or a human) to deploy
Presto Cockpit from nothing to a working dashboard. It covers all three environments,
their architecture, and exactly what information you must collect first.

> Conventions used below:
> - `GPU_HOST` — the machine with the GPU running your models + the `dgx-vitals` sidecar.
> - `GATEWAY_HOST` — the machine running OpenClaw + the `openclaw-shim`. May be the same box as `GPU_HOST`.
> - `DEV` — the laptop/desktop you flash the Presto from (needs `mpremote`).
> All of these can be one physical machine or three; the Presto just needs to reach the
> backend ports over WiFi.

---

## 0. The architecture (read first)

Three environments cooperate. You deploy to each one independently.

```
 ENV A — the Presto device (MicroPython)          ENV B — GPU_HOST (Linux + Docker + NVIDIA)
 ───────────────────────────────────────          ────────────────────────────────────────
 • RP2350, 480x480 touch, 7 RGB LEDs, WiFi          • dgx-vitals container (this repo)
 • boots → reads /secrets.json → joins WiFi          • --network host --pid=host --gpus all
 • app/app.py poll loop renders 8 screens            • reads NVML + psutil + docker.sock
 • polls backend URLs over HTTP every 1–2 s          • scrapes vLLM/ASR :8000/:8001 /metrics
 • I2C: BME280 + LTR559 + LSM6DS3 + nav pad          • serves  GET :9876/vitals
        │                                                     ▲
        │  WiFi / HTTP                                        │ HTTP
        ├─────────────────────────────────────────────────────┘
        │
        └──────────────► ENV C — GATEWAY_HOST (Linux)
                         ──────────────────────────
                         • OpenClaw gateway (your AI agents) — optional
                         • openclaw-shim (this repo): shells the `openclaw` CLI,
                           scans /proc, scrapes vLLM, polls per-agent voip /status
                         • serves  GET :9787/agents
```

**Independence:** every backend is optional. The Crypto / Environment / Clock / News
screens need no backend. The **DGX** screen needs ENV B. The **OpenClaw** and
**Resources** screens need ENV C (and an OpenClaw install). Deploy only what you want.

---

## 1. Information to collect before you start

| Need | For | Example |
|---|---|---|
| WiFi SSID + password + 2‑letter country code | the Presto to get online | `MyNet` / `…` / `US` |
| `GPU_HOST` address | DGX screen | `10.0.0.10` or `gpu.local` |
| `GATEWAY_HOST` address | OpenClaw + Resources screens | `10.0.0.20` |
| vLLM / ASR Prometheus URLs (optional) | per‑model tok/s on the DGX screen | `http://localhost:8000/metrics` |
| A Presto on USB‑C + `mpremote` on `DEV` | flashing | `pip3 install --user mpremote` |
| SSH to `GPU_HOST` / `GATEWAY_HOST` | deploying the backends | `youruser@10.0.0.10` |

If you only want the no‑backend screens, you just need the **WiFi** row.

---

## 2. ENV B — deploy `dgx-vitals` on the GPU box (for the DGX screen)

**Architecture:** a `python:3.12-slim` container running `uvicorn app:app` on `:9876`.
It needs the host's real view, so it runs `--network host --pid=host --gpus all` and
mounts the Docker socket read‑only. `GET /vitals` returns one JSON snapshot:
`{ host, uptime_s, gpu[], cpu, mem, net, containers[], models[] }`.

```bash
# on GPU_HOST (needs Docker + the NVIDIA container runtime)
scp -r dgx-vitals youruser@GPU_HOST:~/        # or git clone the repo there
ssh youruser@GPU_HOST
cd ~/dgx-vitals

# OPTIONAL: tell it which vLLM/ASR metrics endpoints to scrape for tok/s
export VLLM_METRICS_URLS="http://localhost:8000/metrics,http://localhost:8001/metrics"

./run.sh        # builds the image, runs with --restart=unless-stopped, smoke-tests /vitals
```

Verify:
```bash
curl -s http://localhost:9876/vitals | python3 -m json.tool   # on the box
curl -s http://GPU_HOST:9876/vitals                            # from the LAN (open firewall to the Presto's subnet)
```
You want HTTP 200 with a `gpu`/`cpu`/`mem`/`containers` body. `run.sh` already sets
`--restart=unless-stopped`, so it survives reboots. If `/vitals` is unreachable from the
LAN, open `:9876/tcp` on the host firewall to the Presto's subnet.

> No NVIDIA GPU? It still serves CPU/mem/containers; the `gpu` array just reports what
> NVML can (some unified‑memory boards report `mem_*` as `null` — that's expected).

---

## 3. ENV C — deploy `openclaw-shim` on the gateway box (for OpenClaw + Resources)

Skip this unless you run **OpenClaw**. The gateway only speaks RPC/WS, so the shim
shells out to the `openclaw` CLI and serves a digested JSON.

**Architecture:** a stdlib‑only Python HTTP server on `:9787`. Background threads refresh
(a) `openclaw agents/sessions list` → per‑agent tok/s, sessions, token ledger;
(b) `openclaw status/tasks list` → job counts + per‑agent activity;
(c) a `/proc` scan → host CPU/RAM + per‑process consumers;
(d) the vLLM `/metrics` → live generation rate;
(e) each agent's voice‑call sidecar `/status` (the `VOIP_PORTS` map) → on‑call state.
`GET /agents` returns it all from cache (never blocks on the CLI).

```bash
# on GATEWAY_HOST (needs the `openclaw` CLI installed for the running user)
scp -r openclaw-shim youruser@GATEWAY_HOST:~/openclaw-shim
ssh youruser@GATEWAY_HOST
cd ~/openclaw-shim

# Edit two things in shim.py for your setup:
#   - VLLM_METRICS_URL  (or set the env var)         -> your vLLM host
#   - VOIP_PORTS = { "agent-id": port, ... }         -> only if you use voice-call sidecars
# Then install the service (edit 'youruser' / paths in the unit first):
cp openclaw-shim.service ~/.config/systemd/user/      # or /etc/systemd/system for a system service
systemctl --user daemon-reload
systemctl --user enable --now openclaw-shim.service
```

Verify:
```bash
curl -s http://localhost:9787/agents  | python3 -m json.tool | head -40
curl -s http://GATEWAY_HOST:9787/agents | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["agents"]),"agents")'
```
Open `:9787/tcp` to the Presto's subnet. The shim needs **no bearer** by default (it's
LAN/firewall‑scoped); set `OPENCLAW_BEARER` only if you put auth in front of it.

> Operational note baked into the unit: keep `CPUQuota` **generous** (≥ 200%). Too tight
> a quota starves the CLI wait‑loop and makes long calls look like timeouts, blanking the
> agent list. The default unit ships `400%`.

---

## 4. ENV A — configure and flash the Presto

**Architecture:** on boot the Presto reads `/secrets.json`, joins WiFi, syncs NTP, then
`app/app.py` runs a poll loop: it fetches each enabled backend URL on its own interval,
reads the I²C sensors, renders the current screen, and drives the rear LEDs. Files live
at the device root: `/boot.py`, `/main.py`, `/app/…`, `/secrets.json`, `/images/`.

```bash
# on DEV (your laptop), in this repo:
cp .env.example .env
$EDITOR .env            # WiFi creds; set DGX_URL -> http://GPU_HOST:9876/vitals
                        #             set OPENCLAW_URL -> http://GATEWAY_HOST:9787/agents
                        #             (leave a URL blank to disable that screen's fetch)

pip3 install --user mpremote      # if not already
# plug the Presto into DEV via USB-C, then:
./deploy.sh             # runs gen-secrets.sh (.env -> secrets.json) and pushes everything, then soft-resets
```

`deploy.sh` auto‑detects the Presto (`PRESTO_DEV=auto`) and copies `secrets.json`,
`boot.py`, `main.py`, and all of `app/` to the device. Watch it come up:

```bash
mpremote connect <DEV-PORT> repl     # live logs; deploy.sh prints the exact command
# or run the on-device self-test:
mpremote connect <DEV-PORT> run tools/boottest.py
```

---

## 5. Verify each screen

```
[ ] Presto joins WiFi + shows the clock (NTP synced)
[ ] Environment screen shows temp / humidity / pressure / lux   (sensor stick present)
[ ] Crypto screen shows prices                                  (internet only)
[ ] News screen shows headlines                                 (internet only)
[ ] DGX screen shows GPU/CPU/mem/containers                     (ENV B reachable)
[ ] OpenClaw screen lists your agents                           (ENV C reachable)
[ ] Resources screen shows the gateway host donuts              (ENV C reachable)
[ ] rear LEDs glow the current screen's accent color
[ ] L/R on the pad (or touch) flips screens
```

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| DGX screen: `ECONNRESET` / `couldn't connect` | `dgx-vitals` container down | `docker start dgx-vitals` (set `--restart=unless-stopped`); check `:9876` firewall |
| OpenClaw screen blank / `timeout` | shim can't reach the `openclaw` CLI, or CPUQuota too tight | `systemctl --user status openclaw-shim`; raise `CPUQuota`; confirm `openclaw agents list` works as that user |
| A screen shows "no url" | that backend URL is blank in `.env` | set it and re‑run `./deploy.sh` |
| WiFi won't join | wrong SSID/country, or 5 GHz‑only AP | check `WIFI_*` in `.env`; the Presto is 2.4 GHz |
| Environment screen empty | sensor stick not detected on I²C | reseat the Qw/ST cable; check the stick address |
| Nothing deploys | `mpremote` not found / wrong port | `pip3 install --user mpremote`; set `PRESTO_DEV=/dev/tty…` |

Backend logs are the fastest signal:
```bash
docker logs --tail 50 dgx-vitals                       # ENV B
journalctl --user -u openclaw-shim -n 50 --no-pager    # ENV C
mpremote connect <DEV-PORT> repl                        # ENV A (device console)
```

---

## 7. What information lives where (secrets map)

| Item | Lives in | Committed? |
|---|---|---|
| WiFi password, host URLs, bearer | `.env` on `DEV` → `secrets.json` on the Presto | **never** (git‑ignored) |
| vLLM/ASR metrics URLs | `dgx-vitals` env (`VLLM_METRICS_URLS`) | n/a (host env) |
| `openclaw` auth | handled by the OpenClaw CLI on `GATEWAY_HOST` | n/a |

No secret belongs in the code or this repo — everything is a placeholder here. Fill in
your own values in `.env` and on the backend hosts only.
