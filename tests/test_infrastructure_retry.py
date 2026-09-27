import unittest
from ade.infrastructure_retry import *
class RetryTests(unittest.TestCase):
 def test_retryable(self):
  for m in ["GitHub network error: reset","GitHub HTTP 429: rate","GitHub HTTP 503: down","request timeout"]: self.assertEqual(classify_github_error(m),InfrastructureFailure.RETRYABLE)
 def test_terminal(self):
  for m in ["GitHub HTTP 401: bad credentials","GitHub HTTP 403: forbidden","GitHub HTTP 404: missing","GitHub HTTP 422: invalid"]: self.assertEqual(classify_github_error(m),InfrastructureFailure.TERMINAL)
 def test_bounded_backoff(self): self.assertEqual([retry_delay(RetryPolicy(max_attempts=3,base_delay_seconds=.5),i) for i in (1,2,3)],[.5,1.,2.])
if __name__=="__main__":unittest.main()
