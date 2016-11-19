#!/bin/bash

# Create log dir for Keystone logs
KEYSTONE_LOG_DIR="/var/log/kolla/redis/"
if [[ ! -d "${KEYSTONE_LOG_DIR}" ]]; then
    mkdir -p ${KEYSTONE_LOG_DIR}
fi
if [[ $(stat -c %U:%G ${KEYSTONE_LOG_DIR}) != "redis:kolla" ]]; then
    chown redis:kolla ${KEYSTONE_LOG_DIR}
fi
if [[ $(stat -c %a ${KEYSTONE_LOG_DIR}) != "755" ]]; then
    chmod 755 ${KEYSTONE_LOG_DIR}
fi
