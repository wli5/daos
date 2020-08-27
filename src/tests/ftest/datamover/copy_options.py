#!/usr/bin/python
'''
  (C) Copyright 2020 Intel Corporation.

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  GOVERNMENT LICENSE RIGHTS-OPEN SOURCE SOFTWARE
  The Government's rights to use, modify, reproduce, release, perform, display,
  or disclose this software are subject to the terms of the Apache License as
  provided in Contract No. B609815.
  Any reproduction of computer software, computer software documentation, or
  portions thereof marked with this legend must also reproduce the markings.
'''
from command_utils import CommandFailure
from ior_test_base import IorTestBase
from daos_utils import DaosCommand
from test_utils_pool import TestPool
from test_utils_container import TestContainer
from general_utils import pcmd
from ClusterShell.NodeSet import NodeSet
import os


class DcpBasicTest(IorTestBase):
    """
    Test Class Description:
    Tests basic functionality of the dcp utility. Tests the following cases.
    TODO
    
    :avocado: recursive
    """

    def __init__(self, *args, **kwargs):
       	"""Initialize a DcpBasicTest object."""
        super(DcpBasicTest, self).__init__(*args, **kwargs)
        self.container = []

    def setUp(self):
        """Set up each test case."""
        # Start the servers and agents
        super(DcpBasicTest, self).setUp()
        self.flags_write = self.params.get("flags_write", "/run/ior/dcp_basics/*")
        self.flags_read = self.params.get("flags_read", "/run/ior/dcp_basics/*")
        # TODO - what about self.workdir?
        self.uns_dir = None
        test_file = self.params.get("test_file", "/run/ior/dcp_basics/*")
        self.daos_test_file = test_file
        self.posix_test_file = self.tmp + test_file

    def tearDown(self):
        """Tear down each test case."""
        if self.uns_dir is not None:
            cmd = "rm -r '{}'".format(self.uns_dir)
            self.execute_cmd(cmd)
        cmd = "if [ -f '{}' ]; then rm '{}'; fi;".format(self.posix_test_file, self.posix_test_file)
        self.execute_cmd(cmd)
        # Stop the servers and agents
        super(DcpBasicTest, self).tearDown()

    def create_cont(self, path=None):
        """Create a TestContainer object."""
        # Get container params
        container = TestContainer(
            self.pool, daos_command=DaosCommand(self.bin))
        container.get_params(self)

        if path is not None:
            container.path.update(path)
        
        # Create container
        container.create()

        self.container.append(container)
        return container

    def test_copy_with_uuid(self):
        """Jira ID: DAOS-5508
        Test Description:
            Verify ability to copy using pool/container UUIDs.
        Use Cases:
            Create pool.
            Create POSIX type container1, container2, container3.
            Create a single 1K file in container1 using ior.
            Copy all data from container1 to container2 using UUIDs.
            Copy all data from container1 to external POSIX.
            Copy all data from external POSIX to container3.
        :avocado: tags=all,daosio
        :avocado: tags=copy_options,copy_with_uuid
        """
        # Create pool and containers
        self.create_pool()
        container1 = self.create_cont()
        container2 = self.create_cont()
        container3 = self.create_cont()

        # Create test file
        self.write_daos(container1)

        # (DAOS -> DAOS)
        self.dcp(
            "/", "/",
            daos_src_pool=self.pool.uuid, daos_src_cont=container1.uuid,
            daos_dst_pool=self.pool.uuid, daos_dst_cont=container2.uuid)
        self.read_verify_daos(container2)

        # (DAOS -> POSIX)
        self.dcp(
            "/", self.tmp,
            daos_src_pool=self.pool.uuid, daos_src_cont=container1.uuid)
        self.read_verify_posix()

        # (POSIX -> DAOS)
        self.dcp(
            self.posix_test_file, "/",
            daos_dst_pool=self.pool.uuid, daos_dst_cont=container3.uuid)
        self.read_verify_daos(container3)

    def test_copy_with_uns(self):
        """Jira ID: DAOS-5508
        Test Description:
            Verify ability to copy using UNS paths.
        Use Cases:
            Create pool.
            Create POSIX container1, container2, container3 with UNS paths.
            Create a single 1K file in container1 using ior.
            Copy all data from container1 to container2 using UNS paths.
            Copy all data from container1 to external POSIX using UNS path.
            Copy all data from external POSIX to container3 using UNS path.
        :avocado: tags=all,daosio
        :avocado: tags=copy_options,copy_with_uns
        """
        # Create pool and containers
        self.create_pool()
        self.create_uns_dir()
        uns1 = os.path.join(self.uns_dir, "uns1")
        uns2 = os.path.join(self.uns_dir, "uns2")
        uns3 = os.path.join(self.uns_dir, "uns3")
        container1 = self.create_cont(uns1)
        container2 = self.create_cont(uns2)
        container3 = self.create_cont(uns3)

        # Create test file
        self.write_daos(container1)

        # (DAOS -> DAOS)
        self.dcp(
            uns1, uns2)
        self.read_verify_daos(container2)

        # (DAOS -> POSIX)
        self.dcp(
            uns1, self.tmp)
        self.read_verify_posix()

        # (POSIX -> DAOS)
        self.dcp(
            self.posix_test_file, uns3)
        self.read_verify_daos(container3)

    def test_copy_with_uuid_uns(self):
        """Jira ID: DAOS-5508
        Test Description:
            Verify ability to copy with UUIDs and UNS paths.
        Use Cases:
            Create pool.
            Create POSIX container1, container2 (UNS path), container3.
            Create a single 1K file in container1 using ior.
            Copy all data from container1 (UUID) to container2 (UNS).
            Copy all data from container2 (UNS) to container3 (UUID).
        :avocado: tags=all,daosio
        :avocado: tags=copy_options,copy_with_uuid_uns
        """
        # Create pool and containers
        self.create_pool()
        self.create_uns_dir()
        uns2 = os.path.join(self.uns_dir, "uns2")
        container1 = self.create_cont()
        container2 = self.create_cont(uns2)
        container3 = self.create_cont()

        # Create test file
        self.write_daos(container1)

        # (UUID -> UNS)
        self.dcp(
            "/", uns2,
            daos_src_pool=self.pool.uuid, daos_src_cont=container1.uuid)
        self.read_verify_daos(container2)

        # (UNS -> UUID)
        self.dcp(
            uns2, "/",
            daos_dst_pool=self.pool.uuid, daos_dst_cont=container3.uuid)
        self.read_verify_daos(container3)

    def write_daos(self, container):
        """Uses ior to write the test file to a DAOS container."""
        self.ior_cmd.api.update("DFS")
        self.ior_cmd.flags.update(self.flags_write)
        self.ior_cmd.test_file.update(self.daos_test_file)
        self.ior_cmd.set_daos_params(self.server_group, self.pool, container.uuid)
        out = self.run_ior(self.get_ior_job_manager_command(), self.processes)

    def write_posix(self):
        """Uses ior to write the test file in POSIX."""
        self.ior_cmd.api.update("POSIX")
        self.ior_cmd.flags.update(self.flags_write)
        self.ior_cmd.test_file.update(self.posix_test_file)
        self.ior_cmd.set_daos_params(self.server_group, self.pool)
        out = self.run_ior(self.get_ior_job_manager_command(), self.processes)

    def read_verify_daos(self, container):
        """Uses ior to read-verify the test file in a DAOS container."""
        self.ior_cmd.api.update("DFS")
        self.ior_cmd.flags.update(self.flags_read)
        self.ior_cmd.test_file.update(self.daos_test_file)
        self.ior_cmd.set_daos_params(self.server_group, self.pool, container.uuid)
        out = self.run_ior(self.get_ior_job_manager_command(), self.processes)

    def read_verify_posix(self):
        """Uses ior to read-verify the test file in POSIX."""
        self.ior_cmd.api.update("POSIX")
        self.ior_cmd.flags.update(self.flags_read)
        self.ior_cmd.test_file.update(self.posix_test_file)
        self.ior_cmd.set_daos_params(self.server_group, self.pool)
        out = self.run_ior(self.get_ior_job_manager_command(), self.processes)

    def create_uns_dir(self):
        """Returns the uns_dir path, creating it if needed"""
        self.uns_dir = self.params.get("uns_dir", "/")
        cmd = "mkdir -p {}".format(self.uns_dir)
        self.execute_cmd(cmd)

    def dcp(self, source, target,
             daos_src_pool=None, daos_dst_pool=None, daos_src_cont=None, daos_dst_cont=None):
        """Use mpirun to execute the dcp utility"""
        # TODO - use mpirun with varying ranks
        # TODO - convert to instead use Saurabh's object class
        dcp_path = "/home/dbohninx/mpifileutils/install/bin/dcp"
        cmd = dcp_path + " --daos-svcl 0"
        if daos_src_pool is not None:
            cmd += " --daos-src-pool {}".format(daos_src_pool)
        if daos_dst_pool is not None:
            cmd += " --daos-dst-pool {}".format(daos_dst_pool)
        if daos_src_cont is not None:
            cmd += " --daos-src-cont {}".format(daos_src_cont)
        if daos_dst_cont is not None:
            cmd += " --daos-dst-cont {}".format(daos_dst_cont)
        cmd += " {} {}".format(source, target)
        self.execute_cmd(cmd)

