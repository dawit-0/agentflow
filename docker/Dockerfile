# AgentFlow Claude sandbox image.
#
# Each task run gets its own disposable container started with `docker run --rm`.
# The host's work_dir is bind-mounted in, ~/.claude is mounted read-only for auth.
#
# Build:
#   bash docker/build.sh
# Or directly:
#   docker build -t agentflow/claude-sandbox:latest docker/

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH=/usr/local/bin:/usr/bin:/bin:/home/agent/.local/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        less \
        passwd \
        python3 \
        python3-pip \
        python3-venv \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20 (needed by the Claude CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force

# Non-root user. The orchestrator mounts ~/.claude here so the CLI re-uses
# the host's login.
RUN useradd --create-home --uid 1000 --shell /bin/bash agent
USER agent
WORKDIR /home/agent

ENTRYPOINT []
CMD ["bash"]
