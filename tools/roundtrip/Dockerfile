# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/roundtrip

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev --ignore-scripts

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m venv /opt/venv \
    && pip install --no-compile --requirement requirements.txt

COPY roundtrip.py run.sh *.mjs ./

RUN groupadd --gid 10001 roundtrip \
    && useradd --uid 10001 --gid roundtrip --no-create-home --shell /usr/sbin/nologin roundtrip \
    && chmod 0555 /opt/roundtrip/run.sh /opt/roundtrip/roundtrip.py /opt/roundtrip/*.mjs

WORKDIR /workspace

USER 10001:10001
ENTRYPOINT ["/opt/roundtrip/run.sh"]
