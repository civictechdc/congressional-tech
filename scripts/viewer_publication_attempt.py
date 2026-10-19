"""Re-export the viewer publication attempt runner.

The implementation is packages/viewer_publication. This module object is that
implementation, so existing imports and test patches see the executing code.
"""
import sys

import viewer_publication.viewer_publication_attempt as _implementation

sys.modules[__name__] = _implementation
