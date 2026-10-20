"""Early disk admission for typed preparation; native admission remains authoritative."""
import json
from pathlib import Path
import shutil
import stat

# Reference profile in the pinned DocSpec src/budget.rs. Explicit native limits
# override it; this check never writes or changes those limits.
_NATIVE_SCRATCH_BYTES = 32 << 30
_HEADROOM_BYTES = 8 << 30


class AdoptionCapacityError(ValueError):
    """Preparation cannot fit alongside the declared native scratch requirement."""

    def __init__(self, receipt):
        self.receipt = receipt
        missing = max(row["required_free_bytes"] - row["available_bytes"]
                      for row in receipt["filesystems"])
        super().__init__(
            f"Adoption needs at least {missing:,} additional bytes before preparation; "
            "free space or choose another staging volume. Native limits are unchanged.")


def preparation_budget(metadata):
    """Estimate a finite enforced stage budget from Parquet metadata, without decoding.

    Three times the uncompressed size allows typed input parts, the ordered
    derivative, and external sort/write scratch; the row allowance covers
    lookup keys. This is a planning estimate, not a guarantee about Parquet
    compression or Python objects. Preparation enforces its budget.
    """
    return (3 * sum(metadata.row_group(i).total_byte_size
                    for i in range(metadata.num_row_groups))
            + 4096 * metadata.num_rows + (1 << 20))


def _filesystem(path):
    ancestor = Path(path).resolve()
    while not ancestor.exists():
        ancestor = ancestor.parent
    return ancestor.stat().st_dev, str(ancestor), shutil.disk_usage(ancestor).free


def _retained_bytes(directory):
    if directory.is_symlink():
        raise ValueError("Preparation directory cannot be a symlink")
    if not directory.exists():
        return 0
    total = 0
    for path in directory.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Preparation cannot contain a symlink")
        if stat.S_ISREG(info.st_mode):
            total += info.st_size
    return total


def require_adoption_capacity(native, directory, staging_bytes, *,
                              headroom_bytes=_HEADROOM_BYTES):
    """Check additional preparation and native scratch on their actual volumes.

    Already retained preparation occupies disk and is not charged a second time.
    This snapshot does not reserve space against other processes. The bounded
    preparation writer and native owner continue enforcing their own limits.
    """
    if type(staging_bytes) is not int or staging_bytes < 0:
        raise ValueError("Preparation budget must be a nonnegative integer")
    if type(headroom_bytes) is not int or headroom_bytes < 0:
        raise ValueError("Headroom must be a nonnegative integer")
    scratch = _NATIVE_SCRATCH_BYTES
    if getattr(native, "limits", None) is not None:
        with Path(native.limits).open("rb") as source:
            body = source.read((1 << 20) + 1)
        if len(body) > 1 << 20:
            raise ValueError("Native limits configuration exceeds its byte budget")
        settings = json.loads(body)
        if not isinstance(settings, dict):
            raise ValueError("Native limits must be a JSON object")
        scratch = settings.get("scratch_bytes", scratch)
    if type(scratch) is not int or scratch <= 0:
        raise ValueError("Native scratch_bytes must be a positive integer")
    directory = Path(directory)
    retained = _retained_bytes(directory)
    additional = max(0, staging_bytes - retained)
    volumes = {}
    for path, required, preparation in (
            (directory, additional, True), (Path(native.workspace), scratch, False)):
        device, location, available = _filesystem(path)
        if device not in volumes:
            volumes[device] = dict(path=location, available_bytes=available,
                                   device=device, preparation=False,
                                   required_free_bytes=headroom_bytes,
                                   base_required_free_bytes=headroom_bytes)
        volumes[device]["available_bytes"] = min(volumes[device]["available_bytes"], available)
        volumes[device]["required_free_bytes"] += required
        if preparation:
            volumes[device]["preparation"] = True
        else:
            volumes[device]["base_required_free_bytes"] += required
    receipt = dict(version=1, staging_budget_bytes=staging_bytes,
                   staging_retained_bytes=retained, staging_additional_bytes=additional,
                   native_scratch_bytes=scratch, headroom_bytes=headroom_bytes,
                   filesystems=list(volumes.values()))
    if any(row["available_bytes"] < row["required_free_bytes"]
           for row in receipt["filesystems"]):
        raise AdoptionCapacityError(receipt)
    return receipt


def recheck_adoption_capacity(receipt, retained_bytes):
    """Refresh free space using tracked stage bytes, without walking files again."""
    if type(retained_bytes) is not int or retained_bytes < 0:
        raise ValueError("Retained preparation bytes must be a nonnegative integer")
    additional = max(0, receipt["staging_budget_bytes"] - retained_bytes)
    volumes = []
    for volume in receipt["filesystems"]:
        device, _, available = _filesystem(Path(volume["path"]))
        if device != volume["device"]:
            raise ValueError("Adoption filesystem changed after capacity admission")
        required = volume["base_required_free_bytes"]
        if volume["preparation"]:
            required += additional
        volumes.append(dict(volume, available_bytes=available, required_free_bytes=required))
    current = dict(receipt, staging_retained_bytes=retained_bytes,
                   staging_additional_bytes=additional, filesystems=volumes)
    if any(row["available_bytes"] < row["required_free_bytes"] for row in volumes):
        raise AdoptionCapacityError(current)
    return current
