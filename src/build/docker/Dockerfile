# Must get executed from the root of the source code repository

FROM alpine
RUN apk add --no-cache python3 borgbackup openssh-client py3-prometheus-client py3-dateutil envsubst
RUN apk del apk-tools

ARG USER=prometheus-borg-exporter
RUN adduser --disabled-password ${USER}

ENV BORG_RELOCATED_REPO_ACCESS_IS_OK=yes
ENV BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=yes
ENV BORG_DISPLAY_PASSPHRASE=no

ARG INSTALL_PATH=/usr/local/prometheus-borg-exporter
RUN mkdir -p ${INSTALL_PATH}
COPY src/main/python/ ${INSTALL_PATH}/
RUN chmod u=rx,go= ${INSTALL_PATH} \
    && chmod u+rx ${INSTALL_PATH}/main.py \
    && chown -R ${USER}:${USER} ${INSTALL_PATH}

RUN mkdir -p /etc/borg
COPY src/main/resources/config.json /etc/borg/exporter-config.json
RUN chown -R ${USER}:${USER} /etc/borg

ARG DEFAULT_REPO_PATH=/var/lib/borg/repos/default
ARG DEFAULT_REPO_PASSPHRASES_PATH=/etc/borg/passphrases
ARG DEFAULT_REPO_PASSPHRASE=trivial
ARG DEFAULT_REPO_FLOCK_PATH=/var/lock/borg
RUN mkdir -p ${DEFAULT_REPO_PATH} ${DEFAULT_REPO_PASSPHRASES_PATH} ${DEFAULT_REPO_FLOCK_PATH}
RUN chown ${USER}:${USER} ${DEFAULT_REPO_PATH} ${DEFAULT_REPO_PASSPHRASES_PATH} ${DEFAULT_REPO_FLOCK_PATH}
RUN BORG_PASSPHRASE="${DEFAULT_REPO_PASSPHRASE}" borg init -e repokey-blake2 ${DEFAULT_REPO_PATH}
RUN echo "${DEFAULT_REPO_PASSPHRASE}" > ${DEFAULT_REPO_PASSPHRASES_PATH}/default
RUN chown -R ${USER}:${USER} ${DEFAULT_REPO_PATH} ${DEFAULT_REPO_PASSPHRASES_PATH}/default

RUN mkdir -p /home/${USER}
RUN chown ${USER}:${USER} /home/${USER}

USER ${USER}
WORKDIR /home/${USER}
STOPSIGNAL SIGINT
EXPOSE 9401
ENTRYPOINT [ \
    "python3", \
    "-u", \
    "/usr/local/prometheus-borg-exporter/main.py" \
    ]
