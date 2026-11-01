# devops-tools agent image: a project's toolchain image (BASE_IMAGE, itself built on
# devops-tools-base) plus Node, Claude Code, and an `agent` user with the host's uid and gid,
# so files in the checkout stay the host user's. The home is a named volume, so the agent's
# logins survive the container and never touch the host's. No project needs its own copy.
# `devops-tools container agent` builds it and passes BASE_IMAGE and the ids.

ARG BASE_IMAGE

FROM ubuntu:24.04 AS node

ARG NODE_VERSION=22.23.4
ARG NODE_SHA256=1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/node.tar.xz \
        "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    && echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c - \
    && mkdir -p /opt/node \
    && tar -xJf /tmp/node.tar.xz -C /opt/node --strip-components=1 \
    && rm -f /tmp/node.tar.xz

FROM ${BASE_IMAGE}

ARG CLAUDE_CODE_VERSION=2.1.316
ARG AGENT_USER_ID=1000
ARG AGENT_GROUP_ID=1000

USER root

ENV PATH="/opt/node/bin:${PATH}" \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client ripgrep \
    && rm -rf /var/lib/apt/lists/* /var/tmp/* /tmp/*

COPY --from=node /opt/node /opt/node

RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force

# Ubuntu's image ships user ubuntu with uid 1000; remove it so the agent user can take any id.
RUN userdel --remove ubuntu 2>/dev/null || true \
    && if ! getent group "${AGENT_GROUP_ID}" >/dev/null; then \
        groupadd --gid "${AGENT_GROUP_ID}" agent; \
    fi \
    && useradd --uid "${AGENT_USER_ID}" --gid "${AGENT_GROUP_ID}" \
        --home-dir /home/agent --create-home --shell /bin/bash agent \
    && mkdir -p /home/agent/.claude \
    && chown -R "${AGENT_USER_ID}:${AGENT_GROUP_ID}" /home/agent

COPY agent_start.py /usr/local/lib/devops-tools/agent_start.py

ENV HOME=/home/agent \
    CLAUDE_CONFIG_DIR=/home/agent/.claude

USER agent
ENTRYPOINT ["python3", "-I", "/usr/local/lib/devops-tools/agent_start.py"]
CMD ["bash"]
