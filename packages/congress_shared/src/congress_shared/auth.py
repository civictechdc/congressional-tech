import os
import pathlib
import sys


def _load_api_key(arg_name: str, env_var: str, *default_filenames: str) -> str:
    flag = f"--{arg_name}"
    prefix = f"--{arg_name}="
    args = sys.argv[1:] if hasattr(sys, "argv") and sys.argv else []
    for idx, arg in enumerate(args):
        if arg == flag and idx + 1 < len(args):
            return args[idx + 1]
        if arg.startswith(prefix):
            return arg[len(prefix):]

    api_key = os.environ.get(env_var)
    if api_key:
        return api_key

    ## accept every filename the docs have used over time
    key_paths = [os.path.join(pathlib.Path.home(), name) for name in default_filenames]
    for key_path in key_paths:
        if os.path.exists(key_path):
            with open(key_path) as handle:
                return handle.read().strip()
    raise RuntimeError(
        f"{env_var} not found. Provide via --{arg_name}, {env_var} env var, or save it to {key_paths[0]}"
    )


def load_congress_api_key() -> str:
    return _load_api_key(
        "congress-api-key", "DATA_GOV_API_KEY", ".data.gov.api.key", ".data.gov.key"
    )


def load_youtube_api_key() -> str:
    return _load_api_key("youtube-api-key", "YOUTUBE_API_KEY", ".youtube.api.key")
