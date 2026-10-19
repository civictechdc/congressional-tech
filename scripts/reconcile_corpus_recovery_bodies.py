"""Read-only reconciliation command for a sealed recovery batch.

Library code lives in corpus_recovery. This command keeps the checkout root,
because a shim's ``if __name__`` block does not run.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    from corpus_recovery.reconcile_corpus_recovery_bodies import main
    main(root=ROOT)
else:
    import corpus_recovery.reconcile_corpus_recovery_bodies as _implementation
    sys.modules[__name__] = _implementation
