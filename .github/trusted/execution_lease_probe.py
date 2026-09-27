from __future__ import annotations
import copy, sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from ade.execution_lease_store import claim_execution

class Missing(RuntimeError): pass
class FakeGitHub:
    def __init__(self): self.file=None; self.sha=None; self.writes=0
    def get_json_file(self,path,*,ref="main"):
        if self.file is None: raise Missing("GitHub HTTP 404: missing")
        return copy.deepcopy(self.file), self.sha
    def put_json_file(self,path,payload,*,sha,message,branch="main"):
        if sha != self.sha: raise RuntimeError("stale sha")
        self.file=copy.deepcopy(payload); self.sha=f"sha-{self.writes+1}"; self.writes+=1

def main():
    gh=FakeGitHub(); now=datetime(2026,9,27,3,tzinfo=UTC); created=[]
    a=claim_execution(gh,task_id="task-1",owner_id="run-1",now=now,ttl=timedelta(minutes=10)); created.append(a.owner_id)
    same=claim_execution(gh,task_id="task-1",owner_id="run-1",now=now+timedelta(seconds=1),ttl=timedelta(minutes=10))
    assert same==a and gh.writes==1
    try: claim_execution(gh,task_id="task-1",owner_id="run-2",now=now+timedelta(minutes=1),ttl=timedelta(minutes=10))
    except RuntimeError: pass
    else: raise AssertionError("duplicate dispatch was not blocked")
    b=claim_execution(gh,task_id="task-1",owner_id="run-2",now=now+timedelta(minutes=10),ttl=timedelta(minutes=10)); created.append(b.owner_id)
    assert b.attempt==2 and gh.writes==2
    print('{"ok":true,"provider_session_creations_allowed":2,"duplicate_live_dispatch_blocked":true,"stale_reclaim":true}')
    return 0
if __name__=="__main__": raise SystemExit(main())
