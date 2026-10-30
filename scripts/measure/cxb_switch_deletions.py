"""Read-only F5 inventory from committed git blobs. This tool never deletes."""
import argparse
import ast
from collections import defaultdict
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess


CODE = {'.py', '.ts', '.tsx', '.js', '.mjs', '.rs', '.sh', '.toml', '.yml', '.yaml', '.astro', '.sql'}
CA = 'packages/congress_api/src/congress_api/'
RET = CA + 'retention/'
VP = 'packages/viewer_publication/src/viewer_publication/'
CR = 'packages/corpus_recovery/src/corpus_recovery/'
DC = 'packages/docspec_client/src/docspec_client/'
SITE = 'apps/site/src/components/explorer/reader/filenames/'
PUBLICATION_CLIENT_KEEP = ['require_publication_client','publish_manifest_pointer','VerifiedTransfer']
PUBLICATION_CLIENT_KEEP_IMPORTS = ['dataclasses.dataclass','hashlib']
RAW_READER_KEEP = ['R2GetTransportExhausted','_ReadyPrefetch','_raw_pin','_stream_read_attempts','_stream_retry_delay',
    '_read_stream','_throttle_delay','_configure_retries','R2Store.__init__',
    'R2Store._write_manifest_disk_cache','R2Store._immutable_cache_path',
    'R2Store.prefetch_immutable_ready','R2Store.prefetch_immutable','R2Store.read','R2Store._read',
    'R2Store.read_file','R2Store._read_checked_file','R2Store.read_derived_file',
    'R2Store.read_body_cache_file','R2Store.keys']
SPEED_KEEP = ['scripts/measure/process_rss.py', 'apps/site/scripts/measure-archive.mjs',
              'apps/site/scripts/archive-targets.mjs','apps/site/scripts/archive-browser.mjs',
              'apps/site/scripts/archive-server.mjs','apps/site/scripts/archive-tools.test.mjs']
HARD_KEEP = [CA+'lake/', CA+'retention/body_store.py', CA+'retention/receipt_writer.py',
    CA+'retention/archive_expander.py', CA+'retention/provenance.py', CA+'retention/raw_verifier.py',
    CA+'retention/derived_files.py', 'packages/congress_shared/src/congress_shared/custody.py',
    RET+'parser_worker.py',RET+'process_resources.py',RET+'concurrency.py',
    CA+'retention/raw_repair.py', CA+'acquisition/fetcher.py', CA+'acquisition/capture_scheduler.py',
    CA+'transport/raw_adapters.py', CA+'parsers/archive_readings.py', CA+'parsers/sniff.py',
    'packages/house-naming/', 'packages/news_lake/', 'apps/committee_youtube/',
    VP+'filename_review_binding.py',VP+'data/document-review-',
    'model/', 'apps/site/src/components/explorer/reader/archive',
    SITE+'cache.ts', SITE+'cooperative.ts',
    'apps/site/src/components/explorer/reader/range-file.ts', *SPEED_KEEP]


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe(path):
    p = PurePosixPath(path)
    return (not p.is_absolute() and '..' not in p.parts
        and bool(p.parts) and p.parts[0] not in ('.cache','.venv','node_modules','target','output','.git')
        and not any(x in p.parts for x in ('.venv','node_modules','.git'))
        and not path.startswith('packages/source-fetch/target/')
        and not any(x.endswith('.env') or 'credentials' in x.lower() or x.lower().endswith('.token') for x in p.parts))


def snapshot(repo, rev):
    """One git tree and one batched blob read; untracked/live data is excluded."""
    head = git(repo, 'rev-parse', rev).decode().strip()
    entries = {}
    for entry in git(repo, 'ls-tree', '-r', '-z', head).split(b'\0'):
        if not entry:
            continue
        metadata, raw_path = entry.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        path = raw_path.decode()
        if kind == 'blob' and mode != '120000' and safe(path):
            entries[path] = oid
    read = {path: oid for path, oid in entries.items()
            if Path(path).suffix in CODE or path.endswith('.md') or
            path.startswith('apps/site/document-review-') or
            path.startswith(VP+'data/document-review-') or
            (path.endswith('.json') and path.startswith(('model/','packages/house-naming/src/','infra/cloudflare/'))) or
            path == 'infra/cloudflare/congressional-data-r2-edge.json'}
    oids = sorted(set(read.values()))
    raw = subprocess.run(['git', '-C', str(repo), 'cat-file', '--batch'],
        input=('\n'.join(oids)+'\n').encode(), stdout=subprocess.PIPE, check=True).stdout
    bodies = {}
    at = 0
    for oid in oids:
        end = raw.index(b'\n', at)
        header = raw[at:end].decode().split()
        size = int(header[2])
        bodies[oid] = raw[end+1:end+1+size]
        at = end+size+2
    return head, entries, {path: bodies[oid] for path, oid in read.items()}


def module_name(path):
    tail = path.split('/src/', 1)[-1] if '/src/' in path else path
    name = tail.removesuffix('.py').replace('/', '.')
    return name.removesuffix('.__init__')


def test_file(path):
    p = PurePosixPath(path)
    return (any(x == 'tests' for x in p.parts) or p.name.startswith('test_')
            or '.test.' in p.name or p.name=='tests.rs' or p.name.endswith('_tests.rs'))


def consumer_role(path):
    """Separate production references from evidence about obsolete subjects."""
    parts=PurePosixPath(path).parts
    if 'fixtures' in parts:return 'fixture'
    if test_file(path):return 'test'
    if path.startswith('scripts/measure/'):return 'measurement'
    if path.startswith('docs/') or path.endswith('.md'):return 'documentation'
    return 'production'


def expression(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = expression(node.value)
        return base+'.'+node.attr if base else '<expression>.'+node.attr


def py_index(path, source):
    symbols, imports, calls, dynamic, strings, exports = [], [], [], [], [], []
    module = module_name(path)
    try:
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return dict(symbols=[], imports=[], calls=[], dynamic=[dict(line=0, kind='parse_unavailable')])
    class BoundNames(ast.NodeVisitor):
        def __init__(self):self.names=set();self.nonlocal_names=set()
        def visit_Name(self,node):
            if isinstance(node.ctx,ast.Store):self.names.add(node.id)
        def visit_Import(self,node):
            self.names.update(x.asname or x.name.split('.')[0] for x in node.names)
        def visit_ImportFrom(self,node):
            self.names.update(x.asname or x.name for x in node.names if x.name!='*')
        def visit_FunctionDef(self,node):self.names.add(node.name)
        visit_AsyncFunctionDef=visit_FunctionDef
        def visit_ClassDef(self,node):self.names.add(node.name)
        def visit_Lambda(self,node):pass
        def visit_Global(self,node):self.nonlocal_names.update(node.names)
        visit_Nonlocal=visit_Global
    def definitions(body,prefix):
        result={}
        class Collect(ast.NodeVisitor):
            def visit_FunctionDef(self,node):result[node.name]=prefix+'.'+node.name
            visit_AsyncFunctionDef=visit_FunctionDef
            def visit_ClassDef(self,node):result[node.name]=prefix+'.'+node.name
            def visit_Lambda(self,node):pass
        collector=Collect()
        for node in body:collector.visit(node)
        return result
    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.scope=[];self.aliases={};self.alias_stack=[('module',self.aliases)]
            self.bound_stack=[];self.definitions=definitions(tree.body,module)
            self.definition_stack=[('module',self.definitions)]
        def definition(self, node):
            name = '.'.join([*self.scope, node.name])
            start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
            symbols.append(dict(name=name, start=start, end=node.end_lineno,
                                kind='class' if isinstance(node, ast.ClassDef) else 'function'))
            outer=self.aliases;outer_definitions=self.definitions
            inherited={};inherited_definitions={}
            # Methods close over enclosing function scopes, never a class
            # namespace. A local import must not mutate the module's bindings.
            for kind,bindings in self.alias_stack:
                if kind!='class':inherited.update(bindings)
            for kind,bindings in self.definition_stack:
                if kind!='class':inherited_definitions.update(bindings)
            bound=set()
            if not isinstance(node,ast.ClassDef):
                binder=BoundNames()
                for statement in node.body:binder.visit(statement)
                bound=binder.names-binder.nonlocal_names
                bound.update(arg.arg for arg in [*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs])
                if node.args.vararg:bound.add(node.args.vararg.arg)
                if node.args.kwarg:bound.add(node.args.kwarg.arg)
                for local in bound:inherited.pop(local,None)
                for local in bound:inherited_definitions.pop(local,None)
                if binder.nonlocal_names:dynamic.append(dict(line=node.lineno,kind='global_or_nonlocal_binding'))
            self.aliases=inherited
            inherited_definitions.update(definitions(node.body,module+'.'+name))
            self.definitions=inherited_definitions
            self.alias_stack.append(('class' if isinstance(node,ast.ClassDef) else 'function',self.aliases))
            self.definition_stack.append(('class' if isinstance(node,ast.ClassDef) else 'function',self.definitions))
            self.bound_stack.append(bound)
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()
            self.bound_stack.pop();self.alias_stack.pop();self.aliases=outer
            self.definition_stack.pop();self.definitions=outer_definitions
        visit_ClassDef = definition
        visit_FunctionDef = definition
        visit_AsyncFunctionDef = definition
        def visit_Import(self, node):
            for item in node.names:
                self.aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
                imports.append(dict(module=item.name, name=None, line=node.lineno))
        def visit_ImportFrom(self, node):
            if node.level:
                base = module.split('.') if path.endswith('__init__.py') else module.split('.')[:-1]
                base = base[:len(base)-node.level+1]
                target = '.'.join([*base, *([node.module] if node.module else [])])
            else:
                target = node.module or ''
            for item in node.names:
                imports.append(dict(module=target, name=item.name, line=node.lineno))
                self.aliases[item.asname or item.name] = target+'.'+item.name
                if item.name == '*':
                    dynamic.append(dict(line=node.lineno, kind='import_star'))
        def visit_Call(self, node):
            name = expression(node.func) or '<expression>'
            if name:
                root, *tail = name.split('.')
                target = '.'.join([self.aliases.get(root, root), *tail])
                if root in self.aliases:resolution='lexical_import_reference'
                elif '.' not in name and root in self.definitions:
                    target=self.definitions[root];resolution='lexical_definition_reference'
                elif any(root in bound for bound in self.bound_stack):
                    target='<unresolved-local>.'+name;resolution='unresolved_local_call_syntax'
                elif '.' in name:
                    target='<unresolved-receiver>.'+name;resolution='unresolved_attribute_call_syntax'
                else:
                    target='<unresolved-name>.'+name;resolution='unresolved_name_call_syntax'
                calls.append(dict(name=name, target=target, line=node.lineno,
                                  scope='.'.join(self.scope) or '<module>',resolution=resolution))
                if resolution.startswith('unresolved_'):
                    dynamic.append(dict(line=node.lineno,kind=resolution,call_syntax=name))
                if root in {'getattr','eval','exec','__import__'} or target.startswith('importlib.'):
                    dynamic.append(dict(line=node.lineno, kind=name))
            self.generic_visit(node)
        def visit_Constant(self, node):
            if isinstance(node.value,str) and ('/' in node.value or '.' in node.value):
                strings.append(dict(value=node.value,line=node.lineno))
        def visit_Assign(self, node):
            if not self.scope:
                for target in node.targets:
                    if isinstance(target,ast.Name) and target.id.isupper():
                        symbols.append(dict(name=target.id,start=node.lineno,end=node.end_lineno,kind='constant_assignment'))
            if any(isinstance(n,ast.Name) and n.id=='__all__' for n in node.targets):
                try:
                    value=ast.literal_eval(node.value)
                    if isinstance(value,(list,tuple)):
                        exports.extend(v for v in value if isinstance(v,str))
                except (ValueError,TypeError):
                    dynamic.append(dict(line=node.lineno,kind='dynamic___all__'))
            self.generic_visit(node)
    Visitor().visit(tree)
    return dict(symbols=symbols, imports=imports, calls=calls, dynamic=dynamic,
                string_literals=strings,exports=sorted(set(exports)))


def other_index(path, source):
    text = source.decode('utf-8', 'replace')
    symbols, refs = [], []
    for line, value in enumerate(text.splitlines(), 1):
        found = re.search(r'\b(?:fn|function|class|interface|enum|struct)\s+([A-Za-z_]\w*)', value)
        if found:
            symbols.append(dict(name=found.group(1), start=line, end=None,
                                kind='declaration_only_manual_range'))
        for match in re.finditer(r'''(?:from\s*|import\s*|require\(|use\s+|mod\s+)["']?([A-Za-z_./:@-][\w./:@-]*)''', value):
            refs.append(dict(module=match.group(1), name=None, line=line,
                syntax='rust_mod' if re.search(r'\bmod\s+'+re.escape(match.group(1)),value)
                    else 'rust_use' if path.endswith('.rs') else 'relative_import'))
    return dict(symbols=symbols, imports=refs, calls=[], dynamic=[],exports=[])


def group(num, name, patterns=(), partial=None, *, repo='ct', gate='F5: switch first; migrate every remaining caller', owner='engine', phase=1):
    return dict(id=f'G{num:02}', binding_row=num, name=name, repo=repo,
        patterns=list(patterns), partial=partial or {}, owner=owner, phase=phase,
        prerequisites=[gate], files=[], ranges=[], unresolved=[])


def seeds():
    inc = ['catalog_'+n for n in 'adoption availability batches dependencies dependency_preparation dependency_storage inputs memberships partitions qualification raw_updates rows scope selection types updates'.split()]
    inc += ['source_'+n for n in 'update_proof capture_inputs inputs observations replay'.split()]
    inc += ['raw_catalog','native_features']
    raw = 'partition_routing raw_schemas raw_values raw_state_map raw_state_routes raw_capture_pages raw_changes raw_readings raw_reading_inventory raw_readings_adoption raw_adoption raw_adoption_inputs capture_metadata native_capacity'.split()
    rebuild = 'catalog_staging catalog_publication catalog_cache catalog_validation document_evidence document_recovery saved_responses source_aliases immutable_metadata derived_files index_selector document_index docspec docspec_host'.split()
    v6 = 'filename_native native filename_native_recoveries filename_renderer_state filename_navigation filename_observations filename_json_stream filename_budget filename_details filename_compression filename_resources filename_alias_index filename_aliases filename_recoveries filename_review_binding publish_filename_viewer filename_test_fixture filename_viewer'.split()
    journal = 'attempt continuation local reconciliation resume plan verify publish_viewer_r2 publication_cli cli release_identity'.split()
    measurement = 'benchmark_catalog_grouping benchmark_core_rebuild benchmark_viewer_publication compare_publication_costs measure_publication_control publication_costs compare_raw_keyed_updates compare_raw_keyed_updates_scale measure_alias_preparation measure_catalog_partition_reuse measure_preparation_decoded measure_preparation_resources probe_corpus_recovery_memory'.split()
    groups = [
        group(1,'Python incremental catalog',[*[RET+n+'.py' for n in inc],RET+'catalog/*.py','scripts/incremental_boundary_proof.py']),
        group(2,'Python rebuild and oracle paths',[*[RET+n+'.py' for n in rebuild],RET+'index/*.py','packages/congress_api/tests/historical_*.py']),
        group(3,'Raw index and legacy merge',[*[RET+n+'.py' for n in raw],RET+'raw_storage.py',RET+'raw_archive.py',RET+'raw/*.py'],partial={
            RET+'r2.py':['R2Store'], DC+'client.py':['NativeDatasets.update_table'],
            DC+'specs.py':['_merge_row_pair','_iter_table_rows','apply_update_merge_spec']},
            gate='F5 plus B9/D1 old-index consumers migrated; B13 copier lifted or phase2 wait; shared client merge waits news_lake/committee explorer'),
        group(4,'Old capture receipt building',[RET+'bundles.py'],partial={RET+'raw_archive.py':['prepare_capture','metadata_body_keys','body_payload','existing_body_info'],
             CA+'transport/http.py':['get_with_retry']},gate='F2 target writers active; inventory transport still used by weekly/explorer remains until B14/migration'),
        group(5,'Raw intake exclusion and removed substitution',partial={
            RET+'raw_storage.py':['ExcludedBodyError','_extract_excluded_digests','load_excluded_body_hashes','enforce_body_ingest_gate','store_public_body'],
            RET+'body_files.py':['retain_body_file'],RET+'body_keys.py':['quarantine_body_key']},
            gate='F5 old live raw writers drained; B11 substitution already removed in 1f45cc50; inspect hooks separately'),
        group(6,'Publication journal, resume and attempt',[*[VP+n+'.py' for n in journal],
            RET+'viewer_inventory.py',RET+'control_documents.py',
            'scripts/publication/prepare_workflow_resume.py','scripts/publication/publication_cli.py',
            'scripts/publication/publish-viewer-r2.py','scripts/publication_preflight.py'],partial={VP+'client.py':['GuardedPublicationClient','ContinuedPublicationClient']},
            gate='F1/E target publish active; preserve namespace firewall and lifted public canary probes'),
        group(7,'V6 preparer and local/legacy site reader',[*[VP+n+'.py' for n in v6],
            'scripts/publication/publish-filename-viewer.py','scripts/publication/filename-test-fixture.py',
            SITE+'catalog-v6.ts',SITE+'observations.ts',SITE+'detail-record.ts',SITE+'recoveries.ts',
            'apps/site/src/components/explorer/reader/range-file.ts'],
            partial={SITE+n+'.ts':['*manual*'] for n in 'catalog bootstrap worker startup session client publication cache cooperative types'.split()},
            gate='Track A target active; split legacy route from repurposed reader shell, retain source evidence'),
        group(8,'Old review publication',[VP+'filename_reviews.py','apps/site/scripts/stage-document-reviews.py',
            'apps/site/document-review-*.json',VP+'data/document-review-*.json',SITE+'reviews.ts'],
            gate='B8 actual 86-record provenance import and qualification; local staging alone is insufficient'),
        group(9,'Old pipeline status',['scripts/publication/pipeline_status.py'],
            gate='F2 decides heartbeat; preserve heartbeat symbols if target still consumes them'),
        group(10,'Archive-only docspec client lines',partial={
            DC+'client.py':['NativeDatasets.read_receipts','NativeDatasets.read_evidence','NativeDatasets.read_occurrences'],
            DC+'specs.py':['facet_summary','_normalize_fold_readings','_normalize_facet_sets',
                '_normalize_child_table_spec','_normalize_child_tables'],
            DC+'models.py':['ConnectedEdgeSpec','AggregateSpec','ConnectedComponentsTransform'],
            DC+'transport.py':['_BLAKE3_IV','_BLAKE3_MSG_PERMUTATION','_BLAKE3_CHUNK_START',
                '_BLAKE3_CHUNK_END','_BLAKE3_PARENT','_BLAKE3_ROOT','_blake3_rotr32','_blake3_g',
                '_blake3_round','_blake3_compress','_blake3_chunk_output','blake3_hex'],
            'packages/docspec_client/tests/test_export_policy.py':['*manual*']},
            gate='Archive-only evidence per symbol; shared update/export/host/runtime remain for news_lake/explorer; pure Python BLAKE3 waits declared blake3 dependency'),
        group(11,'Review forms catalog binding',[RET+'document_review_*.py',RET+'document_reviews.py',RET+'review/*.py'],
            gate='Forms survive; rebind catalog-dependent functions to provenance before deleting ranges'),
        group(12,'Recovery old-catalog coupling',[*[CR+n+'.py' for n in 'guards acknowledge admission assemble mappings publication preservation diagnostics'.split()],
            'scripts/corpus_recovery/dispatch_corpus_recovery_publication.py'],
            partial={CR+'transfer.py':['checked_put','GuardedStore']},
            gate='B7 target recovery/provenance import bound; old shared-index guards no longer own live import'),
        group(13,'Old CLI/replay, ExportPin and compaction',[CA+'replay/*.py',CA+'acquisition/recovery_queue.py',
            CA+'acquisition/retained_import.py',CA+'acquisition/streamed_recovery.py',CA+'acquisition/raw_sync.py',
            CA+'cli/document_index.py',VP+'filename_exports.py',VP+'compact_readings.py',VP+'compact_reviews.py',
            '.github/scripts/verify-capture-run.py'],partial={CA+'cli/raw_sync.py':['add_catalog_modes','operation_mode','adoption_inputs','adopt_catalog','capture_sources','main']},
            gate='F2 scheduler active, B9 checks bound and F0 replacement qualified; weekly seed helper lifted; shared engine ExportPin remains until other consumers migrate'),
        group(14,'Old end-to-end tests',['tests/e2e/**'],
            gate='Move surviving behavior/fixtures before tree cut; baseline failures never weakened'),
        group(15,'Deleted-subject measurement executables',[*['scripts/measure/'+n+'.py' for n in measurement],
            'scripts/measure/viewer_benchmark_server.py','scripts/measure/benchmark_viewer_browser.mjs',
            'scripts/measure/tests/test_viewer_benchmark.py','scripts/measure/tests/test_viewer_benchmark_server.py'],
            gate='Keep committed measurement reports/evidence and speed harness; only obsolete executables/tests go'),
        group(16,'One-time conversion/copy/receipt tools',[VP+'archive_release.py',VP+'archive_seed.py',VP+'backfill_uncompressed_pdfs.py',
            'scripts/publication/backfill-uncompressed-pdfs.py',RET+'pdf_backfill.py',CA+'cli/receipt_cleanup.py',
            RET+'receipt_cleanup.py',RET+'receipt_cleanup_stores.py'],
            partial={RET+'raw_storage.py':['migrate_pdf_bodies_to_uncompressed']},
            gate='F0 waits E4/switch qualification; B0 waits actual rewrite/final scan/lock; PDF copier waits actual phase2 B13',phase='1_or_2_by_tool'),
        group(17,'Origin planner/simulator/WAF allowlist',['scripts/publication/apply-r2-edge-rules.py'],partial={
            RET+'r2_edge_rules.py':['evaluate_waf_request'],
            VP+'apply_r2_edge_rules.py':['build_cloudflare_plan','apply_cloudflare_plan','verify_live_edge','main']},
            gate='Partial WAF/planner split only; CORS/cache/CSP/filename Content-Disposition and configuration remain'),
        group(18,'Disabled viewer workflow and cron',['.github/workflows/publish-filename-viewer.yml'],
            gate='Site F1 deletion commit or switch approval; do not remove weekly update job before B14'),
    ]
    replacements={
        1:[CA+'lake/tables.py',CA+'lake/daily.py'],
        2:['model/sql/',VP+'archive_model.py'],
        3:[CA+'lake/captures.py',CA+'lake/tables.py'],
        4:[CA+'acquisition/fetcher.py',RET+'receipt_writer.py'],
        5:[RET+'body_store.py'],
        6:[VP+'archive_controller.py',VP+'archive_publish.py'],
        7:['apps/site/src/components/explorer/reader/archive.ts',VP+'archive_model.py'],
        8:[VP+'review_provenance.py',VP+'filename_review_binding.py'],
        9:[CA+'acquisition/capture_scheduler.py'],
        10:[DC+'client.py:NativeDatasets.run_job'],
        11:[VP+'review_provenance.py'],
        12:[RET+'provenance.py',CA+'cli/provenance.py'],
        13:[CA+'cli/capture_schedule.py',RET+'raw_verifier.py'],
        14:['packages/congress_api/tests/test_captures_ingest.py','packages/viewer_publication/tests/test_archive_controller.py'],
        15:['apps/site/scripts/measure-archive.mjs'],
        16:[VP+'archive_model.py'],
        17:['infra/cloudflare/congressional-data-r2-edge.json'],
        18:['.github/workflows/archive-jobs.yml','.github/workflows/capture-archive.yml'],
    }
    for item in groups:
        item['replacement_paths']=replacements[item['binding_row']]
        item['replacement_gate']='Named replacement must be live and every production caller migrated before the cut'
    return groups


def merged_ranges(ranges):
    result=[]
    for start,end in sorted(ranges):
        if result and start<=result[-1][1]+1:
            result[-1][1]=max(result[-1][1],end)
        else:
            result.append([start,end])
    return result


def historical_mixed(ct, current_paths):
    """Reconstruct the review's module-level retention split at its named head."""
    rev='d9730967'
    try:
        head,entries,bodies=snapshot(ct,rev)
    except subprocess.CalledProcessError:
        return dict(status='historical_commit_unavailable',source_commit=rev,files=[])
    old_modules={module_name(p) for p in entries if p.startswith(RET) and p.endswith('.py')}
    rows=seeds()
    patterns=[pattern for number in (1,2,3,6) for pattern in rows[number-1]['patterns']]
    replaced={module_name(p) for p in entries if p.startswith(RET) and p.endswith('.py')
              and any(fnmatch.fnmatch(p,pattern) for pattern in patterns)}
    kept=old_modules-replaced
    files=[]
    for path,body in bodies.items():
        if not path.endswith('.py') or not test_file(path):continue
        index=py_index(path,body);modules=set()
        for ref in index['imports']:
            child=ref['module']+'.'+ref['name'] if ref['name'] else None
            modules.add(child if child in old_modules else ref['module'])
        gone=sorted(modules & replaced);stay=sorted(modules & kept)
        if gone and stay:
            files.append(dict(path=path,sha256=digest(body),wc_l=body.count(b'\n'),
                replaced_modules=gone,retained_modules=stay,
                current_path_status='present' if path in current_paths else 'missing_needs_move_or_deletion_evidence'))
    return dict(status='reconstructed_from_named_commit',source_commit=head,
        expected_historical_files=27,expected_historical_wc_l=5948,
        observed_files=len(files),observed_wc_l=sum(x['wc_l'] for x in files),files=files,
        method='Review RX/IC/RB/SH/VW module sets; keep RW/PDF/WK/REV/EDGE. Symbol-level keeps require current review.')


def build(ct, ds, ct_rev, ds_rev):
    repos={}
    for name,root,rev in [('ct',ct,ct_rev)]:
        head,entries,bodies=snapshot(root,rev)
        indexes={p:(py_index(p,b) if p.endswith('.py') else other_index(p,b))
                 for p,b in bodies.items() if Path(p).suffix in CODE}
        repos[name]=dict(root=str(root),head=head,entries=entries,bodies=bodies,indexes=indexes)
    # Test runners often expose a helper directory directly on sys.path. Resolve
    # an unqualified module only when its tracked basename is unique; ambiguous
    # names stay unresolved instead of guessing a consumer.
    for repo,data in repos.items():
        known={module_name(p) for p in data['indexes'] if p.endswith('.py')}
        short=defaultdict(list)
        for module in known:short[module.rsplit('.',1)[-1]].append(module)
        def canonical(name):
            if name in known:return name
            first,*tail=name.split('.')
            if len(short.get(first,[]))==1:
                return '.'.join([short[first][0],*tail])
            return name
        for path,index in data['indexes'].items():
            if not path.endswith('.py'):continue
            for ref in index['imports']:
                authored=ref['module'];ref['module']=canonical(authored)
                if ref['module']!=authored:ref['authored_module']=authored
            for call in index['calls']:call['target']=canonical(call['target'])
    groups=seeds(); files={}; module_paths={}; references=defaultdict(list); attributes=defaultdict(list)
    for repo,data in repos.items():
        for path,index in data['indexes'].items():
            if path.endswith('.py'):
                module_paths[(repo,module_name(path))]=path
            for ref in index['imports']:
                references[(repo,ref['module'])].append(dict(path=path,line=ref['line'],
                    kind='import',name=ref['name']))
                if ref['name'] and ref['name']!='*':
                    references[(repo,ref['module']+'.'+ref['name'])].append(dict(path=path,line=ref['line'],
                        kind='from_import',name=ref['name']))
            for call in index['calls']:
                if call.get('resolution') in {'lexical_import_reference','lexical_definition_reference'}:
                    references[(repo,call['target'])].append(dict(path=path,line=call['line'],
                        kind=call['resolution'],scope=call['scope']))
                if '.' in call['name']:
                    attributes[(repo,call['name'].rsplit('.',1)[-1])].append(dict(
                        path=path,line=call['line'],kind='attribute_name_candidate_receiver_unresolved',
                        scope=call['scope']))
    def add_file(repo,path,gid,action):
        key=repo+':'+path
        data=repos[repo]
        if key not in files:
            body=data['bodies'].get(path)
            if body is None:
                # Selected JSON files were loaded; a missing non-code tracked
                # candidate is read explicitly from its safe named git blob.
                if path in data['entries'] and safe(path):
                    body=git(Path(data['root']),'show',data['head']+':'+path)
                else:
                    return None
            index=data['indexes'].get(path,dict(symbols=[],imports=[],calls=[],dynamic=[]))
            callers=list(references.get((repo,module_name(path)),[])) if path.endswith('.py') else []
            for caller in callers:caller['consumer_role']=consumer_role(caller['path'])
            symbols=[]
            for sym in index['symbols']:
                s=dict(sym)
                s['callers']=references.get((repo,module_name(path)+'.'+sym['name']),[])
                for caller in s['callers']:caller['consumer_role']=consumer_role(caller['path'])
                s['production_callers']=[c for c in s['callers'] if c['consumer_role']=='production']
                if '.' in sym['name'] and sym['name'].rsplit('.',1)[-1] not in {
                        '__init__','__enter__','__exit__','get','put','read','write','close','keys'}:
                    name=sym['name'].rsplit('.',1)[-1]
                    if attributes.get((repo,name)):
                        s['possible_attribute_callers_ref']=repo+':'+name
                symbols.append(s)
            files[key]=dict(repo=repo,path=path,status='present',sha256=digest(body),bytes=len(body),
                wc_l=body.count(b'\n'),unterminated_final_line=bool(body and not body.endswith(b'\n')),
                groups=[],actions=[],symbols=symbols,imports=index['imports'],
                static_callers=callers,dynamic_uncertainty=index['dynamic'],exports=index.get('exports',[]),
                consumer_role=consumer_role(path),
                production_callers=[c for c in callers if c['consumer_role']=='production'],
                evidence_limits=['Static references do not prove runtime absence.'],
                category='test' if test_file(path) else 'documentation' if path.endswith('.md') else
                    'data_or_config' if path.endswith(('.json','.toml','.yaml','.yml')) else 'source')
        f=files[key]
        if gid not in f['groups']:f['groups'].append(gid)
        if action not in f['actions']:f['actions'].append(action)
        return key
    for g in groups:
        data=repos[g['repo']]
        g['already_removed']=[]
        for pattern in g['patterns']:
            found=[p for p in data['entries'] if fnmatch.fnmatch(p,pattern)]
            if not found:
                spec=':(glob)'+pattern if any(c in pattern for c in '*?[') else pattern
                lines=git(Path(data['root']),'log','-1','--format=%H','--name-only','--diff-filter=D',
                          data['head'],'--',spec).decode().splitlines()
                deletion=lines[0].strip() if lines else ''
                removed=[p.strip() for p in lines[1:] if p.strip()]
                if deletion and removed:
                    for p in removed:
                        old=git(Path(data['root']),'show',deletion+'^:'+p)
                        g['already_removed'].append(dict(path=p,status='already_removed',
                            deletion_commit=deletion,before_sha256=digest(old),before_wc_l=old.count(b'\n')))
                else:
                    g['unresolved'].append(dict(seed=pattern,status='not_found_at_pin',
                        action='Resolve move/deletion evidence before cut; missing is not deletion proof.'))
            for path in found:
                key=add_file(g['repo'],path,g['id'],'candidate_whole_file_after_gates')
                if key:g['files'].append(key)
        for path,names in g['partial'].items():
            key=add_file(g['repo'],path,g['id'],'partial_split_required')
            if key is None:
                deletion=git(Path(data['root']),'log','-1','--format=%H','--diff-filter=D',
                             data['head'],'--',path).decode().strip()
                if deletion:
                    old=git(Path(data['root']),'show',deletion+'^:'+path)
                    g['already_removed'].append(dict(path=path,status='already_removed',
                        deletion_commit=deletion,before_sha256=digest(old),before_wc_l=old.count(b'\n')))
                else:
                    g['unresolved'].append(dict(seed=path,status='not_found_at_pin'))
                continue
            if key not in g['files']:g['files'].append(key)
            available=files[key]['symbols']
            for name in names:
                found=[s for s in available if s['name']==name]
                if name=='*manual*' or not found:
                    g['ranges'].append(dict(file=key,symbol=name,status='manual_range_required',
                        reason='Shared branch or non-Python declaration; no broad deletion authorized.'))
                for symbol in found:
                    split_only=(path in {VP+'apply_r2_edge_rules.py',RET+'r2.py',
                        DC+'client.py',DC+'models.py'} or path.startswith(RET+'document_review'))
                    split_only=split_only or path==DC+'transport.py' and name=='blake3_hex'
                    g['ranges'].append(dict(file=key,symbol=name,start=symbol['start'],end=symbol['end'],
                        status='manual_branch_split_required' if split_only else
                            'resolved_python_ast' if symbol['end'] is not None else 'manual_end_required',
                        range_meaning='inspection boundary; preserve behavior inside it' if split_only else 'candidate symbol removal after gates'))
        g['files']=sorted(set(g['files']))
        del g['patterns'];del g['partial']

    # Literal dynamic imports used by old measurement tests are potential
    # callers too. Keep ambiguous basenames out of this resolution.
    python_paths={p for p in repos['ct']['entries'] if p.endswith('.py')}
    basenames=defaultdict(list)
    for path in python_paths:basenames[PurePosixPath(path).name].append(path)
    for path,index in repos['ct']['indexes'].items():
        deps=[]
        for literal_ref in index.get('string_literals',[]):
            value=literal_ref['value'];target=None
            if value in python_paths:target=value
            elif len(value)<300 and not any(x in value for x in ('\n','{','}')):
                name=PurePosixPath(value).name
                if len(basenames.get(name,[]))==1:target=basenames[name][0]
            if target:
                deps.append(module_name(target))
                key='ct:'+target
                if key in files and target!=path:
                    files[key]['static_callers'].append(dict(path=path,line=literal_ref['line'],
                        kind='literal_dynamic_import_candidate'))
        index['literal_dependency_modules']=sorted(set(deps))

    candidate_modules={module_name(f['path']):f['groups'] for f in files.values()
        if f['repo']=='ct' and f['path'].endswith('.py') and not test_file(f['path'])}
    retention_removed={m for m in candidate_modules if m.startswith('congress_api.retention.')}
    retention_kept={m for (repo,m),p in module_paths.items() if repo=='ct'
        and m.startswith('congress_api.retention.') and m not in retention_removed}
    mixed=[]; historical_reconstructed=[]; nonproduction=[]
    for path,index in repos['ct']['indexes'].items():
        role=consumer_role(path)
        if role not in {'test','fixture','measurement'}:continue
        modules=set()
        for ref in index['imports']:
            child=ref['module']+'.'+ref['name'] if ref['name'] else None
            if child and ('ct',child) in module_paths:modules.add(child)
            else:modules.add(ref['module'])
        modules.update(index.get('literal_dependency_modules',[]))
        removed=sorted(m for m in modules if m in candidate_modules)
        if not removed:continue
        retained=sorted(m for m in modules if ('ct',m) in module_paths and m not in candidate_modules)
        gids=sorted({g for m in removed for g in candidate_modules[m]})
        action='mixed_subject_split_required' if retained else 'remove_with_obsolete_subject'
        for gid in gids:
            key=add_file('ct',path,gid,action)
            if key and key not in next(g for g in groups if g['id']==gid)['files']:
                next(g for g in groups if g['id']==gid)['files'].append(key)
        nonproduction.append(dict(file='ct:'+path,consumer_role=role,
            removed_modules=removed,retained_modules=retained,action=action))
        if role!='test':continue
        if retained:
            mixed.append(dict(file='ct:'+path,removed_modules=removed,retained_modules=retained,
                test_symbols=[s for s in index['symbols'] if s['name'].split('.')[-1].startswith('test')],
                action='Split by surviving behavior; file-level import classification is only a preparation signal.'))
        r=sorted(modules & retention_removed);k=sorted(modules & retention_kept)
        if r and k:historical_reconstructed.append(dict(path=path,removed_retention_modules=r,kept_retention_modules=k))

    # Runtime references in workflow/shell/JS and pyproject console scripts use
    # literal module/path tokens. They are identified as textual, not a resolved call.
    needles=defaultdict(set)
    for key,f in files.items():
        path=f['path']
        needles[path].add(key)
        if path.endswith('.py'):needles[module_name(path)].add(key)
        if Path(path).suffix in {'.ts','.tsx','.js','.mjs'}:
            needles['./'+PurePosixPath(path).stem].add(key)
    token=re.compile(r"[A-Za-z_./][A-Za-z0-9_./-]+")
    for repo,data in repos.items():
        for path,body in data['bodies'].items():
            if Path(path).suffix not in CODE or path.endswith('.py'):continue
            for ref in data['indexes'][path]['imports']:
                target=ref['module']; candidates=[]
                if ref.get('syntax')=='rust_mod':
                    p=PurePosixPath(path)
                    base=p.parent if p.stem in {'lib','main','mod'} else p.parent/p.stem
                    candidates=[str(base/target)+'.rs',str(base/target/'mod.rs')]
                elif ref.get('syntax')=='rust_use' and target.startswith('crate::'):
                    stem='src/'+target.removeprefix('crate::').replace('::','/')
                    candidates=[stem+'.rs',stem+'/mod.rs']
                elif target.startswith('.'):
                    stem=posixpath.normpath(str(PurePosixPath(path).parent/target))
                    candidates=[stem+s for s in ('','.ts','.tsx','.js','.mjs','/index.ts')]
                for candidate in candidates:
                    key=repo+':'+candidate
                    if key in files and candidate!=path:
                        files[key]['static_callers'].append(dict(path=path,line=ref['line'],
                            kind='resolved_literal_module_declaration_or_import'))
            for lineno,line in enumerate(body.decode('utf-8','replace').splitlines(),1):
                hits={key for word in token.findall(line) for key in needles.get(word,set()) if key.startswith(repo+':')}
                for key in hits:
                    f=files[key]
                    if f['path']!=path:
                        f['static_callers'].append(dict(path=path,line=lineno,kind='literal_runtime_or_import_reference'))
    # JS/shell/dynamic test callers need explicit case review too. They are not
    # silently absent from the split list merely because Python AST cannot trace
    # their runtime imports.
    registered_mixed={x['file'] for x in mixed}
    for key,f in list(files.items()):
        for caller in f['static_callers']:
            path=caller['path']
            if f['repo']!='ct' or not test_file(path) or path.endswith('.py'):continue
            test_key='ct:'+path
            for gid in f['groups']:
                if not gid.startswith('G'):continue
                added=add_file('ct',path,gid,'non_python_test_case_split_review')
                if added:
                    next(g for g in groups if g['id']==gid)['files'].append(added)
            if test_key not in registered_mixed:
                registered_mixed.add(test_key)
                mixed.append(dict(file=test_key,removed_modules=[],retained_modules=[],test_symbols=[],
                    action='Non-Python runtime caller: classify old and surviving cases before deleting any test.'))
    for key,f in files.items():
        f['consumer_role']=consumer_role(f['path'])
        for caller in f['static_callers']:
            caller['consumer_role']=consumer_role(caller['path'])
            caller_key=f['repo']+':'+caller['path']
            caller['inventory_groups']=files.get(caller_key,{}).get('groups',[])
            caller['caller_boundary']='outside_candidate_inventory' if caller_key not in files else 'listed_candidate_or_split'
            if f['repo']=='ct' and any(caller['path']==p or caller['path'].startswith(p) for p in HARD_KEEP):
                caller['caller_boundary']='surviving_target_or_parked_consumer'
        f['static_callers']=sorted(f['static_callers'],key=lambda x:(x['path'],x['line'],x['kind']))
        f['production_callers']=[c for c in f['static_callers'] if c['consumer_role']=='production']
        for symbol in f['symbols']:
            for caller in symbol['callers']:caller['consumer_role']=consumer_role(caller['path'])
            symbol['production_callers']=[c for c in symbol['callers'] if c['consumer_role']=='production']
        f['groups']=sorted(f['groups']);f['primary_accounting_group']=f['groups'][0]
        f['hard_keep_boundary']=f['repo']=='ct' and any(f['path']==p or f['path'].startswith(p) for p in HARD_KEEP)
        if f['hard_keep_boundary']:
            f['actions']=['preserve_target_or_parked_consumer']
        if f['path']==RET+'r2.py':
            f['preserve_symbols']=['put_parameters','verify_upload','AsyncBodies','R2Store.put_file',
                *RAW_READER_KEEP]
            f['preserve_globals']=['LOGGER','_read_locks','_read_locks_guard']
            f['evidence_limits'].append('R2Store class is a split boundary, not a whole-class deletion range.')
        if f['path']==VP+'apply_r2_edge_rules.py' or f['path']==RET+'r2_edge_rules.py':
            f['preserve_behavior']=['CORS','immutable/no-store cache','sandbox CSP','Content-Disposition filename safety']
        if f['path'].startswith(DC):
            f['preserve_behavior']=['NativeDatasets.run_job/runtime pinning','news_lake lifecycle/update','committee explorer ExportPin/update']
        if f['path']==DC+'transport.py':
            f['preserve_symbols']=['blake3_hex public API and maintained-library branch',
                'encode_arrow_ipc_stream','_write_producer_parquet','producer_input_entry']
            f['fallback_cut_gate']='Maintained blake3 declared and locked before deleting only the Python fallback.'
        if f['path']==VP+'client.py':
            f['preserve_symbols']=list(PUBLICATION_CLIENT_KEEP)
            f['preserve_imports']=list(PUBLICATION_CLIENT_KEEP_IMPORTS)
        if f['path']==RET+'raw_storage.py':
            f['preserve_until_lifted']=['migrate_pdf_bodies_to_uncompressed (B13 actual phase2 job)']
        if f['path'].startswith(RET+'document_review') or f['path'].startswith(RET+'review/'):
            f['actions']=['partial_catalog_binding_split_forms_survive']
        if f['path']=='scripts/publication/pipeline_status.py':
            f['preserve_until_decided']=['heartbeat if target capture retains it']
        if f['path']==SITE+'cache.ts':
            f['preserve_symbols']=['byteCache','retainedBytes','awaitShared','sharedLoad']
        if f['path']==SITE+'cooperative.ts':
            f['preserve_symbols']=['scanBatchRows','yieldToMessages']
        if f['path']==SITE+'client.ts':
            f['preserve_symbols']=['CatalogWorker','createWorkerClient']
            f['cut_symbols_after_gate']=['createFilenameClient','publicationLifecycle']
            f['split_gate']='Migrate every old filename session caller before cutting only legacy helpers.'
        if f['path']==SITE+'startup.ts':
            f['preserve_symbols']=['withVerifiedBytes']
            f['preserve_behavior']=['caller cancellation','startup deadline','byte digest verification']
            f['preserve_until_lifted']=['withVerifiedJson until legacy review readers migrate after B8 import']
            f['cut_symbols_after_gate']=['canonicalJson after old v6 and recovery consumers migrate']
        if f['path']=='apps/site/src/components/explorer/reader/range-file.ts':
            f['preserve_symbols']=['rangeFile (entire shared module)']
            f['evidence_limits'].append('catalog-v6.ts re-exports this shared module; deleting the re-export never authorizes deleting range-file.ts.')
    # Explicit rewrite and speed keep inventories are accounted separately.
    rewrites=[]
    for p in ['apps/site/FILENAME-VIEWER.md','.github/workflows/raw-source-tables.md']:
        key=add_file('ct',p,'REWRITE','rewrite_at_switch')
        if key:rewrites.append(key)
    keeps=[]
    for p in SPEED_KEEP:
        key=add_file('ct',p,'KEEP','preserve_speed_harness')
        if key:keeps.append(key)
    for key in [*rewrites,*keeps]:
        f=files[key];f['primary_accounting_group']=f['groups'][0];f['hard_keep_boundary']=key in keeps
    for g in groups:
        g['files']=sorted(set(g['files']))
        g['population_wc_l_unique_primary']=sum(files[k]['wc_l'] for k in g['files']
            if files[k]['primary_accounting_group']==g['id'])
        rs=defaultdict(list)
        for r in g['ranges']:
            if r.get('end') is not None:rs[r['file']].append((r['start'],r['end']))
        g['partial_range_union_wc_l']={k:sum(end-start+1-int(files[k]['unterminated_final_line']
            and end==files[k]['wc_l']+1) for start,end in merged_ranges(v)) for k,v in rs.items()}
    boundary_notes=[dict(subject='B11 input substitution',status='already_removed',commit='1f45cc50',
        path=RET+'raw_storage.py',evidence='45-line test-only substitution removed; surviving exclusion definitions remain until switch.'),
        dict(subject='Dormant v6 workflow',status='pinned_presence_recorded',
             evidence='If site F1 deletion is merged later, regenerate and attach its actual deletion commit.'),
        dict(subject='Historical mixed tests',status='reconstructed_from_review_named_commit_below',
             baseline_files=27,baseline_wc_l=5948,
             evidence='Original scripts/JSON were scratch-only; reconstruct the module split at the review source commit, compare its exact count and retain current drift separately.'),
        dict(subject='Site reader split',status='site_owner_keep_boundaries_recorded',
             evidence='New archive readers retain cache/cooperative/range-file modules and worker/verified-byte helpers. Old Explorer, Listing, Evidence, RecordDetail and browse callers still require their legacy files until the switch.'),
        dict(subject='Legacy ID fixture',status='remove_obsolete_oracle_cases_with_subject',
             path='packages/congress_api/tests/test_id_golden_vectors.py',
             evidence='Tests are not production users. Remove old-only oracle imports/cases with the obsolete module; keep checks of the live model.')]
    verify_docs={'docs/plans/bindings-20261025.md','apps/site/FILENAME-VIEWER.md',
                 '.github/workflows/raw-source-tables.md'}
    scans={repo:{p:digest(b) for p,b in data['bodies'].items()
            if Path(p).suffix in CODE or p.endswith('.json') or p in verify_docs}
           for repo,data in repos.items()}
    historical=historical_mixed(ct,repos['ct']['entries'])
    current_mixed_paths={r['path'] for r in historical_reconstructed}
    for row in historical['files']:
        row['current_retention_import_classification']='mixed' if row['path'] in current_mixed_paths else 'reclassify_from_current_symbols_and_imports'
    attribute_refs={s['possible_attribute_callers_ref'] for f in files.values() for s in f['symbols']
                    if 'possible_attribute_callers_ref' in s}
    inventory=dict(version=3,scope='CT-only F5 preparation: duplicate or superseded code only; no deletion authorization',
        source_commits={r:d['head'] for r,d in repos.items()},
        binding_sha256=digest(repos['ct']['bodies']['docs/plans/bindings-20261025.md']),
        generator_sha256=digest(Path(__file__).read_bytes()),
        groups=groups,files={k:files[k] for k in sorted(files)},mixed_tests=sorted(mixed,key=lambda x:x['file']),
        nonproduction_dependents=sorted(nonproduction,key=lambda x:x['file']),
        production_import_graph={p:index['imports'] for p,index in repos['ct']['indexes'].items()
            if consumer_role(p)=='production'},
        deferred_external_audits=[dict(repo='ds',
            source_commit=git(ds,'rev-parse',ds_rev).decode().strip() if ds is not None else None,
            status='outside strip scope; separate future audit across every external consumer')],
        possible_attribute_callers={key:attributes[tuple(key.split(':',1))] for key in sorted(attribute_refs)},
        current_retention_mixed_tests=sorted(historical_reconstructed,key=lambda x:x['path']),
        historical_mixed_tests=historical,
        rewrite_documents=rewrites,preserved_speed_tools=keeps,boundary_notes=boundary_notes,
        external_consumers=[dict(name=n,status='WAIT/MIGRATE') for n in ('news_lake','committee_explorer')],
        totals=dict(unique_files=len(files),wc_l_population=sum(f['wc_l'] for f in files.values()),
            by_category={category:sum(f['wc_l'] for f in files.values() if f['category']==category)
                for category in sorted({f['category'] for f in files.values()})},
            mixed_test_files=len(mixed),retention_mixed_test_files=len(historical_reconstructed)),
        scanned_source_hashes=scans,
        cut_procedure=['Regenerate at the final committed CT head; refuse stale scanned-source hashes.',
            'Name each removed file/function replacement and verify that production replacement is live.',
            'Resolve manual ranges and production callers, workflows and external-consumer references before applying that group.',
            'Prepare one deletion commit per group; remove obsolete-subject tests/fixtures/measurements with it, retain kept-subject cases and partial-file keeps.',
            'Measure wc -l before/after at cut; run affected surviving consumer project lanes.',
            'Do not delete any raw object, provenance, credential, report or active worktree.'])
    assert len(groups)==18 and {g['binding_row'] for g in groups}==set(range(1,19))
    for g in groups:
        assert g['files'] or g['unresolved'] or g['already_removed']
        for r in g['ranges']:
            if r.get('end') is not None:
                assert 1<=r['start']<=r['end']<=files[r['file']]['wc_l']+1
    assert sum(g['population_wc_l_unique_primary'] for g in groups) + sum(files[k]['wc_l'] for k in [*rewrites,*keeps]
        if files[k]['primary_accounting_group'] in {'REWRITE','KEEP'}) == inventory['totals']['wc_l_population']
    return inventory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ct',type=Path,required=True)
    parser.add_argument('--ds',type=Path,help='Optional deferred external-audit source pin; never scanned or stripped')
    parser.add_argument('--ct-head',default='HEAD')
    parser.add_argument('--ds-head',default='HEAD')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--verify',type=Path)
    args=parser.parse_args()
    if args.verify:
        old=json.loads(args.verify.read_text())
        if old.get('version')!=3:parser.error('Regenerate the CT-only version3 inventory before verification')
        changes={};uncommitted={}
        for name,root in [('ct',args.ct)]:
            _,_,bodies=snapshot(root,'HEAD')
            verify_docs={'docs/plans/bindings-20261025.md','apps/site/FILENAME-VIEWER.md',
                         '.github/workflows/raw-source-tables.md'}
            now={p:digest(b) for p,b in bodies.items()
                 if Path(p).suffix in CODE or p.endswith('.json') or p in verify_docs}
            before=old['scanned_source_hashes'][name]
            changes[name]=sorted(p for p in set(now)|set(before) if now.get(p)!=before.get(p))
            tracked=sorted(set(now)|set(before))
            dirty=git(root,'diff','--name-only','-z','HEAD','--',*tracked).decode().split('\0')
            extra=git(root,'ls-files','--others','--exclude-standard','-z').decode().split('\0')
            extra=[p for p in extra if safe(p) and (Path(p).suffix in CODE or
                (p.endswith('.json') and p.startswith(('model/','packages/house-naming/src/','infra/cloudflare/'))))]
            uncommitted[name]=sorted({p for p in [*dirty,*extra] if p})
        generator_changed=old['generator_sha256']!=digest(Path(__file__).read_bytes())
        stale=any(changes.values()) or any(uncommitted.values()) or generator_changed
        print(json.dumps(dict(stale=stale,changed_source_paths=changes,
            uncommitted_source_paths=uncommitted,generator_changed=generator_changed),indent=2))
        raise SystemExit(2 if stale else 0)
    if args.out is None:parser.error('--out or --verify is required')
    result=build(args.ct,args.ds,args.ct_head,args.ds_head)
    with args.out.open('x') as out:
        json.dump(result,out,indent=2,ensure_ascii=False,sort_keys=True)
        out.write('\n')
    print(json.dumps(dict(source_commits=result['source_commits'],totals=result['totals'],
        group_count=len(result['groups']),sha256=digest(args.out.read_bytes())) ,sort_keys=True))


if __name__=='__main__':main()
