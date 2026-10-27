"""One-time native conversion of the pinned, published assistant kind reviews."""
import json
from pathlib import Path

from congress_api.retention.provenance import (
    file_pin,finish_stage,instant,json_input,list_of,parquet_output,parquet_records,
    run_job,stage_records,struct,
)
from viewer_publication.filename_review_binding import pinned_reviews,validate_identities


def stage_reviews(reviews,descriptor,identities,*,output,engine,decided_at):
    instant(decided_at)
    reviews,descriptor,identities=map(Path,(reviews,descriptor,identities))
    pin=json.loads(descriptor.read_text())
    published=pinned_reviews(reviews,pin)
    identity=validate_identities(json.loads(identities.read_text()),pin)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    jobs=output/'jobs';jobs.mkdir()
    inputs=[json_input(jobs,'published',
        (dict(position=index,**row) for index,row in enumerate(published['rows'])),
        position='Int64',document_id='Utf8',status='Utf8',
        selected=struct(document_kind=list_of('Utf8')),
        review=struct(body_observation=struct(sha256='Utf8',notes='Utf8'))),
        json_input(jobs,'identities',identity['rows'],index='Int64',document_id='Utf8',body_key='Utf8')]
    steps=[dict(name='review_join',materialize=True,sql='''SELECT p.*,i.body_key,
        substr(i.body_key,18,64) AS body_hex FROM published p
        JOIN identities i ON p.position=i."index" AND p.document_id=i.document_id''')]
    # Both metadata inputs are pinned before interpolation; only the explicit
    # timestamp needs SQL quoting. Selected values remain native list columns.
    stamp=decided_at.replace("'","''")
    source=pin['sha256']
    sql=f'''SELECT '{source}:' || cast(position AS VARCHAR) AS id,
        substr(body_hex,1,16) AS target,'kind_override' AS verdict,
        selected.document_kind AS value,
        coalesce(review.body_observation.notes,'') || '\nPublished selection: ' || status ||
            '; publication {source}; review {pin['review_sha256']}' AS note,
        'assistant' AS reviewer,'{stamp}' AS decided_at,cast(NULL AS VARCHAR) AS supersedes
        FROM review_join'''
    queries=[dict(name='invariants',sql=f'''SELECT
        (SELECT count(*) FROM review_join) AS matched,
        (SELECT count(*) FROM review_join WHERE (NOT regexp_like(body_key,'^bodies/sha256/[a-f0-9]{{2}}/[a-f0-9]{{64}}[.]gz$'))
            OR (substr(body_key,15,2)<>substr(body_hex,1,2))
            OR (review.body_observation.sha256 IS DISTINCT FROM body_hex)
            OR (coalesce(array_length(selected.document_kind),0)=0)) AS invalid,
        (SELECT count(*) FROM (SELECT substr(body_hex,1,16) FROM review_join
            GROUP BY substr(body_hex,1,16) HAVING count(*)>1)) AS duplicate_targets''')]
    reports=run_job(jobs,engine,inputs=inputs,steps=steps,
        outputs=[parquet_output(output,'reviews',sql,['id'])],queries=queries)
    invariant=reports['invariants'][0]
    if invariant!={'matched':pin['groups'],'invalid':0,'duplicate_targets':0}:
        raise ValueError('Published reviews do not bind one-to-one to their exact bodies')
    key,count=stage_records(output,'reviews',parquet_records(output/'reviews.parquet'),decided_at=decided_at)
    return finish_stage(output,kind='reviews',provenance=key,records=count,
        inputs=dict(reviews=file_pin(reviews),descriptor=file_pin(descriptor),identities=file_pin(identities)))


ROOT=Path(__file__).resolve().parents[4]


def main(argv=None):
    import argparse
    from docspec_client.client import NativeDatasets
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviews',type=Path,required=True)
    parser.add_argument('--descriptor',type=Path,default=ROOT/'apps/site/document-review-publication.json')
    parser.add_argument('--identities',type=Path,default=ROOT/'apps/site/document-review-identities.json')
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--decided-at',required=True,help='Explicit migration decision timestamp, with timezone')
    parser.add_argument('--native-config',type=Path,required=True)
    args=parser.parse_args(argv)
    result=stage_reviews(args.reviews,args.descriptor,args.identities,output=args.stage,
        engine=NativeDatasets.from_config(args.native_config),decided_at=args.decided_at)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
