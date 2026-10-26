import pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc, os, random, collections
base='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/'
out='out/'
cap=pq.read_table(base+'captures.parquet',columns=['sha256','retrieved_at','context_url'])
sh=pc.unique(cap['sha256'].drop_null()).to_pylist()
print('distinct sha256', len(sh))
pre=collections.Counter(s[:16] for s in sh)
print('8-byte prefix collisions', sum(1 for v in pre.values() if v>1))
# retrieved_at formats
ra=cap['retrieved_at'].drop_null().to_pylist()
shapes=collections.Counter()
import re
for s in random.Random(1).sample(ra, min(200000,len(ra))):
    shapes[re.sub(r'\d','9',s)]+=1
print('retrieved_at shapes', shapes.most_common(8))
# filename column like list.parquet
df=pq.read_table(base+'document-filenames.parquet',columns=['filename'])
fn=sorted(set(x for x in df['filename'].to_pylist() if x is not None), key=lambda s:s.encode())
print('distinct filenames', len(fn), 'avg bytes', sum(len(x.encode()) for x in fn)/len(fn))
t=pa.table({'filename':pa.array(fn)})
pq.write_table(t,out+'fn_delta.parquet',compression='zstd',compression_level=3,use_dictionary=False,column_encoding={'filename':'DELTA_BYTE_ARRAY'},row_group_size=65536,data_page_version='2.0')
pq.write_table(t,out+'fn_plain.parquet',compression='zstd',compression_level=3,use_dictionary=False,row_group_size=65536,data_page_version='2.0')
for f in ['fn_delta','fn_plain']: print(f, os.path.getsize(out+f+'.parquet'))
# link_key lookup file
keys=sorted(bytes.fromhex(s[:16]) for s in sh)
rows=list(range(len(keys))); random.Random(2).shuffle(rows)
t=pa.table({'link_key':pa.array(keys,pa.binary(8)),'list_row':pa.array(rows,pa.int32())})
pq.write_table(t,out+'links.parquet',compression='zstd',compression_level=3,use_dictionary=False,data_page_size=16384,row_group_size=len(keys),write_page_index=True,data_page_version='2.0')
print('links rows',len(keys),'bytes',os.path.getsize(out+'links.parquet'))
# url_state-like
ds=pq.read_table(base+'download-state.parquet',columns=['url'])
u=sorted(set(ds['url'].drop_null().to_pylist()), key=lambda s:s.encode())
print('urls',len(u),'avg',sum(len(x) for x in u)/len(u))
t=pa.table({'requested_url':pa.array(u)})
pq.write_table(t,out+'urls.parquet',compression='zstd',compression_level=3,use_dictionary=False,row_group_size=65536)
pq.write_table(t,out+'urls_delta.parquet',compression='zstd',compression_level=3,use_dictionary=False,column_encoding={'requested_url':'DELTA_BYTE_ARRAY'},row_group_size=65536)
print('url col bytes plain', os.path.getsize(out+'urls.parquet'),'delta',os.path.getsize(out+'urls_delta.parquet'))
# placeholder distinct context count
pairs=pc.unique(pc.binary_join_element_wise(cap['sha256'],cap['context_url'],'|').drop_null())
print('distinct (body,context) pairs', len(pairs))
