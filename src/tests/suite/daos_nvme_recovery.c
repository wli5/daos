/**
 * (C) Copyright 2019 Intel Corporation.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * GOVERNMENT LICENSE RIGHTS-OPEN SOURCE SOFTWARE
 * The Government's rights to use, modify, reproduce, release, perform, display,
 * or disclose this software are subject to the terms of the Apache License as
 * provided in Contract No. B609815.
 * Any reproduction of computer software, computer software documentation, or
 * portions thereof marked with this legend must also reproduce the markings.
 */
/**
 * This file is part of daos
 *
 * tests/suite/daos_nvme_recovery.c
 *
 *
 */
#define D_LOGFAC	DD_FAC(tests)

#include "daos_test.h"
#include "daos_iotest.h"

#define IO_SIZE_NVME	(5ULL << 20) /* all records  >= 4K */
#define	IO_SIZE_SCM	64

static void
set_fail_loc(test_arg_t *arg, d_rank_t rank, uint64_t fail_loc)
{
	if (arg->myrank == 0)
		daos_mgmt_set_params(arg->group, rank, DMG_KEY_FAIL_LOC,
				     fail_loc, 0, NULL);
	MPI_Barrier(MPI_COMM_WORLD);
}

static bool
is_nvme_enabled(test_arg_t *arg)
{
	daos_pool_info_t	 pinfo = { 0 };
	struct daos_pool_space	*ps = &pinfo.pi_space;
	int			 rc;

	pinfo.pi_bits = DPI_ALL;
	rc = test_pool_get_info(arg, &pinfo);
	assert_int_equal(rc, 0);

	return ps->ps_free_min[DAOS_MEDIA_NVME] != 0;
}

/* Online faulty reaction */
static void
nvme_recov_1(void **state)
{
	test_arg_t	*arg = *state;
	daos_obj_id_t	 oid;
	struct ioreq	 req;
	char		 dkey[DTS_KEY_LEN] = { 0 };
	char		 akey[DTS_KEY_LEN] = { 0 };
	int		 obj_class, key_nr = 10;
	int		 rank = 0, tgt_idx = 0;
	int		 i, j;

	if (!is_nvme_enabled(arg)) {
		print_message("NVMe isn't enabled.\n");
		skip();
	}

	if (arg->pool.pool_info.pi_nnodes < 2)
		obj_class = DAOS_OC_R1S_SPEC_RANK;
	else
		obj_class = DAOS_OC_R2S_SPEC_RANK;

	oid = dts_oid_gen(obj_class, 0, arg->myrank);
	oid = dts_oid_set_rank(oid, rank);
	oid = dts_oid_set_tgt(oid, tgt_idx);
	ioreq_init(&req, arg->coh, oid, DAOS_IOD_ARRAY, arg);

	print_message("Generating data on obj "DF_OID"...\n", DP_OID(oid));
	for (i = 0; i < key_nr; i++) {
		dts_key_gen(dkey, DTS_KEY_LEN, "dkey");
		for (j = 0; j < key_nr; j++) {
			dts_key_gen(akey, DTS_KEY_LEN, "akey");
			insert_single(dkey, akey, 0, "data", strlen("data") + 1,
				      DAOS_TX_NONE, &req);
		}
	}
	ioreq_fini(&req);

	print_message("Error injection to simulate device faulty.\n");
	set_fail_loc(arg, rank, DAOS_NVME_FAULTY | DAOS_FAIL_ONCE);

	/*
	 * FIXME: Due to lack of infrastructures for checking each target
	 *	  status, let's just wait for an arbitrary time and hope the
	 *	  faulty reaction & rebuild is triggered.
	 */
	print_message("Waiting for faulty reaction being triggered...\n");
	sleep(60);

	print_message("Waiting for rebuild done...\n");
	if (arg->myrank == 0)
		test_rebuild_wait(&arg, 1);
	MPI_Barrier(MPI_COMM_WORLD);

	/*
	 * FIXME: Need to verify target is in DOWNOUT when the infrastructure
	 *	  is ready.
	 */
	print_message("Waiting for faulty reaction done...\n");
	sleep(60);
	print_message("Done\n");
}

/* Verify device states when NVMe set to faulty*/
static void
nvme_recov_2(void **state)
{
	test_arg_t		*arg = *state;
	device_list		*devices = NULL;
	daos_obj_id_t		oid;
	char		data_buf[100];
	char		fetch_buf[100] = { 0 };
	struct ioreq	req;
	int			ndisks;
	int			rc, i;

	if (!is_nvme_enabled(arg)) {
		print_message("NVMe isn't enabled.\n");
		skip();
	}

	oid = dts_oid_gen(dts_obj_class, 0, arg->myrank);
	ioreq_init(&req, arg->coh, oid, DAOS_IOD_ARRAY, arg);
	memset(data_buf, 'a', 100);
	
	/** Insert record **/
	print_message("Insert single record with 100 extents\n");
	insert_single_with_rxnr("dkey", "akey", 0, data_buf,
		1, 100, DAOS_TX_NONE, &req);

	/**
	*Get the Number of devices
	*/
	rc = dmg_storage_device_list(dmg_config_file, &ndisks, NULL);
	assert_int_equal(rc, 0);

	/**
	*Get the Device info
	*/
	D_ALLOC_ARRAY(devices, ndisks);
	rc = dmg_storage_device_list(dmg_config_file, NULL, devices);
	assert_int_equal(rc, 0);
	for (i = 0; i < ndisks; i++) {
		print_message("Rank=%d UUID=%s state=%s host=%s\n",
			devices[i].rank, DP_UUID(devices[i].device_id),
			devices[i].state, devices[i].host);
		if (devices[i].rank == 1)
			get_server_config(strtok(devices[1].host, ":"));
	}

	

	/**
	*Set single device for rank1 to faulty.

	for (i = 0; i < ndisks; i++) {
		if (devices[i].rank == 1) {
			print_message("NVMe with UUID=%s on host=%s set to Faulty\n",
				DP_UUID(devices[i].device_id), devices[i].host);
			rc = dmg_storage_set_nvme_fault(dmg_config_file,
				devices[i].host, devices[i].device_id, 1);
			assert_int_equal(rc, 0);
			break;
		}
	}
	sleep(30);*/

	/**
	*Verify the Rank1 device as FAULTY
	
	rc = dmg_storage_device_list(dmg_config_file, NULL, devices);
	assert_int_equal(rc, 0);
	for (i = 0; i < ndisks; i++) {
		if (devices[i].rank == 1) {
			assert_string_equal(devices[i].state, "\"FAULTY\"");
			break;
		}
	}*/

	/** Lookup all the records **/
	print_message("Lookup and Verify all the records:\n");
	lookup_single_with_rxnr("dkey", "akey", 0, fetch_buf,
		1, 100, DAOS_TX_NONE, &req);
	for (i = 0; i < 100; i++)
		assert_memory_equal(&fetch_buf[i], "a", 1);

	/* Teardown */
	D_FREE(devices);
}

static const struct CMUnitTest nvme_recov_tests[] = {
	{"NVMe Recovery 1: Online faulty reaction",
	 nvme_recov_1, NULL, test_case_teardown},
	{"NVMe Recovery 2: Verify device states after NVMe set to Faulty",
	 nvme_recov_2, NULL, test_case_teardown},
};

static int
nvme_recov_test_setup(void **state)
{
	int     rc;

	rc = test_setup(state, SETUP_CONT_CONNECT, true, DEFAULT_POOL_SIZE,
			NULL);

	return rc;
}

int
run_daos_nvme_recov_test(int rank, int size, int *sub_tests,
			 int sub_tests_size)
{
	int rc = 0;

	MPI_Barrier(MPI_COMM_WORLD);
	if (sub_tests_size == 0) {
		sub_tests_size = ARRAY_SIZE(nvme_recov_tests);
		sub_tests = NULL;
	}

	rc = run_daos_sub_tests("DAOS nvme recov tests", nvme_recov_tests,
				ARRAY_SIZE(nvme_recov_tests), sub_tests,
				sub_tests_size, nvme_recov_test_setup,
				test_teardown);

	MPI_Barrier(MPI_COMM_WORLD);

	return rc;
}
