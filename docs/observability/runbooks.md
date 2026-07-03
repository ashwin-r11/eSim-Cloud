# eSim-Cloud Simulation Pipeline – Runbooks

## RB-1: High Simulation Failure Rate

**Alert**: `SimulationFailureRateHigh` / `SimulationFailureRateCritical`

### Diagnosis
1. Check the Grafana dashboard → **Job Rate** panel for the failure trend.
2. Query the DB for recent failures:
   ```sql
   SELECT error_code, count(*) FROM simulationapi_simulationjob
   WHERE status='FAILED' AND finished_at > NOW() - INTERVAL '1 hour'
   GROUP BY error_code ORDER BY count DESC;
   ```
3. Check Celery worker logs:  
   `kubectl logs -l app=celery --tail=200`
4. Look for ngspice crashes: grep for `CannotRunSpice` or `NGSPICE_FAILURE`.

### Remediation
- **NGSPICE_FAILURE**: Likely bad netlist input. No worker action needed — frontend should surface the `error_help` to users.
- **IO_ERROR / TRANSIENT**: Disk or network issue on the worker pod. Restart affected pods:  
  `kubectl rollout restart deployment/celery`
- **INVALID_NETLIST spike**: Check whether a frontend change is generating malformed netlists.

---

## RB-2: Queue Saturation

**Alert**: `SimulationQueueDepthHigh`

### Diagnosis
1. Check queue depth:
   `redis-cli LLEN celery` (or the named queue)
2. Count active Celery workers:  
   `celery -A esimCloud inspect active`

### Remediation
- Scale out Celery workers:  
  `kubectl scale deployment/celery --replicas=<N>`
- If Redis is overwhelmed, check Redis memory:  
  `redis-cli INFO memory`
- Apply Celery autoscaling via HPA if Kubernetes metrics-server is available.

---

## RB-3: Jobs Stuck in RUNNING (Heartbeat Lost)

**Alert**: `SimulationJobsStuckRunning`

### Diagnosis
1. Query for stale RUNNING jobs:
   ```sql
   SELECT job_id, last_heartbeat_at, NOW() - last_heartbeat_at AS age
   FROM simulationapi_simulationjob
   WHERE status='RUNNING'
   ORDER BY age DESC;
   ```
2. Check if Celery beat is running:  
   `kubectl get pods -l app=celery-beat`
3. Check `recover_stale_jobs` Celery task logs.

### Remediation
- The `recover_stale_jobs` beat task runs every 60 s and will auto-timeout jobs with heartbeat age > 120 s.
- If the beat scheduler is down, manually trigger recovery:  
  `python manage.py shell -c "from simulationAPI.tasks import recover_stale_jobs; recover_stale_jobs()"`
- Restart Celery beat pod if it is not running.

---

## RB-4: Simulation Timeout Rate High

**Alert**: `SimulationTimeoutRateHigh`

### Diagnosis
1. Check which simulation types are timing out:
   ```sql
   SELECT simulation_type, count(*) FROM simulationapi_simulationjob
   WHERE status='TIMEOUT' AND finished_at > NOW() - INTERVAL '1 hour'
   GROUP BY simulation_type;
   ```
2. Review the p99 execution time in the Grafana dashboard.

### Remediation
- If execution_timeout is too low for legitimate workloads, increase it:  
  `SIM_EXECUTION_TIMEOUT=600` in `.env` / Kubernetes secrets.
- If large netlists are causing timeouts, add frontend validation for netlist size.
- Check worker pod CPU throttling: `kubectl top pods -l app=celery`.

---

## RB-5: Orphan Pod Cleanup Failure

### Diagnosis
1. List orphan simulation pods (pods without a Redis session):  
   `kubectl get pods -l component=sim-worker`
2. Check session-manager cleanup logs:  
   `kubectl logs -l app=session-manager --tail=100`

### Remediation
- Force cleanup via session-manager API:  
  `POST /session/<user_id>` → DELETE
- Manually delete stale pods:  
  `kubectl delete pod -l component=sim-worker`
- Run the Django maintenance task:  
  `python manage.py shell -c "from simulationAPI.maintenance_tasks import cleanup_orphan_files; cleanup_orphan_files()"`
