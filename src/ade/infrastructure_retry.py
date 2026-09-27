from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum

class InfrastructureFailure(StrEnum):
    RETRYABLE="RETRYABLE"; TERMINAL="TERMINAL"

@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts:int=3
    base_delay_seconds:float=1.0
    def __post_init__(self):
        if type(self.max_attempts) is not int or self.max_attempts<1: raise ValueError("max_attempts must be positive")
        if not isinstance(self.base_delay_seconds,(int,float)) or self.base_delay_seconds<0: raise ValueError("base_delay_seconds must be non-negative")

def classify_github_error(message:str)->InfrastructureFailure:
    value=message.lower()
    retry_markers=("network error","timed out","timeout","http 408","http 429","http 500","http 502","http 503","http 504")
    return InfrastructureFailure.RETRYABLE if any(x in value for x in retry_markers) else InfrastructureFailure.TERMINAL

def retry_delay(policy:RetryPolicy, attempt:int)->float:
    if type(attempt) is not int or attempt<1: raise ValueError("attempt must be positive")
    return float(policy.base_delay_seconds)*(2**(attempt-1))
