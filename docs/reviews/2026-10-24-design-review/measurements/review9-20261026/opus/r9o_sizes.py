import gzip, os, sys
from multiprocessing import Pool
def size(p):
    n = 0
    with gzip.open(p, "rb") as f:
        while chunk := f.read(1 << 24):
            n += len(chunk)
    return os.path.getsize(p), n
if __name__ == "__main__":
    root = sys.argv[1]
    files = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.endswith(".jsonl.gz")]
    with Pool(10) as pool:
        r = pool.map(size, files)
    print(f"files {len(r)} compressed {sum(a for a,_ in r)/1e9:.2f} GB uncompressed {sum(b for _,b in r)/1e9:.2f} GB")
