-- Common first-name pairs shared across appearance_people, witness_member_names, and person_given_matches.
-- One-way from nickname to formal name (Bob -> Robert, never Barbara -> Robert).
SELECT nick, formal FROM (VALUES
 ('bob','robert'),('bobby','robert'),('rob','robert'),('bill','william'),('billy','william'),
 ('will','william'),('dick','richard'),('rick','richard'),('rich','richard'),('ted','edward'),
 ('ned','edward'),('ed','edward'),('eddie','edward'),('liz','elizabeth'),('beth','elizabeth'),
 ('betsy','elizabeth'),('betty','elizabeth'),('libby','elizabeth'),('peggy','margaret'),('maggie','margaret'),
 ('meg','margaret'),('jim','james'),('jimmy','james'),('mike','michael'),('tom','thomas'),
 ('tommy','thomas'),('chuck','charles'),('jack','john'),('hank','henry'),('joe','joseph'),
 ('tony','anthony'),('larry','lawrence'),('harry','harold'),('jerry','gerald'),('sandy','sandra'),
 ('kathy','katherine'),('lou','luis')
) AS t(nick, formal)
