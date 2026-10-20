import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)



@pytest.fixture(autouse=True)
def _clear_profile_post_cache():
    from tieba_reply_stats import profile

    profile.clear_post_cache()
    yield
    profile.clear_post_cache()
