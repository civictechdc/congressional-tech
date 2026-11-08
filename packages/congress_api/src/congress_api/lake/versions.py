"""Content versions for parser packages, their inputs and locked dependencies."""
from hashlib import sha256
import json
from pathlib import Path


# ct-680z: the f05ca4cc and 8ad5cfa2 lock updates changed these full input
# digests without changing extraction. Match all source, schema, parameter
# and lock inputs before retaining a reviewed ID. Future lock changes need
# their own review. The MODS target includes the ct-x78c extraction change.
_REVIEWED_PRODUCER_VERSIONS = {
    # appearance_records.congress_gov
    "d7f881602c2810f82f977d9dfd577aea9c51c6ce2e4a8c36cd600f84cac72d45":
        "6d9460f5ec203c24c508846092505a875710f565e1ff026479b542c7555e7d48",
    # appearance_records.house_xml
    "59193c0a90c40bf4950ae5662152ec6a68a43de80dc74f6b20e9bfeeb7d55b2b":
        "5078ef426e0e262ffcd972b244c3b472669583f164121cc6189ccf69e6abf3a5",
    # appearance_records.mods
    "2b94824aa7a1faecf07b81077a3d2df4cbd3efb680856edbe909a2fcf5311091":
        "1d57eb4426f67b84116bdb4a66774d0e401668b277586939b5c014db8547e32e",
    # appearance_records.senate_page
    "5e420ab3c0d5f9bc1031f5110eef58b52f4a648d021e02093b7e531144424603":
        "9d48c0f61a9f8ab1407c07f9c49cba7d6e9253a6369d73a8d14389d9bfee6bbb",
    # committee_records.house_xml
    "39cd2d437155f3fac591678d00891e5f9d84befaa20e41e353703d84e9aefdb1":
        "e1c6ad0d1398f1d1985e085a0fb9b94c6c42ad38a2d9175ad3e8908eb46c531e",
    # filename_readings
    "f1aeefdae38584ea8222a97186e1de3cf9712412632b73e95c6b5028583c673b":
        "c65e505ef8eb085e38072297aad395ca532fdc76a348a72b86f88c7734a83b09",
    # meeting_records.congress_gov
    "50487cd7b1525c8fa438939e2691c48593c2a479d84b9b66f16ae9185dac88e1":
        "325702c1794f246323ed30d7430650355121dd4891a7cea62b44a34a8ae5084d",
    # meeting_records.house_xml
    "fd42cc63b3202e511e5a4acd5594e973eba7aaff08076bedf820119b33ed3de2":
        "24c88e855dab86f0c362387ffd4c40cf196e2a6f5c14d8aa1dba66f821ca0df5",
}


def version_digest(*, packages, files, values=None):
    """Hash package source/data recursively, explicit input files and vocabularies.

    Names and lengths delimit bytes, so moving a rule or changing a vocabulary
    changes the version. Runtime caches and build outputs never enter it.
    """
    digest = sha256()
    def add(name, data):
        label = name.encode('utf-8')
        digest.update(len(label).to_bytes(8, 'big')); digest.update(label)
        digest.update(len(data).to_bytes(8, 'big')); digest.update(data)
    for name, directory in sorted(packages.items()):
        directory = Path(directory)
        paths = sorted(path for path in directory.rglob('*')
                       if path.is_file() and path.suffix in {'.py', '.json', '.sql'}
                       and '__pycache__' not in path.parts)
        if not paths:
            raise ValueError('Version package has no source or data: ' + name)
        for path in paths:
            add('package/' + name + '/' + path.relative_to(directory).as_posix(), path.read_bytes())
    for name, path in sorted(files.items()):
        add('file/' + name, Path(path).read_bytes())
    add('values', json.dumps(values or {}, ensure_ascii=False, sort_keys=True,
                            separators=(',', ':'), allow_nan=False).encode('utf-8'))
    fingerprint = digest.hexdigest()
    if "lock" in files:
        return _REVIEWED_PRODUCER_VERSIONS.get(fingerprint, fingerprint)
    return fingerprint
