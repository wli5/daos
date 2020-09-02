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
from apricot import skipForTicket
import os

    
class CopyNegativeTest(IorTestBase):
    """
    Test Class Description:
        Negative testing for the Data Mover.
        Tests the following cases:
            Bad parameters.
            Simple error checking.
    :avocado: recursive
    """

    def __init__(self, *args, **kwargs):
       	"""Initialize a CopyTypesTest object."""
        super(CopyNegativeTest, self).__init__(*args, **kwargs)
        self.containers = []
        self.pools = []
        self.pool = None

    def setUp(self):
        """Set up each test case."""
        # Start the servers and agents
        super(CopyNegativeTest, self).setUp()
        
        # Get the parameters
        self.flags_write = self.params.get("flags_write", "/run/ior/dcp_basics/*")
        self.flags_read = self.params.get("flags_read", "/run/ior/dcp_basics/*")
        self.block_size = self.params.get("block_size", "/run/ior/*")
        self.block_size_large = self.params.get("block_size_large", "/run/ior/dcp_basics/*")
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
        super(CopyNegativeTest, self).tearDown()
    
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

    @skipForTicket("DAOS-5564")
    def bad_param_src_is_dst(self, pool1, container1, uns1):
        # (1.1) UUID source is UUID destination
        self.run_dcp(
            source="/", target="/",
            src_pool=pool1, src_cont=container1,
            dst_pool=pool1, dst_cont=container1,
            expect_fail_desc="copy_bad_params (1.1)")
        
        # (1.2) UNS source is UNS destination
        self.run_dcp(
            source=uns1, target=uns1,
            expect_fail_desc="copy_bad_params (1.2)")

    def test_copy_bad_params(self):
        """Jira ID: DAOS-5515
        Test Description:
            (1) Bad parameter: source is destination.
            (2) Bad parameter: daos-prefix is invalid.
            (3) Bad parameter: UUID, UNS, or POSIX path is invalid.
            (4) Error checking: destination path length is too long.
            (5) Error checking: destination pool out of space.
            (6) Error checking: destination POSIX file system out of space.
        :avocado: tags=all,daosio
        :avocado: tags=copy_options,copy_bad_params
        """
        # Create pool and containers
        pool1 = self.create_pool()
        pool2 = self.create_pool()
        uns1 = os.path.join(self.uns_dir, "uns1")
        container1 = self.create_cont(pool1, uns1)
        container2 = self.create_cont(pool2)

        # Create test files
        self.write_posix()
        self.write_daos(pool1, container1)
        
        # (1) Bad parameter: source is destination
        self.bad_param_src_is_dst(pool1, container1, uns1)
        
        # (2) Bad parameter: daos-prefix is invalid
        # (2.1) Prefix is not UNS path 
        fakeuns = os.path.join(self.uns_dir, "fakeuns")
        fakefile = os.path.join(fakeuns, "fakefile")
        self.run_dcp(
            source=fakefile, target=self.tmp,
            prefix=fakeuns,
            expect_fail_desc="copy_bad_params (2.1)")
        
        # (2.2) Prefix is UNS path but doesn't match source or destination
        fakeuns = os.path.join(self.uns_dir, "fakeuns")
        fakefile = os.path.join(fakeuns, "fakefile")
        self.run_dcp(
            source=fakefile, target=self.tmp,
            prefix=uns1,
            expect_fail_desc="copy_bad_params (2.2)")
        
        # (2.3) Prefix is UNS path but is a substring, not prefix, of source
        src = "/oops" + uns1
        self.run_dcp(
            source=src, target=self.tmp,
            prefix=uns1,
            expect_fail_desc="copy_bad_params (2.3)")

        # (2.4) Prefix is UNS path but is a substring, not prefix, of destination
        dst = "/oops" + uns1
        self.run_dcp(
            source=self.tmp, target=dst,
            prefix=uns1,
            expect_fail_desc="copy_bad_params (2.4)")
        
        # (2.7) Prefix is not UNS path but is prefix of POSIX source
        src = self.posix_test_file
        prefix = os.path.dirname(src)
        self.run_dcp(
            source=src, target=self.daos_test_file,
            prefix=prefix,
            expect_fail_desc="copy_bad_params (2.7)")

        # (2.8) Prefix is not UNS path but is prefix of POSIX destination
        dst = self.posix_test_file
        prefix = os.path.dirname(dst)
        self.run_dcp(
            source=self.daos_test_file, target=dst,
            prefix=prefix,
            expect_fail_desc="copy_bad_params (2.8)")
        
        # (3) Bad parameter: UUID, UNS, or POSIX path is invalid
        # (3.1) Source pool UUID does not exist
        self.run_dcp(
            source=self.daos_test_file, target=self.posix_test_file,
            override_src_pool=container1.uuid, override_src_cont=container1.uuid,
            expect_fail_desc="copy_bad_params (3.1)")

        # TODO - This sometimes fails, but not always.
        #        Waiting for DAOS-5573
        # (3.2) Source pool UUID exists, source containter UUID does not
        """self.run_dcp(
            source=self.daos_test_file, target=self.posix_test_file,
            override_src_pool=pool1.uuid, override_src_cont=pool1.uuid,
            expect_fail_desc="copy_bad_params (3.2)")
        """

        # (3.3) Destination pool UUID does not exist
        self.run_dcp(
            source=self.posix_test_file, target=self.daos_test_file,
            override_dst_pool=container1.uuid, override_dst_cont=container1.uuid,
            expect_fail_desc="copy_bad_params (3.3)")

        # (3.4) Destination pool UUID exists, destination container UUID does not
        # This must be from one pool to another pool.
        # If they are the same pool, or with a POSIX source,
        # then the destination container is automatically created.
        self.run_dcp(
            source=self.daos_test_file, target=self.daos_test_file,
            src_pool=pool1, src_cont=container1,
            override_dst_pool=pool2.uuid, override_dst_cont=pool2.uuid,
            expect_fail_desc="copy_bad_params (3.4)")

        # TODO - This works but should not
        #        Waiting for DAOS-5573
        # (3.5) Source UUIDs are valid, but source path does not exist
        """src = "/fake/fake/fake"
        self.run_dcp(
            source=src, target=self.posix_test_file,
            src_pool=pool1, src_cont=container1,
            expect_fail_desc="copy_bad_params (3.5)")
        """

        # TODO - pending (3.5) above
        # (3.6) Destination UUIDs are valid, but destination path does not exist
        
        
        # (3.7) Source POSIX path does not exist
        src = "/fake/fake/fake"
        self.run_dcp(
            source=src, target=self.daos_test_file,
            dst_pool=pool1, dst_cont=container1,
            expect_fail_desc="copy_bad_params (3.7)")

        # (3.8) Destination POSIX path does not exist
        dst = "/fake/fake/fake"
        self.run_dcp(
            source=self.daos_test_file, target=dst,
            src_pool=pool1, src_cont=container1,
            expect_fail_desc="copy_bad_params (3.8)")
        

    # TODO - move this to a different file or rename copy_options to something
    #        more suitable
    # @skipForTicket("DAOS-5577")
    def test_copy_error_check(self):
        """Jira ID: DAOS-5515
        Test Description:
            (1) Error checking: destination path length is too long.
            (2) Error checking: destination pool out of space.
            (3) Error checking: destination POSIX file system out of space.
        :avocado: tags=all,daosio
        :avocado: tags=copy_options,copy_error_check
        """
        # Create pool and containers
        pool = self.create_pool()
        container1 = self.create_cont(pool)

        # Create test files
        #self.write_posix()
        #self.write_daos(pool, container1)
        
        # TODO
        # (1) Destination path length is too long.

        # (2) Destination pool out of space.
        """self.ior_cmd.block_size.update(self.block_size_large)
        self.write_posix()
        self.run_dcp(
            source=self.posix_test_file, target=self.daos_test_file,
            dst_pool=pool, dst_cont=container1,
            expect_fail_desc="error_check (2)")
        """

        # TODO
        # (3) Destination POSIX file system out of space.
        

    def write_daos(self, pool, container):
        """Uses ior to write the test file to a DAOS container."""
        self.ior_cmd.api.update("DFS")
        self.ior_cmd.flags.update(self.flags_write)
        self.ior_cmd.test_file.update(self.daos_test_file)
        self.ior_cmd.set_daos_params(self.server_group, pool, container.uuid)
        out = self.run_ior(self.get_ior_job_manager_command(), self.processes)

    def write_posix(self, test_file=None):
        """Uses ior to write the test file in POSIX."""
        self.ior_cmd.api.update("POSIX")
        self.ior_cmd.flags.update(self.flags_write)
        if test_file is None:
            self.ior_cmd.test_file.update(self.posix_test_file)
        else:
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

    def read_verify_posix(self, test_file=None):
        """Uses ior to read-verify the test file in POSIX."""
        self.ior_cmd.api.update("POSIX")
        self.ior_cmd.flags.update(self.flags_read)
        if test_file is None:
            self.ior_cmd.test_file.update(self.posix_test_file)
        else:
            self.ior_cmd.test_file.update(test_file)
        self.ior_cmd.set_daos_params(self.server_group, self.pool)
        out = self.run_ior(self.get_ior_job_manager_command(), self.processes)

    def run_dcp(self, source, target,
                prefix=None,
                src_pool=None, dst_pool=None, src_cont=None, dst_cont=None,
                override_src_pool=None, override_dst_pool=None,
                override_src_cont=None, override_dst_cont=None,
                expect_fail_desc=None):
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

        # Handle manual overrides
        if override_src_pool is not None:
            dcp.daos_src_pool.update(override_src_pool)
        if override_src_cont is not None:
            dcp.daos_src_cont.update(override_src_cont)
        if override_dst_pool is not None:
            dcp.daos_dst_pool.update(override_dst_pool)
        if override_dst_cont is not None:
            dcp.daos_dst_cont.update(override_dst_cont)

        # Run the dcp command
        did_fail = False
        try:
            dcp.run(self.workdir, processes)
        except CommandFailure as error:
            did_fail = True
            if expect_fail_desc is not None:
                self.log.info("==> %s", expect_fail_desc)
                self.log.info("==> Expected error: %s", str(error))
            else:
                self.log.error("DCP command failed: %s", str(error))
                self.fail("Test was expected to pass but it failed.\n")
        
        if not did_fail and expect_fail_desc is not None:
            self.fail("Test was expected to fail but it passed: {}".format(expect_fail_desc))
