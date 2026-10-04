"""Record the worker's outcome even when its own cleanup could not execute."""
from datetime import datetime, timezone
import json
import os


def finalize(client, bucket, run_id, attempt, conclusion):
    from botocore.exceptions import ClientError

    key = 'status/raw-source-sync.json'
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response['Error']['Code'] in {'NoSuchKey', '404'}:
            return 'no-status'
        raise
    with response['Body'] as stream:
        state = json.loads(stream.read())
    if (state.get('github_run_id'), state.get('github_run_attempt')) != (run_id, attempt):
        return 'different-run'
    if state['status'] == 'running':
        state['status'] = {'success': 'completed', 'cancelled': 'cancelled'}.get(conclusion, 'failed')
        state['heartbeat_expires_at'] = None
    state.update(github_job_result=conclusion, finalized_at=datetime.now(timezone.utc).isoformat())
    try:
        client.put_object(Bucket=bucket, Key=key, Body=(json.dumps(state, sort_keys=True) + '\n').encode(),
                          ContentType='application/json', IfMatch=response['ETag'])
    except ClientError as error:
        if error.response['Error']['Code'] in {'PreconditionFailed', '412'}:
            return 'superseded'
        raise
    return state['status']


if __name__ == '__main__':
    import boto3
    from botocore.config import Config

    client = boto3.client('s3',
        endpoint_url=f"https://{os.environ['CLOUDFLARE_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name='auto',
        config=Config(connect_timeout=5, read_timeout=10, retries={'total_max_attempts': 3}))
    print(finalize(client, 'congressional-tech-raw', os.environ['GITHUB_RUN_ID'],
                   os.environ['GITHUB_RUN_ATTEMPT'], os.environ['CAPTURE_RESULT']))
