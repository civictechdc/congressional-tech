"""Re-export publication continuation.

The implementation is packages/viewer_publication. This module object is that
implementation, so existing imports and test patches see the executing code.
"""
import sys

import viewer_publication.recovery_publication_continuation as _implementation

sys.modules[__name__] = _implementation
