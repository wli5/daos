/**
 * (C) Copyright 2016 Intel Corporation.
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
 * rebuild: rebuild service
 *
 * Rebuild service module api.
 */
#define DD_SUBSYS	DD_FAC(rebuild)

#include <daos/rpc.h>
#include <daos/pool.h>
#include <daos_srv/daos_server.h>
#include <daos_srv/pool.h>
#include <daos_srv/container.h>
#include "rpc.h"
#include "rebuild_internal.h"

#define RBLD_BCAST_INTV		2	/* seocnds interval to retry bcast */
#define RBLD_BCAST_RETRY_MAX	100	/* more than 3 full cart timeout */

/* rebuild global status */
struct rebuild_globals rebuild_gst;

static int
init(void)
{
	int	rc;

	memset(&rebuild_gst, 0, sizeof(rebuild_gst));
	DAOS_INIT_LIST_HEAD(&rebuild_gst.rg_task_list);

	rc = ABT_cond_create(&rebuild_gst.rg_cond);
	if (rc != ABT_SUCCESS)
		D_GOTO(failed, 0);

	rc = ABT_mutex_create(&rebuild_gst.rg_lock);
	if (rc != ABT_SUCCESS)
		D_GOTO(failed_cond, 0);

	return 0;
failed_cond:
	ABT_cond_free(&rebuild_gst.rg_cond);
failed:
	return rc;
}

static int
fini(void)
{
	if (rebuild_gst.rg_pullers) {
		D_FREE(rebuild_gst.rg_pullers,
		       rebuild_gst.rg_puller_nxs *
		       sizeof(*rebuild_gst.rg_pullers));
	}
	ABT_mutex_free(&rebuild_gst.rg_lock);
	ABT_cond_free(&rebuild_gst.rg_cond);
	return 0;
}

struct pool_map *
rebuild_pool_map_get(void)
{
	struct ds_pool  *pool = rebuild_gst.rg_pool;
	struct pool_map *map;

	D_ASSERT(pool);

	ABT_rwlock_rdlock(pool->sp_lock);
	map = pool->sp_map;
	pool_map_addref(map);
	ABT_rwlock_unlock(pool->sp_lock);

	return map;
}

void
rebuild_pool_map_put(struct pool_map *map)
{
	pool_map_decref(map);
}

static void *
rebuild_tls_init(const struct dss_thread_local_storage *dtls,
		 struct dss_module_key *key)
{
	struct rebuild_tls *tls;

	D_ALLOC_PTR(tls);
	if (!tls)
		return NULL;

	DAOS_INIT_LIST_HEAD(&tls->rebuild_task_list);

	/* Initialize per-thread counters */
	if (!rebuild_gst.rg_pullers) {
		ABT_mutex_lock(rebuild_gst.rg_lock);
		if (!rebuild_gst.rg_pullers) {
			rebuild_gst.rg_puller_nxs = dss_get_threads_number();
			D_ALLOC(rebuild_gst.rg_pullers,
				rebuild_gst.rg_puller_nxs *
				sizeof(*rebuild_gst.rg_pullers));
			if (!rebuild_gst.rg_pullers) {
				ABT_mutex_unlock(rebuild_gst.rg_lock);
				return NULL;
			}
		}
		ABT_mutex_unlock(rebuild_gst.rg_lock);
	}
	return tls;
}

bool
is_rebuild_container(uuid_t cont_hdl_uuid)
{
	struct rebuild_tls *tls = rebuild_tls_get();

	return !uuid_compare(tls->rebuild_cont_hdl_uuid, cont_hdl_uuid);
}

bool
is_rebuild_pool(uuid_t pool_hdl)
{
	struct rebuild_tls *tls = rebuild_tls_get();

	return !uuid_compare(tls->rebuild_pool_hdl_uuid, pool_hdl);
}

static void
rebuild_tls_fini(const struct dss_thread_local_storage *dtls,
		 struct dss_module_key *key, void *data)
{
	struct rebuild_tls *tls = data;

	D_ASSERT(tls->rebuild_local_root_init == 0);
	D_FREE_PTR(tls);
}

struct rebuild_tgt_query_info {
	int scanning;
	int status;
	int rec_count;
	int obj_count;
	ABT_mutex lock;
};

int
dss_rebuild_check_scanning(void *arg)
{
	struct rebuild_tls	*tls = rebuild_tls_get();
	struct rebuild_tgt_query_info	*status = arg;

	ABT_mutex_lock(status->lock);
	if (tls->rebuild_scanning)
		status->scanning++;
	if (tls->rebuild_status != 0 && status->status == 0)
		status->status = tls->rebuild_status;
	status->rec_count += tls->rebuild_rec_count;
	status->obj_count += tls->rebuild_obj_count;
	ABT_mutex_unlock(status->lock);

	return 0;
}

int
ds_rebuild_tgt_query_aggregator(crt_rpc_t *source, crt_rpc_t *result,
				void *priv)
{
	struct rebuild_tgt_query_out    *out_source = crt_reply_get(source);
	struct rebuild_tgt_query_out    *out_result = crt_reply_get(result);

	out_result->rtqo_rebuilding += out_source->rtqo_rebuilding;
	if (out_result->rtqo_status == 0 && out_source->rtqo_status != 0)
		out_result->rtqo_status = out_source->rtqo_status;

	out_result->rtqo_rec_count += out_source->rtqo_rec_count;
	out_result->rtqo_obj_count += out_source->rtqo_obj_count;

	return 0;
}

int
ds_rebuild_tgt_query_handler(crt_rpc_t *rpc)
{
	struct rebuild_tgt_query_out	*rtqo;
	struct rebuild_tgt_query_info	status;
	int				i;
	bool				rebuilding = false;
	int				rc;

	rtqo = crt_reply_get(rpc);
	memset(rtqo, 0, sizeof(*rtqo));
	memset(&status, 0, sizeof(status));
	ABT_mutex_create(&status.lock);
	/* let's check status on every thread*/
	ABT_mutex_lock(rebuild_gst.rg_lock);
	rc = dss_collective(dss_rebuild_check_scanning, &status);
	ABT_mutex_free(&status.lock);
	if (rc) {
		ABT_mutex_unlock(rebuild_gst.rg_lock);
		D_GOTO(out, rc);
	}

	if (status.scanning == 0) {
		/* then check building status*/
		for (i = 0; i < rebuild_gst.rg_puller_nxs; i++) {
			if (rebuild_gst.rg_pullers[i] == 0)
				continue;

			D_DEBUG(DB_TRACE,
				"thread %d rebuilding %d keys, total=%d\n", i,
				rebuild_gst.rg_pullers[i],
				rebuild_gst.rg_puller_total);
				rebuilding = true;
			break;
		}
	} else {
		rebuilding = true;
	}
	ABT_mutex_unlock(rebuild_gst.rg_lock);

	if (rebuilding)
		rtqo->rtqo_rebuilding = 1;

	if (status.status != 0) {
		rtqo->rtqo_status = status.status;
		rebuild_gst.rg_abort = 1;
	}

	D_DEBUG(DB_TRACE, "pool "DF_UUID" scanning %d/%d rebuilding=%s, "
		"obj_count=%d, rec_count=%d, status=%d\n",
		DP_UUID(rebuild_gst.rg_pool_uuid), status.scanning,
		status.status, rebuilding ? "yes" : "no", status.obj_count,
		status.rec_count, rtqo->rtqo_status);
	rtqo->rtqo_rec_count = status.rec_count;
	rtqo->rtqo_obj_count = status.obj_count;

out:
	if (rtqo->rtqo_status == 0)
		rtqo->rtqo_status = rc;

	rc = crt_reply_send(rpc);
	if (rc != 0)
		D_ERROR("send reply failed %d\n", rc);

	return rc;
}

int
ds_rebuild_query(uuid_t pool_uuid, bool do_bcast, daos_rank_list_t *failed_tgts,
		 struct daos_rebuild_status *status)
{
	struct ds_pool			*pool;
	crt_rpc_t			*tgt_rpc;
	struct rebuild_tgt_query_in	*rtqi;
	struct rebuild_tgt_query_out	*rtqo;
	int				 rc;

	memset(status, 0, sizeof(*status));
	status->rs_version = rebuild_gst.rg_rebuild_ver;
	if (status->rs_version == 0) {
		D_DEBUG(DB_TRACE, "No rebuild in progress\n");
		D_GOTO(out, rc = 0);
	}

	if (!do_bcast) { /* just copy the cached information */
		ABT_mutex_lock(rebuild_gst.rg_lock);
		memcpy(status, &rebuild_gst.rg_status, sizeof(*status));
		ABT_mutex_unlock(rebuild_gst.rg_lock);

		D_GOTO(out, rc = 0);
	}

	pool = ds_pool_lookup(pool_uuid);
	if (pool == NULL) {
		D_ERROR("can not find "DF_UUID" rc %d\n",
			DP_UUID(pool_uuid), -DER_NO_HDL);
		D_GOTO(out, rc = -DER_NO_HDL);
	}

	/* Then send rebuild RPC to all targets of the pool */
	rc = ds_pool_bcast_create(dss_get_module_info()->dmi_ctx,
				  pool, DAOS_REBUILD_MODULE,
				  REBUILD_TGT_QUERY, &tgt_rpc, NULL,
				  failed_tgts);
	if (rc != 0)
		D_GOTO(out_put, rc);

	rtqi = crt_req_get(tgt_rpc);
	uuid_copy(rtqi->rtqi_uuid, pool_uuid);
	rc = dss_rpc_send(tgt_rpc);
	if (rc != 0)
		D_GOTO(out_rpc, rc);

	rtqo = crt_reply_get(tgt_rpc);
	D_DEBUG(DB_TRACE, "%p query rebuild ver=%u, status=%d, obj_cnt=%d"
		" rec_cnt=%d\n", rtqo, rebuild_gst.rg_rebuild_ver,
		rtqo->rtqo_rebuilding, rtqo->rtqo_obj_count,
		rtqo->rtqo_rec_count);

	memset(status, 0, sizeof(*status));
	if (rtqo->rtqo_status != 0)
		status->rs_errno = rtqo->rtqo_status;
	else if (rtqo->rtqo_rebuilding == 0)
		status->rs_done = 1;

	status->rs_rec_nr = rtqo->rtqo_rec_count;
	status->rs_obj_nr = rtqo->rtqo_obj_count;

	ABT_mutex_lock(rebuild_gst.rg_lock);
	memcpy(&rebuild_gst.rg_status, status, sizeof(*status));
	ABT_mutex_unlock(rebuild_gst.rg_lock);

	D_EXIT;
out_rpc:
	crt_req_decref(tgt_rpc);
out_put:
	ds_pool_put(pool);
out:
	return rc;
}

/**
 * Finish the rebuild pool, i.e. disconnect pool, close rebuild container,
 * and Mark the failure target to be DOWNOUT.
 */
static int
ds_rebuild_fini(const uuid_t uuid, uint32_t map_ver,
		daos_rank_list_t *tgts_failed)
{
	struct ds_pool		*pool;
	struct rebuild_fini_tgt_in *rfi;
	struct rebuild_out	*ro;
	crt_rpc_t		*rpc;
	double			 now;
	double			 then = 0;
	int			 failed = 0;
	int			 rc;

	D_ENTER;
	if (uuid_compare(uuid, rebuild_gst.rg_pool_uuid) != 0)
		D_GOTO(out, rc = 0); /* even possible? */

	D_DEBUG(DB_TRACE, "mark failed targets of "DF_UUID" as DOWNOUT\n",
		DP_UUID(uuid));
	rc = ds_pool_tgt_exclude_out(rebuild_gst.rg_pool_uuid,
				     tgts_failed, NULL);
	if (rc != 0 && rc != -DER_NOTLEADER) {
		D_ERROR("pool map update failed: rc %d\n", rc);
		D_GOTO(out, rc);
	}
	/* else: if the leader has been changed, it should still broadcast
	 * the fini
	 */
	pool = ds_pool_lookup(uuid);
	if (pool == NULL)
		D_GOTO(out, rc = -DER_NONEXIST);

	while (1) {
		now = ABT_get_wtime();
		if (now - then < RBLD_BCAST_INTV) {
			/* Yield to other ULT */
			ABT_thread_yield();
			continue;
		}
		then = now;

		D_DEBUG(DB_TRACE,
			"Notify all surviving nodes to finalize rebuild\n");
		rc = ds_pool_bcast_create(dss_get_module_info()->dmi_ctx,
					  pool, DAOS_REBUILD_MODULE,
					  REBUILD_TGT_FINI, &rpc, NULL,
					  tgts_failed);
		if (rc != 0) /* can't create RPC, no retry */
			D_GOTO(out_pool, rc);

		rfi = crt_req_get(rpc);
		uuid_copy(rfi->rfti_pool_uuid, uuid);
		rfi->rfti_pool_map_ver = map_ver;

		rc = dss_rpc_send(rpc);
		if (rc == 0) {
			ro = crt_reply_get(rpc);
			rc = ro->ro_status;
		}
		crt_req_decref(rpc);
		if (rc == 0)
			break;

		failed++;
		D_ERROR(DF_UUID": failed to fini rebuild for %d times: %d\n",
			DP_UUID(uuid), failed, rc);

		if (failed >= RBLD_BCAST_RETRY_MAX)
			D_GOTO(out_pool, rc);
	}
	D_EXIT;
out_pool:
	D_DEBUG(DB_TRACE, "pool rebuild "DF_UUID" (map_ver=%u) finish.\n",
		DP_UUID(uuid), map_ver);

	ds_pool_put(pool);
out:
	/* tgt_fini should have done this for me, but just in case... */
	uuid_clear(rebuild_gst.rg_pool_uuid);
	rebuild_gst.rg_abort = 0;
	return rc;
}

#define RBLD_SBUF_LEN	256

enum {
	RB_BCAST_NONE,
	RB_BCAST_MAP,
	RB_BCAST_QUERY,
};

void
ds_rebuild_check(uuid_t pool_uuid, uint32_t map_ver,
		 daos_rank_list_t *tgts_failed)
{
	struct ds_pool	*pool;
	double		 begin = ABT_get_wtime();
	double		 last_print = 0;
	double		 last_bcast = 0;
	double		 now;
	unsigned long	 i = 2;
	unsigned	 failed = 0;
	int		 bcast;
	int		 rc;

	pool = ds_pool_lookup(pool_uuid);
	if (!pool) {
		D_CRIT("No leader anymore?\n");
		return;
	}

	bcast = RB_BCAST_QUERY;
	while (1) {
		char				*str;
		char				 sbuf[RBLD_SBUF_LEN];
		struct daos_rebuild_status	 status;

		now = ABT_get_wtime();
		if (now - last_bcast < RBLD_BCAST_INTV) {
			/* Yield to other ULTs */
			ABT_thread_yield();
			continue;
		}

		if (pool->sp_map_version > rebuild_gst.rg_bcast_ver) {
			/* cascading failure might bump the version again,
			 * in this case, we'd better notify rebuild targets
			 * about the new pool map so they don't pull from
			 * newly dead nodes.
			 */
			bcast = RB_BCAST_MAP;
		}

		/* broadcast new pool map for cascading failure */
		switch (bcast) {
		case RB_BCAST_MAP:
			D_PRINT("cascading failure, bcast pool map\n");
			rc = ds_pool_pmap_broadcast(pool_uuid, NULL);
			if (rc != 0) {
				failed++;
				break;
			}
			rebuild_gst.rg_bcast_ver = pool->sp_map_version;
			bcast = RB_BCAST_QUERY; /* the next step, query */
			failed = 0;
			continue;

		case RB_BCAST_QUERY:
			/* query the current rebuild status */
			rc = ds_rebuild_query(pool_uuid, true, tgts_failed,
					      &status);
			if (rc == 0)
				rc = status.rs_errno;

			if (rc != 0)
				failed++;
			else
				failed = 0;
			break;
		}
		last_bcast = now;

		if (failed && failed < RBLD_BCAST_RETRY_MAX) {
			D_DEBUG(DB_TRACE,
				"Retry bcast %s for the %d times (errno=%d)\n",
				bcast == RB_BCAST_MAP ? "map" : "query",
				failed, rc);
			continue;
		}

		if (failed)
			rebuild_gst.rg_abort = 1;

		if (status.rs_done)
			str = rebuild_gst.rg_abort ? "failed" : "completed";
		else if (status.rs_obj_nr == 0 && status.rs_rec_nr == 0)
			str = "scanning";
		else
			str = "pulling";

		snprintf(sbuf, RBLD_SBUF_LEN,
			"Rebuild [%s] (ver=%u, obj="DF_U64", "
			"rec="DF_U64", duration=%d secs)\n",
			str, map_ver, status.rs_obj_nr, status.rs_rec_nr,
			(int)(now - begin));

		D_DEBUG(DB_TRACE, "%s", sbuf);
		if (status.rs_done) {
			D_PRINT("%s", sbuf);
			break;
		}

		i++;
		/* print something at least for each 10 secons */
		if (IS_PO2(i) || now - last_print > 10) {
			last_print = now;
			D_PRINT("%s", sbuf);
		}
	};
	ds_pool_put(pool);
}

/**
 * Initiate the rebuild process, i.e. sending rebuild requests to every target
 * to find out the impacted objects.
 */
static int
ds_rebuild(const uuid_t uuid, uint32_t map_ver, daos_rank_list_t *tgts_failed,
	   daos_rank_list_t *svc_list)
{
	struct ds_pool		*pool;
	crt_rpc_t		*rpc;
	struct rebuild_scan_in	*rsi;
	struct rebuild_out	*ro;
	int			rc;

	D_DEBUG(DB_TRACE, "rebuild "DF_UUID", map version=%u\n",
		DP_UUID(uuid), map_ver);

	pool = ds_pool_lookup(uuid);
	if (!pool) {
		D_ERROR("Can't find the pool, not leader anymore?\n");
		return -DER_NOTLEADER;
	}

	ABT_mutex_lock(rebuild_gst.rg_lock);
	/* because leader already has already got the latest pool map,
	 * so it might start scan staightaway and send object list to
	 * other nodes which are not ready yet. So we need a barrier
	 * to make sure leader will proceed only if everyone else has
	 * already been aware of the rebuild request and pool map.
	 */
	D_ASSERT(!rebuild_gst.rg_leader_barrier);
	rebuild_gst.rg_leader_barrier = true;
	ABT_mutex_unlock(rebuild_gst.rg_lock);

	/* Send rebuild RPC to all targets of the pool to initialize rebuild.
	 * XXX this should be idempotent as well as query and fini.
	 */
	rc = ds_pool_bcast_create(dss_get_module_info()->dmi_ctx,
				  pool, DAOS_REBUILD_MODULE,
				  REBUILD_OBJECTS_SCAN, &rpc, NULL,
				  tgts_failed);
	if (rc != 0) {
		D_ERROR("pool map broad cast failed: rc %d\n", rc);
		D_GOTO(out, rc = 0); /* ignore the failure */
	}

	rsi = crt_req_get(rpc);
	uuid_generate(rsi->rsi_rebuild_cont_hdl_uuid);
	uuid_generate(rsi->rsi_rebuild_pool_hdl_uuid);
	uuid_copy(rsi->rsi_pool_uuid, uuid);
	D_DEBUG(DB_TRACE, "rebuild "DF_UUID"/"DF_UUID"\n",
		DP_UUID(rsi->rsi_pool_uuid),
		DP_UUID(rsi->rsi_rebuild_cont_hdl_uuid));
	rsi->rsi_pool_map_ver = map_ver;
	rsi->rsi_tgts_failed = tgts_failed;
	rsi->rsi_svc_list = svc_list;

	rc = dss_rpc_send(rpc);
	if (rc != 0)
		D_GOTO(out_rpc, rc);

	ro = crt_reply_get(rpc);
	rc = ro->ro_status;
	if (rc != 0) {
		D_ERROR(DF_UUID": failed to start pool rebuild: %d\n",
			DP_UUID(uuid), rc);
		D_GOTO(out_rpc, rc);
	}

	/* Broadcast the pool map for rebuild */
	rc = ds_pool_pmap_broadcast(uuid, tgts_failed);
	if (rc) {
		D_CRIT("pool map broadcast failed: rc %d\n", rc);
		D_GOTO(out_rpc, rc);
	}

	/* it's time for the leader to go */
	ABT_mutex_lock(rebuild_gst.rg_lock);
	rebuild_gst.rg_leader_barrier = false;
	ABT_cond_broadcast(rebuild_gst.rg_cond);
	ABT_mutex_unlock(rebuild_gst.rg_lock);

	if (rebuild_gst.rg_bcast_ver < map_ver) {
		/* XXX we should not trust this one in case of cascading
		 * failure, instead ds_pool_pmap_broadcast() should return
		 * the version
		 */
		rebuild_gst.rg_bcast_ver = map_ver;
	}
	D_EXIT;
out_rpc:
	crt_req_decref(rpc);
out:
	ds_pool_put(pool);
	return rc;
}

struct ds_rebuild_task {
	daos_list_t	dst_list;
	uuid_t		dst_pool_uuid;
	uint32_t	dst_map_ver;
	daos_rank_list_t *dst_tgts_failed;
	daos_rank_list_t *dst_svc_list;
};

static int
ds_rebuild_one(uuid_t pool_uuid, uint32_t map_ver,
	       daos_rank_list_t *tgts_failed, daos_rank_list_t *svc_list)
{
	int rc;
	int rc1;

	rc = ds_rebuild(pool_uuid, map_ver, tgts_failed, svc_list);
	if (rc != 0) {
		D_ERROR(""DF_UUID" (ver=%u) rebuild failed: rc %d\n",
			DP_UUID(pool_uuid), map_ver, rc);
		D_GOTO(out, rc);
	}
	D_PRINT("Rebuild [started] (ver=%u)\n", map_ver);

	/* Wait until rebuild finished */
	ds_rebuild_check(pool_uuid, map_ver, tgts_failed);
	D_EXIT;
out:
	rc1 = ds_rebuild_fini(pool_uuid, map_ver, tgts_failed);
	if (rc == 0)
		rc = rc1;

	D_PRINT("Rebuild [completed] (ver=%u)\n", map_ver);
	return rc;
}

static void
ds_rebuild_ult(void *arg)
{
	struct ds_rebuild_task	*task;
	int			 rc;

	/* rebuild all failures one by one */
	while (!daos_list_empty(&rebuild_gst.rg_task_list)) {
		task = daos_list_entry(rebuild_gst.rg_task_list.next,
				       struct ds_rebuild_task, dst_list);
		daos_list_del(&task->dst_list);

		ABT_mutex_lock(rebuild_gst.rg_lock);
		memset(&rebuild_gst.rg_status, 0,
		       sizeof(rebuild_gst.rg_status));

		rebuild_gst.rg_status.rs_version =
		rebuild_gst.rg_rebuild_ver = task->dst_map_ver;
		ABT_mutex_unlock(rebuild_gst.rg_lock);

		rc = ds_rebuild_one(task->dst_pool_uuid, task->dst_map_ver,
				    task->dst_tgts_failed, task->dst_svc_list);
		if (rc != 0)
			D_ERROR(""DF_UUID" rebuild failed: rc %d\n",
				DP_UUID(task->dst_pool_uuid), rc);

		daos_rank_list_free(task->dst_tgts_failed);
		daos_rank_list_free(task->dst_svc_list);
		D_FREE_PTR(task);
		ABT_thread_yield();
	}

	rebuild_gst.rg_rebuild_ver	= 0;
	rebuild_gst.rg_bcast_ver	= 0;
	rebuild_gst.rg_leader_barrier	= false;
	rebuild_gst.rg_leader		= false;
}

/**
 * Add rebuild task to the rebuild list and another ULT will rebuild the
 * pool.
 */
int
ds_rebuild_schedule(const uuid_t uuid, uint32_t map_ver,
		    daos_rank_list_t *tgts_failed, daos_rank_list_t *svc_list)
{
	struct ds_rebuild_task	*task;
	int			rc;

	D_ALLOC_PTR(task);
	if (task == NULL)
		return -DER_NOMEM;

	task->dst_map_ver = map_ver;
	uuid_copy(task->dst_pool_uuid, uuid);
	DAOS_INIT_LIST_HEAD(&task->dst_list);

	rc = daos_rank_list_dup(&task->dst_tgts_failed, tgts_failed, true);
	if (rc) {
		D_FREE_PTR(task);
		return rc;
	}

	rc = daos_rank_list_dup(&task->dst_svc_list, svc_list, true);
	if (rc) {
		D_FREE_PTR(task);
		return rc;
	}

	D_PRINT("Rebuild [queued] (ver=%u)\n", map_ver);
	daos_list_add_tail(&task->dst_list, &rebuild_gst.rg_task_list);

	if (rebuild_gst.rg_rebuild_ver == 0) {
		rebuild_gst.rg_rebuild_ver = map_ver;
		rebuild_gst.rg_leader = true;

		rc = dss_ult_create(ds_rebuild_ult, NULL, -1, NULL);
		if (rc) {
			rebuild_gst.rg_rebuild_ver = 0;
			D_GOTO(free, rc);
		}
	}
free:
	if (rc) {
		daos_list_del(&task->dst_list);
		daos_rank_list_free(task->dst_tgts_failed);
		daos_rank_list_free(task->dst_svc_list);
		D_FREE_PTR(task);
	}
	return rc;
}

static int
ds_rebuild_fini_one(void *arg)
{
	struct rebuild_tls *tls = rebuild_tls_get();

	D_DEBUG(DB_TRACE, "close container/pool "DF_UUID"/"DF_UUID"\n",
		DP_UUID(tls->rebuild_cont_hdl_uuid),
		DP_UUID(tls->rebuild_pool_hdl_uuid));

	if (!daos_handle_is_inval(tls->rebuild_pool_hdl)) {
		dc_pool_local_close(tls->rebuild_pool_hdl);
		tls->rebuild_pool_hdl = DAOS_HDL_INVAL;
	}

	ds_cont_local_close(tls->rebuild_cont_hdl_uuid);
	uuid_clear(tls->rebuild_cont_hdl_uuid);

	uuid_clear(tls->rebuild_pool_hdl_uuid);

	daos_rank_list_free(tls->rebuild_svc_list);
	tls->rebuild_svc_list = NULL;

	return 0;
}

int
ds_rebuild_tgt_fini_handler(crt_rpc_t *rpc)
{
	struct rebuild_fini_tgt_in	*rfi = crt_req_get(rpc);
	struct rebuild_out		*ro = crt_reply_get(rpc);
	struct ds_pool			*pool;
	int				 rc;

	ABT_mutex_lock(rebuild_gst.rg_lock);
	if (rebuild_gst.rg_last_ver == rfi->rfti_pool_map_ver) {
		ABT_mutex_unlock(rebuild_gst.rg_lock);
		D_DEBUG(DB_TRACE, "Ignore resend of rebuild fini for "
			DF_UUID", ver=%u\n", DP_UUID(rfi->rfti_pool_uuid),
			rfi->rfti_pool_map_ver);
		D_GOTO(out, rc = 0);
	}

	if (uuid_compare(rfi->rfti_pool_uuid, rebuild_gst.rg_pool_uuid) != 0) {
		ABT_mutex_unlock(rebuild_gst.rg_lock);
		D_GOTO(out, rc = -DER_NO_HDL);
	}

	rebuild_gst.rg_last_ver = rfi->rfti_pool_map_ver;
	D_DEBUG(DB_TRACE, "Finalize rebuild for "DF_UUID", map_ver=%u\n",
		rfi->rfti_pool_uuid, rfi->rfti_pool_map_ver);

	/* close the rebuild pool/container */
	rc = dss_collective(ds_rebuild_fini_one, NULL);

	pool = rebuild_gst.rg_pool;
	rebuild_gst.rg_pool = NULL;
	rebuild_gst.rg_abort = 0;
	uuid_clear(rebuild_gst.rg_pool_uuid);

	ABT_mutex_unlock(rebuild_gst.rg_lock);

	D_ASSERT(pool);
	ds_pool_put(pool);
out:
	ro->ro_status = rc;
	rc = crt_reply_send(rpc);
	if (rc != 0)
		D_ERROR("send reply failed %d\n", rc);

	return rc;
}

/* Note: the rpc input/output parameters is defined in daos_rpc */
static struct daos_rpc_handler rebuild_handlers[] = {
	{
		.dr_opc		= REBUILD_OBJECTS_SCAN,
		.dr_hdlr	= ds_rebuild_scan_handler
	}, {
		.dr_opc		= REBUILD_OBJECTS,
		.dr_hdlr	= ds_rebuild_obj_handler
	}, {
		.dr_opc		= REBUILD_TGT_FINI,
		.dr_hdlr	= ds_rebuild_tgt_fini_handler
	}, {
		.dr_opc		= REBUILD_TGT_QUERY,
		.dr_hdlr	= ds_rebuild_tgt_query_handler,
		.dr_corpc_ops	= {
			.co_aggregate	= ds_rebuild_tgt_query_aggregator,
		}
	}, {
		.dr_opc		= 0
	}
};

struct dss_module_key rebuild_module_key = {
	.dmk_tags = DAOS_SERVER_TAG,
	.dmk_index = -1,
	.dmk_init = rebuild_tls_init,
	.dmk_fini = rebuild_tls_fini,
};

struct dss_module rebuild_module =  {
	.sm_name	= "rebuild",
	.sm_mod_id	= DAOS_REBUILD_MODULE,
	.sm_ver		= 1,
	.sm_init	= init,
	.sm_fini	= fini,
	.sm_srv_rpcs	= rebuild_rpcs,
	.sm_handlers	= rebuild_handlers,
	.sm_key		= &rebuild_module_key,
};
