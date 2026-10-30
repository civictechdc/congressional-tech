import congressMetadata from '../../../data/congress_metadata.json' with { type: 'json' };

const standingCommittees: Record<string, string> = {
  hhah00: "House Ad Hoc Committee on Energy",
  hlcn00: "House Select Climate Crisis",
  hlef00: "House Select Economic Disparity",
  hlgw00: "House Select Energy Independence & Global Warming",
  hlhk00: "House Select Response to Hurricane Katrina",
  hlie00: "House Select Investigative Panel",
  hlig00: "House Intelligence",
  hlij00: "House Select January 6th Attack",
  hlmh00: "House Select Modernization of Congress",
  hlrk00: "House Select U.S. National Security & Concerns with China",
  hlzi00: "House Select Benghazi",
  hlzs00: "House Select Strategic Competition with the CCP",
  hotl00: "Tom Lantos Human Rights Commission",
  hsag00: "House Agriculture",
  hsap00: "House Appropriations",
  hsas00: "House Armed Services",
  hsba00: "House Financial Services",
  hsbu00: "House Budget",
  hsed00: "House Education & Workforce",
  hsfa00: "House Foreign Affairs",
  hsgo00: "House Oversight & Accountability",
  hsha00: "House Administration",
  hshf00: "Committee of the Whole House on the State of the Union",
  hshm00: "House Homeland Security",
  hsif00: "House Energy & Commerce",
  hsii00: "House Natural Resources",
  hsju00: "House Judiciary",
  hspw00: "House Transportation & Infrastructure",
  hsqa00: "House Ethics Enforcement",
  hsro00: "House Select Voting Irregularities",
  hsru00: "House Rules",
  hssm00: "House Small Business",
  hsso00: "House Ethics",
  hssy00: "House Science, Space, & Technology",
  hsvr00: "House Veterans' Affairs",
  hswm00: "House Ways & Means",
  htzt00: "House Task Force on the Attempted Assassination of Donald J. Trump",
  jcfm00: "National Bipartisan Commission on the Future of Medicare",
  jcov00: "Congressional Oversight Commission",
  jcpk00: "Congressional-Executive Commission on China",
  jcse00: "Helsinki Commission",
  jcuc00: "U.S.-China Economic & Security Review Commission",
  jhje00: "Joint Economic Committee",
  jjec00: "Joint Economic Committee",
  jocp00: "Congressional Oversight Panel",
  jsbp00: "Joint Select Budget & Appropriations Process Reform",
  jsdf00: "Joint Select Deficit Reduction",
  jsec00: "Joint Economic Committee",
  jsid00: "Joint Congressional Committee on Inaugural Ceremonies (2000)",
  jsie00: "Joint Congressional Committee on Inaugural Ceremonies (2004)",
  jsif00: "Joint Congressional Committee on Inaugural Ceremonies (2008)",
  jsig00: "Joint Congressional Committee on Inaugural Ceremonies (2012)",
  jsih00: "Joint Congressional Committee on Inaugural Ceremonies (2016)",
  jslc00: "Joint Committee on the Library",
  jspp00: "Joint Select Solvency of Multiemployer Pension Plans",
  jspr00: "Joint Committee on Printing",
  jstx00: "Joint Committee on Taxation",
  scnc00: "Senate International Narcotics Control Caucus",
  slet00: "Senate Select Ethics",
  slia00: "Senate Indian Affairs",
  slin00: "Senate Select Intelligence",
  sowg00: "Senate National Security Working Group",
  sp2k00: "Senate Special Year 2000 Technology Problem",
  spag00: "Senate Special Committee on Aging",
  spia00: "Senate Impeachment Trial Committee",
  ssaf00: "Senate Agriculture, Nutrition, & Forestry",
  ssap00: "Senate Appropriations",
  ssas00: "Senate Armed Services",
  ssbk00: "Senate Banking, Housing, & Urban Affairs",
  ssbu00: "Senate Budget",
  sscm00: "Senate Commerce, Science, & Transportation",
  sseg00: "Senate Energy & Natural Resources",
  ssev00: "Senate Environment & Public Works",
  ssfi00: "Senate Finance",
  ssfr00: "Senate Foreign Relations",
  ssga00: "Senate Homeland Security & Governmental Affairs",
  sshr00: "Senate Health, Education, Labor, & Pensions",
  ssju00: "Senate Judiciary",
  ssra00: "Senate Rules & Administration",
  sssb00: "Senate Small Business & Entrepreneurship",
  ssva00: "Senate Veterans' Affairs",
};

const subcommittees: Record<string, string> = {
  hlfd00: "Select Subcommittee on the Weaponization of the Federal Government",
  hlig01: "Central Intelligence Agency",
  hlig02: "National Security Agency & Cyber",
  hlig03: "Emerging Threats",
  hlig04: "Defense Intelligence & Overhead Architecture",
  hlig05: "Counterterrorism, Counterintelligence, & Counterproliferation",
  hlig06: "National Intelligence Enterprise",
  hlig07: "Terrorism & Homeland Security",
  hlig08: "Intelligence Modernization & Readiness",
  hlig09: "Oversight & Investigations",
  hlig10: "Strategic Technologies & Advanced Research",
  hlig11: "Open Source",
  hlqj00: "Select Subcommittee to Investigate the Remaining Questions Surrounding January 6, 2021",
  hlvc00: "Select Subcommittee on the Coronavirus Pandemic",
  hsag03: "Nutrition & Foreign Agriculture",
  hsag14: "Conservation, Research, & Biotechnology",
  hsag15: "Forestry & Horticulture",
  hsag16: "General Farm Commodities, Risk Management, & Credit",
  hsag22: "Commodity Markets, Digital Assets, & Rural Development",
  hsag23: "General Farm Commodities, Resource Conservation & Credit",
  hsag28: "Risk Management, Research & Specialty Crops",
  hsag29: "Livestock, Dairy, & Poultry",
  hsap01: "Agriculture, Rural Development, & FDA",
  hsap02: "Defense",
  hsap03: "District of Columbia",
  hsap04: "National Security, Department of State, & Related Programs",
  hsap05: "VA, HUD, & Independent Agencies",
  hsap06: "Interior, Environment, & Related Agencies",
  hsap07: "Labor, Health & Human Services, & Education",
  hsap08: "Legislative",
  hsap09: "Military Construction",
  hsap10: "Energy & Water Development",
  hsap11: "Commerce, Justice, State, & the Judiciary",
  hsap12: "Transportation",
  hsap13: "Treasury, Postal Service, & General Government",
  hsap14: "Transportation, Treasury & Independent Agencies",
  hsap15: "Homeland Security",
  hsap18: "Military Construction & Veterans Affairs",
  hsap19: "Commerce, Justice, Science, & Related Agencies",
  hsap20: "Transportation, Housing & Urban Development",
  hsap23: "Financial Services & General Government",
  hsap24: "Legislative Branch",
  hsas01: "Military Research & Development",
  hsas02: "Military Personnel",
  hsas03: "Readiness",
  hsas04: "Military Installations & Facilities",
  hsas06: "Oversight & Investigations",
  hsas11: "Defense Acquisition Reform Panel",
  hsas12: "Special Oversight Panel on Morale, Welfare, & Recreation",
  hsas20: "Military Procurement",
  hsas22: "Special Oversight Panel on Merchant Marine",
  hsas23: "Special Oversight Panel on Department of Energy Reorganization",
  hsas24: "Special Oversight Panel on Terrorism",
  hsas25: "Tactical Air & Land Forces",
  hsas26: "Intelligence & Special Operations",
  hsas27: "Total Force",
  hsas28: "Seapower & Projection Forces",
  hsas29: "Strategic Forces",
  hsas30: "Projection Forces",
  hsas33: "Defense Financial Management & Auditability Reform Panel",
  hsas34: "Panel on Business Challenges Within the Defense Industry",
  hsas35: "Cyber, Information Technologies, & Innovation",
  hsba01: "Terrorism & Illicit Finance",
  hsba04: "Housing & Insurance",
  hsba08: "Domestic & International Monetary Policy",
  hsba09: "Oversight & Investigations",
  hsba10: "National Security, Illicit Finance, & International Financial Institutions",
  hsba13: "Diversity & Inclusion",
  hsba15: "Consumer Protection & Financial Institutions",
  hsba16: "Capital Markets",
  hsba17: "International Monetary Policy & Trade",
  hsba18: "Domestic Monetary Policy, Technology, & Economic Growth",
  hsba19: "Domestic Monetary Policy & Technology",
  hsba20: "Financial Institutions",
  hsba21: "Digital Assets, Financial Technology, & Artificial Intelligence",
  hsed02: "Health, Employment, Labor, & Pensions",
  hsed04: "Healthy Families & Communities",
  hsed07: "Civil Rights & Human Services",
  hsed08: "Postsecondary Education, Training & Life-Long Learning",
  hsed10: "Workforce Protections",
  hsed11: "Early Childhood, Youth & Families",
  hsed12: "Oversight & Investigations",
  hsed13: "Higher Education & Workforce Development",
  hsed14: "Early Childhood, Elementary, & Secondary Education",
  hsfa04: "International Economic Policy & Trade",
  hsfa05: "East Asia & Pacific",
  hsfa06: "Global Health, Global Human Rights, & International Organizations",
  hsfa07: "Western Hemisphere",
  hsfa08: "Africa",
  hsfa12: "International Operations & Human Rights",
  hsfa13: "Middle East & North Africa",
  hsfa14: "Europe",
  hsfa15: "International Terrorism, Nonproliferation & Human Rights",
  hsfa16: "Africa",
  hsfa17: "Oversight & Intelligence",
  hsfa18: "Terrorism, Nonproliferation, & Trade",
  hsfa19: "South & Central Asia",
  hsgo01: "Energy Policy, Natural Resources & Regulatory Affairs",
  hsgo02: "Civil Rights & Civil Liberties",
  hsgo04: "Intergovernmental Affairs",
  hsgo05: "Economic Growth, Energy Policy, & Regulatory Affairs",
  hsgo06: "Military & Foreign Affairs",
  hsgo08: "Regulatory Affairs",
  hsgo09: "Civil Service & Agency Organization",
  hsgo10: "District of Columbia",
  hsgo11: "Postal Service",
  hsgo12: "Cybersecurity, Information Technology, & Government Innovation",
  hsgo13: "Census",
  hsgo14: "Criminal Justice, Drug Policy & Human Resources",
  hsgo15: "Technology & Procurement Policy",
  hsgo16: "Delivering on Government Efficiency",
  hsgo18: "Civil Service & Agency Organization",
  hsgo19: "Government Efficiency & Financial Management",
  hsgo20: "Technology, Information Policy, Intergovernmental Relations & the Census",
  hsgo21: "Human Rights & Wellness",
  hsgo22: "Energy & Resources",
  hsgo23: "Information Policy, Census, & National Archives",
  hsgo24: "Government Operations",
  hsgo25: "Information Technology",
  hsgo26: "Domestic Policy",
  hsgo27: "Health Care & Financial Services",
  hsgo28: "Environment",
  hsgo29: "Transportation & Public Assets",
  hsgo30: "Technology, Information Policy, Intergovernmental Relations & Procurement Reform",
  hsgo33: "Federal Law Enforcement",
  hsha04: "Capitol Security",
  hsha06: "Oversight",
  hsha08: "Elections",
  hsha27: "Modernization & Innovation",
  hshm01: "Infrastructure & Border Security",
  hshm02: "Rules",
  hshm03: "Emergency Preparedness & Response",
  hshm04: "Cybersecurity, Science, & Research & Development",
  hshm05: "Counterterrorism & Intelligence",
  hshm06: "Prevention of Nuclear & Biological Attack",
  hshm07: "Transportation & Maritime Security",
  hshm08: "Cybersecurity & Infrastructure Protection",
  hshm09: "Oversight, Investigations, & Accountability",
  hshm10: "Investigations",
  hshm11: "Border Security & Enforcement",
  hshm12: "Emergency Management & Technology",
  hsif02: "Oversight & Investigations",
  hsif03: "Energy",
  hsif04: "Select Investigative Panel",
  hsif07: "Telecommunications & the Internet",
  hsif12: "Telecommunications, Trade, & Consumer Protection",
  hsif13: "Finance & Hazardous Materials",
  hsif14: "Health",
  hsif15: "Environment & Hazardous Materials",
  hsif16: "Communications & Technology",
  hsif17: "Commerce, Manufacturing, & Trade",
  hsif18: "Environment",
  hsii06: "Energy & Mineral Resources",
  hsii10: "Federal Lands",
  hsii13: "Water, Wildlife & Fisheries",
  hsii15: "Oversight & Investigations",
  hsii20: "Forests & Forest Health",
  hsii22: "Fisheries, Wildlife, Oceans, & Insular Affairs",
  hsii24: "Indian & Insular Affairs",
  hsju01: "Immigration Integrity, Security, & Enforcement",
  hsju03: "Courts, Intellectual Property, AI, & the Internet",
  hsju05: "Administrative State, Regulatory Reform, & Antitrust",
  hsju08: "Crime & Federal Government Surveillance",
  hsju09: "Commercial & Administrative Law",
  hsju10: "Constitution & Limited Government",
  hsju11: "Antitrust (Full Committee Task Force)",
  hsju12: "Over-Criminalization Task Force",
  hsju13: "Oversight",
  hspw02: "Water Resources & Environment",
  hspw05: "Aviation",
  hspw07: "Coast Guard & Maritime Transportation",
  hspw08: "Economic Development, Public Buildings, Hazardous Materials & Pipeline Transportation",
  hspw10: "Ground Transportation",
  hspw11: "Oversight, Investigations & Emergency Management",
  hspw12: "Highways & Transit",
  hspw13: "Economic Development, Public Buildings, & Emergency Management",
  hspw14: "Railroads, Pipelines, & Hazardous Materials",
  hspw33: "Public-Private Partnerships",
  hsru01: "Technology & the House",
  hsru02: "Legislative & Budget Process",
  hsru04: "Rules & Organization of the House",
  hsru05: "Expedited Procedures",
  hssm15: "Government Programs & Oversight",
  hssm17: "Regulations & Healthcare",
  hssm19: "Finance & Tax",
  hssm20: "Empowerment",
  hssm21: "Rural Development, Energy, & Supply Chains",
  hssm22: "Innovation, Entrepreneurship, & Workforce Development",
  hssm23: "Contracting & Infrastructure",
  hssm24: "Oversight, Investigations, & Regulations",
  hssm25: "Underserved, Agricultural, & Rural Business Development",
  hssm26: "Innovation, Entrepreneurship, & Workforce Development",
  hssm27: "Economic Growth, Tax, & Capital Access",
  hssy14: "Research",
  hssy15: "Research & Technology",
  hssy16: "Space & Aeronautics",
  hssy17: "Technology",
  hssy18: "Environment",
  hssy19: "Technology",
  hssy20: "Energy",
  hssy21: "Investigations & Oversight",
  hsvr03: "Health",
  hsvr06: "Benefits",
  hsvr08: "Oversight & Investigations",
  hsvr09: "Disability Assistance & Memorial Affairs",
  hsvr10: "Economic Opportunity",
  hsvr11: "Technology Modernization",
  hswm01: "Social Security",
  hswm02: "Health",
  hswm03: "Work & Welfare",
  hswm04: "Trade",
  hswm05: "Tax",
  hswm06: "Oversight",
  hzgo34: "Task Force on the Declassification of Federal Secrets",
  slin01: "Oversight of the Terrorist Surveillance Program",
  ssaf01: "Production & Price Competitiveness",
  ssaf02: "Marketing, Inspection, & Product Promotion",
  ssaf05: "Forestry, Conservation, & Rural Revitalization",
  ssaf06: "Research, Nutrition, & General Legislation",
  ssaf08: "Domestic & Foreign Marketing, Inspection, & Plant & Animal Health",
  ssaf09: "Energy, Science & Technology",
  ssaf10: "Nutrition & Food Assistance, Sustainable & Organic Agriculture, & General Legislation",
  ssaf11: "Production, Income Protection & Price Support",
  ssaf12: "Rural Revitalization, Conservation, Forestry, & Credit",
  ssaf13: "Commodities, Derivatives, Risk Management, & Trade",
  ssaf14: "Conservation, Forestry, Natural Resources, & Biotechnology",
  ssaf15: "Rural Development, Energy, & Credit",
  ssaf16: "Food & Nutrition, Specialty Crops, Organics, & Research",
  ssaf17: "Livestock, Dairy, Poultry, & Food Safety",
  ssap01: "Agriculture, Rural Development, Food & Drug Administration, & Related Agencies",
  ssap02: "Department of Defense",
  ssap03: "District of Columbia",
  ssap04: "Foreign Operations",
  ssap05: "VA, HUD, & Independent Agencies",
  ssap06: "Interior",
  ssap07: "Labor, Health & Human Services, & Education",
  ssap08: "Legislative Branch",
  ssap09: "Military Construction",
  ssap10: "Energy & Water Development",
  ssap11: "Commerce, Justice, State, & the Judiciary",
  ssap12: "Transportation",
  ssap13: "Treasury & General Government",
  ssap14: "Department of Homeland Security",
  ssap15: "Transportation, Treasury & General Government",
  ssap16: "Commerce, Justice, Science, & Related Agencies",
  ssap17: "Department of the Interior, Environment, & Related Agencies",
  ssap18: "Departments of Labor, Health & Human Services, & Education, & Related Agencies",
  ssap19: "Military Construction, Veterans Affairs, & Related Agencies",
  ssap20: "State, Foreign Operations, & Related Programs",
  ssap21: "Transportation, Treasury, the Judiciary, & Housing & Urban Development, & Related Agencies",
  ssap22: "Energy & Water Development",
  ssap23: "Financial Services & General Government",
  ssap24: "Transportation, Housing & Urban Development, & Related Agencies",
  ssas13: "Seapower",
  ssas14: "Airland",
  ssas15: "Readiness & Management Support",
  ssas16: "Strategic Forces",
  ssas17: "Personnel",
  ssas20: "Emerging Threats & Capabilities",
  ssas21: "Cybersecurity",
  ssbk04: "Securities, Insurance, & Investment",
  ssbk05: "National Security & International Trade & Finance",
  ssbk08: "Financial Institutions & Consumer Protection",
  ssbk09: "Housing, Transportation, & Community Development",
  ssbk12: "Economic Policy",
  ssbk13: "Digital Assets",
  sscm01: "Aviation Operations, Safety, & Security",
  sscm02: "Communications",
  sscm03: "Consumer Affairs & Product Safety",
  sscm05: "Science, Technology, & Space",
  sscm08: "Surface Transportation & Merchant Marine",
  sscm09: "Oceans, Fisheries & Coast Guard",
  sscm10: "Manufacturing & Competitiveness",
  sscm11: "Competition, Foreign Commerce, & Infrastructure",
  sscm12: "Consumer Affairs, Product Safety, & Insurance",
  sscm13: "Disaster Prevention & Prediction",
  sscm14: "Global Climate Change & Impacts",
  sscm15: "Fisheries & Coast Guard",
  sscm16: "National Ocean Policy Study",
  sscm17: "Science & Space",
  sscm18: "Technology, Innovation, & Competitiveness",
  sscm19: "Trade, Tourism, & Economic Development",
  sscm20: "Consumer Protection, Product Safety, Insurance, & Data Security",
  sscm21: "Interstate Commerce, Trade, & Tourism",
  sscm22: "Oceans, Atmosphere, Fisheries, & Coast Guard",
  sscm23: "Science, Technology, & Innovation",
  sscm24: "Space, Science, & Competitiveness",
  sscm25: "Surface Transportation & Merchant Marine Infrastructure, Safety & Security",
  sscm26: "Communications, Technology, Innovation, & the Internet",
  sscm27: "Tourism, Competitiveness, & Innovation",
  sscm28: "Aviation & Space",
  sscm29: "Manufacturing, Trade, & Consumer Protection",
  sscm30: "Science, Oceans, Fisheries, & Weather",
  sscm31: "Security",
  sscm32: "Transportation & Safety",
  sscm33: "Aviation, Space, & Innovation",
  sscm34: "Telecommunications & Media",
  sscm35: "Consumer Protection, Technology, & Data Privacy",
  sscm36: "Coast Guard, Maritime, & Fisheries",
  sscm37: "Science, Manufacturing, & Competitiveness",
  sscm38: "Surface Transportation, Freight, Pipelines, & Safety",
  sscm39: "Tourism, Trade, & Export",
  sseg01: "Energy",
  sseg03: "Public Lands, Forests, & Mining",
  sseg04: "National Parks",
  sseg07: "Water & Power",
  ssev08: "Transportation & Infrastructure",
  ssev09: "Chemical Safety, Waste Management, Environmental Justice, & Regulatory Oversight",
  ssev10: "Clean Air, Climate, & Nuclear Innovation & Safety",
  ssev11: "Fisheries, Wildlife, & Water",
  ssev12: "Public Sector Solutions to Global Warming, Oversight, & Children's Health Protection",
  ssev13: "Private Sector & Consumer Solutions to Global Warming & Wildlife Protection",
  ssev14: "Transportation Safety, Infrastructure Security, & Water Quality",
  ssev15: "Fisheries, Water, & Wildlife",
  ssev16: "Green Jobs & the New Economy",
  ssev17: "Children's Health & Environmental Responsibility",
  ssev18: "Oversight",
  ssfi02: "Social Security, Pensions, & Family Policy",
  ssfi03: "International Trade",
  ssfi06: "Taxation & IRS Oversight",
  ssfi09: "Long-Term Growth & Debt Reduction",
  ssfi10: "Health Care",
  ssfi11: "Taxation & IRS Oversight",
  ssfi12: "Energy, Natural Resources, & Infrastructure",
  ssfi13: "International Trade, Customs, & Global Competitiveness",
  ssfi14: "Fiscal Responsibility & Economic Growth",
  ssfr01: "Europe & Regional Security Cooperation",
  ssfr02: "East Asia, the Pacific, & International Cybersecurity Policy",
  ssfr03: "International Economic Policy, Export & Trade Promotion",
  ssfr04: "International Operations & Terrorism",
  ssfr06: "Western Hemisphere, Transnational Crime, Civilian Security, Democracy, Human Rights, & Global Women's Issues",
  ssfr07: "Near East, South Asia, Central Asia, & Counterterrorism",
  ssfr09: "Africa & Global Health Policy",
  ssfr11: "Central Asia & South Caucasus",
  ssfr12: "International Development & Foreign Assistance, Economic Affairs, International Environmental Protection, & Peace Corps",
  ssfr13: "International Operations & Organizations, Human Rights, Democracy, & Global Women's Issues",
  ssfr14: "State Department & USAID Management, International Operations, & Bilateral International Development",
  ssfr15: "Multilateral International Development, Multilateral Institutions, & International Economic, Energy, & Environmental Policy",
  ssga01: "Investigations",
  ssga03: "Oversight of Government Management, the Federal Workforce, & the District of Columbia",
  ssga07: "International Security, Proliferation & Federal Services",
  ssga09: "Federal Financial Management, Government Information, Federal Services, & International Security",
  ssga10: "State, Local, & Private Sector Preparedness & Integration (Ad Hoc)",
  ssga11: "Disaster Recovery (Ad Hoc)",
  ssga13: "Contracting Oversight (Ad Hoc)",
  ssga14: "Disaster Recovery & Intergovernmental Affairs (Ad Hoc)",
  ssga15: "Financial & Contracting Oversight",
  ssga16: "Efficiency & Effectiveness of Federal Programs & the Federal Workforce",
  ssga17: "Emergency Management, Intergovernmental Relations, & the District of Columbia",
  ssga18: "Federal Spending Oversight & Emergency Management",
  ssga19: "Regulatory Affairs & Federal Management",
  ssga20: "Disaster Management, District of Columbia, & Census",
  ssga22: "Border Management, Federal Workforce, & Regulatory Affairs",
  sshr05: "Aging",
  sshr06: "Children & Families",
  sshr07: "Substance Abuse & Mental Health Services",
  sshr08: "Employment, Safety, & Training",
  sshr09: "Education & the American Family",
  sshr10: "Bioterrorism & Public Health Preparedness",
  sshr11: "Employment & Workplace Safety",
  sshr12: "Primary Health & Retirement Security",
  ssju01: "Antitrust, Competition Policy, & Consumer Rights",
  ssju02: "Administrative Oversight & the Courts",
  ssju03: "Constitution, Civil Rights & Property Rights",
  ssju04: "Border Security & Immigration",
  ssju07: "Youth Violence",
  ssju09: "Terrorism & Homeland Security",
  ssju11: "Criminal Justice Oversight",
  ssju12: "Crime, Corrections & Victims' Rights",
  ssju14: "Corrections & Rehabilitation",
  ssju15: "Crime & Drugs",
  ssju17: "Intellectual Property",
  ssju18: "Constitution",
  ssju19: "Human Rights & the Law",
  ssju20: "Human Rights & the Law",
  ssju21: "Constitution",
  ssju22: "Crime & Counterterrorism",
  ssju23: "Privacy, Technology & the Law",
  ssju24: "Bankruptcy & the Courts",
  ssju25: "Federal Courts, Oversight, Agency Action, & Federal Rights",
  ssju26: "Intellectual Property",
  ssju27: "Human Rights & the Law",
  ssju28: "Privacy, Technology, & the Law",
};

const parentCommitteeOverrides: Record<string, string> = {
  hlfd00: 'hsju00',
  hlqj00: 'hsju00',
  hlvc00: 'hsgo00',
  hzgo34: 'hsgo00',
};

const documentKindLabels: Record<string, string> = {
  'published-hearing': 'Published Hearing',
  'meeting-support': 'Meeting Support Document',
  'testimony': 'Witness Testimony',
  'witness-statement': 'Witness Statement',
  'testimony-disclosure': 'Truth in Testimony Disclosure',
  'witness-biography': 'Witness Biography',
  'committee-amendment': 'Committee Amendment',
  'bill-numbered': 'Numbered Bill',
  'committee-vote': 'Committee Recorded Vote',
  'committee-amendment-described': 'Committee Amendment (Described)',
  'witness-support': 'Witness Supporting Material',
  'member-statement': 'Member Statement',
  'amendment': 'Amendment',
  'opening-statement': 'Opening Statement',
  'statement': 'Statement',
  'witness-list': 'Witness List',
  'committee-transcript': 'Committee Transcript',
  'committee-memorandum': 'Committee Memorandum',
  'bill-untyped-numbered': 'Numbered Legislation',
  'published-report': 'Published Committee Report',
  'meeting-notice': 'Meeting Notice',
  'questions-for-record': 'Questions for the Record',
  'questions-for-record-response': 'Responses to Questions for the Record',
  'bill-untyped-draft': 'Discussion Draft Bill',
  'biography': 'Biography',
  'member-roster': 'Committee Roster',
  'transcript': 'Transcript',
  'legislative-text': 'Legislative Text',
  'bill-suspension-numbered': 'Suspension Bill',
  'nomination': 'Nomination',
  'committee-enbloc-numbered': 'En Bloc Amendment',
  'letter-of-support': 'Letter of Support',
  'questionnaire': 'Questionnaire',
  'bill-measure-list': 'List of Bills & Measures',
  'business-meeting': 'Business Meeting / Markup',
  'committee-report': 'Committee Report',
  'report': 'Report',
  'hearing-charter': 'Hearing Charter',
  'appropriation-described': 'Appropriations Material',
  'letter': 'Letter',
  'committee-print': 'Committee Print',
  'meeting-results': 'Markup / Meeting Results',
  'opening-remarks': 'Opening Remarks',
  'remarks': 'Remarks',
  'bill-unnumbered': 'Unnumbered Bill',
  'appropriation-routed': 'Appropriations Routing Table',
  'summary': 'Summary',
  'attachment': 'Attachment',
  'exhibit': 'Exhibit',
  'committee-document': 'Committee Document',
  'bill-named-draft': 'Named Draft Bill',
  'bill-titled-draft': 'Titled Draft Bill',
  'appendix': 'Appendix',
  'bill-house-amendment': 'House Amendment',
  'bill-preintroduced': 'Pre-Introduced Bill Draft',
  'committee-enbloc-described': 'En Bloc Amendment (Described)',
  'amendment-collection': 'Amendment Packet',
  'bill-numbered-described': 'Numbered Bill (Described)',
  'section-by-section': 'Section-by-Section Summary',
  'oversight-plan': 'Oversight Plan',
  'tally-sheet': 'Vote Tally Sheet',
  'bill-comparison': 'Comparative Print',
  'committee-resolution': 'Committee Resolution',
  'fact-sheet': 'Fact Sheet',
  'committee-report-unnumbered': 'Unnumbered Committee Report',
  'public-law': 'Public Law',
  'field-hearing': 'Field Hearing',
  'explanatory-statement': 'Explanatory Statement',
  'response': 'Response',
  'published-print': 'Published Committee Print',
  'slides': 'Presentation Slides',
  'chair-mark': "Chairman's Mark",
  'budget-views-and-estimates': 'Budget Views & Estimates',
  'revenue-estimate': 'Revenue / Cost Estimate',
  'interchamber-amendment': 'Interchamber Amendment',
  'exhibit-collection': 'Exhibit Packet',
  'managers-package': "Manager's Amendment Package",
  'treaty-document': 'Treaty Document',
  'conference-unnumbered': 'Conference Material',
  'amendment-list': 'Amendment List',
  'mark-description': "Description of the Chairman's Mark",
  'mark-modification': "Modification to the Chairman's Mark",
  'conference-legislation-part': 'Conference Report Part',
  'issue-brief': 'Issue Brief',
  'activity-report': 'Committee Activity Report',
  'committee-report-part': 'Committee Report Part',
  'conference-report': 'Conference Report',
  'exhibit-list': 'Exhibit List',
  'flyer': 'Flyer',
  'graphic': 'Graphic',
  'motion': 'Motion',
  'notice': 'Notice',
  'pamphlet': 'Pamphlet',
  'panel-discussion': 'Panel Discussion',
  'panelist-list': 'Panelist List',
  'participant-list': 'Participant List',
  'rules-memorandum': 'Rules Committee Memorandum',
  'brochure': 'Brochure',
};

const formatNames: Record<string, string> = {
  pdf: 'PDF',
  html: 'HTML',
  xml: 'XML',
  docx: 'DOCX',
  doc: 'DOC',
  zip: 'ZIP',
  json: 'JSON',
  txt: 'TXT',
  text: 'TXT',
  image: 'Image',
  other: 'Other',
};

const measurePrefixes: Record<string, string> = {
  hr: 'H.R.',
  s: 'S.',
  hres: 'H.Res.',
  sres: 'S.Res.',
  hjres: 'H.J.Res.',
  sjres: 'S.J.Res.',
  hconres: 'H.Con.Res.',
  sconres: 'S.Con.Res.',
  pn: 'PN',
};

const billTypeSlugMap: Record<string, string> = {
  hr: 'house-bill',
  s: 'senate-bill',
  hres: 'house-resolution',
  sres: 'senate-resolution',
  hjres: 'house-joint-resolution',
  sjres: 'senate-joint-resolution',
  hconres: 'house-concurrent-resolution',
  sconres: 'senate-concurrent-resolution',
};

const genericAnchorTitles = new Set([
  'zip', 'pdf', 'html', 'htm', 'xml', 'doc', 'docx', 'txt', 'text', 'json', 'csv',
  'xls', 'xlsx', 'ppt', 'pptx', 'mp3', 'mp4', 'click here', 'please click here',
  'here', 'link', 'document', 'file', 'download', 'download file', 'download pdf',
  'download testimony', 'download witness testimony',
  'download executive business meeting results', 'view', 'view pdf', 'view testimony',
  'open', 'read more', 'more', 'email', 'print', 'share', 'website', 'webpage',
  'untitled', 'attachment',
]);

export function ordinal(n: number): string {
  const rem10 = n % 10;
  const rem100 = n % 100;
  if (rem10 === 1 && rem100 !== 11) return `${n}st`;
  if (rem10 === 2 && rem100 !== 12) return `${n}nd`;
  if (rem10 === 3 && rem100 !== 13) return `${n}rd`;
  return `${n}th`;
}

export function congressLabel(congress: number | string | null | undefined): string | null {
  const num = Number(congress);
  if (!Number.isInteger(num) || num < 1 || num > 200) return null;
  return `${ordinal(num)} Congress`;
}

export function congressOptionLabel(congress: number | string): string {
  const num = Number(congress);
  if (!Number.isInteger(num) || num < 1) return String(congress);
  const meta = (congressMetadata as Record<string, { start: string; end: string }>)[String(num)];
  const startYear = meta ? meta.start.slice(0, 4) : String(1789 + (num - 1) * 2);
  const endYear = meta ? meta.end.slice(0, 4) : String(1789 + num * 2);
  return `${ordinal(num)} Congress (${startYear}–${endYear})`;
}

export type CommitteeCatalogInput =
  | any[]
  | Map<string, any>
  | Record<string, any>
  | null
  | undefined;

function normalizeDateString(value: any): string | null {
  if (!value) return null;
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  const str = String(value).trim();
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(str);
  return match ? match[1] : null;
}

export function indexCommittees(committees?: CommitteeCatalogInput): Map<string, any> {
  const map = new Map<string, any>();
  if (!committees) return map;
  if (committees instanceof Map) {
    for (const [k, v] of committees.entries()) {
      map.set(String(k).toLowerCase(), v);
    }
    return map;
  }
  const items = Array.isArray(committees) ? committees : Object.values(committees);
  for (const item of items) {
    if (!item || typeof item !== 'object') continue;
    const keys = [
      item.committee_key,
      item.system_code,
      item.thomas_id,
      item.house_committee_id,
      item.senate_code,
      ...(Array.isArray(item.system_codes) ? item.system_codes : []),
      ...(Array.isArray(item.gpo_codes) ? item.gpo_codes : []),
    ];
    for (const key of keys) {
      if (key) {
        const lower = String(key).trim().toLowerCase();
        if (lower && !map.has(lower)) map.set(lower, item);
      }
    }
  }
  return map;
}

export function resolveCommitteeName(
  committee: any,
  dateOrCongress?: string | number | Date | null,
): string {
  if (!committee) return '';
  const historyList: any[] = Array.isArray(committee.names)
    ? committee.names
    : Array.isArray(committee.histories)
      ? committee.histories
      : [];
  if (dateOrCongress != null && historyList.length > 0) {
    const asNumber = typeof dateOrCongress === 'number'
      ? dateOrCongress
      : /^\d{1,3}$/.test(String(dateOrCongress).trim())
        ? Number(String(dateOrCongress).trim())
        : null;
    if (asNumber != null && Number.isInteger(asNumber) && asNumber >= 1 && asNumber <= 300) {
      for (const entry of historyList) {
        if (entry?.congress != null && Number(entry.congress) === asNumber && entry.name) {
          return String(entry.name);
        }
        if (Array.isArray(entry?.congresses) && entry.congresses.map(Number).includes(asNumber) && entry.name) {
          return String(entry.name);
        }
      }
      const meta = (congressMetadata as Record<string, { start: string; end: string }>)[String(asNumber)];
      if (meta) {
        for (const entry of historyList) {
          const start = normalizeDateString(entry?.start ?? entry?.start_date);
          const end = normalizeDateString(entry?.end ?? entry?.end_date);
          if ((!start || start < meta.end) && (!end || end > meta.start) && entry?.name) {
            return String(entry.name);
          }
        }
      }
    } else {
      const targetDate = normalizeDateString(dateOrCongress);
      if (targetDate) {
        for (const entry of historyList) {
          const start = normalizeDateString(entry?.start ?? entry?.start_date);
          const end = normalizeDateString(entry?.end ?? entry?.end_date);
          if ((!start || targetDate >= start) && (!end || targetDate < end) && entry?.name) {
            return String(entry.name);
          }
        }
      }
    }
  }
  return String(
    committee.current_name
    || committee.name
    || historyList.at(-1)?.name
    || '',
  ).trim();
}

export function parentCommitteeCode(code: string, committees?: CommitteeCatalogInput): string {
  const clean = String(code ?? '').trim().toLowerCase();
  if (!clean) return '';
  if (committees) {
    const map = indexCommittees(committees);
    const entry = map.get(clean);
    const parent = String(entry?.parent_key ?? entry?.parent_system_code ?? '').trim().toLowerCase();
    if (parent) return parent;
  }
  if (parentCommitteeOverrides[clean]) return parentCommitteeOverrides[clean];
  if (clean.length === 6 && /^[a-z]{4}\d{2}$/.test(clean)) {
    const parent = `${clean.slice(0, 4)}00`;
    if (standingCommittees[parent]) return parent;
    if (committees && indexCommittees(committees).has(parent)) return parent;
  }
  return clean;
}

export function committeeShortLabel(
  code: string,
  committees?: CommitteeCatalogInput,
  dateOrCongress?: string | number | Date | null,
): string {
  const clean = String(code ?? '').trim().toLowerCase();
  if (!clean) return '';
  if (committees) {
    const map = indexCommittees(committees);
    const entry = map.get(clean);
    if (entry) {
      const parentKey = String(entry.parent_key ?? entry.parent_system_code ?? '').trim().toLowerCase();
      if (parentKey && map.has(parentKey)) {
        const parentName = resolveCommitteeName(map.get(parentKey), dateOrCongress);
        if (parentName) return parentName;
      }
      const name = resolveCommitteeName(entry, dateOrCongress);
      if (name) return name;
    }
  }
  if (standingCommittees[clean]) return standingCommittees[clean];
  const parent = parentCommitteeCode(clean, committees);
  if (standingCommittees[parent]) return standingCommittees[parent];
  return clean.toUpperCase();
}

export function committeeLabel(
  code: string,
  committees?: CommitteeCatalogInput,
  dateOrCongress?: string | number | Date | null,
): string {
  const clean = String(code ?? '').trim().toLowerCase();
  if (!clean) return '';
  if (committees) {
    const map = indexCommittees(committees);
    const entry = map.get(clean);
    if (entry) {
      const name = resolveCommitteeName(entry, dateOrCongress);
      const parentKey = String(entry.parent_key ?? entry.parent_system_code ?? '').trim().toLowerCase();
      if (parentKey && parentKey !== clean) {
        const parentEntry = map.get(parentKey);
        const parentName = parentEntry
          ? resolveCommitteeName(parentEntry, dateOrCongress)
          : standingCommittees[parentKey] || '';
        if (parentName && name && !name.toLowerCase().startsWith(parentName.toLowerCase())) {
          return `${parentName} — ${name}`;
        }
      }
      if (name) return name;
    }
  }
  if (standingCommittees[clean]) return standingCommittees[clean];
  const parent = parentCommitteeCode(clean, committees);
  const parentName = standingCommittees[parent];
  const subName = subcommittees[clean];
  if (parentName && subName) return `${parentName} — ${subName}`;
  if (parentName && clean !== parent) return `${parentName} (${clean.slice(4)})`;
  return clean.toUpperCase();
}

export function expandCommitteeKeys(
  selected: string,
  facetItems: Array<{ value: string; count: number }>,
  committees?: CommitteeCatalogInput,
): string[] {
  const clean = String(selected ?? '').trim().toLowerCase();
  if (!clean) return [];
  const map = indexCommittees(committees);
  const entry = map.get(clean);
  const explicitSubs: string[] = Array.isArray(entry?.subcommittees)
    ? entry.subcommittees.map((s: any) => String(typeof s === 'string' ? s : (s?.committee_key ?? s?.system_code ?? '')).toLowerCase()).filter(Boolean)
    : [];
  if ((clean.endsWith('00') && (standingCommittees[clean] || entry)) || explicitSubs.length > 0) {
    const prefix = clean.slice(0, 4);
    const subSet = new Set([clean, ...explicitSubs]);
    const matching = facetItems
      .map(item => String(item.value).toLowerCase())
      .filter(code => subSet.has(code) || ((code.startsWith(prefix) || parentCommitteeCode(code, committees) === clean) && parentCommitteeCode(code, committees) === clean));
    for (const s of explicitSubs) {
      if (!matching.includes(s)) matching.push(s);
    }
    return matching.length ? [...new Set([clean, ...matching])] : [clean];
  }
  return [clean];
}

const houseHostMap: Record<string, string> = {
  agriculture: 'hsag00',
  appropriations: 'hsap00',
  armedservices: 'hsas00',
  financialservices: 'hsba00',
  budget: 'hsbu00',
  edworkforce: 'hsed00',
  edlabor: 'hsed00',
  education: 'hsed00',
  foreignaffairs: 'hsfa00',
  oversight: 'hsgo00',
  oversightdemocrats: 'hsgo00',
  cha: 'hsha00',
  houseadministration: 'hsha00',
  homeland: 'hshm00',
  energycommerce: 'hsif00',
  naturalresources: 'hsii00',
  resources: 'hsii00',
  judiciary: 'hsju00',
  transportation: 'hspw00',
  rules: 'hsru00',
  smallbusiness: 'hssm00',
  ethics: 'hsso00',
  science: 'hssy00',
  sciencedems: 'hssy00',
  veterans: 'hsvr00',
  waysandmeans: 'hswm00',
  intelligence: 'hlig00',
  climatecrisis: 'hlcn00',
  modernization: 'hlmh00',
  january6th: 'hlij00',
  coronavirus: 'hlvc00',
  chinaselectcommittee: 'hlzs00',
  selectcommitteeontheccp: 'hlzs00',
  humanrightscommission: 'hotl00',
};

const senateHostMap: Record<string, string> = {
  agriculture: 'ssaf00',
  appropriations: 'ssap00',
  'armed-services': 'ssas00',
  banking: 'ssbk00',
  budget: 'ssbu00',
  commerce: 'sscm00',
  energy: 'sseg00',
  epw: 'ssev00',
  finance: 'ssfi00',
  foreign: 'ssfr00',
  hsgac: 'ssga00',
  help: 'sshr00',
  judiciary: 'ssju00',
  rules: 'ssra00',
  sbc: 'sssb00',
  veterans: 'ssva00',
  indian: 'slia00',
  intelligence: 'slin00',
  ethics: 'slet00',
  aging: 'spag00',
  drugcaucus: 'scnc00',
  jec: 'jsec00',
};

const otherHostMap: Record<string, string> = {
  'd1dth6e84htgma.cloudfront.net': 'hsif00',
  'csce.gov': 'jcse00',
  'www.csce.gov': 'jcse00',
  'cecc.gov': 'jcpk00',
  'www.cecc.gov': 'jcpk00',
  'jct.gov': 'jstx00',
  'www.jct.gov': 'jstx00',
  'appropriations.edgeboss.net': 'hsap00',
  'science.edgeboss.net': 'hssy00',
};

export function normalizeCommitteeCode(raw: any): string {
  const clean = String(raw ?? '').trim().toLowerCase();
  if (!clean) return '';
  if (standingCommittees[clean] || subcommittees[clean]) return clean;
  if (/^[a-z]{2}\d{2}$/.test(clean)) {
    for (const prefix of ['hs', 'hl', 'ht']) {
      const candidate = `${prefix}${clean}`;
      if (standingCommittees[candidate] || subcommittees[candidate]) return candidate;
    }
  }
  if (/^[a-z]{2}$/.test(clean)) {
    for (const prefix of ['hs', 'hl', 'ht']) {
      const candidate = `${prefix}${clean}00`;
      if (standingCommittees[candidate] || subcommittees[candidate]) return candidate;
    }
  }
  if (/^[a-z]{4}\d{2}$/.test(clean) && standingCommittees[`${clean.slice(0, 4)}00`]) {
    return clean;
  }
  return '';
}

function committeeCodeFromUrl(rawUrl: any): string {
  const text = String(rawUrl ?? '').trim();
  if (!text) return '';
  try {
    let parsed = new URL(text);
    if (parsed.hostname.toLowerCase() === 'web.archive.org') {
      const embedded = /\/web\/[^/]+\/(https?:\/\/.+)$/i.exec(parsed.pathname + parsed.search);
      if (embedded) parsed = new URL(embedded[1]);
    }
    const host = parsed.hostname.toLowerCase();
    if (otherHostMap[host]) return otherHostMap[host];
    if (host === 'docs.house.gov') {
      const parts = parsed.pathname.split('/').filter(Boolean);
      if (parts[0]?.toLowerCase() === 'meetings') {
        const sub = normalizeCommitteeCode(parts[2]);
        if (sub) return sub;
        const cmte = normalizeCommitteeCode(parts[1]);
        if (cmte) return cmte;
      }
      const first = normalizeCommitteeCode(parts[0]);
      if (first) return first;
    }
    if (host.endsWith('.house.gov')) {
      const subhost = host.slice(0, -'.house.gov'.length);
      const tokens = subhost.split(/[.-]/).filter(Boolean);
      for (const token of tokens) {
        if (houseHostMap[token]) return houseHostMap[token];
      }
    }
    if (host.endsWith('.senate.gov')) {
      const subhost = host.slice(0, -'.senate.gov'.length).replace(/^www\./, '');
      if (senateHostMap[subhost]) return senateHostMap[subhost];
      for (const token of subhost.split('.')) {
        if (senateHostMap[token]) return senateHostMap[token];
      }
    }
  } catch {
    return '';
  }
  return '';
}

export function deriveCommitteeCodes(document: any, detail?: any, sources?: any[], recoveries?: any[]): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  const add = (code: string) => {
    if (code && !seen.has(code)) {
      seen.add(code);
      result.push(code);
    }
  };
  if (Array.isArray(detail?.facts)) {
    for (const fact of detail.facts) {
      if ((fact?.field === 'committee_code' || fact?.label === 'committee_code') && fact?.value) {
        add(normalizeCommitteeCode(fact.value));
      }
    }
  }
  const urls = [
    document?.source_url,
    ...(Array.isArray(sources) ? sources.flatMap(s => [s?.url, s?.listed_on]) : []),
    ...(Array.isArray(recoveries) ? recoveries.map(r => r?.recovered_url) : []),
  ];
  for (const url of urls) {
    if (url) add(committeeCodeFromUrl(url));
  }
  return result;
}

export function buildCommitteeGroups(
  facetItems: Array<{ value: string; count: number }>,
  committees?: CommitteeCatalogInput,
) {
  const parentTotals = new Map<string, number>();
  const subItems: Array<{ value: string; label: string; count: number }> = [];
  for (const item of facetItems) {
    const code = String(item.value).toLowerCase();
    const count = Number(item.count) || 0;
    const parent = parentCommitteeCode(code, committees);
    parentTotals.set(parent, (parentTotals.get(parent) ?? 0) + count);
    if (code !== parent) {
      subItems.push({ value: code, label: committeeLabel(code, committees), count });
    }
  }
  const primary = [...parentTotals.entries()]
    .map(([value, count]) => ({ value, label: committeeShortLabel(value, committees), count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  subItems.sort((a, b) => a.label.localeCompare(b.label));
  return { primary, subItems };
}

export function documentKindLabel(kind: string): string {
  const clean = String(kind ?? '').trim().toLowerCase();
  if (!clean) return '';
  if (documentKindLabels[clean]) return documentKindLabels[clean];
  return clean
    .split('-')
    .filter(Boolean)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function formatOptionLabel(format: string): string {
  const clean = String(format ?? '').trim().toLowerCase();
  return formatNames[clean] ?? clean.toUpperCase();
}

export function effectiveFormat(document: any, detail?: any): string {
  const filename = String(document?.filename ?? '').trim();
  const extMatch = /\.([a-z0-9]{2,5})$/i.exec(filename);
  const ext = extMatch ? extMatch[1].toLowerCase() : '';
  const knownExt: Record<string, string> = {
    pdf: 'pdf', zip: 'zip', html: 'html', htm: 'html', xml: 'xml',
    docx: 'docx', doc: 'doc', txt: 'txt', text: 'txt', json: 'json', csv: 'csv',
  };
  const docFormat = String(document?.format ?? '').trim().toLowerCase();
  if (ext && knownExt[ext] && (!docFormat || docFormat === 'other' || docFormat === 'json' || docFormat === 'text')) {
    return knownExt[ext];
  }
  if (docFormat && docFormat !== 'other') return docFormat === 'text' ? 'txt' : docFormat;
  if (ext && knownExt[ext]) return knownExt[ext];
  const media = String(detail?.saved_media_type ?? '').toLowerCase();
  if (media.includes('pdf')) return 'pdf';
  if (media.includes('zip')) return 'zip';
  if (media.includes('html')) return 'html';
  if (media.includes('xml')) return 'xml';
  if (media.includes('word') || media.includes('officedocument')) return 'docx';
  if (media.includes('json')) return 'json';
  return docFormat || 'file';
}

export function formatMeasure(key: string): string {
  const raw = String(key ?? '').trim();
  const nomMatch = /^(?:(\d+)-)?pn-([0-9-]+)$/i.exec(raw);
  if (nomMatch) {
    return `PN${nomMatch[2]}`;
  }
  const match = /^(?:(\d+)-)?([a-z]+)-(\d+)$/i.exec(raw);
  if (!match) return raw;
  const prefix = measurePrefixes[match[2].toLowerCase()] ?? match[2].toUpperCase();
  return `${prefix} ${match[3]}`;
}

export function formatSubject(key: string, subject?: any): string {
  if (subject?.citation) return String(subject.citation);
  if (subject?.bill_type && subject?.bill_number != null) {
    const prefix = measurePrefixes[String(subject.bill_type).toLowerCase()] ?? String(subject.bill_type).toUpperCase();
    return `${prefix} ${subject.bill_number}`;
  }
  return formatMeasure(key);
}

export function congressGovBillUrl(billOrKey: any): string | null {
  if (!billOrKey) return null;
  if (typeof billOrKey === 'object' && billOrKey.congress_gov_url) return String(billOrKey.congress_gov_url);
  const key = typeof billOrKey === 'object'
    ? String(billOrKey.subject_key ?? billOrKey.bill_id ?? '')
    : String(billOrKey);
  const match = /^(\d+)-([a-z]+)-(\d+)$/i.exec(key.trim());
  if (match) {
    const congress = Number(match[1]);
    const type = match[2].toLowerCase();
    const num = match[3];
    const slug = billTypeSlugMap[type];
    if (slug && congress > 0) {
      return `https://www.congress.gov/bill/${ordinal(congress)}-congress/${slug}/${num}`;
    }
  }
  if (typeof billOrKey === 'object' && billOrKey.congress && billOrKey.bill_type && billOrKey.bill_number != null) {
    const slug = billTypeSlugMap[String(billOrKey.bill_type).toLowerCase()];
    if (slug) {
      return `https://www.congress.gov/bill/${ordinal(Number(billOrKey.congress))}-congress/${slug}/${billOrKey.bill_number}`;
    }
  }
  return null;
}

export function gpoBillUrl(billOrKey: any): string | null {
  if (!billOrKey) return null;
  if (typeof billOrKey === 'object' && billOrKey.gpo_url) return String(billOrKey.gpo_url);
  const key = typeof billOrKey === 'object'
    ? String(billOrKey.subject_key ?? billOrKey.bill_id ?? '')
    : String(billOrKey);
  const match = /^(\d+)-([a-z]+)-(\d+)$/i.exec(key.trim());
  if (match) {
    const [, congress, type, num] = match;
    if (type.toLowerCase() !== 'pn') {
      return `https://www.govinfo.gov/app/search/%7B%22query%22%3A%22collection%3Abills%20congress%3A${congress}%20billtype%3A${type.toLowerCase()}%20billnum%3A${num}%22%7D`;
    }
  }
  return null;
}

export function congressGovNominationUrl(nomOrKey: any): string | null {
  if (!nomOrKey) return null;
  if (typeof nomOrKey === 'object' && nomOrKey.congress_gov_url) return String(nomOrKey.congress_gov_url);
  const key = typeof nomOrKey === 'object'
    ? String(nomOrKey.subject_key ?? nomOrKey.nomination_id ?? '')
    : String(nomOrKey);
  const match = /^(\d+)-pn-([0-9-]+)$/i.exec(key.trim());
  if (match) {
    const congress = Number(match[1]);
    const number = match[2];
    if (congress > 0) {
      return `https://www.congress.gov/nomination/${ordinal(congress)}-congress/${number}`;
    }
  }
  return null;
}

export function congressGovMemberUrl(bioguideId: string, name?: string): string | null {
  const clean = String(bioguideId ?? '').trim();
  if (!clean) return null;
  if (name) {
    const slug = String(name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    if (slug) return `https://www.congress.gov/member/${slug}/${clean}`;
  }
  return `https://bioguide.congress.gov/search/bio/${clean}`;
}

export function spicyRegsUrl(queryOrBill: string): string | null {
  const clean = String(queryOrBill ?? '').trim();
  if (!clean) return null;
  return `https://spicyregs.org/?q=${encodeURIComponent(clean)}`;
}

export function formatDuration(seconds: number | null | undefined): string | null {
  const num = Number(seconds);
  if (!Number.isFinite(num) || num <= 0) return null;
  const totalSec = Math.round(num);
  const hrs = Math.floor(totalSec / 3600);
  const mins = Math.floor((totalSec % 3600) / 60);
  const secs = totalSec % 60;
  if (hrs > 0) {
    return `${hrs}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }
  return `${mins}:${String(secs).padStart(2, '0')}`;
}

export function formatBytes(value: any): string | null {
  if (value == null) return null;
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) return null;
  if (num < 1024) return `${Math.round(num)} B`;
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(num < 10 * 1024 ? 1 : 0)} KB`;
  return `${(num / (1024 * 1024)).toFixed(1)} MB`;
}

export function cleanIdentityNote(note: any): string | null {
  const text = String(note ?? '').trim();
  if (!text) return null;
  if (/^Reconciled from pinned accepted mappings\s+[0-9a-f]{16,}/i.test(text)) return null;
  return text;
}

export function isGenericTitle(title: any): boolean {
  const clean = String(title ?? '').trim().replace(/\s+/g, ' ');
  if (!clean) return true;
  const lower = clean.toLowerCase().replace(/[.!:]+$/, '');
  if (genericAnchorTitles.has(lower)) return true;
  if (/^(?:please\s+)?click\s+here\b/i.test(lower)) return true;
  if (/^(?:download|view|open)\s+(?:witness\s+)?(?:testimony|statement|document|pdf|file|results)\b/i.test(lower)) return true;
  return false;
}

export function cleanDisplayFilename(filename: any): string {
  const raw = String(filename ?? '').trim();
  if (!raw || !/[0-9a-z]/i.test(raw)) return '';
  return raw.replace(/^[0-9a-f]{64}\./i, '');
}

function urlFallbackLabel(url: any): string {
  const raw = String(url ?? '').trim();
  if (!raw) return '';
  try {
    const parsed = new URL(raw);
    const segments = parsed.pathname.split('/').filter(Boolean);
    const last = segments.at(-1) ? decodeURIComponent(segments.at(-1)!) : '';
    if (last && /\.[a-z0-9]{2,5}$/i.test(last)) return cleanDisplayFilename(last) || last;
    const host = parsed.hostname.replace(/^www\./i, '');
    const pathPart = segments.slice(0, 3).join('/');
    return pathPart ? `${host}/${pathPart}` : host;
  } catch {
    return '';
  }
}

export function presentDocument(
  document: any,
  detail?: any,
  sources?: any[],
  recoveries?: any[],
  committeesCatalog?: CommitteeCatalogInput,
) {
  const rawTitle = String(document?.title ?? '').trim();
  const cleanFile = cleanDisplayFilename(document?.filename);
  const validTitle = !isGenericTitle(rawTitle) ? rawTitle : '';
  const sourceUrl = document?.source_url || sources?.[0]?.url || recoveries?.[0]?.recovered_url || '';
  const urlLabel = (!validTitle && !cleanFile) ? urlFallbackLabel(sourceUrl) : '';
  const kindLabels = Array.isArray(document?.document_kind)
    ? document.document_kind.map(documentKindLabel).filter(Boolean)
    : [];
  const dateOrCongress = document?.document_date || document?.congress;
  const explicitCodes = Array.isArray(document?.committee_keys)
    ? document.committee_keys.map((key: any) => String(key ?? '').trim().toLowerCase()).filter(Boolean)
    : [];
  const rawCodes = explicitCodes.length > 0
    ? explicitCodes
    : deriveCommitteeCodes(document, detail, sources, recoveries);
  const uniqueCodes = [...new Set(rawCodes)];
  const committeeItems = uniqueCodes
    .map(code => ({
      code,
      label: committeeLabel(code, committeesCatalog, dateOrCongress),
      shortLabel: committeeShortLabel(code, committeesCatalog, dateOrCongress),
    }))
    .filter(item => Boolean(item.label));
  const committees = [...new Set(committeeItems.map(item => item.shortLabel).filter(Boolean))];
  const congress = congressLabel(document?.congress);
  const measures = Array.isArray(document?.measure_keys)
    ? document.measure_keys.slice(0, 3).map(formatMeasure).filter(Boolean)
    : [];

  const fmt = effectiveFormat(document, detail).toUpperCase();
  const fallbackKind = kindLabels[0]
    || (document?.saved_kind === 'recovery' ? `Recovered ${fmt} document` : `Archived ${fmt} document`);
  const fallbackSuffix = committees[0]
    ? ` — ${committees[0]}`
    : document?.list_row != null
      ? ` (#${Number(document.list_row) + 1})`
      : '';

  const title = validTitle || cleanFile || urlLabel || `${fallbackKind}${fallbackSuffix}`;
  const subtitle = cleanFile && cleanFile !== title ? cleanFile : '';
  const contextParts = [
    congress,
    ...committees.slice(0, 2),
    ...kindLabels.slice(0, 2),
    ...measures.slice(0, 2),
  ].filter(Boolean) as string[];

  return {
    title,
    subtitle,
    contextParts,
    format: fmt,
    congress,
    committees: [...new Set(committeeItems.map(item => item.label).filter(Boolean))],
    committeeItems,
    kinds: kindLabels,
    measures: Array.isArray(document?.measure_keys)
      ? document.measure_keys.map((key: string) => ({ key, label: formatMeasure(key) }))
      : [],
  };
}
