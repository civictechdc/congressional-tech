"""Bounded archive/search calls using the capture journal and shared admission.

Binary replay returns a sealed FetchResult, never an in-memory response body.
Search results are leads; this provider exposes no exhaustive-index guarantee.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import socket
from urllib.parse import urlsplit

import requests

from congress_api.acquisition.admission import Admission
from congress_api.acquisition.capture_journal import DurableCapture,durable_json
from congress_api.acquisition.fetcher import CaptureScope,Fetcher
from congress_api.transport.raw_adapters import DirectAdapter,network_outcome_unknown
from congress_shared.custody import canonical_json_bytes,verify_local_file
from corpus_recovery.discovery import Response,campaign_lookup,wayback_lookup,relocated_search,validate_wayback_replay


class Budgeted:
    def __init__(self,adapter,admission,kind,cost):
        self.adapter,self.admission,self.kind,self.cost=adapter,admission,kind,cost
    def hop(self,url,destination,*,limit,headers):
        reservation=self.admission.reserve(self.kind,self.cost)
        self.last_attempt=reservation
        result=self.adapter.hop(url,destination,limit=limit,headers=headers)
        if network_outcome_unknown(result):
            from congress_api.acquisition.capture_journal import UnknownRemoteOutcome
            raise UnknownRemoteOutcome('Uncertain discovery response retains its reservation')
        self.admission.settle(reservation,self.cost)
        return result


class DiscoveryRuntime:
    def __init__(self,root,*,binding,admission,session=None,resolve=None,control_limit=4<<20):
        if type(control_limit) is not int or not 0<control_limit<=4<<20:
            raise ValueError('Discovery controls are bounded to 4 MiB')
        self.journal=DurableCapture(root,binding)
        self.admission=admission
        self.session=session or requests.Session()
        self.resolve=resolve or (lambda host:list({r[4][0] for r in socket.getaddrinfo(host,None)}))
        self.control_limit=control_limit

    def _fetch(self,url,*,adapter,limit,definition):
        operation=hashlib.sha256(canonical_json_bytes(dict(url=url,definition=definition))).hexdigest()
        # Exact request URL: redirects require another explicit source decision.
        scope=CaptureScope([re.escape(url)],[],resolve=self.resolve)
        def factory(directory):
            return Fetcher(scope=scope,direct=adapter,provider=None,pace=lambda *_:None,
                directory=directory,spool_limit=limit)
        result=self.journal.fetch(operation,url,factory)
        return result,operation

    def control(self,kind,url):
        if kind!='cdx' or urlsplit(url).hostname not in {'webharvest.gov','web.archive.org'}:
            raise ValueError('Only archive CDX requests enter the control adapter')
        result,operation=self._fetch(url,adapter=Budgeted(DirectAdapter(self.session),self.admission,'cdx',0),
            limit=self.control_limit,definition=dict(kind=kind,limit=self.control_limit))
        final=result.final
        raw=final.body.path.read_bytes() if final.body else b''
        return Response(final.http_status,raw,final.complete,operation,
                        final.headers.get('content-type',''),final.url)

    def replay(self,candidate,*,body_limit=16<<20):
        if type(body_limit) is not int or not 0<body_limit<=16<<20:
            raise ValueError('Replay limit exceeds locally qualified 16 MiB admission')
        url,source=candidate['url'],candidate['source']
        original,timestamp=candidate['original_url'],candidate['timestamp']
        if source=='wayback':
            if not validate_wayback_replay(url,original,timestamp):
                raise ValueError('Invalid Wayback replay identity')
        elif (source!='webharvest' or not re.fullmatch(r'congress(?:109|11[0-8])th',candidate.get('collection',''))
              or not re.fullmatch(r'\d{14}',timestamp)
              or url!=f"https://webharvest.gov/{candidate['collection']}/{timestamp}id_/{original}"):
            raise ValueError('Invalid Web Harvest replay identity')
        result,operation=self._fetch(url,adapter=Budgeted(DirectAdapter(self.session),self.admission,'replay',0),
            limit=body_limit,definition=dict(kind='replay',candidate=candidate,limit=body_limit))
        final=result.final
        if final.url!=url or final.http_status!=200 or not final.complete or final.body is None:
            raise ValueError('Replay is incomplete or redirected')
        digest=candidate.get('digest')
        if digest and digest!='-':
            verified=verify_local_file(final.body.path,expected_sha256=final.body.sha256,
                expected_size=final.body.size,additional_hashes={'sha1':hashlib.sha1})
            encoded=base64.b32encode(bytes.fromhex(verified['sha1'])).decode().rstrip('=')
            if digest.removeprefix('sha1:').upper().rstrip('=')!=encoded:
                raise ValueError('Archive replay digest mismatch')
        return result,operation

    def search(self,*,api_key,upper_cost,result_limit=10):
        if not isinstance(api_key,str) or not api_key or type(upper_cost) is not int or upper_cost<=0:
            raise ValueError('Paid search needs a credential and explicit positive price bound')
        if type(result_limit) is not int or not 1<=result_limit<=100:raise ValueError('Search result limit must be 1..100')
        runtime=self
        def call(query,page,hosts):
            if page is not None:raise ValueError('Firecrawl search does not provide this pagination cursor')
            payload=dict(query=query,limit=result_limit,sources=['web'],includeDomains=list(hosts))
            class PostSession:
                def get(self,url,**kwargs):
                    kwargs['headers']={**kwargs['headers'],'Authorization':'Bearer '+api_key}
                    return runtime.session.post(url,json=payload,**kwargs)
            url='https://api.firecrawl.dev/v2/search'
            result,operation=runtime._fetch(url,adapter=Budgeted(DirectAdapter(PostSession()),runtime.admission,'search',upper_cost),
                limit=runtime.control_limit,definition=dict(kind='firecrawl-search-v2',payload=payload,upper_cost=upper_cost))
            final=result.final
            candidates=[]
            if final.http_status==200 and final.complete and final.body:
                value=json.loads(final.body.path.read_bytes())
                if value.get('success') is True:
                    rows=value.get('data',{}).get('web',[])
                    if not isinstance(rows,list) or len(rows)>result_limit:raise ValueError('Search response exceeded selected result bound')
                    candidates=[r['url'] for r in rows if isinstance(r,dict) and isinstance(r.get('url'),str)]
            return dict(candidates=candidates,evidence=operation,complete=False,next_page=None)
        return call


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',required=True);parser.add_argument('--target',required=True)
    parser.add_argument('--work',required=True);parser.add_argument('--runtime',required=True)
    parser.add_argument('--source',choices=['webharvest','wayback'],required=True)
    parser.add_argument('--collection');parser.add_argument('--max-pages',type=int,required=True)
    parser.add_argument('--request-cap',type=int,required=True)
    parser.add_argument('--spend-cap-micros',type=int,default=0)
    parser.add_argument('--admission-db',type=Path,help='Shared acquisition/discovery campaign admission database')
    args=parser.parse_args(argv)
    from congress_shared.campaign import load_campaign
    from congress_api.retention.provenance import run_job
    from corpus_recovery.campaign import _q,_input
    from docspec_client.client import NativeDatasets
    campaign=load_campaign(args.campaign);root=Path(args.work);root.mkdir(parents=True,exist_ok=True)
    selected=run_job(root/'membership',NativeDatasets.from_config(args.runtime),
        inputs=[_input(campaign,campaign.target_table,'targets')],steps=[],outputs=[],queries=[
            dict(name='target',sql=f'SELECT count(*) AS n FROM targets WHERE target_url={_q(args.target)}')])
    if selected['target']!=[{'n':1}]:raise ValueError('Target is not an unambiguous campaign member')
    runtime=DiscoveryRuntime(root/'calls',binding=dict(campaign=campaign.descriptor_sha256),
        admission=Admission(args.admission_db or root/'admission.sqlite',args.request_cap,args.spend_cap_micros))
    if args.source=='wayback':result=wayback_lookup(args.target,runtime.control,max_pages=args.max_pages)
    else:result=campaign_lookup(args.target,args.collection,runtime.control,max_pages=args.max_pages)
    campaign.require_custody();durable_json(root/'discovery.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
