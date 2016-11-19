CONFIG_FILE="/etc/contrail/contrail-vrouter-agent.conf"
CONTRAIL_LOG_DIR="/var/log/kolla/contrail/"

dev=`grep "^physical_interface" ${CONFIG_FILE} | awk '{print $NF}'`
DEVICE=`grep "^name =" ${CONFIG_FILE} |awk '{print $NF}'`
cidr=`grep "^ip =" ${CONFIG_FILE} | awk '{print $NF}'`

function pkt_setup () {
    for f in /sys/class/net/$1/queues/rx-*
    do
        q="$(echo $f | cut -d '-' -f2)"
        r=$(($q%32))
        s=$(($q/32))
        ((mask=1<<$r))
        str=(`printf "%x" $mask`)
        if [ $s -gt 0 ]; then
            for ((i=0; i < $s; i++))
            do
                str+=,00000000
            done
        fi
        echo $str > $f/rps_cpus
    done
    ifconfig $1 up
}

if [ -f /sys/class/net/pkt1/queues/rx-0/rps_cpus ]; then
    pkt_setup pkt1
fi
if [ -f /sys/class/net/pkt2/queues/rx-0/rps_cpus ]; then
    pkt_setup pkt2
fi
if [ -f /sys/class/net/pkt3/queues/rx-0/rps_cpus ]; then
    pkt_setup pkt3
fi

# check if vhost0 is not present, then create vhost0 and $dev
if [ ! -L /sys/class/net/vhost0 ]; then
    echo "$(date): Creating vhost interface: $DEVICE."
    # for bonding interfaces
    loops=0
    while [ ! -f /sys/class/net/$dev/address ]
    do
        sleep 1
        loops=$(($loops + 1))
        if [ $loops -ge 60 ]; then
            echo "Unable to look at /sys/class/net/$dev/address"
            return 1
        fi
    done

    DEV_MAC=$(cat /sys/class/net/$dev/address)
    vif --create $DEVICE --mac $DEV_MAC
    if [ $? != 0 ]; then
        echo "$(date): Error creating interface: $DEVICE"
    fi
    echo "$(date): Adding $dev to vrouter"
    DEV_MAC=$(cat /sys/class/net/$dev/address)
    vif --add $dev --mac $DEV_MAC --vrf 0 --vhost-phys --type physical
    if [ $? != 0 ]; then
        echo "$(date): Error adding $dev to vrouter"
    fi

    vif --add $DEVICE --mac $DEV_MAC --vrf 0 --type vhost --xconnect $dev
    if [ $? != 0 ]; then
        echo "$(date): Error adding $DEVICE to vrouter"
    fi
fi

ip addr del ${cidr} dev $dev || /bin/true 2> /dev/null
ip addr add ${cidr} dev $DEVICE || /bin/true 2> /dev/null
ip link set up $DEVICE || /bin/true

if [ ! -d ${CONTRAIL_LOG_DIR} ]; then
    mkdir ${CONTRAIL_LOG_DIR}
fi

if [[ $(stat -c %U:%G ${CONTRAIL_LOG_DIR}) != "contrail:kolla" ]]; then
    chown contrail:kolla ${CONTRAIL_LOG_DIR}
fi
if [[ $(stat -c %a ${CONTRAIL_LOG_DIR}) != "755" ]]; then
    chmod 755 ${CONTRAIL_LOG_DIR}
fi

/usr/bin/supervisord -n -c /etc/contrail/supervisord_vrouter.conf
