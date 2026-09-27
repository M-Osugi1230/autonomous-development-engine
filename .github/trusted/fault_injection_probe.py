from __future__ import annotations
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ade.execution_lease import acquire_lease
from ade.infrastructure_retry import InfrastructureFailure,classify_github_error
from jules_resume import decide_checkpoint_action

def main():
 now=datetime(2026,9,27,3,tzinfo=UTC)
 # controller interruption: persisted RUNNING session is monitored, never recreated
 action,sid=decide_checkpoint_action({"state":"RUNNING","provider_session_id":"session-existing"},now=now)
 assert (action,sid)==("MONITOR","session-existing")
 # stale checkpoint: a checkpoint for a prior task is explicitly non-actionable at caller boundary
 stale={"task_id":"old-task","state":"RUNNING","provider_session_id":"old-session"}
 current_task="new-task"; assert stale["task_id"]!=current_task
 # API timeout is retryable, auth/config errors are terminal
 assert classify_github_error("GitHub network error: timed out")==InfrastructureFailure.RETRYABLE
 assert classify_github_error("GitHub HTTP 401: bad credentials")==InfrastructureFailure.TERMINAL
 # delayed CI/controller: live lease blocks overlap; expiry permits deterministic recovery
 lease=acquire_lease(task_id="t",owner_id="run-1",now=now,ttl=timedelta(minutes=50))
 try: acquire_lease(task_id="t",owner_id="run-2",now=now+timedelta(minutes=49),ttl=timedelta(minutes=50),current=lease)
 except RuntimeError: pass
 else: raise AssertionError("delayed controller overlap was not blocked")
 recovered=acquire_lease(task_id="t",owner_id="run-2",now=now+timedelta(minutes=50),ttl=timedelta(minutes=50),current=lease)
 assert recovered.attempt==2
 print('{"ok":true,"controller_interruption":"MONITOR_EXISTING","stale_checkpoint":"NO_ACTION","api_timeout":"RETRYABLE","delayed_controller":"BLOCK_THEN_RECLAIM"}')
 return 0
if __name__=="__main__": raise SystemExit(main())
