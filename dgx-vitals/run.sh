#!/usr/bin/env bash
set -euo pipefail
docker rm -f dgx-vitals 2>/dev/null || true
docker build -t dgx-vitals:latest .
# --network host: psutil sees real host CPU/mem/net; service binds host :9876 directly.
# --pid=host: host process view. nvidia default runtime injects the driver libs.
docker run -d --restart=unless-stopped --name dgx-vitals \
  --gpus all \
  --pid=host \
  --network host \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e VLLM_METRICS_URLS="${VLLM_METRICS_URLS:-}" \
  -e OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}" \
  dgx-vitals:latest
sleep 2
echo "---- /vitals smoke ----"
curl -sf http://localhost:9876/vitals | python3 -m json.tool | head -60 || { echo "smoke failed; logs:"; docker logs --tail 30 dgx-vitals; }
