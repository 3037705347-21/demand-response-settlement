# syntax=docker/dockerfile:1.7
FROM python:3.12.8-slim-bookworm@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0 AS codex
ADD --checksum=sha256:dc6e7c4d6de71c23a0f60d05e2577ff7eef615b76f22630d58ad384b84763522 \
    https://cdn.npmmirror.com/packages/%40openai/codex/0.163.0-linux-arm64/codex-0.163.0-linux-arm64.tgz \
    /tmp/codex-arm64.tgz
ADD --checksum=sha256:30efc97738b975940d78b59a9bea115fa34040b732807d54ec35ae6b7528de94 \
    https://cdn.npmmirror.com/packages/%40openai/codex/0.163.0-linux-x64/codex-0.163.0-linux-x64.tgz \
    /tmp/codex-x64.tgz
ARG TARGETARCH
RUN case "$TARGETARCH" in \
      arm64) archive=/tmp/codex-arm64.tgz ;; \
      amd64) archive=/tmp/codex-x64.tgz ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && mkdir -p /opt/codex \
    && tar -xzf "$archive" -C /opt/codex \
       --wildcards \
       'package/vendor/*/bin/codex' \
       'package/vendor/*/bin/codex-code-mode-host' \
       'package/vendor/*/codex-path/rg' \
       'package/vendor/*/codex-resources/bwrap'

FROM python:3.12.8-slim-bookworm@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0
COPY --from=codex /opt/codex /opt/codex
RUN ln -s /opt/codex/package/vendor/*/bin/codex /usr/local/bin/codex \
    && ln -s /opt/codex/package/vendor/*/codex-path/rg /usr/local/bin/rg

RUN find /usr/local/lib/python3.12 -type f -name '*.pyc' -delete \
    && find /usr/local/lib/python3.12 -type d -name '__pycache__' -empty -delete

RUN useradd --create-home --uid 10001 worker
WORKDIR /workspace
COPY workspace/ /workspace/
RUN chown -R worker:worker /workspace
USER worker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

CMD ["bash"]
