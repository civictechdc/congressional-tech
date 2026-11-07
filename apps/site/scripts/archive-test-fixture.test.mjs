import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {archiveFixture,loadArchiveFixture} from './archive-test-fixture.mjs';

async function transportFiles(run){
  const folder=await mkdtemp(join(tmpdir(),'archive-transport-'));
  try{
    const names=['list.parquet',`queries/${'a'.repeat(64)}.sql`,'lineage/0000.openlineage.json'];
    const manifest={release_id:'b'.repeat(64),files:names.map(name=>({name,size:6,sha256:'deliberately-unverified'}))};
    // Physical filenames and parent directories deliberately differ from logical names.
    await mkdir(join(folder,'controls'));
    await mkdir(join(folder,'native'));
    const files={'manifest.json':join(folder,'controls','control.bin')};
    await writeFile(files['manifest.json'],JSON.stringify(manifest));
    for(const [index,name] of names.entries()){
      files[name]=join(folder,'native',`asset-${index}.bin`);
      await writeFile(files[name],`value${index}`);
    }
    await run(files,manifest);
  }finally{await rm(folder,{recursive:true,force:true});}
}

test('explicit inventories retain nested logical names without verifying reader-owned hashes',async()=>{
  await transportFiles(async(files,manifest)=>{
    const fixture=await archiveFixture(files),base=`https://fixture.test/releases/${manifest.release_id}/`;
    assert.equal((await fixture.fetcher('https://fixture.test/manifest.json')).status,200);
    for(const [index,file] of manifest.files.entries())assert.equal(await (await fixture.fetcher(base+file.name)).text(),`value${index}`);
    for(const route of ['missing.parquet','asset-0.bin','0000.openlineage.json',`${'a'.repeat(64)}.sql`])assert.equal((await fixture.fetcher(base+route)).status,404);
    const changed=base.replace(manifest.release_id,'c'.repeat(64))+'list.parquet';
    assert.equal((await fixture.fetcher(changed)).status,404);
    assert.equal(await (await fixture.fetcher(fixture.remapRelease(changed))).text(),'value0');
  });
});

test('range responses distinguish valid bytes from invalid requests',async()=>{
  await transportFiles(async(files,manifest)=>{
    const fixture=await archiveFixture(files),url=`https://fixture.test/releases/${manifest.release_id}/list.parquet`;
    const response=await fixture.fetcher(url,{headers:new Headers({Range:'bytes=1-3'})});
    assert.equal(response.status,206);assert.equal(response.headers.get('Content-Range'),'bytes 1-3/6');assert.equal(await response.text(),'alu');
    for(const range of ['bytes=4-3','bytes=0-6','bytes=-1','bytes=0-','bytes=0-1,3-4','bytes=9007199254740992-9007199254740993'])assert.equal((await fixture.fetcher(url,{headers:{Range:range}})).status,416);
  });
});

test('inventories require exact membership, absolute paths and present files',async()=>{
  await transportFiles(async(files)=>{
    await assert.rejects(archiveFixture({...files,extra:files['list.parquet']}),/membership/);
    const missing={...files};delete missing['list.parquet'];
    await assert.rejects(archiveFixture(missing),/membership/);
    await assert.rejects(archiveFixture({...files,'manifest.json':'manifest.json'}),/absolute/);
    await assert.rejects(archiveFixture({...files,'list.parquet':'list.parquet'}),/absolute/);
    await assert.rejects(archiveFixture({...files,'list.parquet':join(files['list.parquet'],'absent')}),/ENOENT|ENOTDIR/);
    await assert.rejects(loadArchiveFixture('ARCHIVE_TRANSPORT_UNSET_TEST_ENV'),/ARCHIVE_TRANSPORT_UNSET_TEST_ENV is required/);
  });
});
