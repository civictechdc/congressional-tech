-- ct-kw85: the first names witness_member_candidates compares, read once for both sides. Per Member: each word of
-- the family name (name_last: 'Bono Mack') with each first name (name_first, a nickname it holds in parentheses, the
-- members data's name_nickname). Per eligible witness row with a family name (witness_member_facts): that family name
-- with each first name. A common name is also read in its formal form (Bob and Robert: the members data holds a
-- nickname for 273 Members only), and a Member's abbreviated first name ('Wm.') as its letters in order, from the
-- first. The common-name pairs repeat appearance-people.sql's, which feeds precedence and stays untouched here.
-- Its own step: both arms of the candidate comparison read each side.
WITH nicknames(nick,formal) AS (VALUES ('bob','robert'),('bobby','robert'),('rob','robert'),('bill','william'),('billy','william'),
 ('will','william'),('dick','richard'),('rick','richard'),('rich','richard'),('ted','edward'),('ned','edward'),('ed','edward'),
 ('eddie','edward'),('liz','elizabeth'),('beth','elizabeth'),('betsy','elizabeth'),('betty','elizabeth'),('libby','elizabeth'),
 ('peggy','margaret'),('maggie','margaret'),('meg','margaret'),('jim','james'),('jimmy','james'),('mike','michael'),('tom','thomas'),
 ('tommy','thomas'),('chuck','charles'),('jack','john'),('hank','henry'),('joe','joseph'),('tony','anthony'),('larry','lawrence'),
 ('harry','harold'),('jerry','gerald'),('sandy','sandra'),('kathy','katherine')
), given AS (
 SELECT 'witness' AS side,id,family,unnest(givens) AS given,false AS abbreviated
 FROM witness_member_facts WHERE eligible AND family IS NOT NULL
 UNION ALL
 SELECT 'member' AS side,f.id,f.family,g.given,g.abbreviated
 FROM (SELECT id,unnest(toks) AS family FROM witness_member_facts WHERE side='member' AND part='family') f
  JOIN (SELECT id,unnest(toks) AS given,abbreviated FROM witness_member_facts WHERE side='member' AND part='given') g ON g.id=f.id
)
SELECT g.side,g.id,g.family,g.given,coalesce(k.formal,g.given) AS canon,
 -- 'Wm.' -> ^w[a-z]*m[a-z]*$
 CASE WHEN g.abbreviated THEN '^'||substr(g.given,1,1)||'[a-z]*'||substr(g.given,2,1)||'[a-z]*'||substr(g.given,3,1)||'[a-z]*'
  ||substr(g.given,4,1)||'[a-z]*$' END AS abbreviation
FROM nicknames k RIGHT JOIN given g ON k.nick=g.given
