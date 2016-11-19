#!/bin/bash

CONTRAIL_LOG_DIR="/var/log/kolla/contrail/"
if [ ! -d ${CONTRAIL_LOG_DIR} ]; then
    mkdir ${CONTRAIL_LOG_DIR}
fi

if [[ $(stat -c %U:%G ${CONTRAIL_LOG_DIR}) != "contrail:kolla" ]]; then
    chown contrail:kolla ${CONTRAIL_LOG_DIR}
fi
if [[ $(stat -c %a ${CONTRAIL_LOG_DIR}) != "755" ]]; then
    chmod 755 ${CONTRAIL_LOG_DIR}
fi
