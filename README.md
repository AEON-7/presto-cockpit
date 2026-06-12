# Presto Cockpit

*A physical, glanceable dashboard for a home AI/GPU lab — on a tiny touchscreen you
can set on your desk.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat)](LICENSE)

Presto Cockpit turns a **Pimoroni Presto** (a 480×480 touchscreen running MicroPython)
into a live wall of dials for the things a home lab actually cares about: your **GPU
box's vitals**, your **AI agents**, the **gateway host's load**, **crypto** prices, the
**room's** temperature and pressure, a word‑clock, and trending **AI news** — plus a
ring of rear RGB LEDs that glow the accent color of whatever screen you're on.

It's two small **backends** feeding one little **screen**:

```
   ┌──────────────────────────┐         ┌──────────────────────────────┐
   │  GPU / DGX box           │         │  OpenClaw gateway box        │
   │  dgx-vitals  :9876       │         │  openclaw-shim  :9787        │
   │  (GPU/CPU/mem/containers │         │  (per-agent tok/s, sessions, │
   │   + vLLM/ASR tok/s)      │         │   on-call, host load)        │
   └────────────┬─────────────┘         └───────────────┬──────────────┘
                │  HTTP /vitals                          │  HTTP /agents
                └──────────────────┬─────────────────────┘
                                   ▼   (WiFi, polled every 1–2 s)
                        ┌─────────────────────────┐
                        │   Pimoroni Presto       │  480×480 touch · RP2350
                        │   8 swipeable screens   │  + 7 rear RGB LEDs
                        │   + sensor stick        │  + Qw/ST nav pad
                        └─────────────────────────┘
```

Both backends are optional and independent — run one, both, or neither. Crypto,
environment, clock, and news screens work with no backend at all.

---

## Hardware

| Part | Role |
|---|---|
| **Pimoroni Presto** | 480×480 IPS touchscreen, RP2350, 7 rear RGB LEDs, WiFi, runs MicroPython |
| **Multi‑Sensor Stick** (Qw/ST) | BME280 (temp / humidity / pressure) + LTR559 (ambient light) + LSM6DS3 (IMU) |
| **Qw/ST Pad** (addr `0x21`) | physical L/R buttons to flip screens (touch also works) |

The sensor stick and pad daisy‑chain on the Presto's Qwic/STEMMA‑QT I²C bus — no
soldering. Everything else is optional.

---

## The screens

Swipe (touch) or press **L/R** on the pad to move between them. Default rotation:

| Screen | What it shows |
|---|---|
| **DGX** | Your GPU box: GPU name/temp/util/power, CPU load, RAM, a list of running containers, and live **tok/s + prompt‑prefill tok/s** per model. Fed by `dgx-vitals`. |
| **OpenClaw** | Every AI agent on your OpenClaw gateway: live **gen tok/s**, ingest rate, sessions, context size, "working"/"on‑call" state, and a 7d/30d/1y **token‑usage** ledger. Tap an agent for a session detail view. Fed by `openclaw-shim`. |
| **Resources** | The gateway host itself: CPU + RAM **donut gauges** and a ranked list of the top process consumers (chat gateway, per‑agent voice sidecars, browser, …). Fed by `openclaw-shim`. |
| **News** | Trending AI/tech headlines (Hacker News front page, filtered). No backend or key needed. |
| **Crypto** | Live prices for a configurable basket (default BTC / ETH / XMR / SOL) via the free CoinGecko API. |
| **Environment** | Room temperature, humidity, and barometric pressure from the BME280, plus ambient light (lux). |
| **Clock** | A full‑screen **QlockTwo‑style word grid** that spells out the time, synced over NTP. |
| **Settings** | On‑device view of the current config (hosts, poll intervals, brightness) and LED controls. |

Also in the tree but **not in the default rotation** (kept for reference / re‑enable in
`app/app.py`'s `SCREENS_ORDER`): an **altitude / artificial‑horizon** screen (pressure +
IMU) and a **lights** screen (LED animations + image color‑sampling). They were dropped
from the live rotation for refresh speed.

### Rear LEDs
The 7 rear RGB LEDs glow the **accent color of the current screen**, and (optionally)
**auto‑dim** from the ambient‑light sensor so the cockpit isn't blinding in a dark room.

---

## The backends

### `dgx-vitals/` — GPU box telemetry (Docker)
A tiny FastAPI service you run **on the GPU machine**. One `GET /vitals` returns a JSON
snapshot: GPU (via NVML), CPU/RAM/net (via `psutil`), the running Docker containers, and
per‑model **tok/s** scraped from vLLM/ASR Prometheus endpoints. Runs with
`--network host --pid=host --gpus all` so it sees the real host. See
[`dgx-vitals/`](dgx-vitals/) and [`AGENTS.md`](AGENTS.md).

### `openclaw-shim/` — agent + host stats (systemd)
A stdlib‑only Python service you run **on the OpenClaw gateway box** (only relevant if
you run [OpenClaw](https://github.com/openclaw/openclaw)). The gateway speaks RPC/WS, so
the shim shells out to the `openclaw` CLI, digests the output, scans `/proc`, and serves
a clean `GET /agents` JSON for the OpenClaw + Resources screens. It's hardened against a
CLI‑subprocess leak and reports stale‑but‑present data rather than going blank on a
hiccup. See [`openclaw-shim/`](openclaw-shim/).

---

## Repo layout

```
presto-cockpit/
├── app/                  the MicroPython cockpit that runs ON the Presto
│   ├── app.py            screen router, input dispatch, poll loop
│   ├── screens/          one file per screen
│   ├── net/              tiny HTTP clients (dgx, openclaw, crypto, news)
│   ├── hw/               drivers: sensor stick, Qw/ST pad, rear LEDs
│   ├── lights/           LED animations + image color-sampling
│   ├── state.py theme.py shared state + colors
├── boot.py main.py       device entry points
├── deploy.sh             gen-secrets + push all files to the Presto via mpremote
├── gen-secrets.sh        .env  ->  secrets.json (UTF-8 safe)
├── dgx-vitals/           the GPU-box telemetry sidecar (Docker)
├── openclaw-shim/        the OpenClaw agent/host stats service (systemd)
├── tools/boottest.py     on-device self-test
├── .env.example          copy to .env and fill in
└── AGENTS.md             full step-by-step setup (for an AI agent or a human)
```

## Quickstart

```bash
cp .env.example .env      # fill in WiFi + your GPU_HOST / GATEWAY_HOST
./deploy.sh               # generates secrets.json and flashes the Presto over USB-C
# (then stand up the backends you want — see AGENTS.md)
```

**Full setup — including the two backends and each environment's architecture — is in
[`AGENTS.md`](AGENTS.md).** It's written so an AI agent can do the whole deployment, but
it reads fine for a human too.

## Configuration

Everything is driven by `.env` (→ `secrets.json` on the device). Hosts, poll intervals,
the crypto basket, LED brightness, and sea‑level pressure are all there. No secret ever
lives in the code — see [`.env.example`](.env.example). `.env` and `secrets.json` are
git‑ignored; keep them that way.

## License

MIT — see [`LICENSE`](LICENSE). The libraries it builds on (MicroPython, Pimoroni's
Presto modules, FastAPI, psutil) carry their own licenses.
