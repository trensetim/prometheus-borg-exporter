FROM alpine

ARG USER=prometheus-borg-exporter
RUN adduser --disabled-password ${USER}

RUN apk add --no-cache python3 borgbackup openssh-client py3-prometheus-client py3-dateutil
COPY main.py /bin/prometheus-borg-exporter.py
RUN chmod u=rx,g=,o= /bin/prometheus-borg-exporter.py
RUN chown ${USER}:${USER} /bin/prometheus-borg-exporter.py

ARG DEFAULT_REPO_PATH=/var/lib/borg/repo
RUN mkdir -p ${DEFAULT_REPO_PATH}
RUN chown ${USER}:${USER} ${DEFAULT_REPO_PATH}
RUN borg init -e none ${DEFAULT_REPO_PATH}
RUN chown -R ${USER}:${USER} ${DEFAULT_REPO_PATH}

RUN mkdir -p /home/${USER}
RUN chown ${USER}:${USER} /home/${USER}

USER ${USER}
WORKDIR /home/${USER}
ENV BORG_RELOCATED_REPO_ACCESS_IS_OK=yes
ENV BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=yes
STOPSIGNAL SIGINT
EXPOSE 9401
ENTRYPOINT ["python3", "-u", "/bin/prometheus-borg-exporter.py"]
