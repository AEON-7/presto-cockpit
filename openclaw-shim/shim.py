#!/usr/bin/env python3
"""OpenClaw LAN shim — runs on the OpenClaw gateway host.

The gateway only exposes WebSocket/RPC + a locked HTTP surface, and the
documented Prometheus REST path 404s on this build. The `openclaw` CLI speaks
the RPC correctly and emits clean JSON, so this shim fans out to the CLI and
serves a digested view on the LAN. Stdlib only — no pip deps.

Background refreshers keep HTTP responses instant:
  - fast (~4s):  agents list + sessions list -> per-agent activity + tok/s,
                 and a persistent daily TOKEN LEDGER (per-session deltas) so we
                 can report accurate 7d/30d/1y totals over time. OpenClaw keeps
                 no usage history and prunes sessions at ~30d, so we accumulate.
  - slow (~30s): status --json -> global task/job counts (slow; isolated).

  GET /agents   -> digested JSON (served from cache, never blocks on the CLI)
  GET /healthz  -> "ok"
"""
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

OPENCLAW = os.environ.get("OPENCLAW_BIN", os.path.expanduser("~/.npm-global/bin/openclaw"))
PORT = int(os.environ.get("SHIM_PORT", "9787"))
ACTIVE_WINDOW_S = float(os.environ.get("ACTIVE_WINDOW_S", "120"))
FAST_S = float(os.environ.get("FAST_REFRESH_S", "4"))
SLOW_S = float(os.environ.get("SLOW_REFRESH_S", "30"))
LEDGER_PATH = os.environ.get("LEDGER_PATH", os.path.expanduser("~/openclaw-shim/usage_ledger.json"))
CALL_S = float(os.environ.get("CALL_REFRESH_S", "3"))
# Live generation rate straight from vLLM. Session token deltas only move at turn
# boundaries and voice calls bypass the gateway entirely (no session), so the
# per-agent meter reads 0 mid-interaction. vLLM serves every agent, so its live
# rate is the real signal — we attribute it to whichever agent is driving it.
VLLM_METRICS_URL = os.environ.get("VLLM_METRICS_URL", "http://127.0.0.1:8000/metrics")  # set VLLM_METRICS_URL to your vLLM host
VLLM_S = float(os.environ.get("VLLM_REFRESH_S", "2"))
# Per-process resource scan of THIS box (the OpenClaw gateway host). Chat for every agent runs in
# one shared gateway process (not separable per agent); each agent's voip
# instance + any spawned subagent IS its own process. So we attribute what the
# OS can attribute and bucket the rest (gateway=all chat, browser=shared).
PROC_S = float(os.environ.get("PROC_REFRESH_S", "3"))
# Per-agent durable-task activity (running/queued runs + subagents) from the CLI.
ACT_S = float(os.environ.get("ACTIVITY_REFRESH_S", "6"))
# Reaper: the `openclaw` CLI spawns helper subprocesses (`openclaw-sessions`)
# that can detach and survive a killed parent, landing as PPID-1 orphans inside
# THIS shim's cgroup. Left alone they pile up (~350MB each) until the box swaps
# and the gateway's CLI calls time out — which makes the Presto agent list go
# blank. Sweep our own cgroup for these orphans and reap them.
REAP_S = float(os.environ.get("REAP_REFRESH_S", "30"))
REAP_AGE_S = float(os.environ.get("REAP_AGE_S", "90"))   # CLI calls finish in <30s; older orphan == leak
try:
    _CLK_TCK = os.sysconf("SC_CLK_TCK")
except Exception:  # noqa: BLE001
    _CLK_TCK = 100

# Voice-call activity: the matrix-voip-agents bypass the gateway, so call activity
# is invisible to the session-based stats. Poll each agent's voip `/status`.
VOIP_PORTS = {
    # agent-id -> the localhost port that agent's voice-call sidecar serves /status on.
    # Edit to match YOUR agents; leave empty to disable on-call detection entirely.
    # "agent-one": 8181,
    # "agent-two": 8182,
}


def _load_voip_token():
    if os.environ.get("VOIP_TOKEN"):
        return os.environ["VOIP_TOKEN"]
    # The voip sidecars share one API_TOKEN; read it from any sidecar's .env.
    for p in ("~/voip-<your-agent>/.env", "~/matrix-voip-agent/.env"):
        try:
            for ln in open(os.path.expanduser(p)):
                if ln.startswith("API_TOKEN="):
                    return ln.split("=", 1)[1].strip()
        except Exception:  # noqa: BLE001
            pass
    return ""


VOIP_TOKEN = _load_voip_token()

_lock = threading.Lock()
_agents = []
_agents_err = None
_agents_ts = 0.0
_tasks = {"active": 0, "running": 0, "queued": 0, "total": 0, "failures": 0, "subagents": 0}
_tasks_err = None
_tasks_ts = 0.0
_usage = {}
_agent_sessions = {}    # agentId -> [per-session detail] for the tap-to-inspect view
_prev_tokens = {}
_on_call = {}           # agentId -> bool: on a live Matrix voice call right now
_vllm = {"gen_tok_s": 0.0, "pp_tok_s": 0.0, "running": 0, "ts": 0.0}
_vllm_prev = None       # (ts, gen_total, prompt_total) for delta-rate
_agent_activity = {}    # agentId -> {"runs": n, "subagents": m} running/queued durable tasks
_host = {}              # box (gateway host) resource snapshot: cpu/mem + per-process consumers
_proc_agents = {}       # agentId -> {"cpu": %, "rss": MB} of that agent's own processes
_proc_prev = {}         # pid -> (utime+stime) ticks, for instantaneous CPU% deltas
_proc_sys_prev = None   # (total_jiffies, idle_jiffies) for system-wide CPU%

# token ledger (accurate, accumulating)
_ledger = {}          # "YYYY-MM-DD" (UTC) -> tokens counted that day
_session_seen = {}    # sessionId -> last totalTokens observed
_tracked_since = None


def _kill_tree(proc):
    """Kill a CLI call's whole process group, then reap it. subprocess.run's
    timeout only SIGKILLs the direct child; the `openclaw` CLI's helper
    grandchildren survive as orphans and leak. Killing the process group (we
    start each call in its own session) takes the non-detaching helpers down
    with it; the reaper mops up any that setsid'd away."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        pass


def _cli_json(args, timeout):
    """Run an `openclaw` CLI command and parse the JSON it prints.

    Capture via temp files + wait(), NOT pipes + communicate(). The CLI spawns
    helper subprocesses (`openclaw-sessions`) that inherit our stdout/stderr fds.
    communicate() blocks until EVERY holder of the pipe's write-end closes it, so
    a lingering helper keeps the pipe open and the call hangs to the full timeout
    even though the JSON was already written and the CLI itself has exited — which
    is exactly what was blanking the Presto agent list. wait() returns the moment
    the direct child exits; we then read the files (a helper still holding the fd
    cannot block a read of an unlinked temp file). _kill_tree + the reaper dispose
    of the helper so it doesn't pile up."""
    proc = None
    try:
        with tempfile.TemporaryFile("w+") as outf, tempfile.TemporaryFile("w+") as errf:
            proc = subprocess.Popen(
                [OPENCLAW] + args,
                stdout=outf, stderr=errf, text=True,
                env={**os.environ, "NO_COLOR": "1"},
                start_new_session=True,   # own process group so _kill_tree can take the helpers too
            )
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # A CPU-starved parent can miss a child that already exited inside
                # the window — under a tight cgroup CPUQuota the wait-loop doesn't
                # get scheduled before the wall-clock deadline, so a fast call looks
                # like a timeout. Check once more: if the child really finished, use
                # its output; only declare a timeout if it's genuinely still running.
                if proc.poll() is None:
                    _kill_tree(proc)
                    return None, "timeout"
            outf.seek(0)
            s = outf.read()
            if proc.returncode != 0:
                errf.seek(0)
                return None, "rc={} {}".format(proc.returncode, (errf.read() or "")[:120])
        for marker in ("[", "{"):
            i = s.find(marker)
            if i >= 0:
                try:
                    return json.loads(s[i:]), None
                except ValueError:
                    continue
        return None, "no json"
    except Exception as e:  # noqa: BLE001
        if proc is not None:
            _kill_tree(proc)
        return None, str(e)


def _btime():
    try:
        for ln in open("/proc/stat"):
            if ln.startswith("btime"):
                return int(ln.split()[1])
    except Exception:  # noqa: BLE001
        pass
    return 0


def _proc_age_s(pid):
    """Seconds since a pid started, from /proc/<pid>/stat field 22 (starttime)."""
    try:
        d = open("/proc/{}/stat".format(pid)).read()
        rest = d[d.rfind(")") + 2:].split()   # fields from #3 onward (skip pid + comm)
        start_epoch = _btime() + int(rest[19]) / _CLK_TCK   # field 22 == index 19 here
        return time.time() - start_epoch
    except Exception:  # noqa: BLE001
        return None


def _shim_cgroup_procs():
    """Path to THIS shim's cgroup.procs (v2). Scopes the reaper to our own
    cgroup so the gateway's workers (a different cgroup) are never touched."""
    try:
        rel = open("/proc/self/cgroup").read().strip().split("::", 1)[1]
        return "/sys/fs/cgroup" + rel + "/cgroup.procs"
    except Exception:  # noqa: BLE001
        return None


def reap_leaked_cli():
    path = _shim_cgroup_procs()
    if not path or not os.path.exists(path):
        return
    me = os.getpid()
    try:
        pids = [int(x) for x in open(path).read().split()]
    except Exception:  # noqa: BLE001
        return
    reaped = 0
    for pid in pids:
        if pid == me:
            continue
        try:
            comm = open("/proc/{}/comm".format(pid)).read().strip()
            if not comm.startswith("openclaw"):
                continue
            stat = open("/proc/{}/stat".format(pid)).read()
            ppid = int(stat[stat.rfind(")") + 2:].split()[1])   # field 4 == index 1
        except Exception:  # noqa: BLE001
            continue
        if ppid != 1:           # an in-flight call's child still has the shim as parent
            continue
        age = _proc_age_s(pid)
        if age is not None and age < REAP_AGE_S:
            continue            # too young — might be a normal teardown race
        try:
            os.kill(pid, signal.SIGKILL)
            reaped += 1
        except Exception:  # noqa: BLE001
            pass
    if reaped:
        print("reaper: killed {} leaked openclaw CLI helper(s)".format(reaped))


def _load_ledger():
    global _ledger, _session_seen, _tracked_since
    try:
        with open(LEDGER_PATH) as f:
            d = json.load(f)
        _ledger = d.get("ledger", {})
        _session_seen = d.get("session_seen", {})
        _tracked_since = d.get("tracked_since")
        print("ledger loaded: {} days, since {}".format(len(_ledger), _tracked_since))
    except Exception:
        print("ledger: starting fresh")


def _save_ledger():
    try:
        tmp = LEDGER_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"ledger": _ledger, "session_seen": _session_seen,
                       "tracked_since": _tracked_since}, f)
        os.replace(tmp, LEDGER_PATH)
    except Exception as e:  # noqa: BLE001
        print("ledger save err:", e)


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _update_ledger(sessions):
    """Accumulate per-session totalTokens growth into today's bucket.
    On the very first run we seed without counting pre-existing tokens (they
    predate tracking); thereafter every increase is real new usage."""
    global _session_seen, _tracked_since
    first_run = not _session_seen and not _ledger
    if _tracked_since is None:
        _tracked_since = _today()
    today = _today()
    delta = 0
    seen_now = {}
    for s in sessions:
        sid = s.get("sessionId")
        if not sid:
            continue
        tt = s.get("totalTokens") or 0
        seen_now[sid] = tt
        prev = _session_seen.get(sid)
        if prev is None:
            if not first_run:
                delta += tt          # brand-new session -> all its tokens are new
        elif tt > prev:
            delta += tt - prev       # session grew -> count the growth
        # tt < prev means a compaction/reset; ignore the drop
    _session_seen = seen_now
    if delta > 0:
        _ledger[today] = _ledger.get(today, 0) + delta
    # prune anything older than ~13 months
    cutoff = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%d")
    for ds in [d for d in _ledger if d < cutoff]:
        del _ledger[ds]
    _save_ledger()


def _ledger_window(days):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    return sum(v for ds, v in _ledger.items() if ds >= cutoff)


def _build_usage(sessions):
    now_ms = time.time() * 1000
    def approx(days):
        w = days * 86400000
        return sum((s.get("totalTokens") or 0) for s in sessions
                   if now_ms - s.get("updatedAt", 0) <= w)
    if _tracked_since:
        days_tracked = (datetime.now(timezone.utc).date()
                        - datetime.strptime(_tracked_since, "%Y-%m-%d").date()).days
    else:
        days_tracked = 0
    return {
        "approx_7d": approx(7),
        "approx_30d": approx(30),
        "ledger_7d": _ledger_window(7),
        "ledger_30d": _ledger_window(30),
        "ledger_365d": _ledger_window(365),
        "tracked_since": _tracked_since,
        "days_tracked": days_tracked,
    }


def refresh_agents():
    global _agents, _agents_err, _agents_ts, _usage, _agent_sessions
    roster, e1 = _cli_json(["agents", "list", "--json"], 20)
    # wide window (~368d) so the ledger + approx see all retained sessions, not just 24h
    sess_doc, e2 = _cli_json(
        ["sessions", "list", "--json", "--all-agents", "--active", "530000", "--limit", "500"], 30)

    # Keep-last-good: if either CLI call failed, DON'T rebuild — record the error
    # and leave the previous snapshot in place so the Presto keeps showing the
    # last-known agents (aging via agents_age_s) instead of going blank. A half
    # snapshot (roster without sessions) would also reset the ledger and spike
    # tok/s, so we only commit when both calls succeeded.
    if e1 or e2:
        with _lock:
            _agents_err = e1 or e2
        return

    sessions = []
    if isinstance(sess_doc, dict):
        sessions = sess_doc.get("sessions", [])
    elif isinstance(sess_doc, list):
        sessions = sess_doc

    # ledger uses the widest session view we can get (more history = better)
    if sessions:
        try:
            _update_ledger(sessions)
        except Exception as ex:  # noqa: BLE001
            print("ledger update err:", ex)

    by_agent = {}
    for s in sessions:
        by_agent.setdefault(s.get("agentId") or "unknown", []).append(s)

    now = time.time()
    out = []
    detail = {}
    for a in (roster or []):
        aid = a.get("id")
        mine = by_agent.get(aid, [])
        mine.sort(key=lambda s: s.get("ageMs", 1 << 62))
        recent = mine[0] if mine else None
        total_tokens = sum((s.get("totalTokens") or 0) for s in mine)
        in_tokens = sum((s.get("inputTokens") or 0) for s in mine)
        out_tokens = sum((s.get("outputTokens") or 0) for s in mine)
        age_ms = recent.get("ageMs") if recent else None
        last_seen_s = (age_ms / 1000.0) if age_ms is not None else None
        active = last_seen_s is not None and last_seen_s <= ACTIVE_WINDOW_S

        tok_s = 0.0
        pp_tok_s = 0.0
        prev = _prev_tokens.get(aid)
        if prev:
            dt = now - prev[0]
            if dt > 0:
                if out_tokens >= prev[1]:
                    tok_s = (out_tokens - prev[1]) / dt
                if len(prev) > 2 and in_tokens >= prev[2]:
                    pp_tok_s = (in_tokens - prev[2]) / dt
        _prev_tokens[aid] = (now, out_tokens, in_tokens)
        active_sessions = sum(
            1 for s in mine
            if (s.get("ageMs") if s.get("ageMs") is not None else 1 << 62) <= ACTIVE_WINDOW_S * 1000)

        detail[aid] = [{
            "key": s.get("key"),
            "kind": s.get("kind"),
            "model": s.get("model"),
            "provider": s.get("modelProvider"),
            "context_tokens": s.get("contextTokens"),
            "total_tokens": s.get("totalTokens") or 0,
            "in_tokens": s.get("inputTokens") or 0,
            "out_tokens": s.get("outputTokens") or 0,
            "age_ms": s.get("ageMs"),
            "thinking": s.get("thinkingLevel"),
            "aborted": bool(s.get("abortedLastRun")),
        } for s in mine[:20]]

        pa = _proc_agents.get(aid) or {}
        act = _agent_activity.get(aid) or {}
        out.append({
            "id": aid,
            "name": a.get("identityName") or a.get("name") or aid,
            "emoji": a.get("identityEmoji") or "",
            "model": (recent.get("model") if recent else None) or a.get("model"),
            "provider": recent.get("modelProvider") if recent else None,
            "active": active or _on_call.get(aid, False),
            "on_call": _on_call.get(aid, False),
            "working": _on_call.get(aid, False),  # overlay flips this for the live model-driving agent
            "last_seen_s_ago": int(last_seen_s) if last_seen_s is not None else None,
            "tok_s": round(tok_s, 1),
            "pp_tok_s": round(pp_tok_s, 1),
            "active_sessions": active_sessions,
            "runs_active": act.get("runs", 0),
            "subagents_active": act.get("subagents", 0),
            "proc_cpu": pa.get("cpu"),
            "proc_rss_mb": pa.get("rss"),
            "total_tokens": total_tokens,
            "in_tokens": in_tokens,
            "out_tokens": out_tokens,
            "context_tokens": recent.get("contextTokens") if recent else None,
            "sessions": len(mine),
            "current": recent.get("kind") if recent else None,
            "is_default": a.get("isDefault", False),
        })
    out.sort(key=lambda x: (not x["active"], -(x["tok_s"]), x["id"]))

    usage = _build_usage(sessions)
    with _lock:
        _agents = out
        _agents_err = e1 or e2
        _agents_ts = now
        _usage = usage
        _agent_sessions = detail


def refresh_tasks():
    global _tasks, _tasks_err, _tasks_ts
    usage, e = _cli_json(["status", "--json", "--timeout", "4000"], 25)
    if isinstance(usage, dict) and "tasks" in usage:
        t = usage.get("tasks", {})
        bs = t.get("byStatus", {})
        with _lock:
            _tasks = {
                "active": t.get("active", 0),
                "running": bs.get("running", 0),
                "queued": bs.get("queued", 0),
                "total": t.get("total", 0),
                "failures": t.get("failures", 0),
                "subagents": t.get("byRuntime", {}).get("subagent", 0),
            }
            _tasks_err = None
            _tasks_ts = time.time()
    else:
        with _lock:
            _tasks_err = e


def _loop(fn, interval):
    while True:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print("refresh error in {}: {}".format(fn.__name__, e))
        time.sleep(interval)


def _overlay_live_rate(agents, v):
    """Attribute the live vLLM generation rate to the agent driving the model.
    Done per-request (not at the slow CLI refresh) so the meter tracks vLLM in
    real time: an agent on a call (which has no gateway session, so its
    session-derived tok_s is always 0), else the most-recently-active chat agent.
    Split across agents if more than one is busy (approx; one-at-a-time is the norm)."""
    if not (v.get("running", 0) > 0 or v.get("gen_tok_s", 0) > 1.0):
        return
    targets = [a for a in agents if a.get("on_call")]
    if not targets:
        act = [a for a in agents if a.get("active")]
        act.sort(key=lambda a: a["last_seen_s_ago"] if a.get("last_seen_s_ago") is not None else 1 << 30)
        targets = act[:1]
    if not targets:
        return
    g = v["gen_tok_s"] / len(targets)
    p = v["pp_tok_s"] / len(targets)
    in_flight = v.get("running", 0) > 0
    for a in targets:
        a["tok_s"] = round(max(a.get("tok_s", 0.0), g), 1)
        a["pp_tok_s"] = round(max(a.get("pp_tok_s", 0.0), p), 1)
        if in_flight:
            a["working"] = True
    agents.sort(key=lambda x: (not x["active"], -(x["tok_s"]), x["id"]))


def snapshot():
    now = time.time()
    with _lock:
        agents = [dict(a) for a in _agents]   # copies so the overlay can't mutate cache
        v = dict(_vllm)
        tasks = dict(_tasks)
        usage = dict(_usage)
        host = dict(_host)
        a_ts, t_ts = _agents_ts, _tasks_ts
        errors = {}
        if _agents_err:
            errors["agents"] = _agents_err
        if _tasks_err:
            errors["tasks"] = _tasks_err
    _overlay_live_rate(agents, v)
    return {
        "ts": now,
        "warming": a_ts == 0.0,
        "agents": agents,
        "agents_age_s": int(now - a_ts) if a_ts else None,
        "tasks": tasks,
        "tasks_age_s": int(now - t_ts) if t_ts else None,
        "usage": usage,
        "vllm": v,
        "host": host,
        "errors": errors or None,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="application/json"):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.startswith("/healthz"):
            return self._send(200, "ok", "text/plain")
        if self.path.startswith("/agents"):
            return self._send(200, json.dumps(snapshot(), ensure_ascii=False))
        if self.path.startswith("/agent"):
            q = parse_qs(urlparse(self.path).query)
            aid = (q.get("id") or [""])[0]
            with _lock:
                sess = list(_agent_sessions.get(aid, []))
            return self._send(200, json.dumps({"id": aid, "sessions": sess}, ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *a):
        pass


def refresh_calls():
    global _on_call
    import urllib.request
    oc = {}
    for aid, port in VOIP_PORTS.items():
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:{}/status".format(port),
                headers={"Authorization": "Bearer " + VOIP_TOKEN})
            with urllib.request.urlopen(req, timeout=0.9) as r:
                d = json.loads(r.read().decode("utf-8"))
            oc[aid] = (d.get("activeCalls") or 0) > 0
        except Exception:  # noqa: BLE001
            oc[aid] = False
    with _lock:
        _on_call = oc


def _metric_val(ln):
    try:
        return float(ln.rsplit(" ", 1)[1])
    except Exception:  # noqa: BLE001
        return 0.0


def _parse_vllm_metrics(text):
    # Sum counters across every model_name label (one vLLM serves all agents).
    gen = prompt = run = 0.0
    for ln in text.splitlines():
        if ln.startswith("#"):
            continue
        if ln.startswith("vllm:generation_tokens_total"):
            gen += _metric_val(ln)
        elif ln.startswith("vllm:prompt_tokens_total"):
            prompt += _metric_val(ln)
        elif ln.startswith("vllm:num_requests_running"):
            run += _metric_val(ln)
    return gen, prompt, run


def refresh_vllm():
    global _vllm_prev, _vllm
    import urllib.request
    try:
        with urllib.request.urlopen(VLLM_METRICS_URL, timeout=2.5) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return  # spark unreachable -> keep last-good; don't zero the meter
    gen, prompt, run = _parse_vllm_metrics(text)
    now = time.time()
    gen_s = pp_s = 0.0
    if _vllm_prev:
        dt = now - _vllm_prev[0]
        if dt > 0:
            if gen >= _vllm_prev[1]:
                gen_s = (gen - _vllm_prev[1]) / dt
            if prompt >= _vllm_prev[2]:
                pp_s = (prompt - _vllm_prev[2]) / dt
    _vllm_prev = (now, gen, prompt)
    with _lock:
        _vllm = {"gen_tok_s": round(gen_s, 1), "pp_tok_s": round(pp_s, 1),
                 "running": int(run), "ts": now}


def refresh_activity():
    # Per-agent live work from durable tasks: running/queued runs + subagents.
    # (Plain interactive turns may not create a durable task; this captures
    # background/subagent/flow work, which is what spawns extra processes.)
    global _agent_activity
    doc, _ = _cli_json(["tasks", "list", "--json"], 15)
    ts = doc.get("tasks", doc) if isinstance(doc, dict) else doc
    if not isinstance(ts, list):
        return
    act = {}
    for t in ts:
        if t.get("status") not in ("running", "queued"):
            continue
        aid = t.get("agentId") or "unknown"
        e = act.setdefault(aid, {"runs": 0, "subagents": 0})
        e["runs"] += 1
        if t.get("runtime") == "subagent":
            e["subagents"] += 1
    with _lock:
        _agent_activity = act


def _proc_ticks(pid):
    try:
        d = open("/proc/{}/stat".format(pid)).read()
        rest = d[d.rfind(")") + 2:].split()   # skip comm (may contain spaces/parens)
        return int(rest[11]) + int(rest[12])  # utime + stime
    except Exception:  # noqa: BLE001
        return None


def _proc_rss_mb(pid):
    try:
        for ln in open("/proc/{}/status".format(pid)):
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1]) / 1024.0
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _proc_field(pid, name):
    try:
        if name == "cmdline":
            return open("/proc/{}/cmdline".format(pid), "rb").read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        return os.readlink("/proc/{}/cwd".format(pid))
    except Exception:  # noqa: BLE001
        return ""


def _classify_proc(pid):
    """Map a pid to (label, kind, agentId) or None if not OpenClaw-related."""
    cl = _proc_field(pid, "cmdline")
    if not cl:
        return None
    low = cl.lower()
    if "brave" in low:
        return ("browser (shared)", "browser", None)
    if "node" not in low or ("openclaw" not in low and "matrix-voip-agent" not in low):
        return None
    cw = _proc_field(pid, "cwd")
    if "/voip-" in cw:
        a = cw.rsplit("voip-", 1)[-1]
        return ("voip:" + a, "voip", a)
    if cw.endswith("/matrix-voip-agent"):
        return ("voip:default", "voip", "default")
    if "gateway" in low:
        return ("gateway (all chat)", "gateway", None)
    if "--agent" in cl:
        try:
            a = cl.split("--agent", 1)[1].split()[0]
        except Exception:  # noqa: BLE001
            a = "?"
        return ("run:" + a, "run", a)
    return ("node:other", "other", None)


def _sys_cpu():
    vals = [int(x) for x in open("/proc/stat").readline().split()[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)   # idle + iowait
    return sum(vals), idle


def refresh_proc():
    global _proc_prev, _proc_sys_prev, _host, _proc_agents
    import glob
    prev_sys = _proc_sys_prev
    sys_total, sys_idle = _sys_cpu()
    sys_d = (sys_total - prev_sys[0]) if prev_sys else 0

    procs = {}   # pid -> (label, kind, agent, ticks, rss)
    for dr in glob.glob("/proc/[0-9]*"):
        pid = dr.rsplit("/", 1)[-1]
        c = _classify_proc(pid)
        if not c:
            continue
        ticks = _proc_ticks(pid)
        if ticks is None:
            continue
        procs[pid] = (c[0], c[1], c[2], ticks, _proc_rss_mb(pid))

    agg = {}        # label -> {label, kind, agent, cpu, rss}
    per_agent = {}  # agentId -> {cpu, rss}
    for pid, (label, kind, agent, ticks, rss) in procs.items():
        prev = _proc_prev.get(pid)
        cpu = max(0.0, 100.0 * (ticks - prev) / sys_d) if (prev is not None and sys_d > 0) else 0.0
        e = agg.setdefault(label, {"label": label, "kind": kind, "agent": agent, "cpu": 0.0, "rss": 0.0})
        e["cpu"] += cpu
        e["rss"] += rss
        if agent:
            pa = per_agent.setdefault(agent, {"cpu": 0.0, "rss": 0.0})
            pa["cpu"] += cpu
            pa["rss"] += rss

    _proc_prev = {pid: v[3] for pid, v in procs.items()}
    _proc_sys_prev = (sys_total, sys_idle)

    cpu_pct = 0.0
    if prev_sys and sys_d > 0:
        cpu_pct = round(100.0 * (sys_d - (sys_idle - prev_sys[1])) / sys_d, 1)

    mt = ma = 0.0
    try:
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemTotal:"):
                mt = int(ln.split()[1]) / 1024.0
            elif ln.startswith("MemAvailable:"):
                ma = int(ln.split()[1]) / 1024.0
    except Exception:  # noqa: BLE001
        pass
    try:
        load1 = os.getloadavg()[0]
    except Exception:  # noqa: BLE001
        load1 = 0.0

    def bucket(kind):
        return {
            "cpu": round(sum(e["cpu"] for e in agg.values() if e["kind"] == kind), 1),
            "rss": round(sum(e["rss"] for e in agg.values() if e["kind"] == kind)),
        }

    consumers = sorted(agg.values(), key=lambda e: (-e["cpu"], -e["rss"]))[:16]
    for e in consumers:
        e["cpu"] = round(e["cpu"], 1)
        e["rss"] = round(e["rss"])

    host = {
        "cores": os.cpu_count(),
        "cpu_pct": cpu_pct,
        "load1": round(load1, 2),
        "mem_total_mb": round(mt),
        "mem_avail_mb": round(ma),
        "mem_used_mb": round(mt - ma),
        "gateway": bucket("gateway"),
        "browser": bucket("browser"),
        "voip_total": bucket("voip"),
        "consumers": consumers,
        "ts": time.time(),
    }
    pa_round = {a: {"cpu": round(x["cpu"], 1), "rss": round(x["rss"])} for a, x in per_agent.items()}
    with _lock:
        _host = host
        _proc_agents = pa_round


def main():
    print("openclaw-shim on :{} (openclaw={})".format(PORT, OPENCLAW))
    _load_ledger()
    threading.Thread(target=_loop, args=(refresh_agents, FAST_S), daemon=True).start()
    threading.Thread(target=_loop, args=(refresh_tasks, SLOW_S), daemon=True).start()
    threading.Thread(target=_loop, args=(refresh_calls, CALL_S), daemon=True).start()
    threading.Thread(target=_loop, args=(refresh_vllm, VLLM_S), daemon=True).start()
    threading.Thread(target=_loop, args=(refresh_activity, ACT_S), daemon=True).start()
    threading.Thread(target=_loop, args=(refresh_proc, PROC_S), daemon=True).start()
    threading.Thread(target=_loop, args=(reap_leaked_cli, REAP_S), daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
