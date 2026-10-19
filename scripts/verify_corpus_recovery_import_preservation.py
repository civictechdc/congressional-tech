"""Read-only preservation audit command.

Library code lives in corpus_recovery. Running this file invokes that command;
importing it returns the library module.
"""
import sys

if __name__ == '__main__':
    from corpus_recovery.verify_corpus_recovery_import_preservation import main
    main()
else:
    import corpus_recovery.verify_corpus_recovery_import_preservation as _implementation
    sys.modules[__name__] = _implementation
