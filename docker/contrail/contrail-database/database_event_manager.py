#
# Copyright (c) 2015 Juniper Networks, Inc. All rights reserved.
#

from gevent import monkey
monkey.patch_all()
import os
import sys
import socket
import subprocess
import json
import time
import datetime
import platform
import select
import gevent
import ConfigParser
import yaml

from nodemgr.common.event_manager import EventManager

from ConfigParser import NoOptionError

from supervisor import childutils

from cassandra.cluster import Cluster

from pysandesh.sandesh_base import *
from pysandesh.gen_py.sandesh.ttypes import SandeshLevel
from pysandesh.sandesh_logger import SandeshLogger
from pysandesh.sandesh_session import SandeshWriter
from pysandesh.gen_py.sandesh_trace.ttypes import SandeshTraceRequest
from sandesh_common.vns.ttypes import Module, NodeType
from sandesh_common.vns.constants import ModuleNames, NodeTypeNames,\
    Module2NodeType, INSTANCE_ID_DEFAULT, SERVICE_CONTRAIL_DATABASE, \
    RepairNeededKeyspaces
from subprocess import Popen, PIPE
from StringIO import StringIO

from database.sandesh.database.ttypes import \
    NodeStatusUVE, NodeStatus, DatabaseUsageStats,\
    DatabaseUsageInfo, DatabaseUsage
from database.sandesh.database.process_info.ttypes import \
    ProcessStatus, ProcessState, ProcessInfo, DiskPartitionUsageStats
from database.sandesh.database.process_info.constants import \
    ProcessStateNames


class DatabaseEventManager(EventManager):
    def __init__(self, rule_file, discovery_server,
                 discovery_port, collector_addr,
                 hostip, minimum_diskgb, contrail_databases,
                 cassandra_repair_interval,
                 cassandra_repair_logdir):
        self.node_type = "contrail-database"
        self.module = Module.DATABASE_NODE_MGR
        self.module_id = ModuleNames[self.module]
        self.hostip = hostip
        self.minimum_diskgb = minimum_diskgb
        self.contrail_databases = contrail_databases
        self.cassandra_repair_interval = cassandra_repair_interval
        self.cassandra_repair_logdir = cassandra_repair_logdir
        self.supervisor_serverurl = "unix:///tmp/supervisord_database.sock"
        self.add_current_process()
        node_type = Module2NodeType[self.module]
        node_type_name = NodeTypeNames[node_type]
        self.sandesh_global = sandesh_global
        EventManager.__init__(
            self, rule_file, discovery_server,
            discovery_port, collector_addr, sandesh_global, send_build_info = True)
        self.sandesh_global = sandesh_global
        if self.rule_file is '':
            self.rule_file = "/etc/contrail/" + \
                "supervisord_database_files/contrail-database.rules"
        json_file = open(self.rule_file)
        self.rules_data = json.load(json_file)
        _disc = self.get_discovery_client()
        sandesh_global.init_generator(
            self.module_id, socket.gethostname(), node_type_name,
            self.instance_id, self.collector_addr, self.module_id, 8103,
            ['database.sandesh'], _disc)
        sandesh_global.set_logging_params(enable_local_log=True)
    # end __init__

    def _get_cassandra_config_option(self, config):
        (linux_dist, x, y) = platform.linux_distribution()
        if (linux_dist == 'Ubuntu'):
            yamlstream = open("/etc/cassandra/cassandra.yaml", 'r')
        else:
            yamlstream = open("/etc/cassandra/conf/cassandra.yaml", 'r')

        cfg = yaml.safe_load(yamlstream)
        yamlstream.close()
        return cfg[config]

    def msg_log(self, msg, level):
        self.sandesh_global.logger().log(SandeshLogger.get_py_logger_level(
                            level), msg)

    @staticmethod
    def cassandra_old():
        (PLATFORM, VERSION, EXTRA) = platform.linux_distribution()
        if PLATFORM.lower() == 'ubuntu':
            if VERSION.find('12.') == 0:
                return True
        if PLATFORM.lower() == 'centos':
            if VERSION.find('6.') == 0:
                return True
        return False

    def process(self):
        try:
            cassandra_data_dirs = self._get_cassandra_config_option("data_file_directories")
            cassandra_data_dir_exists = False
            total_disk_space_used = 0
            total_disk_space_available = 0
            for cassandra_data_dir in cassandra_data_dirs:
                if DatabaseEventManager.cassandra_old():
                    analytics_dir = cassandra_data_dir + '/ContrailAnalytics'
                else:
                    analytics_dir = cassandra_data_dir + '/ContrailAnalyticsCql'

                if os.path.exists(analytics_dir):
                    cassandra_data_dir_exists = True
                    msg = "analytics_dir is " + analytics_dir
                    self.msg_log(msg, level=SandeshLevel.SYS_DEBUG)
                    df = subprocess.Popen(["df", analytics_dir],
                            stdout=subprocess.PIPE)
                    output = df.communicate()[0]
                    device, size, disk_space_used, disk_space_available, \
                       percent, mountpoint = output.split("\n")[1].split()
                    total_disk_space_used += int(disk_space_used)
                    total_disk_space_available += int(disk_space_available)
            if cassandra_data_dir_exists == False:
                if 'analytics' not in self.contrail_databases:
                    self.fail_status_bits &= ~self.FAIL_STATUS_DISK_SPACE_NA
                else:
                    self.fail_status_bits |= self.FAIL_STATUS_DISK_SPACE_NA
            else:
                disk_space_analytics = int(total_disk_space_used) + int(total_disk_space_available)
                if (disk_space_analytics / (1024 * 1024) < self.minimum_diskgb):
                    cmd_str = "service " + SERVICE_CONTRAIL_DATABASE + " stop"
                    (ret_value, error_value) = Popen(
                        cmd_str, shell=True, stdout=PIPE).communicate()
                    self.fail_status_bits |= self.FAIL_STATUS_DISK_SPACE
                self.fail_status_bits &= ~self.FAIL_STATUS_DISK_SPACE_NA
        except:
            msg = "Failed to get database usage"
            self.msg_log(msg, level=SandeshLevel.SYS_ERR)
            self.fail_status_bits |= self.FAIL_STATUS_DISK_SPACE_NA

    def send_process_state_db(self, group_names):
        self.send_process_state_db_base(
            group_names, ProcessInfo, NodeStatus, NodeStatusUVE)

    def send_nodemgr_process_status(self):
        self.send_nodemgr_process_status_base(
            ProcessStateNames, ProcessState, ProcessStatus,
            NodeStatus, NodeStatusUVE)

    def get_process_state(self, fail_status_bits):
        return self.get_process_state_base(
            fail_status_bits, ProcessStateNames, ProcessState)

    def get_failbits_nodespecific_desc(self, fail_status_bits):
        description = ""
        if fail_status_bits & self.FAIL_STATUS_DISK_SPACE:
            description += "Disk for analytics db is too low," + \
                " cassandra stopped."
        if fail_status_bits & self.FAIL_STATUS_SERVER_PORT:
            if description != "":
                description += " "
            description += "Cassandra state detected DOWN."
        if fail_status_bits & self.FAIL_STATUS_DISK_SPACE_NA:
            description += "Disk space for analytics db not retrievable."
        return description

    def database_periodic(self):
        try:
            cassandra_data_dirs = self._get_cassandra_config_option("data_file_directories")
            cassandra_data_dir_exists = False
            total_disk_space_used = 0
            total_disk_space_available = 0
            total_analytics_db_size = 0
            for cassandra_data_dir in cassandra_data_dirs:
                if DatabaseEventManager.cassandra_old():
                    analytics_dir = cassandra_data_dir + '/ContrailAnalytics'
                else:
                    analytics_dir = cassandra_data_dir + '/ContrailAnalyticsCql'

                if os.path.exists(analytics_dir):
                    cassandra_data_dir_exists = True
                    msg = "analytics_dir is " + analytics_dir
                    self.msg_log(msg, level=SandeshLevel.SYS_DEBUG)
                    df = subprocess.Popen(["df", analytics_dir],
                            stdout=subprocess.PIPE)
                    output = df.communicate()[0]
                    device, size, disk_space_used, disk_space_available, \
                        percent, mountpoint =  output.split("\n")[1].split()
                    total_disk_space_used += int(disk_space_used)
                    total_disk_space_available += int(disk_space_available)
                    du = subprocess.Popen(["du", "-skl", analytics_dir],
                            stdout=subprocess.PIPE)
                    analytics_db_size, directory = du.communicate()[0].split()
                    total_analytics_db_size += int(analytics_db_size)
            if cassandra_data_dir_exists == False:
                if 'analytics' not in self.contrail_databases:
                    self.fail_status_bits &= ~self.FAIL_STATUS_DISK_SPACE_NA
                else:
                    self.fail_status_bits |= self.FAIL_STATUS_DISK_SPACE_NA
            else:
                self.fail_status_bits &= ~self.FAIL_STATUS_DISK_SPACE_NA

                db_stat = DatabaseUsageStats()
                db_info = DatabaseUsageInfo()

                db_stat.disk_space_used_1k = int(total_disk_space_used)
                db_stat.disk_space_available_1k = int(total_disk_space_available)
                db_stat.analytics_db_size_1k = int(total_analytics_db_size)

                db_info.name = socket.gethostname()
                db_info.database_usage = [db_stat]
                usage_stat = DatabaseUsage(data=db_info)
                usage_stat.send()
        except:
            msg = "Failed to get database usage"
            self.msg_log(msg, level=SandeshLevel.SYS_ERR)
            self.fail_status_bits |= self.FAIL_STATUS_DISK_SPACE_NA

        if not self.cassandra_local_running():
            self.fail_status_bits |= self.FAIL_STATUS_SERVER_PORT
        else:
            self.fail_status_bits &= ~self.FAIL_STATUS_SERVER_PORT
        self.send_nodemgr_process_status()
        # Record cluster status and shut down cassandra if needed
        subprocess.Popen(["contrail-cassandra-status",
                          "--log-file", "/var/log/cassandra/status.log",
                          "--debug"])
    # end database_periodic

    def cassandra_local_running(self):
        cluster = Cluster([self.hostip])
        try:
            cluster.connect()
            return True
        except Exception:
            return False
    # end cassandra_connect

    def cassandra_repair(self):
        logdir = self.cassandra_repair_logdir + "repair.log"
        subprocess.Popen(["contrail-cassandra-repair",
                          "--log-file", logdir,
                          "--debug"])
    #end cassandra_repair

    def send_disk_usage_info(self):
        self.send_disk_usage_info_base(
            NodeStatusUVE, NodeStatus, DiskPartitionUsageStats)

    def runforever(self, test=False):
        prev_current_time = int(time.time())
        while 1:
            # we explicitly use self.stdin, self.stdout, and self.stderr
            # instead of sys.* so we can unit test this code
            headers, payload = self.listener_nodemgr.wait(
                self.stdin, self.stdout)

            # self.stderr.write("headers:\n" + str(headers) + '\n')
            # self.stderr.write("payload:\n" + str(payload) + '\n')

            pheaders, pdata = childutils.eventdata(payload + '\n')
            # self.stderr.write("pheaders:\n" + str(pheaders)+'\n')
            # self.stderr.write("pdata:\n" + str(pdata))

            # check for process state change events
            if headers['eventname'].startswith("PROCESS_STATE"):
                self.event_process_state(pheaders, headers)
            # check for flag value change events
            if headers['eventname'].startswith("PROCESS_COMMUNICATION"):
                self.event_process_communication(pdata)
            # do periodic events
            if headers['eventname'].startswith("TICK_60"):
                self.database_periodic()
                prev_current_time = self.event_tick_60(prev_current_time)
                # Perform nodetool repair every cassandra_repair_interval hours
                if self.tick_count % (60 * self.cassandra_repair_interval) == 0:
                    self.cassandra_repair()
            self.listener_nodemgr.ok(self.stdout)
