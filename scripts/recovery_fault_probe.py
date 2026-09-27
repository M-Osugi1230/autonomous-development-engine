from __future__ import annotations
import json
from ade.recovery import RecoveryAction, RecoveryFailure
from ade.recovery_runtime import RecoveryRecord, advance_recovery

def main() -> int:
    ci1=advance_recovery("ci-task", RecoveryFailure.CI_FAILURE, "test:assertion")
    assert ci1.action is RecoveryAction.REPAIR
    ci2=advance_recovery("ci-task", RecoveryFailure.CI_FAILURE, "test:assertion", RecoveryRecord.from_dict(ci1.to_dict()))
    assert ci2.action is RecoveryAction.REPAIR
    ci3=advance_recovery("ci-task", RecoveryFailure.CI_FAILURE, "test:assertion", RecoveryRecord.from_dict(ci2.to_dict()))
    assert ci3.action is RecoveryAction.HUMAN_WAIT

    infra1=advance_recovery("infra-task", RecoveryFailure.INFRASTRUCTURE, "github:503")
    infra2=advance_recovery("infra-task", RecoveryFailure.INFRASTRUCTURE, "github:503", RecoveryRecord.from_dict(infra1.to_dict()))
    assert infra1.action is infra2.action is RecoveryAction.RETRY

    conflict=advance_recovery("merge-task", RecoveryFailure.MERGE_CONFLICT, "base:moved")
    assert conflict.action is RecoveryAction.REBASE
    conflict2=advance_recovery("merge-task", RecoveryFailure.MERGE_CONFLICT, "base:moved-again", RecoveryRecord.from_dict(conflict.to_dict()))
    assert conflict2.action is RecoveryAction.REPLAN

    invalid=advance_recovery("bad-task", RecoveryFailure.INVALID_IMPLEMENTATION, "scope:invalid")
    assert invalid.action is RecoveryAction.REPLAN

    print(json.dumps({"ok":True,"ci":"REPAIR->REPAIR->HUMAN_WAIT","infrastructure":"RETRY->RETRY","merge":"REBASE->REPLAN","invalid":"REPLAN","restart_safe":True},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
