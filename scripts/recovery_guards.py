"""Re-export recovery_guards.

The implementation is packages/corpus_recovery. Importing this module returns
that implementation. Loading it by file path also copies the implementation
attributes onto this module.
"""
import sys

import corpus_recovery.recovery_guards as _implementation

sys.modules[__name__] = _implementation
globals().update(_implementation.__dict__)
