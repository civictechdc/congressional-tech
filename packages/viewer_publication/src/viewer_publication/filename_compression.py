"""Shared typed viewer-file compression settings."""
from collections import namedtuple

CompressionPolicy = namedtuple('CompressionPolicy', 'codec level batch_size row_group_size',
                               defaults=('zstd', 3, 8192, 8192))
DEFAULT_COMPRESSION_POLICY = CompressionPolicy()


def validate_compression(policy):
    if policy.codec != 'zstd' or not 1 <= policy.level <= 22 or min(policy.batch_size, policy.row_group_size) < 1:
        raise ValueError('Invalid viewer compression policy')
    return policy
