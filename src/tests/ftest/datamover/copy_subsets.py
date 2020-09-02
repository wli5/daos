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
from mdtest_test_base import MdtestBase
from ior_test_base import IorTestBase
from daos_utils import DaosCommand
from test_utils_pool import TestPool
from test_utils_container import TestContainer
from data_mover_utils import DataMover
import os

    
class CopySubsetsTest(IorTestBase, MdtestBase):
    """
    Test Class Description:
        Tests basic functionality of the datamover utility. 
        Tests the following cases:
            Copying between UUIDs, UNS paths, and external POSIX systems.
            Copying between pools.
    :avocado: recursive
    """

    def __init__(self, *args, **kwargs):
       	"""Initialize a CopyTypesTest object."""
        super(CopySubsetsTest, self).__init__(*args, **kwargs)
        self.containers = []
        self.pool = None

    def setUp(self):
        """Set up each test case."""
        # Start the servers and agents
        super(CopySubsetsTest, self).setUp()
        
        # Get the parameters
        self.flags_write = self.params.get("flags_write", "/run/mdtest/dcp_basics/*")
        self.flags_read = self.params.get("flags_read", "/run/mdtest/dcp_basics/*")
        self.uns_dir = self.params.get("uns_dir", "/run/container/dcp_basics/*")

        # Setup the directory structures
        self.posix_test_path = os.path.join(self.tmp, "posix_test") + os.path.sep
        
        # Create the directory
        cmd = "mkdir -p '{}' '{}'".format(
            self.uns_dir,
            self.posix_test_path)
        self.execute_cmd(cmd)

    def tearDown(self):
        """Tear down each test case."""
        # Remove the created directory
        cmd = "rm -r '{}' '{}'".format(
            self.uns_dir,
            self.posix_test_path)
        self.execute_cmd(cmd)
        
        # Stop the servers and agents
        super(CopySubsetsTest, self).tearDown()
    
    def create_cont(self, pool, path=None):
        """Create a TestContainer object."""
        # Get container params
        container = TestContainer(
            pool, daos_command=DaosCommand(self.bin))
        container.get_params(self)

        if path is not None:
            container.path.update(path)
        
        # Create container
        container.create()

        self.containers.append(container)
        return container

    def test_copy_subsets(self):
        """
        Test Description:
            DAOS-5512: Verify ability to copy container subsets.
        Use Cases:
            Create a pool.
            Create POSIX container1 with a UNS path and container2.
            Create a directory structure with a single 1K file in container1.
            Copy a subset of container1 to container2.
            Copy a subset of container1 to an external POSIX file system.
            Copy an external POSIX filesystem to a new dir in container1.
        :avocado: tags=all,daosio
        :avocado: tags=copy_subsets
        """
        # Create pool and containers
        self.create_pool()
        uns1 = os.path.join(self.uns_dir, "uns1") 
        container1 = self.create_cont(self.pool, uns1)
        container2 = self.create_cont(self.pool)

        # Relative container paths
        daos_path1 = "/test1"
        daos_path2 = "/test2"

        # Absolute container paths with UNS
        cont1_path1 = os.path.join(uns1, "test1")
        cont1_path2 = os.path.join(uns1, "test2")
        
        # External POSIX paths
        posix_path1 = os.path.join(self.posix_test_path, "test1")
        
        # (DAOS -> DAOS)
        self.write_daos(self.pool, container1, daos_path1)
        self.run_dcp(
            src=cont1_path1, dst="/",
            prefix=uns1,
            dst_pool=self.pool, dst_cont=container2)
        self.read_verify_daos(self.pool, container2, daos_path1)

        # (DAOS -> POSIX)
        self.run_dcp(
            src=cont1_path1, dst=posix_path1,
            prefix=uns1)
        self.read_verify_posix(posix_path1)

        # (POSIX -> DAOS)
        # Does not work as expected: DAOS-5573
        #self.run_dcp(
        #    src=posix_path1, dst=cont1_path2,
        #    prefix=uns1)
        #self.read_verify_daos(self.pool, container1, daos_path2)

    def write_daos(self, pool, container, test_dir):
        """Uses mdtest to write the test file to a DAOS container."""
        self.mdtest_cmd.api.update("DFS")
        self.mdtest_cmd.flags.update(self.flags_write)
        self.mdtest_cmd.test_dir.update(test_dir)
        self.mdtest_cmd.set_daos_params(self.server_group, pool, container.uuid)
        out = self.run_mdtest(self.get_mdtest_job_manager_command(self.manager), 
                              self.processes)

    def write_posix(self, test_dir):
        """Uses mdtest to write the test file in POSIX."""
        self.mdtest_cmd.api.update("POSIX")
        self.mdtest_cmd.flags.update(self.flags_write)
        self.mdtest_cmd.test_dir.update(test_dir)
        self.mdtest_cmd.set_daos_params(self.server_group, self.pool)
        out = self.run_mdtest(self.get_mdtest_job_manager_command(self.manager),
                              self.processes)

    def read_verify_daos(self, pool, container, test_dir):
        """Uses mdtest to read-verify the test file in a DAOS container."""
        self.mdtest_cmd.api.update("DFS")
        self.mdtest_cmd.flags.update(self.flags_read)
        self.mdtest_cmd.test_dir.update(test_dir)
        self.mdtest_cmd.set_daos_params(self.server_group, pool, container.uuid)
        out = self.run_mdtest(self.get_mdtest_job_manager_command(self.manager),
                              self.processes)

    def read_verify_posix(self, test_dir):
        """Uses mdtest to read-verify the test file in POSIX."""
        self.mdtest_cmd.api.update("POSIX")
        self.mdtest_cmd.flags.update(self.flags_read)
        self.mdtest_cmd.test_dir.update(test_dir)
        self.mdtest_cmd.set_daos_params(self.server_group, self.pool)
        out = self.run_mdtest(self.get_mdtest_job_manager_command(self.manager),
                              self.processes)
    
    def run_dcp(self, src, dst,
                prefix=None,
                src_pool=None, dst_pool=None, src_cont=None, dst_cont=None):
        """Use mpirun to execute the dcp utility"""
        # param for dcp processes
        processes = self.params.get("processes", "/run/datamover/*")

        # Set up the dcp command
        dcp = DataMover(self.hostlist_clients)
        dcp.get_params(self)
        dcp.daos_prefix.update(prefix)
        dcp.src_path.update(src)
        dcp.dest_path.update(dst)
        dcp.set_datamover_params(src_pool, dst_pool, src_cont, dst_cont)

        # Run the dcp command
        try:
            dcp.run(self.workdir, processes)
        except CommandFailure as error:
            self.log.error("DCP command failed: %s", str(error))
            self.fail("Test was expected to pass but it failed.\n")
