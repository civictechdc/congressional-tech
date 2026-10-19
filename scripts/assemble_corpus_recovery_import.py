"""Re-export assemble_corpus_recovery_import.

The implementation is packages/corpus_recovery. Importing this module returns
that implementation. Loading it by file path also copies the implementation
attributes onto this module.
"""
import sys

import corpus_recovery.assemble_corpus_recovery_import as _implementation

sys.modules[__name__] = _implementation
globals().update(_implementation.__dict__)
