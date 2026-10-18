"""Close preparation-owned resources without replacing the primary failure."""
from contextlib import contextmanager, ExitStack


@contextmanager
def owned_resources():
    resources = ExitStack()
    try:
        yield resources
    except BaseException as error:
        try:
            resources.__exit__(type(error), error, error.__traceback__)
        except BaseException as cleanup:
            error.add_note(f'Preparation resource cleanup also failed: {cleanup}')
        raise
    else:
        resources.close()
