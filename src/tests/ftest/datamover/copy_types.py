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
from data_mover_utils import DataMover
import os

    
class CopyTypesTest(IorTestBase):
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
        super(CopyTypesTest, self).__init__(*args, **kwargs)
        self.containers = []
        self.pools = []
        self.pool = None

    def setUp(self):
        """Set up each test case."""
        # Start the servers and agents
        super(CopyTypesTest, self).setUp()
        
        # Get the parameters
        self.flags_write = self.params.get("flags_write", "/run/ior/dcp_basics/*")
        self.flags_read = self.params.get("flags_read", "/run/ior/dcp_basics/*")
        self.block_size = self.params.get("block_size", "/run/ior/*")
        self.test_file = self.params.get("test_file", "/run/ior/dcp_basics/*")
        self.uns_dir = self.params.get("uns_dir", "/run/container/dcp_basics/*")

        # Setup the directory structures
        self.posix_test_path = os.path.join(self.tmp, "posix_test") + os.path.sep
        self.posix_test_path2 = os.path.join(self.tmp, "posix_test2") + os.path.sep
        self.posix_test_file = os.path.join(self.posix_test_path, self.test_file)
        self.posix_test_file2 = os.path.join(self.posix_test_path2, self.test_file)
        self.daos_test_file = "/" + self.test_file
        
        # Create the directories
        cmd = "mkdir -p '{}' '{}' '{}'".format(
            self.uns_dir,
            self.posix_test_path,
            self.posix_test_path2)
        self.execute_cmd(cmd)

    def tearDown(self):
        """Tear down each test case."""
        # Remove the created directories
        cmd = "rm -r '{}' '{}' '{}'".format(
            self.uns_dir,
            self.posix_test_path,
            self.posix_test_path2)
        self.execute_cmd(cmd)
        
        # Stop the servers and agents
        super(CopyTypesTest, self).tearDown()
    
    def create_pool(self):
        """Create a TestPool object."""
        # Get the pool params
        pool = TestPool(
            self.context, dmg_command=self.get_dmg_command())
        pool.get_params(self)

        # Create a pool
        pool.create()
        
        self.pools.append(pool)
        self.pool = self.pools[0]
        return pool

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

    def test_copy_src_dst_type(self):
        """
        Test Description:
            DAOS-5508: Verify ability to copy using pool/container UUIDs.
            DAOS-5508: Verify ability to copy using UNS paths.
            Daos-5511: Verify ability to copy across pools.
        Use Cases:
            Create pool1 and pool2.
            Create POSIX type container1 and container2 in pool1 with UNS paths.
            Create POSIX type container3 in pool2 with a UNS path.
            Create a single 1K file in container1 using ior.
            Copy all data from container1 (UUIDs) to container2 (UUIDs).
            Copy all data from container1 (UUIDs) to container2 (UNS).
            Copy all data form container1 (UUIDs) to container3 (UUIDs).
            Copy all data from container1 (UUIDs) to container3 (UNS).
            Copy all data from container1 (UUIDs) to an external POSIX filesystem.
            Remove the destination files from container2 and POSIX.
            Copy all data from container1 (UNS) to container2 (UUIDs).
            Copy all data from container1 (UNS) to container2 (UNS).
            Copy all data from container1 (UNS) to container3 (UUIDs).
            Copy all data from container1 (UNS) to container3 (UNS).
            Copy all data from container1 (UNS) to an external POSIX filesystem.
            Remove the destination files from container2 and POSIX.
            Create a single 1K file in the external POSIX using ior.
            Copy all data from POSIX to container2 (UUIDs).
            Copy all data from POSIX to container2 (UNS).
            Copy all data from POSIX to a different POSIX destination.
        :avocado: tags=all,daosio
        :avocado: tags=copy_options,copy_types
        """
        # Create pool and containers
        pool1 = self.create_pool()
        pool2 = self.create_pool()
        uns1 = os.path.join(self.uns_dir, "uns1")
        uns2 = os.path.join(self.uns_dir, "uns2")
        uns3 = os.path.join(self.uns_dir, "uns3")
        container1 = self.create_cont(pool1, uns1)
        container2 = self.create_cont(pool1, uns2)
        container3 = self.create_cont(pool2, uns3)

        # Each source and desination is formatted as:
        # [type, path, ior_pool, ior_cont, dcp_pool, dcp_cont]
        sources = [
            ["UUID", "/", pool1, container1, pool1, container1],
            ["UNS", uns1, pool1, container1, None, None],
            ["POSIX", self.posix_test_path, None, None, None, None]]

        destinations = [
            ["UUID", "/", pool1, container2, pool1, container2],
            ["UNS", uns2, pool1, container2, None, None],
            ["UUID", "/", pool2, container3, pool2, container3],
            ["UNS", uns3, pool2, container3, None, None],
            ["POSIX", self.posix_test_path2, None, None, None, None]]

        # Try each source type...
        for (src_type, src_path, src_ior_pool, src_ior_cont, 
                src_dcp_pool, src_dcp_cont) in sources:
            
            # Create the source file
            if src_type == "POSIX":
                self.write_posix(os.path.join(src_path, self.test_file))
            else:
                self.write_daos(src_ior_pool, src_ior_cont)

            # ... with each destination type
            for (dst_type, dst_path, dst_ior_pool, dst_ior_cont,
                    dst_dcp_pool, dst_dcp_cont) in destinations:

                # Copy the source to the destination
                self.run_dcp(
                    source=src_path, target=dst_path,
                    src_pool=src_dcp_pool, src_cont=src_dcp_cont,
                    dst_pool=dst_dcp_pool, dst_cont=dst_dcp_cont)
                
                # Verify results
                if dst_type == "POSIX":
                    self.read_verify_posix(os.path.join(dst_path, self.test_file))
                else:
                    self.read_verify_daos(dst_ior_pool, dst_ior_cont)

    def write_daos(self, pool, container):
        """Uses ior to write the test file to a DAOS container."""
        self.ior_cmd.api.update("DFS")
        self.ior_cmd.flags.update(self.flags_write)
        self.ior_cmd.test_file.update(self.daos_test_file)
        self.ior_cmd.set_daos_params(self.server_group, pool, container.uuid)
        out = self.run_ior(self.get_ior_job_manager_command(), self.processes)

    def write_posix(self, test_file):
        """Uses ior to write the test file in POSIX."""
        self.ior_cmd.api.update("POSIX")
        self.ior_cmd.flags.update(self.flags_write)
        self.ior_cmd.test_file.update(test_file)
        self.ior_cmd.set_daos_params(self.server_group, self.pool)
        out = self.run_ior(self.get_ior_job_manager_command(), self.processes)

    def read_verify_daos(self, pool, container):
        """Uses ior to read-verify the test file in a DAOS container."""
        self.ior_cmd.api.update("DFS")
        self.ior_cmd.flags.update(self.flags_read)
        self.ior_cmd.test_file.update(self.daos_test_file)
        self.ior_cmd.set_daos_params(self.server_group, pool, container.uuid)
        out = self.run_ior(self.get_ior_job_manager_command(), self.processes)

    def read_verify_posix(self, test_file):
        """Uses ior to read-verify the test file in POSIX."""
        self.ior_cmd.api.update("POSIX")
        self.ior_cmd.flags.update(self.flags_read)
        self.ior_cmd.test_file.update(test_file)
        self.ior_cmd.set_daos_params(self.server_group, self.pool)
        out = self.run_ior(self.get_ior_job_manager_command(), self.processes)

    def run_dcp(self, source, target,
                prefix=None,
                src_pool=None, dst_pool=None, src_cont=None, dst_cont=None):
        """Use mpirun to execute the dcp utility"""
        # param for dcp processes
        processes = self.params.get("processes", "/run/datamover/*")

        # Set up the dcp command
        dcp = DataMover(self.hostlist_clients)
        dcp.get_params(self)
        dcp.daos_prefix.update(prefix)
        dcp.src_path.update(source)
        dcp.dest_path.update(target)
        dcp.set_datamover_params(src_pool, dst_pool, src_cont, dst_cont)

        # Run the dcp command
        try:
            dcp.run(self.workdir, processes)
        except CommandFailure as error:
            self.log.error("DCP command failed: %s", str(error))
            self.fail("Test was expected to pass but it failed.\n")
