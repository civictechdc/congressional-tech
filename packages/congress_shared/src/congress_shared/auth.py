import os
import pathlib
import argparse


def _load_api_key(arg_name: str, env_var: str, *default_filenames: str) -> str:
    parser = argparse.ArgumentParser(description="API Key Loader")
    parser.add_argument(f"--{arg_name}", help=f"{env_var} key")
    args, _ = parser.parse_known_args()

    arg_val = getattr(args, arg_name.replace("-", "_"))
    if arg_val:
        return arg_val

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
