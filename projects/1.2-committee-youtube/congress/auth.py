import os
import pathlib
import argparse


def load_api_key() -> str:
    """
    Load the DATA.GOV API key, in order of precedence:
    1. Command-line argument (--api-key)
    2. Environment variable DATA_GOV_API_KEY
    3. File at ~/.data.gov.key

    Returns:
        str: The API key string.

    Raises:
        RuntimeError: If no API key is found.
    """
    parser = argparse.ArgumentParser(description="Congress.gov API data fetcher.")
    parser.add_argument("--api-key", help="DATA.GOV API key")
    args, _ = parser.parse_known_args()

    if args.api_key:
        return args.api_key

    api_key = os.environ.get("DATA_GOV_API_KEY")
    if api_key:
        return api_key

    key_path = os.path.join(pathlib.Path.home(), ".data.gov.key")
    try:
        with open(key_path) as handle:
            return handle.read().strip()
    except Exception:
        raise RuntimeError(
            f"API key not found. Provide it via --api-key, DATA_GOV_API_KEY env var, or save it to {key_path}"
        )
