# congressional-tech

# Civic & Congressional Tech Project Proposals

We're establishing a relationship with key technical personel in and around congress, this is an aggregated list of problems that have been identified, and are potential project ideas.

**Overarching Goal:** Enhance congressional operations, transparency, and public access to information through targeted civic technology projects.

---

## I. Enhancing Congressional Data Accessibility & Usability

**Focus:** Projects improving the discoverability, structure, and utility of legislative data for both congressional staff and the public.

### 1. Unified Congressional Hearing & Markup Data Platform

*   **Problem:** Information about congressional hearings and markups is scattered across multiple websites (Congress.gov, Docs.house.gov, committee pages, YouTube), making it difficult for staff and the public to get a comprehensive view of legislative activity.
*   **Solution:** Create a centralized, regularly updated platform (initially a spreadsheet, then a public-facing website/wiki) that aggregates key data points:
    *   Date of the hearing or markup.
    *   Event Type (Hearing or Markup).
    *   Title of the Proceeding (and separate column for Event ID).
    *   Committee of Jurisdiction (and separate column for unique Committee ID).
    *   Indication of Full Committee or Subcommittee proceeding.
    *   Direct Links to:
        *   The committee's webpage for the proceeding.
        *   The Docs.house.gov page for the proceeding (if it's a House event).
        *   The video of the proceeding (YouTube or Akami).
        *   The transcript of the proceeding (when available).
*   **Phases:**
    1.  **Data Aggregation (Spreadsheet):** Build the initial spreadsheet, populating it with data from the various sources. Implement automated data scraping where possible.
    2.  **Public-Facing Platform (Wiki/Website):** Publish the aggregated data on a user-friendly website or wiki, with clear navigation and search capabilities. Manage hyperlinks appropriately.
    3.  **Alert System:** Develop an alert system (e.g., email notifications) to notify users when new information is added for committees they are tracking. *Priority: House Administration and Senate Rules Committees.*
*   **Value:**
    *   **Congressional-Tech:** Enables staff to efficiently track committee proceedings across different sources, ensuring comprehensive oversight and saving time.
    *   **Civic-Tech:** Provides researchers, journalists, and the public with easier access to information, promoting transparency and accountability.

### 2. Congressional Committee YouTube Video Dashboard & Event ID Tracking

*   **Problem:** Committees often fail to include official Event IDs in the descriptions of their YouTube videos. This makes it difficult to link videos to official records on Congress.gov and hinders public discoverability.
*   **Solution:** Develop a dashboard that:
    *   **Tracks All Committee Channels:** Monitors all House and Senate committee YouTube channels and their uploaded videos.
    *   **Cross-References with Official Data:** Uses APIs from Congress.gov and Docs.house.gov to cross-reference video metadata (title, date, description) with official hearing and markup information. Employs fuzzy logic matching for video titles when Event IDs are missing.
    *   **Displays Consistency Metrics:** Presents a clear ranking of committees based on their consistency in including Event IDs in video descriptions.
    *   **Alerts and Reporting:**
        *   *Potential Feature:* Sends automated weekly emails to committee staff, listing videos that are missing Event IDs and providing the correct ID for easy updating.
        *   Provides a user interface to view detailed information about each committee's video metadata and Event ID compliance.
*   **Value:**
    *   **Congressional-Tech:** Empowers staff to easily monitor video metadata consistency across committees, identify areas for improvement, and ensure proper indexing on Congress.gov.
    *   **Civic-Tech:** Enhances the discoverability of congressional proceedings on YouTube, making it easier for the public to find and access relevant videos.

### 3. Statements of Disbursements as Structured Data

*   **Problem:** The House's Statements of Disbursements (spending reports) are primarily available as scanned PDF documents, making data analysis and historical trend identification extremely difficult.
*   **Solution:** Digitize and structure historic Statements of Disbursements data, going back to approximately 1980, into machine-readable spreadsheets.
    *   **Data Source:** Utilize existing scrapers developed by the Sunlight Foundation and ProPublica, supplemented by Optical Character Recognition (OCR) and data cleaning techniques. Source historical documents from the Boston Public Library (and other potential archives).
    *   **Data Structure:** Create a consistent schema for the extracted data, allowing for easy querying and analysis across different years and reporting periods.
*   **Value:**
    *   **Congressional-Tech:** Provides readily analyzable historical data for financial oversight, enabling staff to identify spending trends, anomalies, and potential areas of concern.
    *   **Civic-Tech:** Enables researchers, watchdog groups, and journalists to conduct data-driven analyses of congressional spending, promoting accountability and transparency.

### 4. Appropriations Data Pipeline & Historical Analysis

*   **Problem:** Information related to the appropriations process (bill text, committee reports, amendments, press releases) is distributed across multiple sources and often experiences delays in being updated on official platforms like Congress.gov.  Analyzing historical line-item spending data and tracking changes in report language over time is also challenging.
*   **Solution:** Develop a comprehensive system encompassing:
    *   **Real-time Appropriations Tracker:** A spreadsheet-based system to track the progress of appropriations bills through each stage of the legislative process (subcommittee, full committee, House/Senate floor, conference committee, joint explanatory statements).  Include:
        *   Bill text versions at each stage.
        *   Committee report language versions at each stage.
        *   Links to press releases summarizing committee actions.
        *   Details of amendments offered and adopted (or rejected) at each stage.
        *   *Leverage an existing spreadsheet example as a starting point.*
    *   **Line-Item Data Extraction & Visualization:** Extract line-item spending data from appropriations committee reports and transform it into structured data tables.  Develop visualizations to track spending trends over time and across different accounts.
    *   **Report Language Analysis:** Implement a system to:
        *   Identify changes in bill and report language as measures move through the legislative process.
        *   Compare House and Senate versions of bill and report language to highlight differences.
        *   Flag deadlines and directives to agencies contained within report language.
        *   *Advanced Feature Suggestion:* Perform trend analysis on recurring report language sections across multiple Congresses to illustrate the evolution of policy and funding priorities.
*   **Value:**
    *   **Congressional-Tech:** Streamlines the appropriations tracking process for staff, facilitating detailed analysis of spending changes, legislative intent embedded in report language, and mandated agency actions. Historical data analysis tools offer deeper insights into long-term spending patterns.
    *   **Civic-Tech:**  Increases transparency surrounding the appropriations process, making it easier for the public, researchers, and advocacy groups to track spending priorities and hold Congress accountable.

---

## II. Workflow Efficiency Tools for Congressional Operations

**Focus:** Streamlining workflows to improve efficiency for congressional staff.

### 1. Automated Google Doc Creator for Meetings

*   **Problem:** Manually creating Google Docs for meeting notes is a repetitive and time-consuming task, often leading to inconsistencies in formatting and file naming.
*   **Solution:** Develop a Firefox browser bookmarklet that automates the creation of new Google Docs for meeting notes:
    *   **Folder Creation:** Creates the new document within a pre-defined Google Drive folder.
    *   **Standardized Naming:** Automatically names the file using a consistent format: `YYYY-MM-DD [Person's Name]`.  (e.g., "2025-01-15 Jane Smith"). A window should popup prompting the user for this name.
    *   **Pre-populated Format:**  Sets up the document with a pre-defined template:
        *   Person's name centered on the first line.
        *   Date centered on the second line.
        *   Cursor positioned, left-aligned, on the fourth line for note-taking.
    *   **Deployment:** *Current Status:* The script is already built, but deployment as a persistent Firefox bookmarklet is the remaining challenge.
*   **Value:**
    *   **Congressional-Tech:** Saves staff valuable time and ensures consistency in meeting documentation practices across offices.
    *   **Civic-Tech:** Demonstrates a practical, quick-win solution that can be readily implemented within a congressional environment.

### 2. GitHub Wiki Indexing Bookmarklet

*   **Problem:** Manually creating and maintaining indexes for GitHub Wiki pages is tedious and time-consuming, especially for large or complex wikis.
*   **Solution:** Develop a Firefox browser bookmarklet that automatically generates a table of contents (index) for any GitHub Wiki page. The bookmarklet should parse the page's headings (H1, H2, H3, etc.) and create links to those sections.
*   **Value:**
    *   **Congressional-Tech:** Enhances internal documentation and knowledge sharing within congressional offices that utilize GitHub wikis for collaborative projects or internal knowledge bases.
    *   **Civic-Tech:** A useful general-purpose tool for anyone managing GitHub wikis in collaborative projects, improving navigation and usability.

### 3. Crosswalk Spreadsheet to Member Office Appropriations Submission Tool

*   **Problem:** Submitting appropriations requests to multiple Member offices is a highly manual and error-prone process.  Each office typically has its own Google Form with slightly different fields and formats, requiring repetitive data entry and increasing the risk of mistakes.
*   **Solution:** Develop a tool that streamlines the submission of appropriations requests:
    *   **"Crosswalk" Functionality:** Allows users to create a standardized spreadsheet containing all their appropriations requests. The tool then "crosswalks" this data to the specific fields and formats required by each individual Member office's Google Form.
    *   **Automated Form Filling:** Automates the process of filling out and submitting multiple Google Forms, reusing the data from the standardized spreadsheet and minimizing manual data entry.
    *   **Input Flexibility:**
        *   *Enhancement:* Provide a feature to transform a Google Doc containing appropriations requests into the standardized spreadsheet format, further reducing manual input.
*   **Value:**
    *   **Congressional-Tech:** Dramatically reduces the time and effort required for staff to submit appropriations requests to numerous offices, minimizing errors and improving efficiency.
    *   **Civic-Tech:** Directly addresses a well-understood pain point in the appropriations process, making it easier for organizations and individuals to engage with Congress on funding priorities.

### 4. Floor Schedule to iCal & Enhanced Congressional Schedule Aggregation

*   **Problem:** Floor schedules and committee schedules are typically provided in separate, non-integrated formats, making it difficult to get a holistic view of the congressional calendar.
*   **Solution:**
    *   **Floor Schedule iCal Generation:** Develop a script or tool to automatically transform publicly available House and Senate floor schedule data (from official notices) into iCal (.ics) format. This allows users to easily import the floor schedule into their personal calendars (Google Calendar, Outlook, etc.).
    *   **Integrated Congressional Schedule:**  Explore integrating floor schedule data into existing committee schedule tracking platforms (such as Congress.gov and GovTrack.us). This would provide a unified view of both floor action and committee meetings, improving overall schedule awareness.
*   **Value:**
    *   **Congressional-Tech:** Improves schedule management and awareness for staff who need to track both floor action and committee meetings concurrently. Provides a more comprehensive picture of the legislative week.
    *   **Civic-Tech:** Offers a more accessible and unified view of the congressional schedule for the public, facilitating engagement and informed participation.

### 5. Congressional Job Board Aggregator
*   **Problem:** Congressional job postings are scattered across various sources, including weekly PDFs, Senate websites, and USAJOBS, creating an inefficient and time-consuming search process for prospective applicants.
*   **Solution:** Create a centralized platform (BSky feed, spreadsheet, or dedicated website) to aggregate congressional job postings from multiple sources:
    *   **House Employment Bulletin PDFs:** Parse and clean the data from the weekly House Employment Bulletin PDFs, likely using AI-powered techniques to extract job titles, descriptions, and application information.
    *   **Senate Postings:** Scrape job postings from the Senate's websites for both political and non-political entities.
    *   **House Support Office Websites:** Scrape job postings directly from the websites of House support offices.
    *   **USAJOBS:** Monitor USAJOBS for relevant postings from congressional support offices and agencies (e.g., GAO, Library of Congress, CRS, USCP, Architect of the Capitol).
    *   **Tracking:** Keep track of when job postings are first published.
* **Value:**
  * **Congressional-Tech:** Streamlines the hiring process for congressional offices by expanding their reach to potential candidates and making it easier to advertise open positions.
  * **Civic-Tech:** Makes congressional employment opportunities more accessible and transparent to the public, encouraging a wider range of individuals to consider careers on Capitol Hill.

---

## III. Leveraging AI for Content Enhancement & Analysis

**Focus:** Explore AI applications to improve congressional information quality and analysis.

### 1. CRS Report Accessibility & Integration

*   **Problem:** CRS Reports are a vital source of non-partisan policy analysis, but they have historically been less accessible to the public and not fully integrated into broader online policy discussions.
*   **Solution:** Undertake a multi-faceted project to enhance CRS Report accessibility and integration:
    *   **EveryCRSReport.com Enhancement:** Integrate the newly available HTML versions of CRS Reports (accessible via API from CRS.Congress.gov) onto EveryCRSReport.com.
    *   **HTML Conversion of Legacy Reports:** Utilize existing tools (and potentially refine them) to convert older CRS Reports (currently available primarily as PDFs) into HTML format. *Investigate the committee.report tool as a potential solution.* Ideally, convert to Markdown for maximum flexibility.
    *   **Multi-Format Distribution:** Generate EPUB versions of all CRS Reports (both new and converted) to make them easily readable on e-readers and mobile devices. *Consider low-cost or free distribution on platforms like Amazon.com to counter vendors charging excessive prices for older reports.*
    *   **AI-Powered Tagging and Subject Identification:** Employ AI techniques (e.g., natural language processing, topic modeling) to analyze the content of CRS Reports and automatically generate subject matter tags. This will improve search and discovery on EveryCRSReport.com.
    *   **Wikipedia Integration:** Explore using AI and other technologies to systematically incorporate the content and citations from CRS Reports into relevant Wikipedia pages. This will improve the quality and accuracy of Wikipedia articles on policy topics and provide readers with direct links to authoritative sources.
*   **Value:**
    *   **Congressional-Tech:** Improves staff research efficiency by making CRS Reports more accessible, searchable, and discoverable in modern formats.
    *   **Civic-Tech:** Democratizes access to high-quality, non-partisan policy analysis, enhances Wikipedia as a public resource, combats misinformation by increasing the visibility of credible research, and promotes informed public discourse.

### 2. GAO Report Transformation & Dissemination

*   **Problem:** GAO Reports are typically published as PDF documents, which are not optimized for accessibility, searchability, or re-use in different formats.
*   **Solution:**
    *   **GAO Report to Markdown/EPUB Conversion:** Develop or adapt a tool to transform GAO Report PDFs into Markdown format (for maximum flexibility and future-proofing) and EPUB format (for easy reading on e-readers). *Investigate existing tools that might offer partial solutions.*
    *   **GAO Report Hosting and Publication:** Host the converted GAO Reports on a publicly accessible platform and develop a system for disseminating them widely.
*   **Value:**
    *   **Congressional-Tech:** Enables staff to more easily read, search, and utilize GAO Reports in various formats, improving their ability to conduct oversight and inform policy decisions.
    *   **Civic-Tech:** Makes GAO Reports significantly more accessible to the public, researchers, and journalists, promoting government oversight and accountability.

### 3. Automated Committee Hearing Transcripts & Summaries

*   **Problem:** Official transcripts of committee hearings are often delayed by a year or more, or require expensive private services for timely access. This hinders both congressional staff's ability to quickly analyze hearing content and the public's access to information.
*   **Solution:**
    *   **Real-Time Transcript Generation:** Implement AI-powered speech-to-text tools to create immediate (though potentially not perfectly accurate) transcripts of committee proceedings. Publish these transcripts on a dedicated, static website.
    *   **Automated Summarization:** Explore the use of AI-based summarization techniques (e.g., natural language processing) to generate concise summaries of the key topics discussed in each hearing.
    *   **Format Versatility:** Publish transcripts in multiple formats, including EPUB for e-readers.  Integrate the transcripts with the "Unified Hearing & Markup Data" project (described above) to provide a comprehensive record of each proceeding.
*   **Value:**
    *   **Congressional-Tech:** Provides near real-time access to hearing content for staff analysis, communication, and legislative drafting, bypassing the delays and costs associated with official transcripts.
    *   **Civic-Tech:** Greatly enhances public transparency and access to the content of congressional hearings, allowing citizens, journalists, and researchers to follow proceedings more closely and in a timely manner.

### 4. Write My GovTrack Newsletter (AI-Powered Legislative Newsletter)

*   **Problem:** Manually compiling a weekly legislative newsletter summarizing floor action, committee activity, and recently passed resolutions is a time-consuming task.
*   **Solution:** Develop an AI-powered tool to automatically generate a newsletter similar in format to GovTrack's weekly updates, drawing data from various sources:
    *   **Data Sources:**
        *   House and Senate floor schedules and notices.
        *   Committee schedule information.
        *   The Congressional Record (for information on resolutions passed, particularly "sneaky" resolutions that may not be readily apparent on Congress.gov).
    *   **Newsletter Content Modules:**
        *   **House Floor Action Summary:** A concise overview of bills up for a vote, including those on suspension.
        *   **Senate Floor Action Summary:** A summary of bills and nominations being considered on the Senate floor (potentially extracting information from the "colloquy").
        *   **Committee Hearing/Markup Overview:** A summary of committee activity in each chamber, organized by frequency of meetings and highlighting key committees (e.g., Appropriations, Armed Services for NDAA) and significant nominations.
        *   **Daily Resolution Alerts:** Automated alerts for resolutions passed the previous day, including the full text of the resolution (often published in the Congressional Record but not always easily accessible on Congress.gov).
*   **Value:**
    *   **Congressional-Tech:** Could provide a customizable newsletter template for congressional offices to quickly and efficiently distribute legislative updates to constituents, saving staff time and improving communication.
    *   **Civic-Tech:** Provides a scalable model for creating informative legislative newsletters, enhancing public awareness of congressional activities and promoting civic engagement.

### 5. Witness Database with Proceeding Links & Testimony Summarization

*   **Problem:** Witness testimony is typically siloed within the records of individual hearings. Tracking a particular witness's appearances and the content of their testimony across multiple committees and Congresses is a difficult and time-consuming manual process.
*   **Solution:** Create a comprehensive database of congressional witnesses that includes:
    *   **Unique Witness IDs:** Assign a unique identifier to each witness.
    *   **Proceeding Links:** Track all proceedings (hearings and markups) where the witness has testified, with links to the relevant records.
    *   **Testimony Transcripts:** Include transcripts of both written and oral remarks made by the witness.
    *   **Testimony Summaries:** Generate summaries of both written and oral testimony, potentially using AI-powered summarization techniques.
    *   **Questions for the Record (QFRs):** Capture Questions for the Record submitted to the witness and their responses, which often appear in committee transcripts.
    *   **Indexing:** Index the database by both the witness's name *and* their title/affiliation (e.g., "Jane Smith," "FAA Administrator"). This allows for searching based on specific individuals or roles.
*   **Value:**
    *   **Congressional-Tech:** Enables staff to easily track the expertise and past testimony of witnesses across committees and over time, facilitating issue analysis, identifying key stakeholders, and preparing for future hearings.
    *   **Civic-Tech:** Creates a valuable public resource for researching expert testimony on legislative issues, enhancing transparency, accountability, and informed public discourse.

---

## IV. Predictive & Analytical Tools for Legislative Insight

**Focus:** Projects using data to generate predictive insights and facilitate analysis of legislative processes.

### 1. Bills to Committee Referral Prediction

*   **Problem:** Understanding bill referral patterns is important for legislative strategy, but manually analyzing historical data to predict which committees will receive jurisdiction over a new bill is time-consuming.
*   **Solution:** Develop a predictive model, using machine learning techniques, to forecast bill referrals to committees based on historical referral patterns. The model should consider factors such as bill text, sponsor, and subject matter.  The output could be:
    *   A standalone dataset of predicted referrals.
    *   An add-on application that integrates with existing legislative tracking platforms like Congress.gov or GovTrack.us.
*   **Value:**
    *   **Congressional-Tech:** Provides strategic insights for legislative staff, helping them anticipate the likely committee jurisdiction for new bills and inform coalition-building and amendment strategies.
    *   **Civic-Tech:** Could offer researchers, advocacy groups, and the public better insight into the likely path of legislation through Congress, allowing for more effective engagement.

### 2. Bill Delay Tracker

*   **Problem:** There are often delays between the publication of bill text on Congress.gov and the availability of a corresponding bill summary. This delay hinders users who need a quick overview of new legislation.
*   **Solution:** Create a dashboard that tracks the time lag between bill text publication and Congress.gov summary availability. The dashboard should provide metrics such as:
    *   The total number of pages in the bills processed.
    *   The number of bills summarized.
    *   The number of bills that have been reported by a committee.
    *   Average, median, and maximum delay times.
*   **Value:**
    *   **Congressional-Tech:** Provides data-driven feedback to the Congress.gov development team on summary processing times and identifies areas for improvement in their workflow.
    *   **Civic-Tech:** Highlights an important user experience issue with Congress.gov, promoting transparency and advocating for improvements to the platform.

### 3. Appropriations Notices & Deadlines Tracker

*   **Problem:** Information about upcoming appropriations proceedings (instructions for public witnesses and Member offices, deadlines for submitting testimony, hearing dates) is scattered across the websites of the House and Senate Appropriations Committees and their 12 subcommittees. This makes it difficult to track deadlines and requirements comprehensively.
*   **Solution:** Create a centralized system (spreadsheet or dedicated website) to gather and organize appropriations-related information:
    *   **Public Witness Instructions:** Instructions for public witnesses seeking to provide testimony.
    *   **Member Office Instructions:** Instructions for Member offices submitting testimony or requests.
    *   **Deadlines:**
        *   Due dates for the public to submit written testimony.
        *   Due dates for the public to request to testify in person.
        *   Due dates for Member offices to request to testify.
        *   Due dates for Member offices to submit written testimony.
    *   **Hearing Dates:**
        *   Dates of public witness testimony hearings.
        *   Dates for Member office testimony.
    *   **Communication Channels:** Information on to whom submissions should be sent.
    *   *Leverage an existing spreadsheet model as a starting point.*
*   **Value:**
    *   **Congressional-Tech:** An essential tool for staff involved in the appropriations process, enabling them to manage deadlines, submit testimony effectively, and track key hearing dates for both public and Member witnesses.
    *   **Civic-Tech:** Increases transparency and facilitates public participation in the appropriations process by making deadlines and procedures clearer and more accessible.

### 4. Committee Funding Tracker & Visualization

*   **Problem:** Information on the funding levels allocated to House and Senate committees is not readily accessible or easily tracked over time.
*   **Solution:** Locate and extract data from committee funding resolutions passed by the House and Senate for each Congress.  These resolutions typically follow a formula. Compile the extracted data into a spreadsheet, going back as far as possible, and develop visualizations to show funding trends over time.
*   **Value:**
    *   **Congressional-Tech:** Provides a historical overview of committee resource allocation, which can be useful for budget analysis and understanding how resources have been distributed across different committees over time.
    *   **Civic-Tech:** Increases transparency regarding the financial resources allocated to different congressional committees, allowing for potential oversight analysis and public scrutiny.

### 5. Line Up CBJs and Appropriations Committee Report Language
*   **Problem:** Connecting agency budget justifications (CBJs) with relevant sections of appropriations committee reports (which explain funding decisions and provide directives to agencies) requires manual cross-referencing and analysis.
*   **Solution:** Develop a system to automatically link sections of CBJs to corresponding sections in appropriations committee reports. This could involve:
    *   **Keyword Matching:** Identifying shared keywords and phrases between CBJ sections and report sections.
    *   **Topic Modeling:** Using natural language processing techniques to identify thematic similarities between documents.
    *   **Machine Learning:** Training a model to recognize relationships between CBJ requests and committee report language.
*   **Value:**
    *   **Congressional-Tech:** Streamlines the analysis of appropriations bills by directly connecting stated agency funding requests with congressional justifications and directives articulated in committee reports. Facilitates a deeper understanding of appropriations intent and the rationale behind funding decisions.
    *   **Civic-Tech:** Enhances public understanding of how congressional appropriations align (or deviate from) agency budget requests and policy priorities as expressed in report language. Promotes greater accountability and transparency in the appropriations process.

---
## V. Basic Utility Tools

### 1. Inflation Calculator for Google Sheets

*   **Problem:** Manually calculating inflation across different years in spreadsheets is inefficient and prone to errors.
*   **Solution:** Create a custom formula for Google Sheets that leverages inflation data from the Bureau of Labor Statistics (BLS) or another reliable source to automatically calculate the inflation-adjusted value of a monetary amount.
    *   **Formula Structure:** The formula should take three inputs:
        *   `source_cell`: The cell containing the original monetary amount.
        *   `start_year_cell`: The cell containing the year of the original amount.
        *   `end_year_cell`: The cell containing the year to which the amount should be adjusted.
    *   **Example Formula:** `=INFLATION(A2, B2, C2)` (where A2 contains the amount, B2 the start year, and C2 the end year).
    *   The formula should also be "drag-able" to automatically update references for a range of data, allowing the inflation calculations to be easily expanded down a column.
*   **Value:**
    *   **Congressional-Tech:** A useful tool for staff performing economic analysis, cost adjustments, and budget projections in spreadsheets.
    *   **Civic-Tech:** A widely applicable utility for general users who need to perform inflation calculations in their spreadsheets, enhancing the functionality of Google Sheets.
