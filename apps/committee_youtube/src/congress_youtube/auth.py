import os
import pathlib
import argparse


def _load_api_key(arg_name: str, env_var: str, default_filename: str) -> str:
    parser = argparse.ArgumentParser(description="API Key Loader")
    parser.add_argument(f"--{arg_name}", help=f"{env_var} key")
    args, _ = parser.parse_known_args()

    arg_val = getattr(args, arg_name.replace("-", "_"))
    if arg_val:
        return arg_val

    api_key = os.environ.get(env_var)
    if api_key:
        return api_key

    key_path = os.path.join(pathlib.Path.home(), default_filename)
    try:
        with open(key_path) as handle:
            return handle.read().strip()
    except Exception:
        raise RuntimeError(
            f"{env_var} not found. Provide via --{arg_name}, {env_var} env var, or save it to {key_path}"
        )


def load_congress_api_key() -> str:
    return _load_api_key("congress-api-key", "DATA_GOV_API_KEY", ".data.gov.key")


def load_youtube_api_key() -> str:
    return _load_api_key("youtube-api-key", "YOUTUBE_API_KEY", ".youtube.api.key")
