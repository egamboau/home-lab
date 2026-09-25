# syntax=docker/dockerfile:1

ARG DOCKER_CLI_IMAGE=docker:29.8.1-cli
ARG JENKINS_AGENT_IMAGE=jenkins/inbound-agent:3391.va_37fa_a_305d6d-3-jdk21

FROM ${DOCKER_CLI_IMAGE} AS docker-cli

FROM ${JENKINS_AGENT_IMAGE} AS base

USER root

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx

RUN git --version \
    && curl --version \
    && docker --version \
    && docker buildx version

USER jenkins

FROM base AS rsync

USER root

ARG JENKINS_UID=1000
ARG JENKINS_GID=1000

ENV REMOTING_OPTS="-workDir /tmp/jenkins-agent"

RUN set -eux; \
    case "${JENKINS_UID}:${JENKINS_GID}" in \
        *[!0-9:]*|:*|*:) echo "JENKINS_UID and JENKINS_GID must be positive integers" >&2; exit 1 ;; \
    esac; \
    [ "${JENKINS_UID}" -gt 0 ] && [ "${JENKINS_GID}" -gt 0 ] \
        || { echo "JENKINS_UID and JENKINS_GID must not be 0" >&2; exit 1; }; \
    apt-get update; \
    apt-get install --yes --no-install-recommends openssh-client rsync; \
    rm -rf /var/lib/apt/lists/*; \
    if [ "$(id -g jenkins)" != "${JENKINS_GID}" ]; then \
        existing_group="$(getent group "${JENKINS_GID}" | cut -d: -f1 || true)"; \
        if [ -n "${existing_group}" ]; then \
            usermod --gid "${existing_group}" jenkins; \
        else \
            groupmod --gid "${JENKINS_GID}" "$(id -gn jenkins)"; \
        fi; \
    fi; \
    if [ "$(id -u jenkins)" != "${JENKINS_UID}" ]; then \
        existing_user="$(getent passwd "${JENKINS_UID}" | cut -d: -f1 || true)"; \
        [ -z "${existing_user}" ] \
            || { echo "UID ${JENKINS_UID} already belongs to ${existing_user}" >&2; exit 1; }; \
        usermod --uid "${JENKINS_UID}" jenkins; \
    fi; \
    chown -R "${JENKINS_UID}:${JENKINS_GID}" /home/jenkins; \
    install --directory --owner="${JENKINS_UID}" --group="${JENKINS_GID}" /tmp/jenkins-agent; \
    [ "$(id -u jenkins)" = "${JENKINS_UID}" ]; \
    [ "$(id -g jenkins)" = "${JENKINS_GID}" ]; \
    rsync --version; \
    ssh -V; \
    docker --version

USER jenkins

FROM base AS node

USER root

ARG TARGETARCH
ARG NODE_VERSION=24.21.0
ARG NODE_SHA256=fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6

RUN set -eux; \
    [ "${TARGETARCH}" = amd64 ] \
        || { echo "Unsupported architecture: ${TARGETARCH}; expected amd64" >&2; exit 1; }; \
    archive="node-v${NODE_VERSION}-linux-x64.tar.xz"; \
    apt-get update; \
    apt-get install --yes --no-install-recommends xz-utils; \
    curl --fail --show-error --location --output "/tmp/${archive}" \
        "https://nodejs.org/dist/v${NODE_VERSION}/${archive}"; \
    echo "${NODE_SHA256}  /tmp/${archive}" | sha256sum --check --strict; \
    tar --extract --xz --file "/tmp/${archive}" --directory /usr/local --strip-components=1; \
    rm "/tmp/${archive}"; \
    apt-get purge --yes --auto-remove xz-utils; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*; \
    node --version; \
    npm --version; \
    git --version; \
    docker --version

USER jenkins
