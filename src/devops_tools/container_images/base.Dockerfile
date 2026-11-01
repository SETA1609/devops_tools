# devops-tools base image: what every project container needs for the shared tooling, and no
# language toolchain. A project's Dockerfile builds on it and adds its own tools:
#     ARG BASE_IMAGE
#     FROM ${BASE_IMAGE}
#     RUN apt-get update && apt-get install -y --no-install-recommends <toolchain> ...
# `devops-tools container` builds this image first and passes BASE_IMAGE.

FROM ghcr.io/astral-sh/uv:0.10.12@sha256:72ab0aeb448090480ccabb99fb5f52b0dc3c71923bffb5e2e26517a1c27b7fec AS uv

FROM ubuntu:24.04

ARG PYTHON_VERSION=3.13

# uv keeps its Python under /opt/uv so every user, including the host's uid, can run it.
ENV DEBIAN_FRONTEND=noninteractive \
    UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_PYTHON="${PYTHON_VERSION}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        less \
        procps \
        python3 \
    && rm -rf /var/lib/apt/lists/* /var/tmp/* /tmp/*

COPY --from=uv /uv /uvx /usr/local/bin/

RUN uv python install "${PYTHON_VERSION}" \
    && chmod -R a+rX /opt/uv

COPY entrypoint.sh /usr/local/bin/devops-tools-entrypoint
RUN chmod 755 /usr/local/bin/devops-tools-entrypoint

ENTRYPOINT ["/usr/local/bin/devops-tools-entrypoint"]
CMD ["bash"]
