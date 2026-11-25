-- Replay append-only org_decisions provenance: drop withdrawn and superseded rows,
-- resolve witness_key subjects through witness_key_map, and take the latest decision
-- per (subject, object) by decided_at instant then id (ct-6him).
WITH remaining AS (
 SELECT d.id,d.subject,d.verdict,d.object,d.note,d.reviewer,d.decided_at,d.supersedes
 FROM org_decisions d
 WHERE d.verdict<>'withdraw'
  AND NOT EXISTS (SELECT 1 FROM org_decisions s WHERE s.supersedes=d.id)
), parsed AS (
 SELECT r.*,
  CASE
   WHEN r.subject LIKE 'bag:%' THEN 'bag'
   WHEN r.subject LIKE 'witness:%' THEN 'witness'
   ELSE 'bare'
  END AS explicit_kind,
  CASE
   WHEN r.subject LIKE 'bag:%' THEN substr(r.subject,5)
   WHEN r.subject LIKE 'witness:%' THEN substr(r.subject,9)
   ELSE r.subject
  END AS raw_subject_key,
  CASE
   WHEN r.object LIKE 'org:%' THEN 'org'
   WHEN r.object LIKE 'bag:%' THEN 'bag'
   WHEN r.object LIKE 'wikidata:%' THEN 'wikidata'
  END AS object_kind,
  CASE
   WHEN r.object LIKE 'org:%' THEN substr(r.object,5)
   WHEN r.object LIKE 'bag:%' THEN substr(r.object,5)
   WHEN r.object LIKE 'wikidata:%' THEN substr(r.object,10)
  END AS object_key
 FROM remaining r
), resolved_subject AS (
 SELECT p.*,
  CASE
   WHEN p.explicit_kind='bag' THEN 'bag'
   WHEN p.explicit_kind='witness' THEN 'witness'
   WHEN bg.bag_key IS NOT NULL THEN 'bag'
   WHEN lw.witness_key IS NOT NULL OR wkm.old_key IS NOT NULL THEN 'witness'
   ELSE 'bag'
  END AS subject_kind,
  CASE
   WHEN p.explicit_kind='bag' OR (p.explicit_kind='bare' AND bg.bag_key IS NOT NULL) THEN p.raw_subject_key
   WHEN p.explicit_kind='witness' OR (p.explicit_kind='bare' AND (lw.witness_key IS NOT NULL OR wkm.old_key IS NOT NULL)) THEN
    CASE
     WHEN lw.witness_key IS NOT NULL THEN p.raw_subject_key
     WHEN wkm.status='unambiguous' THEN wkm.witness_key
     ELSE cast(NULL AS VARCHAR)
    END
   ELSE p.raw_subject_key
  END AS subject_key,
  CASE
   WHEN p.explicit_kind='bag' OR (p.explicit_kind='bare' AND bg.bag_key IS NOT NULL) THEN
    CASE WHEN bg.bag_key IS NOT NULL THEN 'live' ELSE 'missing' END
   WHEN p.explicit_kind='witness' OR (p.explicit_kind='bare' AND (lw.witness_key IS NOT NULL OR wkm.old_key IS NOT NULL)) THEN
    CASE
     WHEN lw.witness_key IS NOT NULL THEN 'live'
     WHEN wkm.status='unambiguous' THEN 'remapped'
     ELSE coalesce(wkm.status,'missing')
    END
   ELSE 'missing'
  END AS resolution_status
 FROM parsed p
 LEFT JOIN (SELECT DISTINCT bag_key FROM org_strings) bg ON bg.bag_key=p.raw_subject_key
 LEFT JOIN (SELECT DISTINCT witness_key FROM org_witness_mentions) lw ON lw.witness_key=p.raw_subject_key
 LEFT JOIN witness_key_map wkm ON wkm.old_key=p.raw_subject_key
), keyed AS (
 SELECT
  id,subject,verdict,object,note,reviewer,decided_at,supersedes,
  subject_kind,subject_key,resolution_status,object_kind,object_key,
  CASE
   WHEN subject_key IS NULL THEN cast(NULL AS VARCHAR)
   WHEN subject_kind='bag' THEN 'b:'||subject_key
   ELSE 'w:'||subject_key
  END AS subject_node,
  CASE object_kind
   WHEN 'bag' THEN 'b:'||object_key
   WHEN 'wikidata' THEN 'wd:'||object_key
   ELSE 'o:'||object_key
  END AS object_node
 FROM resolved_subject
), ranked AS (
 SELECT k.*,
  row_number() OVER (
   PARTITION BY CASE
    WHEN k.subject_kind='bag' AND k.object_kind='bag' AND k.subject_node IS NOT NULL
     THEN least(k.subject_node,k.object_node)||'|'||greatest(k.subject_node,k.object_node)
    ELSE coalesce(k.subject_node,k.subject)||'|'||k.object_node
   END
   ORDER BY cast(k.decided_at AS TIMESTAMP WITH TIME ZONE) DESC,k.id DESC
  ) AS selected
 FROM keyed k
)
SELECT
 id,subject,verdict,object,note,reviewer,decided_at,supersedes,
 subject_kind,subject_key,resolution_status,subject_node,
 object_kind,object_key,object_node
FROM ranked
WHERE selected=1
