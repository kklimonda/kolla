#!/bin/bash

if [ "$0" = "/contrail-webui-jobserver.sh" ]; then
    SCRIPT="jobServerStart.js"
    SERVICE="jobserver"
elif [ "$0" = "/contrail-webui-webserver.sh" ]; then
    SCRIPT="webServerStart.js"
    SERVICE="webserver"
else
    exit 1
fi

LOGPATH="/var/log/kolla/contrail/contrail-webui-${SERVICE}.log"

cd /var/lib/contrail-webui/contrail-web-core \
  && /usr/bin/nodejs ${SCRIPT} > ${LOGPATH} 2>&1
