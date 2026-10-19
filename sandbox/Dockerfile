FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates curl procps util-linux coreutils bash \
    && rm -rf /var/lib/apt/lists/*

ENV GIT_TERMINAL_PROMPT=0 HOME=/tmp
CMD ["sleep", "infinity"]
