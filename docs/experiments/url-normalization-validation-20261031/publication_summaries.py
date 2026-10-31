from common import *
c=connect();members=PUB/'model/evidence/source_members.parquet'
dump('alias-membership-results.json',rows(c,f"""SELECT s.target_url,s.candidate_url,s.body_sha256,
count(DISTINCT m.document_id) AS published_document_memberships,
list(DISTINCT m.document_id) FILTER(WHERE m.document_id IS NOT NULL) AS document_ids
FROM selected s LEFT JOIN '{members}' m ON regexp_extract(m.body_key,'/([0-9a-f]{{64}})',1)=s.body_sha256
WHERE s.candidate_source='stored_url_key_alias' GROUP BY s.target_url,s.candidate_url,s.body_sha256"""))
dump('publication-link-impact.json',rows(c,f"""SELECT l.target_url,l.source_id,l.context_url,n.baseline_key,n.proposed_key,
count(DISTINCT m.document_id) AS published_target_documents FROM links l JOIN normalized n ON l.target_url=n.url
LEFT JOIN '{members}' m USING(source_id) WHERE n.baseline_key IS DISTINCT FROM n.proposed_key GROUP BY ALL"""))
dump('lookup-different-documents.json',rows(c,"""SELECT DISTINCT l.kind,l.original,l.list_row expected,u.list_row actual,
a.title expected_title,a.format expected_format,lower(hex(a.saved_body)) expected_body,
b.title actual_title,b.format actual_format,lower(hex(b.saved_body)) actual_body
FROM lookup_results l JOIN urls u ON l.lookup_key=lower(hex(u.lookup_key))
JOIN docs a ON a.list_row=l.list_row JOIN docs b ON b.list_row=u.list_row
WHERE l.kind!='exact' AND u.list_row!=l.list_row
AND NOT EXISTS(SELECT 1 FROM urls x WHERE lower(hex(x.lookup_key))=l.lookup_key AND x.list_row=l.list_row)"""))
dump('lookup-summary.json',rows(c,"""SELECT kind,count(*) source_rows,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM urls u WHERE lower(hex(u.lookup_key))=l.lookup_key AND u.list_row=l.list_row)) same_document_found,
count(*) FILTER(WHERE NOT EXISTS(SELECT 1 FROM urls u WHERE lower(hex(u.lookup_key))=l.lookup_key)) no_document_found
FROM lookup_results l GROUP BY kind ORDER BY kind"""))
sha='f984b8439d21b0ef80f8a6f2e16f1dfc20d1ff57a53afe3f65ceefca67b551ee'
r={'body_sha256':sha,'documents':rows(c,'SELECT document_id,list_row,title,format FROM docs WHERE lower(hex(saved_body))=?',[sha]),
'source_rows':rows(c,'SELECT s.* FROM sources s JOIN docs d USING(list_row) WHERE lower(hex(d.saved_body))=?',[sha]),
'selected_targets':rows(c,'SELECT * FROM selected WHERE body_sha256=?',[sha]),
'visual_check':'Rendered retained first page confirms H. R. 4755, 118th Congress. No text-extraction ambiguity.',
'official_bill_sources':[
 {'bill':'118-HR-4755','title':'Privacy Enhancing Technology Research Act','url':'https://www.govinfo.gov/content/pkg/BILLS-118hr4755ih/html/BILLS-118hr4755ih.htm'},
 {'bill':'118-HR-4824','title':'Carbon Sequestration Collaboration Act','url':'https://www.govinfo.gov/content/pkg/BILLS-118hr4824ih/html/BILLS-118hr4824ih.htm'},
 {'bill':'118-HR-4775','title':'Helping Tobacco Users Quit Act','url':'https://www.govinfo.gov/content/pkg/BILLS-118hr4775ih/html/BILLS-118hr4775ih.htm'}]}
dump('bill-mismatch-publication.json',r)
