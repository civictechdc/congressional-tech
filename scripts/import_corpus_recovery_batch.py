"""Re-export import_corpus_recovery_batch.

The implementation is packages/corpus_recovery. Importing this module returns
that implementation. Loading it by file path also copies the implementation
attributes onto this module.
"""
import sys

import corpus_recovery.import_corpus_recovery_batch as _implementation

sys.modules[__name__] = _implementation
globals().update(_implementation.__dict__)
