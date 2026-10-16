"""Stage the pinned public review assets before every site build."""
import json
from pathlib import Path
import tempfile
import urllib.request
from filename_reviews import extract_archive, verify_directory

root = Path(__file__).resolve().parents[1]
descriptor = json.loads((root/'document-review-publication.json').read_text())
target = root/'public/data/document-reviews'
if target.exists():
    verify_directory(target, descriptor['sha256'])
else:
    url = f"https://github.com/civictechdc/congressional-tech/releases/download/{descriptor['release']}/{descriptor['asset']}"
    with tempfile.TemporaryDirectory(prefix='document-reviews-') as temporary:
        archive = Path(temporary)/descriptor['asset']
        request = urllib.request.Request(url, headers={'User-Agent':'congressional-tech-review-publisher/1.0'})
        with urllib.request.urlopen(request, timeout=60) as source, archive.open('xb') as out:
            import shutil
            shutil.copyfileobj(source, out)
        extract_archive(archive, target, descriptor)
print(f"Verified public evidence for {descriptor['groups']} assistant-reviewed documents")
