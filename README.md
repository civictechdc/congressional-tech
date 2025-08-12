# congressional-tech

# Civic & Congressional Tech Project Proposals

We're establishing a relationship with key technical personel in and around congress, this is an aggregated list of problems that have been identified, and are potential project ideas.

**Overarching Goal:** Enhance congressional operations, transparency, and public access to information through targeted civic technology projects.

This is based on the this [wiki](https://github.com/DanielSchuman/Policy/wiki/Leg-Tech) by [DanielSchuman](https://github.com/DanielSchuman)

---

## I. Enhancing Congressional Data Accessibility & Usability
**Focus:** Projects improving the discoverability, structure, and utility of legislative data for both congressional staff and the public.

<table>
<thead><tr><th>Name</th><th>Problem</th><th>Solution</th><th>Value</th><th>Level of Effort (1-5)</th><th>Potential Impact</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>Unified Congressional Hearing & Markup Data Platform
</td><td><details open><summary>Problem</summary>Information about congressional hearings and markups is scattered across multiple websites (Congress.gov, Docs.house.gov, committee pages, YouTube), making it difficult for staff and the public to get a comprehensive view of legislative activity.</details></td><td><details><summary>Solution</summary>Create a centralized, regularly updated platform (initially a spreadsheet, then a public-facing website/wiki) that aggregates key data points:<br> 🔹  Date of the hearing or markup.<br> 🔹  Event Type (Hearing or Markup).<br> 🔹  Title of the Proceeding (and separate column for Event ID).<br> 🔹  Committee of Jurisdiction (and separate column for unique Committee ID).<br> 🔹  Indication of Full Committee or Subcommittee proceeding.<br> 🔹  Direct Links to:<br>&nbsp;&nbsp; 🔹🔹  The committee's webpage for the proceeding.<br>&nbsp;&nbsp; 🔹🔹  The Docs.house.gov page for the proceeding (if it's a House event).<br>&nbsp;&nbsp; 🔹🔹  The video of the proceeding (YouTube or Akami).<br>&nbsp;&nbsp; 🔹🔹  The transcript of the proceeding (when available).<br> 🔹  Phases:<br>&nbsp;&nbsp; 🔹🔹  <b>Data Aggregation (Spreadsheet):</b> Build the initial spreadsheet, populating it with data from the various sources. Implement automated data scraping where possible.<br>&nbsp;&nbsp; 🔹🔹  <b>Public-Facing Platform (Wiki/Website):</b> Publish the aggregated data on a user-friendly website or wiki, with clear navigation and search capabilities. Manage hyperlinks appropriately.<br>&nbsp;&nbsp; 🔹🔹  <b>Alert System:</b> Develop an alert system (e.g., email notifications) to notify users when new information is added for committees they are tracking. <i>Priority: House Administration and Senate Rules Committees.</i></details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Enables staff to efficiently track committee proceedings across different sources, ensuring comprehensive oversight and saving time.<br> 🔹  <b>Civic-Tech:</b> Provides researchers, journalists, and the public with easier access to information, promoting transparency and accountability.</details></td>
<td> 3 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
        Steps: Identify all events, link to assets (youtube video), display aggregate in dashboard
  </details>
</td>
</tr>
<tr><td>Congressional Committee YouTube Video Dashboard & Event ID Tracking
</td><td><details open><summary>Problem</summary>Committees often fail to include official Event IDs in the descriptions of their YouTube videos. This makes it difficult to link videos to official records on Congress.gov and hinders public discoverability.</details></td><td><details><summary>Solution</summary>Develop a dashboard that:<br> 🔹  <b>Tracks All Committee Channels:</b> Monitors all House and Senate committee YouTube channels and their uploaded videos.<br> 🔹  <b>Cross-References with Official Data:</b> Uses APIs from Congress.gov and Docs.house.gov to cross-reference video metadata (title, date, description) with official hearing and markup information. Employs fuzzy logic matching for video titles when Event IDs are missing.<br> 🔹  <b>Displays Consistency Metrics:</b> Presents a clear ranking of committees based on their consistency in including Event IDs in video descriptions.<br> 🔹  <b>Alerts and Reporting:</b><br>&nbsp;&nbsp; 🔹🔹  <i>Potential Feature:</i> Sends automated weekly emails to committee staff, listing videos that are missing Event IDs and providing the correct ID for easy updating.<br>&nbsp;&nbsp; 🔹🔹  Provides a user interface to view detailed information about each committee's video metadata and Event ID compliance.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Empowers staff to easily monitor video metadata consistency across committees, identify areas for improvement, and ensure proper indexing on Congress.gov.<br> 🔹  <b>Civic-Tech:</b> Enhances the discoverability of congressional proceedings on YouTube, making it easier for the public to find and access relevant videos.</details></td>
<td> 2 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    Steps: Identify all events, link to assets (youtube video)
  </details>
</td>
</tr>
<tr><td>Statements of Disbursements as Structured Data
</td><td><details open><summary>Problem</summary>The House's Statements of Disbursements (spending reports) are primarily available as scanned PDF documents, making data analysis and historical trend identification extremely difficult.</details></td><td><details><summary>Solution</summary>Digitize and structure historic Statements of Disbursements data, going back to approximately 1980, into machine-readable spreadsheets.<br> 🔹  <b>Data Source:</b> Utilize existing scrapers developed by the Sunlight Foundation and ProPublica, supplemented by Optical Character Recognition (OCR) and data cleaning techniques. Source historical documents from the Boston Public Library (and other potential archives).<br> 🔹  <b>Data Structure:</b> Create a consistent schema for the extracted data, allowing for easy querying and analysis across different years and reporting periods.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Provides readily analyzable historical data for financial oversight, enabling staff to identify spending trends, anomalies, and potential areas of concern.<br> 🔹  <b>Civic-Tech:</b> Enables researchers, watchdog groups, and journalists to conduct data-driven analyses of congressional spending, promoting accountability and transparency.</details></td>
<td> 4 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    ABG: Existing tools = +; finding historical data from the library = - :( 
  </details>
</td>
</tr>
<tr><td>Appropriations Data Pipeline & Historical Analysis
</td><td><details open><summary>Problem</summary>Information related to the appropriations process (bill text, committee reports, amendments, press releases) is distributed across multiple sources and often experiences delays in being updated on official platforms like Congress.gov.  Analyzing historical line-item spending data and tracking changes in report language over time is also challenging.</details></td><td><details><summary>Solution</summary>Develop a comprehensive system encompassing:<br> 🔹  <b>Real-time Appropriations Tracker:</b> A spreadsheet-based system to track the progress of appropriations bills through each stage of the legislative process (subcommittee, full committee, House/Senate floor, conference committee, joint explanatory statements).  Include:<br>&nbsp;&nbsp; 🔹🔹  Bill text versions at each stage.<br>&nbsp;&nbsp; 🔹🔹  Committee report language versions at each stage.<br>&nbsp;&nbsp; 🔹🔹  Links to press releases summarizing committee actions.<br>&nbsp;&nbsp; 🔹🔹  Details of amendments offered and adopted (or rejected) at each stage.<br>&nbsp;&nbsp; 🔹🔹  <i>Leverage an existing spreadsheet example as a starting point.</i><br> 🔹  <b>Line-Item Data Extraction & Visualization:</b> Extract line-item spending data from appropriations committee reports and transform it into structured data tables.  Develop visualizations to track spending trends over time and across different accounts.<br> 🔹  <b>Report Language Analysis:</b> Implement a system to:<br>&nbsp;&nbsp; 🔹🔹  Identify changes in bill and report language as measures move through the legislative process.<br>&nbsp;&nbsp; 🔹🔹  Compare House and Senate versions of bill and report language to highlight differences.<br>&nbsp;&nbsp; 🔹🔹  Flag deadlines and directives to agencies contained within report language.<br>&nbsp;&nbsp; 🔹🔹  <i>Advanced Feature Suggestion:</i> Perform trend analysis on recurring report language sections across multiple Congresses to illustrate the evolution of policy and funding priorities.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Streamlines the appropriations tracking process for staff, facilitating detailed analysis of spending changes, legislative intent embedded in report language, and mandated agency actions. Historical data analysis tools offer deeper insights into long-term spending patterns.<br> 🔹  <b>Civic-Tech:</b>  Increases transparency surrounding the appropriations process, making it easier for the public, researchers, and advocacy groups to track spending priorities and hold Congress accountable.</details></td>
<td> 5+ </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
        Steps: make appropriations database, identify all events, link to assets (bills & bill actions), interpret assets as steps in appropriations process, match to appropriations database, make web UI for live tracking
  </details>
</td>
</tr>
</tbody>
</table>

## II. Workflow Efficiency Tools for Congressional Operations
**Focus:** Streamlining workflows to improve efficiency for congressional staff.

<table>
<thead><tr><th>Name</th><th>Problem</th><th>Solution</th><th>Value</th><th>Level of Effort (1-5)</th><th>Potential Impact</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>Automated Google Doc Creator for Meetings
</td><td><details open><summary>Problem</summary>Manually creating Google Docs for meeting notes is a repetitive and time-consuming task, often leading to inconsistencies in formatting and file naming.</details></td><td><details><summary>Solution</summary>Develop a Firefox browser bookmarklet that automates the creation of new Google Docs for meeting notes:<br> 🔹  <b>Folder Creation:</b> Creates the new document within a pre-defined Google Drive folder.<br> 🔹  <b>Standardized Naming:</b> Automatically names the file using a consistent format: `YYYY-MM-DD [Person's Name]`.  (e.g., "2025-01-15 Jane Smith"). A window should popup prompting the user for this name.<br> 🔹  <b>Pre-populated Format:</b>  Sets up the document with a pre-defined template:<br>&nbsp;&nbsp; 🔹🔹  Person's name centered on the first line.<br>&nbsp;&nbsp; 🔹🔹  Date centered on the second line.<br>&nbsp;&nbsp; 🔹🔹  Cursor positioned, left-aligned, on the fourth line for note-taking.<br> 🔹  <b>Deployment:</b> <i>Current Status:</i> The script is already built, but deployment as a persistent Firefox bookmarklet is the remaining challenge.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Saves staff valuable time and ensures consistency in meeting documentation practices across offices.<br> 🔹  <b>Civic-Tech:</b> Demonstrates a practical, quick-win solution that can be readily implemented within a congressional environment.</details></td>
<td> 2 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    browser extension
  </details>
</td>
</tr>
<tr><td>GitHub Wiki Indexing Bookmarklet
</td><td><details open><summary>Problem</summary>Manually creating and maintaining indexes for GitHub Wiki pages is tedious and time-consuming, especially for large or complex wikis.</details></td><td><details><summary>Solution</summary>Develop a Firefox browser bookmarklet that automatically generates a table of contents (index) for any GitHub Wiki page. The bookmarklet should parse the page's headings (H1, H2, H3, etc.) and create links to those sections.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Enhances internal documentation and knowledge sharing within congressional offices that utilize GitHub wikis for collaborative projects or internal knowledge bases.<br> 🔹  <b>Civic-Tech:</b> A useful general-purpose tool for anyone managing GitHub wikis in collaborative projects, improving navigation and usability.</details></td>
<td> 2 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    browser extension
  </details>
</td>
</tr>
<tr><td>Crosswalk Spreadsheet to Member Office Appropriations Submission Tool
</td><td><details open><summary>Problem</summary>Submitting appropriations requests to multiple Member offices is a highly manual and error-prone process.  Each office typically has its own Google Form with slightly different fields and formats, requiring repetitive data entry and increasing the risk of mistakes.</details></td><td><details><summary>Solution</summary>Develop a tool that streamlines the submission of appropriations requests:<br> 🔹  <b>"Crosswalk" Functionality:</b> Allows users to create a standardized spreadsheet containing all their appropriations requests. The tool then "crosswalks" this data to the specific fields and formats required by each individual Member office's Google Form.<br> 🔹  <b>Automated Form Filling:</b> Automates the process of filling out and submitting multiple Google Forms, reusing the data from the standardized spreadsheet and minimizing manual data entry.<br> 🔹  <b>Input Flexibility:</b><br>&nbsp;&nbsp; 🔹🔹  <i>Enhancement:</i> Provide a feature to transform a Google Doc containing appropriations requests into the standardized spreadsheet format, further reducing manual input.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Dramatically reduces the time and effort required for staff to submit appropriations requests to numerous offices, minimizing errors and improving efficiency.<br> 🔹  <b>Civic-Tech:</b> Directly addresses a well-understood pain point in the appropriations process, making it easier for organizations and individuals to engage with Congress on funding priorities.</details></td>
<td> 3 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    Proposed technical solution:
    <ol>
        <li><strong>Form scraping:</strong> A GitHub Actions workflow runs Playwright to scrape live Google Forms from all participating Members of Congress. For each form, it extracts all visible labels, input types, and field metadata.</li>
        <li><strong>Fuzzy matching & mapping:</strong> Each scraped form’s fields are run through a fuzzy matching engine that adds them to a growing canonical list of standardized field names. This process builds a crosswalk: a mapping from each live label to a canonical schema key (e.g., mapping "Title of Project" → "Project Name"). The result is stored in a <code>translations.csv</code> (or JSON) file, associating each MOC’s form fields with standardized identifiers.</li>
        <li><strong>Schema & version publishing:</strong> The <code>translations.csv</code> and a <code>version.txt</code> file (containing a hash) are published publicly (committed to the repo and accessed by `raw.githubusercontent.com`) for use by the template sheet and chrome/firefox extension.</li>
        <li><strong>Template Sheet:</strong> A read-only Google Sheet imports <code>translations.csv</code> into a hidden sheet using <code>=IMPORTDATA</code>. A second, visible, sheet exposes only the ~15 common input columns. The hidden sheet uses formulas to reference the visible columns based on the precomputed mappings from <code>translations.csv</code>, generating values for all 500 canonical fields without additional user input.</li>
        <li><strong>Version enforcement:</strong> The sheet also imports the remote <code>version.txt</code> into a designated cell (ABG: there needs to be a hard copy step at template duplication otherwise this will be a circular reference). The Chrome extension checks this value against the latest published value (by accessing it itself). If there’s a mismatch, the extension blocks execution, ensuring users don’t submit data using an outdated template sheet. </li>
        <li><strong>Staffer workflow:</strong> Staffers duplicate the template and enter their data in the ~15 visible fields. Once ready, they click the Chrome extension to begin the guided submission process.</li>
        <li><strong>Chrome Extension:</strong> The extension loads the full ~500 field values from the hidden sheet values into memory (ABG: or if necessary don't hide the sheet, point is to avoid auth by scraping the values directly from the open tab) and presents a UI showing submission progress. The extension will navigate the user to each MOC's form and autofill in the correct inputs from the ~500 field values on the live Google Form. The staffer manually reviews each form and submits. After each form, they advance to the next using the extension UI.</li>
    </ol>
    ABG: Could also build out the Chrome extension such that clicking it from any page that isn't the template will duplicate a new template for you and navigate you to it. For the proposed enhancement, that would require live fuzzy matching which would require a backend and an API. Very different solution required-- unfortunately. Could look into browser-based fuzzy matching solutions with web assembly.
  </details>
</td>
</tr>
<tr><td>Floor Schedule to iCal & Enhanced Congressional Schedule Aggregation
</td><td><details open><summary>Problem</summary>Floor schedules and committee schedules are typically provided in separate, non-integrated formats, making it difficult to get a holistic view of the congressional calendar.</details></td><td><details><summary>Solution</summary><br> 🔹  <b>Floor Schedule iCal Generation:</b> Develop a script or tool to automatically transform publicly available House and Senate floor schedule data (from official notices) into iCal (.ics) format. This allows users to easily import the floor schedule into their personal calendars (Google Calendar, Outlook, etc.).<br> 🔹  <b>Integrated Congressional Schedule:</b>  Explore integrating floor schedule data into existing committee schedule tracking platforms (such as Congress.gov and GovTrack.us). This would provide a unified view of both floor action and committee meetings, improving overall schedule awareness.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Improves schedule management and awareness for staff who need to track both floor action and committee meetings concurrently. Provides a more comprehensive picture of the legislative week.<br> 🔹  <b>Civic-Tech:</b> Offers a more accessible and unified view of the congressional schedule for the public, facilitating engagement and informed participation.</details></td>
<td> 1 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    Steps: Identify all events
  </details>
</td>
</tr>
<tr><td>Congressional Job Board Aggregator
</td><td><details open><summary>Problem</summary>Congressional job postings are scattered across various sources, including weekly PDFs, Senate websites, and USAJOBS, creating an inefficient and time-consuming search process for prospective applicants.</details></td><td><details><summary>Solution</summary>Create a centralized platform (BSky feed, spreadsheet, or dedicated website) to aggregate congressional job postings from multiple sources:<br> 🔹  <b>House Employment Bulletin PDFs:</b> Parse and clean the data from the weekly House Employment Bulletin PDFs, likely using AI-powered techniques to extract job titles, descriptions, and application information.<br> 🔹  <b>Senate Postings:</b> Scrape job postings from the Senate's websites for both political and non-political entities.<br> 🔹  <b>House Support Office Websites:</b> Scrape job postings directly from the websites of House support offices.<br> 🔹  <b>USAJOBS:</b> Monitor USAJOBS for relevant postings from congressional support offices and agencies (e.g., GAO, Library of Congress, CRS, USCP, Architect of the Capitol).<br> 🔹  <b>Tracking:</b> Keep track of when job postings are first published.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Streamlines the hiring process for congressional offices by expanding their reach to potential candidates and making it easier to advertise open positions.<br> 🔹  <b>Civic-Tech:</b> Makes congressional employment opportunities more accessible and transparent to the public, encouraging a wider range of individuals to consider careers on Capitol Hill.</details></td>
<td> 1 </td>
<td> <!-- TODO: Potential Impact --> </td>
<td>
  <details>
    <summary>Notes</summary>
    <!-- TODO: Add notes here -->
  </details>
</td>
</tr>
</tbody>
</table>

## III. Leveraging AI for Content Enhancement & Analysis
**Focus:** Explore AI applications to improve congressional information quality and analysis.

<table>
<thead><tr><th>Name</th><th>Problem</th><th>Solution</th><th>Value</th><th>Level of Effort (1-5)</th><th>Potential Impact</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>CRS Report Accessibility & Integration
</td><td><details open><summary>Problem</summary>CRS Reports are a vital source of non-partisan policy analysis, but they have historically been less accessible to the public and not fully integrated into broader online policy discussions.</details></td><td><details><summary>Solution</summary>Undertake a multi-faceted project to enhance CRS Report accessibility and integration:<br> 🔹  <b>EveryCRSReport.com Enhancement:</b> Integrate the newly available HTML versions of CRS Reports (accessible via API from CRS.Congress.gov) onto EveryCRSReport.com.<br> 🔹  <b>HTML Conversion of Legacy Reports:</b> Utilize existing tools (and potentially refine them) to convert older CRS Reports (currently available primarily as PDFs) into HTML format. <i>Investigate the committee.report tool as a potential solution.</i> Ideally, convert to Markdown for maximum flexibility.<br> 🔹  <b>Multi-Format Distribution:</b> Generate EPUB versions of all CRS Reports (both new and converted) to make them easily readable on e-readers and mobile devices. <i>Consider low-cost or free distribution on platforms like Amazon.com to counter vendors charging excessive prices for older reports.</i><br> 🔹  <b>AI-Powered Tagging and Subject Identification:</b> Employ AI techniques (e.g., natural language processing, topic modeling) to analyze the content of CRS Reports and automatically generate subject matter tags. This will improve search and discovery on EveryCRSReport.com.<br> 🔹  <b>Wikipedia Integration:</b> Explore using AI and other technologies to systematically incorporate the content and citations from CRS Reports into relevant Wikipedia pages. This will improve the quality and accuracy of Wikipedia articles on policy topics and provide readers with direct links to authoritative sources.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Improves staff research efficiency by making CRS Reports more accessible, searchable, and discoverable in modern formats.<br> 🔹  <b>Civic-Tech:</b> Democratizes access to high-quality, non-partisan policy analysis, enhances Wikipedia as a public resource, combats misinformation by increasing the visibility of credible research, and promotes informed public discourse.</details></td>
<td> 3 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    <!-- TODO: Add notes here -->
  </details>
</td>
</tr>
<tr><td>GAO Report Transformation & Dissemination
</td><td><details open><summary>Problem</summary>GAO Reports are typically published as PDF documents, which are not optimized for accessibility, searchability, or re-use in different formats.</details></td><td><details><summary>Solution</summary><br> 🔹  <b>GAO Report to Markdown/EPUB Conversion:</b> Develop or adapt a tool to transform GAO Report PDFs into Markdown format (for maximum flexibility and future-proofing) and EPUB format (for easy reading on e-readers). <i>Investigate existing tools that might offer partial solutions.</i><br> 🔹  <b>GAO Report Hosting and Publication:</b> Host the converted GAO Reports on a publicly accessible platform and develop a system for disseminating them widely.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Enables staff to more easily read, search, and utilize GAO Reports in various formats, improving their ability to conduct oversight and inform policy decisions.<br> 🔹  <b>Civic-Tech:</b> Makes GAO Reports significantly more accessible to the public, researchers, and journalists, promoting government oversight and accountability.</details></td>
<td> 3 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    <!-- TODO: Add notes here -->
  </details>
</td>
</tr>
<tr><td>Automated Committee Hearing Transcripts & Summaries
</td><td><details open><summary>Problem</summary>Official transcripts of committee hearings are often delayed by a year or more, or require expensive private services for timely access. This hinders both congressional staff's ability to quickly analyze hearing content and the public's access to information.</details></td><td><details><summary>Solution</summary><br> 🔹  <b>Real-Time Transcript Generation:</b> Implement AI-powered speech-to-text tools to create immediate (though potentially not perfectly accurate) transcripts of committee proceedings. Publish these transcripts on a dedicated, static website.<br> 🔹  <b>Automated Summarization:</b> Explore the use of AI-based summarization techniques (e.g., natural language processing) to generate concise summaries of the key topics discussed in each hearing.<br> 🔹  <b>Format Versatility:</b> Publish transcripts in multiple formats, including EPUB for e-readers.  Integrate the transcripts with the "Unified Hearing & Markup Data" project (described above) to provide a comprehensive record of each proceeding.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Provides near real-time access to hearing content for staff analysis, communication, and legislative drafting, bypassing the delays and costs associated with official transcripts.<br> 🔹  <b>Civic-Tech:</b> Greatly enhances public transparency and access to the content of congressional hearings, allowing citizens, journalists, and researchers to follow proceedings more closely and in a timely manner.</details></td>
<td> 2.5 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    Steps: Identify all events, link to assets (youtube video), extract transcript (youtube transcript?)
  </details>
</td>
</tr>
<tr><td>Write My GovTrack Newsletter (AI-Powered Legislative Newsletter)
</td><td><details open><summary>Problem</summary>Manually compiling a weekly legislative newsletter summarizing floor action, committee activity, and recently passed resolutions is a time-consuming task.</details></td><td><details><summary>Solution</summary>Develop an AI-powered tool to automatically generate a newsletter similar in format to GovTrack's weekly updates, drawing data from various sources:<br> 🔹  <b>Data Sources:</b><br>&nbsp;&nbsp; 🔹🔹  House and Senate floor schedules and notices.<br>&nbsp;&nbsp; 🔹🔹  Committee schedule information.<br>&nbsp;&nbsp; 🔹🔹  The Congressional Record (for information on resolutions passed, particularly "sneaky" resolutions that may not be readily apparent on Congress.gov).<br> 🔹  <b>Newsletter Content Modules:</b><br>&nbsp;&nbsp; 🔹🔹  <b>House Floor Action Summary:</b> A concise overview of bills up for a vote, including those on suspension.<br>&nbsp;&nbsp; 🔹🔹  <b>Senate Floor Action Summary:</b> A summary of bills and nominations being considered on the Senate floor (potentially extracting information from the "colloquy").<br>&nbsp;&nbsp; 🔹🔹  <b>Committee Hearing/Markup Overview:</b> A summary of committee activity in each chamber, organized by frequency of meetings and highlighting key committees (e.g., Appropriations, Armed Services for NDAA) and significant nominations.<br>&nbsp;&nbsp; 🔹🔹  <b>Daily Resolution Alerts:</b> Automated alerts for resolutions passed the previous day, including the full text of the resolution (often published in the Congressional Record but not always easily accessible on Congress.gov).</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Could provide a customizable newsletter template for congressional offices to quickly and efficiently distribute legislative updates to constituents, saving staff time and improving communication.<br> 🔹  <b>Civic-Tech:</b> Provides a scalable model for creating informative legislative newsletters, enhancing public awareness of congressional activities and promoting civic engagement.</details></td>
<td> 5 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    Steps: Identify all events, link to assets (youtube video), extract transcript (youtube transcript?), analyze content, rank importance, generate (newsletter) text
  </details>
</td>
</tr>
<tr><td>Witness Database with Proceeding Links & Testimony Summarization
</td><td><details open><summary>Problem</summary>Witness testimony is typically siloed within the records of individual hearings. Tracking a particular witness's appearances and the content of their testimony across multiple committees and Congresses is a difficult and time-consuming manual process.</details></td><td><details><summary>Solution</summary>Create a comprehensive database of congressional witnesses that includes:<br> 🔹  <b>Unique Witness IDs:</b> Assign a unique identifier to each witness.<br> 🔹  <b>Proceeding Links:</b> Track all proceedings (hearings and markups) where the witness has testified, with links to the relevant records.<br> 🔹  <b>Testimony Transcripts:</b> Include transcripts of both written and oral remarks made by the witness.<br> 🔹  <b>Testimony Summaries:</b> Generate summaries of both written and oral testimony, potentially using AI-powered summarization techniques.<br> 🔹  <b>Questions for the Record (QFRs):</b> Capture Questions for the Record submitted to the witness and their responses, which often appear in committee transcripts.<br> 🔹  <b>Indexing:</b> Index the database by both the witness's name <i>and</i> their title/affiliation (e.g., "Jane Smith," "FAA Administrator"). This allows for searching based on specific individuals or roles.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Enables staff to easily track the expertise and past testimony of witnesses across committees and over time, facilitating issue analysis, identifying key stakeholders, and preparing for future hearings.<br> 🔹  <b>Civic-Tech:</b> Creates a valuable public resource for researching expert testimony on legislative issues, enhancing transparency, accountability, and informed public discourse.</details></td>
<td> 5 </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    Steps: Identify all events, link to assets (youtube video), extract transcript (youtube transcript?), analyze content, identify named entities, track/store in database, build interface to access database
  </details>
</td>
</tr>
</tbody>
</table>

## IV. Predictive & Analytical Tools for Legislative Insight
**Focus:** Projects using data to generate predictive insights and facilitate analysis of legislative processes.

<table>
<thead><tr><th>Name</th><th>Problem</th><th>Solution</th><th>Value</th><th>Level of Effort (1-5)</th><th>Potential Impact</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>Bills to Committee Referral Prediction
</td><td><details open><summary>Problem</summary>Understanding bill referral patterns is important for legislative strategy, but manually analyzing historical data to predict which committees will receive jurisdiction over a new bill is time-consuming.</details></td><td><details><summary>Solution</summary>Develop a predictive model, using machine learning techniques, to forecast bill referrals to committees based on historical referral patterns. The model should consider factors such as bill text, sponsor, and subject matter.  The output could be:<br> 🔹  A standalone dataset of predicted referrals.<br> 🔹  An add-on application that integrates with existing legislative tracking platforms like Congress.gov or GovTrack.us.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Provides strategic insights for legislative staff, helping them anticipate the likely committee jurisdiction for new bills and inform coalition-building and amendment strategies.<br> 🔹  <b>Civic-Tech:</b> Could offer researchers, advocacy groups, and the public better insight into the likely path of legislation through Congress, allowing for more effective engagement.</details></td>
<td> <!-- TODO: Level of Effort (1-5) --> </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    <!-- TODO: Add notes here -->
  </details>
</td>
</tr>
<tr><td>Bill Delay Tracker
</td><td><details open><summary>Problem</summary>There are often delays between the publication of bill text on Congress.gov and the availability of a corresponding bill summary. This delay hinders users who need a quick overview of new legislation.</details></td><td><details><summary>Solution</summary>Create a dashboard that tracks the time lag between bill text publication and Congress.gov summary availability. The dashboard should provide metrics such as:<br> 🔹  The total number of pages in the bills processed.<br> 🔹  The number of bills summarized.<br> 🔹  The number of bills that have been reported by a committee.<br> 🔹  Average, median, and maximum delay times.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Provides data-driven feedback to the Congress.gov development team on summary processing times and identifies areas for improvement in their workflow.<br> 🔹  <b>Civic-Tech:</b> Highlights an important user experience issue with Congress.gov, promoting transparency and advocating for improvements to the platform.</details></td>
<td> <!-- TODO: Level of Effort (1-5) --> </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    <!-- TODO: Add notes here -->
  </details>
</td>
</tr>
<tr><td>Appropriations Notices & Deadlines Tracker
</td><td><details open><summary>Problem</summary>Information about upcoming appropriations proceedings (instructions for public witnesses and Member offices, deadlines for submitting testimony, hearing dates) is scattered across the websites of the House and Senate Appropriations Committees and their 12 subcommittees. This makes it difficult to track deadlines and requirements comprehensively.</details></td><td><details><summary>Solution</summary>Create a centralized system (spreadsheet or dedicated website) to gather and organize appropriations-related information:<br> 🔹  <b>Public Witness Instructions:</b> Instructions for public witnesses seeking to provide testimony.<br> 🔹  <b>Member Office Instructions:</b> Instructions for Member offices submitting testimony or requests.<br> 🔹  <b>Deadlines:</b><br>&nbsp;&nbsp; 🔹🔹  Due dates for the public to submit written testimony.<br>&nbsp;&nbsp; 🔹🔹  Due dates for the public to request to testify in person.<br>&nbsp;&nbsp; 🔹🔹  Due dates for Member offices to request to testify.<br>&nbsp;&nbsp; 🔹🔹  Due dates for Member offices to submit written testimony.<br> 🔹  <b>Hearing Dates:</b><br>&nbsp;&nbsp; 🔹🔹  Dates of public witness testimony hearings.<br>&nbsp;&nbsp; 🔹🔹  Dates for Member office testimony.<br> 🔹  <b>Communication Channels:</b> Information on to whom submissions should be sent.<br> 🔹  <i>Leverage an existing spreadsheet model as a starting point.</i></details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> An essential tool for staff involved in the appropriations process, enabling them to manage deadlines, submit testimony effectively, and track key hearing dates for both public and Member witnesses.<br> 🔹  <b>Civic-Tech:</b> Increases transparency and facilitates public participation in the appropriations process by making deadlines and procedures clearer and more accessible.</details></td>
<td> <!-- TODO: Level of Effort (1-5) --> </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    <!-- TODO: Add notes here -->
  </details>
</td>
</tr>
<tr><td>Committee Funding Tracker & Visualization
</td><td><details open><summary>Problem</summary>Information on the funding levels allocated to House and Senate committees is not readily accessible or easily tracked over time.</details></td><td><details><summary>Solution</summary>Locate and extract data from committee funding resolutions passed by the House and Senate for each Congress.  These resolutions typically follow a formula. Compile the extracted data into a spreadsheet, going back as far as possible, and develop visualizations to show funding trends over time.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Provides a historical overview of committee resource allocation, which can be useful for budget analysis and understanding how resources have been distributed across different committees over time.<br> 🔹  <b>Civic-Tech:</b> Increases transparency regarding the financial resources allocated to different congressional committees, allowing for potential oversight analysis and public scrutiny.</details></td>
<td> <!-- TODO: Level of Effort (1-5) --> </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    <!-- TODO: Add notes here -->
  </details>
</td>
</tr>
<tr><td>Line Up CBJs and Appropriations Committee Report Language
</td><td><details open><summary>Problem</summary>Connecting agency budget justifications (CBJs) with relevant sections of appropriations committee reports (which explain funding decisions and provide directives to agencies) requires manual cross-referencing and analysis.</details></td><td><details><summary>Solution</summary>Develop a system to automatically link sections of CBJs to corresponding sections in appropriations committee reports. This could involve:<br> 🔹  <b>Keyword Matching:</b> Identifying shared keywords and phrases between CBJ sections and report sections.<br> 🔹  <b>Topic Modeling:</b> Using natural language processing techniques to identify thematic similarities between documents.<br> 🔹  <b>Machine Learning:</b> Training a model to recognize relationships between CBJ requests and committee report language.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> Streamlines the analysis of appropriations bills by directly connecting stated agency funding requests with congressional justifications and directives articulated in committee reports. Facilitates a deeper understanding of appropriations intent and the rationale behind funding decisions.<br> 🔹  <b>Civic-Tech:</b> Enhances public understanding of how congressional appropriations align (or deviate from) agency budget requests and policy priorities as expressed in report language. Promotes greater accountability and transparency in the appropriations process.</details></td>
<td> <!-- TODO: Level of Effort (1-5) --> </td>
<td> <!-- TODO: Potential Impact --></td>
<td>
  <details>
    <summary>Notes</summary>
    <!-- TODO: Add notes here -->
  </details>
</td>
</tr>
</tbody>
</table>

## V. Basic Utility Tools
Focus: N/A

<table>
<thead><tr><th>Name</th><th>Problem</th><th>Solution</th><th>Value</th><th>Level of Effort (1-5)</th><th>Potential Impact</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>
  <s> <a href="https://github.com/agurvich/congressional-tech/tree/main/projects/5.1-inflation-gsheets" target="_blank"> Inflation Calculator for Google Sheets </a> </s>
</td><td><details open><summary>Problem</summary>Manually calculating inflation across different years in spreadsheets is inefficient and prone to errors.</details></td><td><details><summary>Solution</summary>Create a custom formula for Google Sheets that leverages inflation data from the Bureau of Labor Statistics (BLS) or another reliable source to automatically calculate the inflation-adjusted value of a monetary amount.<br> 🔹  <b>Formula Structure:</b> The formula should take three inputs:<br>&nbsp;&nbsp; 🔹🔹  `source_cell`: The cell containing the original monetary amount.<br>&nbsp;&nbsp; 🔹🔹  `start_year_cell`: The cell containing the year of the original amount.<br>&nbsp;&nbsp; 🔹🔹  `end_year_cell`: The cell containing the year to which the amount should be adjusted.<br> 🔹  <b>Example Formula:</b> `=INFLATION(A2, B2, C2)` (where A2 contains the amount, B2 the start year, and C2 the end year).<br> 🔹  The formula should also be "drag-able" to automatically update references for a range of data, allowing the inflation calculations to be easily expanded down a column.</details></td><td><details><summary>Value</summary><br> 🔹  <b>Congressional-Tech:</b> A useful tool for staff performing economic analysis, cost adjustments, and budget projections in spreadsheets.<br> 🔹  <b>Civic-Tech:</b> A widely applicable utility for general users who need to perform inflation calculations in their spreadsheets, enhancing the functionality of Google Sheets.</details></td>
<td> 1 </td>
<td> <!-- TODO: Potential Impact --> </td>
<td>
  <details>
    <summary>Notes</summary>
    The current solution relies on a <a href="https://github.com/agurvich/congressional-tech/blob/main/.github/workflows/bls-cpi-update.yml" target="_blank"> Github Action </a> that updates a CSV to mirror the data from the Bureau of Labor Statistics.
  </details>
</td>
</tr>
</tbody>
</table>

