# syntax=docker/dockerfile:1

ARG JENKINS_CONTROLLER_IMAGE=jenkins/jenkins:lts-jdk21

FROM ${JENKINS_CONTROLLER_IMAGE}

USER root

ARG JENKINS_UID
ARG JENKINS_GID

RUN set -eux; \
    case "${JENKINS_UID}:${JENKINS_GID}" in \
        *[!0-9:]*|:*|*:) echo "JENKINS_UID and JENKINS_GID must be positive integers" >&2; exit 1 ;; \
    esac; \
    [ "${JENKINS_UID}" -gt 0 ] && [ "${JENKINS_GID}" -gt 0 ] \
        || { echo "JENKINS_UID and JENKINS_GID must not be 0" >&2; exit 1; }; \
    existing_user="$(getent passwd "${JENKINS_UID}" | cut -d: -f1 || true)"; \
    [ -z "${existing_user}" ] || [ "${existing_user}" = jenkins ] \
        || { echo "UID ${JENKINS_UID} already belongs to ${existing_user}" >&2; exit 1; }; \
    if [ "$(id -g jenkins)" != "${JENKINS_GID}" ]; then \
        existing_group="$(getent group "${JENKINS_GID}" | cut -d: -f1 || true)"; \
        if [ -n "${existing_group}" ]; then \
            usermod --gid "${existing_group}" jenkins; \
        else \
            groupmod --gid "${JENKINS_GID}" "$(id -gn jenkins)"; \
        fi; \
    fi; \
    if [ "$(id -u jenkins)" != "${JENKINS_UID}" ]; then \
        usermod --uid "${JENKINS_UID}" jenkins; \
    fi; \
    [ "$(id -u jenkins)" = "${JENKINS_UID}" ]; \
    [ "$(id -g jenkins)" = "${JENKINS_GID}" ]; \
    getent passwd "${JENKINS_UID}" | grep '^jenkins:'

USER jenkins
