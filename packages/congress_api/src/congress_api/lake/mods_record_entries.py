"""Reviewed GovInfo MODS contents entries that do not establish witness attendance.

Each entry binds a package and one-based witness locator to the SHA-256
of the stripped original line. A supplied name is the person named in
the entry; several names are Members who asked questions for the record
jointly, each given a row, the second at `<locator>/part[2]`, the third at
`/part[3]` and so on. The optional third value says how the entry reads:
"record_material", a reviewed paper rather than a member's own statement;
"title", a document title, record_material with no name that keeps the
line's `organization` reading; "askers", a line the rules still read,
whose named Members asked questions the rules do not see, each appended as
a record_material row at the line's next part. The original MODS retains
the full text.

Reviewed 2026-11-09 (ct-3aap, ct-zs48), all `record_material`: sixteen
document titles a line prints alone or after their publisher ("Association of
American Railroads, "AAR Calls for ..."", "Report of the National Surface
Transportation ... Commission"); four dot-leader leftovers of a witness's
prepared-statement entry ("Prepared Statement of ........ 300,", "Prepared
statement..........213,"), kept as typed rows rather than dropped; and CHRG-114hhrg94806's Andre Carson and Peter A.
DeFazio after Sarah Feinberg's testimony, the askers of the print's other
question-for-the-record headings, listed here without one; and CHRG-115shrg25981's
Patty Murray, an asker whose page numbers run into the next heading. Review r3
adds the Senate Veterans' Affairs askers printed after a witness's entry as
"Hon. Jon Tester......22,32 Hon. Roland W. Burris" and CHRG-113shrg80510's
"Response to request arising during the hearing by: Hon. Richard Burr". A shape
rule would mistype the real witnesses printed the same way ("Hon. Condoleeza
Rice, Secretary ... ........285,"), so these are reviewed one by one.

Owner decisions 2026-11-10: a question line that names several Members who
asked names each (Tester with Burris, Begich and, twice, Moran; Brown with
Manchin), CHRG-115shrg24586's heading "Response to posthearing questions
submitted by: Hon. Jon Tester......49,55 Hon. Jerry Moran" among them (ct-gfo7
item 2: it had published the heading as a name); and the sixteen document
titles keep their text in `organization`, as before they were typed. A survey
of all 35,020 MODS originals found the rest of that kind; the regular ones
("Senators Boxer and Carper", "Senator Boxer Senator Inhofe", two paged askers
on one line) are read by the question rule, and these are reviewed:
CHRG-115shrg33409's four lists of Senators printed after witnesses with no
heading; Patty Murray's line, which runs into the heading naming Bill Cassidy;
CHRG-116shrg40570's and CHRG-112shrg86775's headings naming three askers, which
had published as a witness's name; CHRG-115hhrg25242's heading naming Frank A.
LoBiondo, who submitted questions on behalf of Paul Mitchell (both shown); and
two lines whose witness keeps its row while the askers printed before it are
appended (CHRG-106shrg66382's Inhofe and Smith before Jeff Sessions, and
CHRG-107shrg83717's Jeffords and Leahy before Hilton Kelley). Members print by
surname alone in a list of Senators, so their rows name them so.
"""

from typing import Literal

Names = str | tuple[str, ...] | None
RecordEntry = tuple[str, Names] | tuple[str, Names, Literal["record_material", "title", "askers"]]

MODS_RECORD_ENTRIES: dict[str, dict[int, RecordEntry]] = {
    'CHRG-106hhrg55613': {
        3: ('41d409bf6240374a4ac65994590e3e72b3f2fc3e907830c977986df22a2439b3', None),
    },
    'CHRG-106hhrg61647': {
        13: ('c17628f0ef744175d03d1b03a533cf2d18f9ceecfe652cd1b7b50a39edb03dd2', 'Frank Strauss'),
        14: ('1b7db93ea69d40fadef8c8d8e55ea2de8565f16e6375801daf6b67fc7870748c', 'Robert Klein'),
        15: ('12bc6cac3c63105717e2b7140c3becc3ebd112e60a17169de294df0870864416', 'Mark Golden'),
        16: ('1a4562cf20bbfd3f3ce052e67848c433dd1adbffbbe33905459b0f564b053a9d', 'Sandra Skommesa'),
        17: ('a6deaf5423aec61a4c723ca02218a937302fe71a30cdb4074e5c4c06b1c4aaf7', 'Ann Brown'),
        18: ('38b8ed10818943c62a497104e5e19401cfe6e7f3a33f7c325746a2f8e1f723a9', 'Ed Weil'),
        19: ('20ca781a91e180b3123a6dee36d71a0e064db8201ff00c860723b0da45986cde', 'Shawn Khorrami'),
        20: ('8a6324aca0999446c294d64a468fc310cc0a19c6ababf4dd2c80d91cd99da198', 'Jeffrey Margulies'),
    },
    'CHRG-106hhrg63607': {
        4: ('9ccfcfe28f239ea62967ea4d9b3450c0162d85e9eea659a33a36a6938c943cda', None),
    },
    'CHRG-106hhrg65695': {
        13: ('7a5d09ce1541c4ee63b44be281273293b584eeab6612ba6189948b8f089a4c78', None),
        16: ('72836c101ac0ed8e2eaaf1dcba70c3f2a1ed352f67d22d697650ed96ccb8b94a', None),
        17: ('bbb0f0a5cf06ec5b499ef04488970891fdf9ba8378ca11bea818edf305cecb75', 'E. Ratcliffe Anderson, Jr.'),
        18: ('d5098a2141e2a01783603383a96078670a629a170676f5553e893e5af4df9edc', None),
        21: ('864ae008abb5894d9a05c820d7e11197f3def7742bce46847d7077ca1c46ab25', 'Lloyd H. Harrison'),
    },
    'CHRG-106shrg59382': {
        20: ('a1cfe3e56a0d13ebf4c066338214a1407f2d24c4bc59724c24dceb99841c556a', None),
    },
    'CHRG-106shrg66376': {
        17: ('f7efd85d4cb7c2c8af6fa2546a6108b12485e5095d6576ea14f6213cf7b1eb9b', 'Smith'),
        25: ('c0072a5d03d490de0212885e9a7eae2aed5758dd3ad2ec35f94c9b7d5cd3a694', 'Ella Wong-Ruskinko'),
    },
    'CHRG-106shrg66381': {
        26: ('cea4b6c24e32e60b55b1ece9c3dedeb722bb1aaf5f5dbe7b877dae6f8de7441c', None, 'record_material'),
    },
    'CHRG-106shrg66382': {
        9: ('499f7fc61f653266fffc75a29ad9f2e7152b61349a073a3674adfce6b3296d50', ('Inhofe', 'Smith'), 'askers'),
    },
    'CHRG-106shrg73821': {
        19: ('ebaac7aca5d25b82c2825243fae3db6c93986b3ddd8d716b328752cfca9f4965', 'Paul Warner'),
    },
    'CHRG-106shrg77325': {
        6: ('7e3ca7ad6086d701b7bb3d5eade7cad2ecdfa7bcfdb195abfa9fa4dd48cf57f0', None, 'title'),
    },
    'CHRG-106shrg85219': {
        7: ('2513ed90ad15dfc46574afa7cf2ac5df0da7aa8cfec47d5662fd2c24effa211d', 'Rodney E. Slater'),
    },
    'CHRG-107hhrg81751': {
        9: ('7b39d497f1893ae5120d5285d3d6f2b6be50cbf7f7b1d4ff22a5576b11e73ede', 'David G. Schulke'),
    },
    'CHRG-107shrg80650': {
        5: ('79a4b63181e073d547a1063017a268534f271d8b9a5a074ea800b76417d7d788', None),
    },
    'CHRG-107shrg80654': {
        7: ('58101642e7d76b41315f08cd8b40aeabfbb10aee3753203a567863a244b3d1d2', None),
    },
    'CHRG-107shrg81998': {
        54: ('bc351fa25e56f86ec14035855236f8ed9ba89904faa2bf551d3b7a702b3da97e', None),
        60: ('c44bfe6afdadc9ca62c866a3c0ca8c63945d2c43eae1fefab6ce882a35026ab3', None),
        67: ('32dd1a0e518dd307fe04544082d9cdd3a99d55adc43c8e84ded687be71adac0d', None),
        70: ('3a544f38efb872d807f096594072df80e00f2d669962809107fb42f2d0d4bec0', 'William F. Schulz'),
    },
    'CHRG-107shrg83683': {
        9: ('108a1c684d41b19e49af0be82d559020c163cd343e1405dc77c28f50a7d3a372', None),
    },
    'CHRG-107shrg83717': {
        6: ('3a5967378feb74a175675af24f37841c92f5c3ba419671463340f1a51051e283', ('Jeffords', 'Leahy'), 'askers'),
        25: ('814b704f2cb2de804fa8df804a5349917a8b7a8e94921ee7da087bf69a68ddf1', None),
    },
    'CHRG-107shrg89642': {
        6: ('2b5d381c972b0ca1e4d0ac59d564fb69c22e9b05dda1724e77042fb6b57f0e4a', None, 'title'),
    },
    'CHRG-108hhrg85516': {
        7: ('6f789ff04f11030b8049da40d2fc520add885e9e14cd3a45782deae79d25c983', 'Charles G. Groat'),
        8: ('7d7f75199d43467d4cfafd02f07149635d819d669db154f30ca8cb51d4ad8d44', 'Wayne W. Carmichael'),
        9: ('26870e2072591a5667c8f9777798d7a9fb0a0cebcdef7ec857361645d200123d', 'Donald M. Anderson'),
        10: ('c6602ffa0eb35432b256b5be7b5af937993bb93bb3ebf518c0d5fb66032b076e', 'Dan L. Ayres'),
    },
    'CHRG-108hhrg86341': {
        9: ('ced9cade110329384dff4a83fd159dee9f645c9c3974e08ae425cfd084c14bce', 'Eric E. Harm'),
        10: ('e3d43cbf1721e420ddfd6aefda5ec0e75750cdd490831b512b60106ad19246dc', 'C. Michael Walton'),
        11: ('4a9c71909bc9823e506bf2a77b70d6a6208c589b4ab3515e7b3df232fff750c7', 'Katherine Siggerud'),
        12: ('562e048ee9217fdf3092fb91f387f91a25ab53189ccb0f3eb1d80af336a16f3e', 'Anne P. Canby'),
        13: ('27dcf42c5b0da5cf5377567a52b241bf4acab4f4f2a8cb1f682b48402bb12f2c', 'Michael D. Meyer'),
    },
    'CHRG-108hhrg87544': {
        7: ('64d693aa6434a46dacdc1b7c0f77a8875098771bb56b217a0996193c6ccfadad', 'Lawrence J. Rhoades'),
        8: ('fe2fcb70b7bda17d7c080362494f55a8dc15a31e9e3aefcd39c2a21213d6a06f', 'Herman M. Reininga'),
        9: ('db971c1ddf6b61932d046c763391f8181a3ce95ff6a412d2144b8f48e766831d', 'Jay R. Dunwell'),
        10: ('e67d62fb5f918dcbeb3b22daac765ff5e1be6715e0c434804a43a300c52fca4a', 'Jason Farmer'),
    },
    'CHRG-108shrg21190': {
        8: ('5564c8357b4c519547adc04f40e9b40f4a9371707e1cf4a902ae3db25626cc11', 'Thomas H. Collins'),
    },
    'CHRG-108shrg92386': {
        5: ('8640edf1613251e943547430c3773c0be33e32882611283dd85dacff8ccb0338', None, 'title'),
    },
    'CHRG-108shrg94598': {
        7: ('dbd748985d0fcd74d6e11445001b958bc07fcf265d0af4943d1ed13259dcce99', None),
    },
    'CHRG-109hhrg28454': {
        5: ('b0f16ef3d5d901ed7d56964368ab28f1859827ec0c9e632dae843553ecec4fe0', 'Robert Brandewie'),
    },
    'CHRG-109hhrg29565': {
        3: ('c6d37563b7cbd3caafc255f118db8e98f49144163c788018dc12d16f2f36d6aa', None),
    },
    'CHRG-109shrg22551': {
        6: ('7cc18dca3203d43571e8a86c1ad95ac3d5a5026b19677799104b944af389ca20', None, 'title'),
    },
    'CHRG-109shrg37444': {
        4: ('c1524a77161b644431ace94a70b538fa9d0c40fc6a4d8ed3ec67d5688b29e0e6', None),
    },
    'CHRG-109shrg64524': {
        5: ('f0b7986368f76ece266e0248d0dfa6f68cf847ce7cfb6ae77bb5522c67cfb061', 'Adam M. Eisgrau'),
    },
    'CHRG-109shrg71844': {
        3: ('55ba33366f6d9e5c46ee2b3dd883741808ace614490ac9ce19f24050eb0530af', None),
        4: ('b9016b23be58efb805777bbb235870fa6577d45a10acfd42346cd2d430068fa2', None),
        5: ('34aa179a2b989faacd42aa4be3387e6b4fb4260d84bcccdd302762e1abc96faf', None),
        6: ('277caf33ade8836b1ce4726b5eadd346b59648eb2aeeb509d42d4aad70cc1f05', None),
    },
    'CHRG-110hhrg34496': {
        7: ('fdb3beb838def3b05c9f13794d072dfae02eec17265c92f7da67408fd3c2e2d3', None),
        9: ('41e34f41aa4dee054e806d49e5f51578449d426db3d2147fb29b1c86b842ed03', None),
    },
    'CHRG-110hhrg37692': {
        13: ('bd71dddcc5ede4f648cad67c2660b713ffd2ca08b0c7548864617e81d05e1e2b', None),
    },
    'CHRG-110hhrg42334': {
        9: ('6054c7ce244ae5fbd199754c5a941b12f13533ec952bf16e6907972a68366eed', None),
    },
    'CHRG-110hhrg44215': {
        9: ('1224a1e659455fbe570bc28fe8402db41c27fe0c835c2a52f5c299bf03b834b7', None, 'title'),
    },
    'CHRG-110hhrg48907': {
        6: ('6b05415a0e4e51476747192b34eb62bb9fad325fd83deb0241c1e8fa1971a34e', None),
    },
    'CHRG-110shrg52887': {
        16: ('f80dbd0215387353a0cbe56d5a0a2188dbbb8f516768a5ffe397c5922b60293b', None, 'title'),
    },
    'CHRG-110shrg55921': {
        3: ('096a8068427b1be79a410cb58a0dfe43efa578e83926680de43eac481a2701c5', None, 'record_material'),
    },
    'CHRG-110shrg72249': {
        3: ('7c2220cc4188d8761e8589358e2f07ff002770932cf3b7cf1763fc34a0a3f0e5', None),
        4: ('9b11d7028569abb53a5533baea7c74f081e748ab509e5cc2577032a8b6209c04', None),
        5: ('9cc5c24997a2a77f7cabaed32cf96f1890058996863b9d824bf7ae6db9c5f9f6', None),
        6: ('4fdb62c03417c7b9aa1cb431f92a925333137426bb724b7117e0eee0d14fab9d', None),
        7: ('dcef65b733889722d90faa0791ba3f0e7e878fbbe3c5340682c03982bd0d86ba', None),
    },
    'CHRG-110shrg75776': {
        25: ('ff7b4d327132dbb18d1e1a12b1b6c269f9b91f28a499ebdbf0e266d3eed4aec3', 'Robert V. Smith'),
    },
    'CHRG-110shrg77232': {
        7: ('951344cef708cee0794a42749eebb5eb5c6df1fa08fbce8ac60891847ef28ce7', None),
    },
    'CHRG-111hhrg51877': {
        4: ('2ec288ab84138197e9a29004a67311addcf1a8c603c19f28daf4d36a27203642', 'Kortney Clemons'),
    },
    'CHRG-111hhrg55850': {
        5: ('9d260641607123e8c5849e5a3c064ea902aa9c9b0e812ba6fd2571fb79c5f8cc', None, 'title'),
        6: ('881eeda28c54c73b0f5712ca2c8137c31761d04c968a6d91220c8c89579bd89a', None, 'title'),
    },
    'CHRG-111shrg47763': {
        2: ('2c5b4414728a6d4f6fb5adff87f632062c8b41e063dbeb87a71d23db0fc9ad72',
            ('Jon Tester', 'Roland W. Burris'), 'record_material'),
    },
    'CHRG-111shrg51121': {
        2: ('00684bf42d469b94d532bcad2b8bcf79f7cda200e59446812425f43a7a68a851', 'Mark Begich', 'record_material'),
    },
    'CHRG-111shrg52162': {
        6: ('b6f369b7d66aa2d51eb6a5e49bd96bff3a65750646955c6f923a9ca4a55daf2d', None),
        7: ('7af23ea39cb80a0ad43508d37094d76e15d76a8e3c2a1c689cb2248f6e1f5f66', None),
    },
    'CHRG-111shrg64440': {
        2: ('af274e4c95a5953397994ade14d576f6d96bb530cadc5bc307ded06d76bc8e90',
            ('Jon Tester', 'Mark Begich'), 'record_material'),
    },
    'CHRG-111shrg68174': {
        3: ('fb6b185d9dd5a8e6e94849c1097a41b5ebb1cb0d6cafb26872d00487bbde84b5', 'Glenn F. Tilton'),
    },
    'CHRG-112hhrg64533': {
        2: ('6c3b8d2f59ddee276dce5387eae92ba0d76cb937febd0697b2f960db0954b2a8', None, 'title'),
        3: ('449c937bbd076a17ea44359ca1a9998d8f09bd3add563a0f49fa9fe4a0125021', None, 'title'),
        5: ('c7e315dd2ba93cb317d4385401363d47910263e53ebc7db7dcaa3009b5bc25ed', None),
    },
    'CHRG-112hhrg68336': {
        2: ('81b348c4e8e2bcd85d4ad1951484b8a2112948477874c71b9a27b48e12a96109', None),
        15: ('0022e0935d7db8e7c4a2704e5ae72d0302b4a14ca1960bd2b3b75ca4413864ed', None),
        24: ('fc6e158ea53f2020b569eb9c172fc0a416e630ac062e5f2845f5139f32b41ea1', None),
    },
    'CHRG-112hhrg73287': {
        6: ('0107bdea1d4c4a9838cd18c1d8cc0b47d11df810d74bf7e6edd260c2f8624f58', None),
    },
    'CHRG-112hhrg74178': {
        9: ('691410178eef230a8cdc2f04592cea990cc3be8cb0338bb25a043e6765b62851', None),
    },
    'CHRG-112hhrg75611': {
        5: ('577c3cf1ff8d6e7fab24c611c6f59fe72082b77f25c48c9f4cb279e9bb9cf23c', None),
        6: ('c8046b3b664feb938c880a6d138c10fb437e7142eed16a9637830f866321da9e', None),
    },
    'CHRG-112hhrg78765': {
        8: ('d4dea91d5cbcfa9ade7fe762b664207dbf2e94a977f7b7561890d1e26b69da72', 'Robert A. Petzel'),
    },
    'CHRG-112hhrg78768': {
        2: ('67b60d3699af86d1751b93ac9f8cc97544135fc9239255c1fa18d792bccf9c0f', None),
    },
    'CHRG-112hhrg78772': {
        3: ('b8139cdbc2334beb266b049fa7e810e2a8af9fe0afe490d6d8a94d03194cdd51', None),
        4: ('7d72f6e9e1c08759c641cb575814bf8a7530a3c14719d1ad863e94058d8f14b0', None),
    },
    'CHRG-112hhrg82216': {
        15: ('a5d7355a8f5538d2113e4c19e822d4a7cb5381b066f8892448b77310bc1f7d6d', None),
    },
    'CHRG-112jhrg71179': {
        8: ('9d7a754bdfe0d10426617de592fe8de5f531c3e8318070fe78057122e6b430a8', 'Jeb Hensarling'),
    },
    'CHRG-112jhrg73772': {
        5: ('6b741a67c55d9a2e336a1c3b963fe7b141ec0e441825d7bc4b74144892e2213b', None),
    },
    'CHRG-112jhrg85228': {
        8: ('819d3e27deb6ca377c9f5848bacc7ec49fe760b6f42fee0f6e63dd60c261b5a2', None, 'title'),
        10: ('23b6e24c5ba9841d3e8135fde1154decda6286caca11e02fc86ea78f46f50124', None, 'title'),
        23: ('1312032ad8acaf6dfd00fbc1f9782bd75ef58f8bd68bc2f514ad59421c80c53b', 'Anne Mayer'),
    },
    'CHRG-112shrg86775': {
        8: ('17bcc7af0f77ed9daa3f507d2c8c4c24e1499690f97f949ac8a498c5fe9519a5',
            ('Al Franken', 'Richard Blumenthal', 'Tom Coburn'), 'record_material'),
    },
    'CHRG-112shrg85223': {
        3: ('ff46dbe866a34997363eaa52347aa28ca494cd507170d7a58cc5197ab2c77498', None),
    },
    'CHRG-112shrg85232': {
        3: ('494ecd9f0cb7c1aead06b9e9ca313960d54639847a80a024f220de164198316d', None, 'title'),
    },
    'CHRG-113hhrg80816': {
        3: ('edf183d0e07b2af67fbca21af752392b9c31677d872ac8017224fc65aae35faa', None, 'title'),
    },
    'CHRG-113hhrg82220': {
        3: ('501432a9c33fd15c6d553b9ba54273156c85520ef94d76972ebac92ae604901f', 'Matthew Stepp'),
    },
    'CHRG-113hhrg85864': {
        8: ('03f7320549006086d3fb3f5a3233c973b806f84cc5adcb97407dde54dd7e948c', None),
    },
    'CHRG-113hhrg85873': {
        3: ('4fd06d69bf55f21f303ab5b6107242645b76a6cc51d55d04962a5df45d104d70', None),
    },
    'CHRG-113shrg80510': {
        2: ('e52b150a51bb82a540b35281c2602cd446b8c6935253a44fe4fe9dbf96ae6cef', 'Richard Burr', 'record_material'),
        3: ('c46b121a566b47fb460da5f924708b67933dd1d27b5b5e5a94cd0553fe48956c', 'Jerry Moran', 'record_material'),
    },
    'CHRG-113shrg88369': {
        6: ('f7075fa4ada87f99df81cd42c428812b9c20d751e065970ab8341c6a845f8170', None),
    },
    'CHRG-114hhrg93069': {
        4: ('3882d9b193f6a097144d68149e66a539a0191b22a792eb390a1cd7796c44d743', None, 'title'),
    },
    'CHRG-114hhrg94806': {
        9: ('8b3705e13bcd877c7e0c670cfe5a19774e60b11ea7d0057a8e05698c3aa16b16', 'Andre Carson', 'record_material'),
        10: ('a415850d34c059d4e7f51fef85e1208c853889097d8d58f223e384a53be6dc3f', 'Peter A. DeFazio', 'record_material'),
    },
    'CHRG-114hhrg96269': {
        2: ('682824679f8f0f5ed8cd774cd88282f11a846d6907605a8bf403d78e7d6843ae', 'Alexis Taylor'),
        13: ('ffb76f9cca6a2d1aee4acf3250ca5034edeef6d7e44940b5c08d7206e300833c', 'Edward M Avalos'),
    },
    'CHRG-114hhrg98359': {
        22: ('afb2f393f470baee8c43bcee90c9991b5d3508300bd8130a4f0c51bf975ec206', 'Peter Weber'),
    },
    'CHRG-114hhrg99585': {
        6: ('26f346a7e954733d826682511825a711cea166262c5b36a67686fee397cb06c5', 'Robert Bonnie'),
        9: ('682824679f8f0f5ed8cd774cd88282f11a846d6907605a8bf403d78e7d6843ae', 'Alexis Taylor'),
        13: ('ffb76f9cca6a2d1aee4acf3250ca5034edeef6d7e44940b5c08d7206e300833c', 'Edward M Avalos'),
    },
    'CHRG-114hhrg99853': {
        35: ('7696891183014b4cc8059d06b1b5b478d5d9e1f6850d5d024e19853e264b2136', 'Jim Costa'),
    },
    'CHRG-114shrg94274': {
        2: ('c9938097cc6447df2cdfac661cf536bdc95f4b470de9722f5220ee39a0f01e9e', 'Eugene Dodaro'),
    },
    'CHRG-114shrg97368': {
        4: ('d646f835d493085e5bd7b0a1b3cd09b1c125c71cbd5962f5a7b915565525e12e', None, 'title'),
    },
    'CHRG-115hhrg25242': {
        2: ('8e8e80c14aa8efd74682837c08390a1a726ec44c3336510f2e87475c28072f2c',
            ('Frank A. LoBiondo', 'Paul Mitchell'), 'record_material'),
    },
    'CHRG-115shrg24586': {
        3: ('86b0b2cc099e95d14eb67ec0994781b2c05b1e9faec057845fabe8de77afcc1a',
            ('Jon Tester', 'Jerry Moran'), 'record_material'),
        4: ('d93140033571f046aedaf33c589111bb2aa6016d29d781ce53f036a240ba7bab',
            ('Jon Tester', 'Jerry Moran'), 'record_material'),
    },
    'CHRG-115shrg25981': {
        4: ('527e535a4f89ea672523fe5972f4897408d7082e36d7727c62c394050db4adfc',
            ('Patty Murray', 'Bill Cassidy'), 'record_material'),
    },
    'CHRG-115shrg26915': {
        5: ('b27836ef058075b90e1a1d9efefd7f3d5e648f4da0bcb6be94aff16b2eedbd72', None, 'record_material'),
    },
    'CHRG-115shrg33409': {
        2: ('542b1a37b2d7a93472e2f427774f5b98a4db212bef3af1f3254d5f1bc85f9d07', ('Warner', 'Cotton', 'Tillis', 'Jones')),
        4: ('542b1a37b2d7a93472e2f427774f5b98a4db212bef3af1f3254d5f1bc85f9d07', ('Warner', 'Cotton', 'Tillis', 'Jones')),
        6: ('542b1a37b2d7a93472e2f427774f5b98a4db212bef3af1f3254d5f1bc85f9d07', ('Warner', 'Cotton', 'Tillis', 'Jones')),
        8: ('542b1a37b2d7a93472e2f427774f5b98a4db212bef3af1f3254d5f1bc85f9d07', ('Warner', 'Cotton', 'Tillis', 'Jones')),
    },
    'CHRG-115shrg34881': {
        5: ('c030adbf8f01de81a247dbfbec67727e0e3c657186f65c7733ea6a4488880316',
            ('Sherrod Brown', 'Joe Manchin III'), 'record_material'),
    },
    'CHRG-115shrg57804': {
        6: ('b84f0982a08e4207738d802d274b2556ca23cf908c7d9a513c10e25bb465ef77', None),
    },
    'CHRG-116hhrg44091': {
        10: ('f81ee95c12cf35889542143e57008238f6cf04a93b39f48a28ca8592d2276977', 'David Cicilline', 'record_material'),
        11: ('1e2c28c1352c50c9ced760ead7e4fa278362445391db9cabedd0fbadf28c07c7', 'David Cicilline', 'record_material'),
        12: ('f4f441fa3bba03c5e8e5c2e84486a7865bbb775e54ae0082b3fc5c8dbc82c5f6', 'David Cicilline', 'record_material'),
        13: ('da87589782b6dafb128c6ec0ebd6a3a3220220cd6679112e7810760cd0ebb99e', 'David Cicilline', 'record_material'),
    },
    'CHRG-116shrg39734': {
        4: ('6abeb975664b585397deb125ca9ce09dfcf0c227737d91d9270c589e3a885c0a', None, 'record_material'),
    },
    'CHRG-116shrg40570': {
        2: ('43001738c8e1513e19740b17d61c393c67c9aff18540922c200e063f43a51b01',
            ('Patty Murray', 'Jon Tester', 'Jerry Moran'), 'record_material'),
    },
    'CHRG-117hhrg49906': {
        73: ('90fad09498efeba8e1f7def4b216fe40478737e6790fff0f055b18d4763fa13a', 'Glenn Thompson'),
    },
    'CHRG-118hhrg53922': {
        15: ('c954bacf7fd3c1693b6ac1f429e74381dc43426a921ebcd69e8d6b326e842204', None),
        16: ('774ebc969f6ceb94be35717b1b7e19d5bc7f819ee24887b42160b8284dc7452b', None),
    },
    'CHRG-119hhrg60291': {
        9: ('375bdc6921b733f41b2ba4f7bf5f645e3dc125ed6115b5f5d68342db0af015d8', None),
    },
    'CHRG-119shrg64122': {
        11: ('9d9ab24fc2f867396fb3373455e84d8cf840ef6e1e91169dc5b1284ea596fcd2', 'Charlton Allen'),
    },
}

# The print's contents and oral proceedings both name Jim Bresson separately.
# The MODS line joins his roster entry to Robert Brandewie's prepared statement.
# https://www.govinfo.gov/content/pkg/CHRG-109hhrg28454/pdf/CHRG-109hhrg28454.pdf
MODS_MIXED_RECORD_ENTRIES = frozenset({("CHRG-109hhrg28454", 5)})
