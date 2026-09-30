# Slipwright: API + web UI + the toolchains the agents need to build the projects they
# work on (git, gh, uv/Python, Node, JDK/Gradle/Android SDK). State (SQLite, secret key, clones, worktrees, logs)
# lives under /data — mount a volume there.
#
#   docker compose up --build
#   docker compose exec slipwright slipwright user add ada
#
# Stage 1: build the web UI ----------------------------------------------------------------
# On the build machine's own platform: its output is static files, the same for every
# architecture, and building it under emulation for arm64 is several times slower.
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY schemas/openapi.json /src/schemas/openapi.json
COPY web/ ./
# vite writes to ../slipwright/api/static (see vite.config.ts)
RUN mkdir -p /src/slipwright/api && npm run build

# Stage 2: the Android SDK and Gradle -------------------------------------------------------
# A project's own commands run as an ordinary user with no package manager, so a mobile
# project whose build fetched its own SDK failed every fix round it was given. They are
# installed here instead. On the build machine's own platform, like the web UI: what lands
# in /opt is the same files for every architecture, and sdkmanager is a JVM program that
# takes minutes under arm64 emulation to do what takes seconds natively.
#
# The build-tools binaries (aapt2, zipalign) are x86_64 only -- Google publishes no others --
# so on an arm64 installation an Android build still fails, now with an honest error.
#
# Gradle 8.14 is the last 8.x and runs every Android Gradle Plugin 8 release, which is what a
# model writes; a project needing AGP 9 names a wrapper of its own. Kept in step with
# Dockerfile.runner, which is where the commands run on a hosted installation.
FROM --platform=$BUILDPLATFORM eclipse-temurin:21-jdk AS android
ARG ANDROID_TOOLS=16111833
ARG ANDROID_TOOLS_SHA1=e025545c62a8e64c7559119566a569fb1dec5f60
ARG ANDROID_PACKAGES="platforms;android-35 platforms;android-36 build-tools;35.0.0 build-tools;36.0.0"
ARG GRADLE_VERSION=8.14.3
ARG GRADLE_SHA256=bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSLo /tmp/tools.zip \
         "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_TOOLS}_latest.zip" \
    && echo "${ANDROID_TOOLS_SHA1}  /tmp/tools.zip" | sha1sum -c - \
    && mkdir -p /opt/android-sdk/cmdline-tools \
    && unzip -q /tmp/tools.zip -d /opt/android-sdk/cmdline-tools \
    && mv /opt/android-sdk/cmdline-tools/cmdline-tools /opt/android-sdk/cmdline-tools/latest \
    && rm /tmp/tools.zip
# the licences, accepted once here: Gradle refuses an SDK whose licences nobody accepted
RUN yes | /opt/android-sdk/cmdline-tools/latest/bin/sdkmanager \
         --sdk_root=/opt/android-sdk --licenses > /dev/null \
    && /opt/android-sdk/cmdline-tools/latest/bin/sdkmanager --sdk_root=/opt/android-sdk \
         ${ANDROID_PACKAGES} > /tmp/sdk.log || { cat /tmp/sdk.log; exit 1; }
# sdkmanager itself is only needed to get here: Gradle fetches a missing platform on its own
RUN rm -rf /opt/android-sdk/cmdline-tools
RUN curl -fsSLo /tmp/gradle.zip \
         "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" \
    && echo "${GRADLE_SHA256}  /tmp/gradle.zip" | sha256sum -c - \
    && mkdir -p /opt/gradle \
    && unzip -q /tmp/gradle.zip -d /opt/gradle \
    && rm /tmp/gradle.zip

# Stage 3: runtime --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# UV_PROJECT_ENVIRONMENT is set only where Slipwright's own venv is built: a project's
# `uv sync` in a job worktree must create its own .venv, never write into /opt/venv
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:/root/.local/bin:${PATH}" \
    SLIPWRIGHT_STATE_DIR=/data \
    SLIPWRIGHT_HOST=0.0.0.0 \
    SLIPWRIGHT_PORT=8500

# git + gh (DevOps role), curl (health checks), node (projects that need it)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git gnupg openssh-client \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
         -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
         > /etc/apt/sources.list.d/github-cli.list \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh nodejs \
    && rm -rf /var/lib/apt/lists/*

# Java and Android for mobile projects (stage 2). The JDK is this platform's own; the SDK
# belongs to uid 1000 so Gradle may add a platform a project asks for that is not here yet.
COPY --from=eclipse-temurin:21-jdk /opt/java/openjdk /opt/java/openjdk
COPY --from=android --chown=1000:1000 /opt/android-sdk /opt/android-sdk
COPY --from=android /opt/gradle /opt/gradle
RUN ln -s /opt/gradle/gradle-*/bin/gradle /usr/local/bin/gradle
ENV JAVA_HOME=/opt/java/openjdk \
    ANDROID_HOME=/opt/android-sdk \
    PATH="/opt/java/openjdk/bin:${PATH}"

# OpenAI's Codex CLI: how a ChatGPT plan runs the agents (providers/codex.py). Signed in per
# account from Settings -> Models; each session is kept under /data, never under /work.
RUN npm install -g @openai/codex && npm cache clean --force

# uv: runs Slipwright and is the package manager of the example (Python) profile
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
# dependencies first so source edits do not invalidate this layer
# `--extra postgres` brings psycopg: the image has to be able to reach a database server,
# because a hosted installation keeps everything there rather than in /data
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-dev --extra postgres \
        --no-install-project
COPY slipwright/ ./slipwright/
COPY examples/ ./examples/
COPY standards/ ./standards/
COPY schemas/ ./schemas/
COPY scripts/ ./scripts/
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-dev --extra postgres
COPY --from=web /src/slipwright/api/static ./slipwright/api/static

# jobs commit on their branches; give git an identity so commits never fail
RUN git config --global user.name slipwright \
    && git config --global user.email slipwright@localhost \
    && git config --global --add safe.directory '*'

# The server does not need to be root, and on a hosted installation it must not be: with
# SLIPWRIGHT_RUNNER=local a job's own commands run as this user too, and the difference
# between "a stranger's build script" and "a stranger's build script as root" is the
# whole machine.
#
# /work is where checkouts live and /data holds the database and the key that decrypts
# every stored credential. They are separate volumes so that a relative path out of a
# worktree cannot reach the key -- see `Settings.work_dir`.
RUN useradd --uid 1000 --create-home --shell /bin/sh slipwright \
    && mkdir -p /data /work /repos \
    && cp /root/.gitconfig /home/slipwright/.gitconfig \
    && chown -R 1000:1000 /data /work /repos /app /home/slipwright
USER 1000:1000
ENV HOME=/home/slipwright \
    SLIPWRIGHT_WORK_DIR=/work

VOLUME ["/data"]
VOLUME ["/work"]

# What this image was released as (update.py's running_version), set by CI from the tag it
# computed. Last, so a new number does not rebuild every layer above; empty in a local
# build, which then reports pyproject.toml's version.
ARG SLIPWRIGHT_VERSION=""
ENV SLIPWRIGHT_VERSION=${SLIPWRIGHT_VERSION}
EXPOSE 8500
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS http://127.0.0.1:8500/healthz || exit 1

ENTRYPOINT ["slipwright"]
CMD ["serve"]
