#!/usr/bin/env bash
# Build the default AgentFlow sandbox image.
#
# After this completes, flip "Sandbox mode" to "Docker" in Settings to start
# running tasks inside containers.
set -euo pipefail
cd "$(dirname "$0")"
docker build -t agentflow/claude-sandbox:latest .
echo
echo "Built agentflow/claude-sandbox:latest"
echo "Enable it under Settings → Sandbox → Default sandbox mode: Docker"
