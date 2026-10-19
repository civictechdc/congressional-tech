"""Read-only reconciliation command for a sealed recovery batch.

Library code lives in corpus_recovery. This command keeps the checkout root,
because a shim's ``if __name__`` block does not run.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if __name__ == '__main__':
    from corpus_recovery.inventory import main
    main(root=ROOT)
