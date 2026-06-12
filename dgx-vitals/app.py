"""DGX Spark vitals service.

Exposes GET /vitals with a single JSON blob for the Presto cockpit.
Runs as a Docker container on the DGX itself. On GB10 the GPU uses unified
LPDDR5X, so discrete VRAM may report null — the Presto falls back to the
system MEM tile in that case.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import docker
import httpx
import psutil
from fastapi import FastAPI, Response
from pynvml import (
    NVMLError,
    nvmlDeviceGetCount,
    nvmlDeviceGetFanSpeed,
    nvmlDeviceGetHandleByIndex,
    nvmlDeviceGetMemoryInfo,
    nvmlDeviceGetName,
    nvmlDeviceGetPowerUsage,
    nvmlDeviceGetTemperature,
    nvmlDeviceGetUtilizationRates,
    nvmlInit,
    nvmlShutdown,
    NVML_TEMPERATURE_GPU,
)

VLLM_METRICS_URLS = [u for u in os.getenv("VLLM_METRICS_URLS", "").split(",") if u.strip()]
OLLAMA_URL = os.getenv("OLLAMA_URL", "").strip()

app = FastAPI()
_docker = docker.from_env() if os.path.exists("/var/run/docker.sock") else None
_prev_net: tuple[float, int, int] | None = None
_prev_tok_counts: dict[str, tuple[float, float]] = {}


@app.on_event("startup")
def _nvml_start() -> None:
    try:
        nvmlInit()
    except NVMLError:
        pass


@app.on_event("shutdown")
def _nvml_stop() -> None:
    try:
        nvmlShutdown()
    except NVMLError:
        pass


def _gpu() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        n = nvmlDeviceGetCount()
    except NVMLError:
        return out
    for i in range(n):
        h = nvmlDeviceGetHandleByIndex(i)
        # GB10 / integrated GPUs use unified memory and may not report via NVML.
        mem_used_mb = mem_total_mb = None
        try:
            mem = nvmlDeviceGetMemoryInfo(h)
            if mem.total:
                mem_used_mb = mem.used // (1024 * 1024)
                mem_total_mb = mem.total // (1024 * 1024)
        except NVMLError:
            pass
        try:
            fan = nvmlDeviceGetFanSpeed(h)
        except NVMLError:
            fan = None
        try:
            power_w = nvmlDeviceGetPowerUsage(h) / 1000.0
        except NVMLError:
            power_w = None
        try:
            util_pct = nvmlDeviceGetUtilizationRates(h).gpu
        except NVMLError:
            util_pct = None
        try:
            temp_c = nvmlDeviceGetTemperature(h, NVML_TEMPERATURE_GPU)
        except NVMLError:
            temp_c = None
        name = nvmlDeviceGetName(h)
        out.append({
            "index": i,
            "name": name.decode() if isinstance(name, bytes) else name,
            "temp_c": temp_c,
            "util_pct": util_pct,
            "mem_used_mb": mem_used_mb,
            "mem_total_mb": mem_total_mb,
            "power_w": power_w,
            "fan_pct": fan,
        })
    return out


def _net() -> dict[str, float]:
    global _prev_net
    counters = psutil.net_io_counters()
    now = time.time()
    rx_bps = tx_bps = 0.0
    if _prev_net is not None:
        dt = now - _prev_net[0]
        if dt > 0:
            rx_bps = (counters.bytes_recv - _prev_net[1]) / dt
            tx_bps = (counters.bytes_sent - _prev_net[2]) / dt
    _prev_net = (now, counters.bytes_recv, counters.bytes_sent)
    return {"rx_bps": rx_bps, "tx_bps": tx_bps}


def _containers() -> list[dict[str, Any]]:
    # name/image/status only — `stats()` is a ~1-2s blocking call per container
    # and would make /vitals time out on a busy host.
    if _docker is None:
        return []
    out: list[dict[str, Any]] = []
    try:
        for c in _docker.containers.list():
            tags = c.image.tags
            out.append({
                "id": c.short_id,
                "name": c.name,
                "image": tags[0] if tags else c.image.short_id,
                "status": c.status,
            })
    except Exception:
        return out
    return out


async def _vllm_models(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Scrape vLLM /metrics endpoints for tok/s and in-flight requests."""
    if not VLLM_METRICS_URLS:
        return []
    out: list[dict[str, Any]] = []
    for url in VLLM_METRICS_URLS:
        try:
            r = await client.get(url, timeout=2.0)
            if r.status_code != 200:
                continue
            model = None
            gen_tokens = None
            prompt_tokens = None
            in_flight = None
            for line in r.text.splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                if "vllm:generation_tokens_total" in line:
                    parts = line.rsplit(" ", 1)
                    try:
                        gen_tokens = float(parts[1])
                    except (ValueError, IndexError):
                        pass
                    if "model_name=" in line:
                        seg = line.split("model_name=\"", 1)[1].split("\"", 1)[0]
                        model = seg
                elif "vllm:prompt_tokens_total" in line:
                    parts = line.rsplit(" ", 1)
                    try:
                        prompt_tokens = float(parts[1])
                    except (ValueError, IndexError):
                        pass
                elif "vllm:num_requests_running" in line:
                    parts = line.rsplit(" ", 1)
                    try:
                        in_flight = int(float(parts[1]))
                    except (ValueError, IndexError):
                        pass
            tok_s = None
            pp_tok_s = None
            now = time.time()
            if gen_tokens is not None or prompt_tokens is not None:
                prev = _prev_tok_counts.get(url)
                if prev:
                    dt = now - prev[0]
                    if dt > 0:
                        if gen_tokens is not None and prev[1] is not None:
                            tok_s = max(0.0, (gen_tokens - prev[1]) / dt)
                        if prompt_tokens is not None and prev[2] is not None:
                            pp_tok_s = max(0.0, (prompt_tokens - prev[2]) / dt)
                _prev_tok_counts[url] = (now, gen_tokens, prompt_tokens)
            out.append({
                "source": "vllm",
                "endpoint": url,
                "model": model,
                "tok_s": tok_s,
                "pp_tok_s": pp_tok_s,
                "requests_in_flight": in_flight,
            })
        except Exception:
            continue
    return out


async def _ollama_models(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    if not OLLAMA_URL:
        return []
    try:
        r = await client.get(f"{OLLAMA_URL.rstrip('/')}/api/ps", timeout=2.0)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []
    out = []
    for m in data.get("models", []):
        out.append({
            "source": "ollama",
            "model": m.get("name"),
            "size_mb": (m.get("size_vram") or m.get("size") or 0) // (1024 * 1024),
            "tok_s": None,
            "requests_in_flight": None,
        })
    return out


@app.get("/vitals")
async def vitals() -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        vllm_task = asyncio.create_task(_vllm_models(client))
        ollama_task = asyncio.create_task(_ollama_models(client))
        gpu = _gpu()
        cpu_pct = psutil.cpu_percent(interval=None)
        load = os.getloadavg()
        vm = psutil.virtual_memory()
        net = _net()
        containers = _containers()
        models = await vllm_task + await ollama_task
    return {
        "ts": time.time(),
        "host": os.uname().nodename,
        "uptime_s": time.time() - psutil.boot_time(),
        "gpu": gpu,
        "cpu": {"util_pct": cpu_pct, "load1": load[0], "load5": load[1], "load15": load[2]},
        "mem": {"used_mb": vm.used // (1024 * 1024), "total_mb": vm.total // (1024 * 1024), "pct": vm.percent},
        "net": net,
        "containers": containers,
        "models": models,
    }


@app.get("/container/{cid}")
def container_detail(cid: str) -> dict[str, Any]:
    """Per-container drill-down for the cockpit's tap-to-inspect view: state plus
    the tail of the log with error-looking lines pulled out separately."""
    if _docker is None:
        return {"error": "docker unavailable"}
    try:
        c = _docker.containers.get(cid)
    except Exception as e:
        return {"error": "not found: " + str(e)[:100]}
    try:
        raw = c.logs(tail=60, timestamps=False).decode("utf-8", "replace")
    except Exception:
        raw = ""
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    kw = ("error", "exception", "traceback", "fatal", "panic", "fail", "critical", "oom", "warn")
    errors = [ln for ln in lines if any(k in ln.lower() for k in kw)]
    attrs = c.attrs or {}
    state = attrs.get("State", {})
    tags = c.image.tags
    return {
        "id": c.short_id,
        "name": c.name,
        "image": tags[0] if tags else c.image.short_id,
        "status": c.status,
        "started_at": state.get("StartedAt"),
        "restart_count": attrs.get("RestartCount"),
        "exit_code": state.get("ExitCode"),
        "health": (state.get("Health") or {}).get("Status"),
        "oom_killed": state.get("OOMKilled"),
        "recent": lines[-20:],
        "errors": errors[-12:],
    }


@app.get("/healthz")
def health() -> Response:
    return Response("ok", media_type="text/plain")
