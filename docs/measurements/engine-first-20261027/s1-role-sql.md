# S1 draft record-role SQL

The draft SQL matches all **28 role/placeholder cases**, with no outcome difference, duplicate capture key or unexpected placeholder. This is S1 fixture evidence in the temporary M2 DataFusion harness, not completion of S1 or a production engine job. Real registry seeds, labeled thresholds, the capture/read/copy join, grouping, real slices and C7 integration remain open.

Fixture commits `8c731589`, `b39ae086`, `6debbdb0` and `eb660d18` precede the SQL. The accepted run is `cx_s1_roles_joined_retry_report.json`; its inputs, SQL job, physical plans and resource log remain in scratch. It uses DataFusion 53.1.0, four target partitions and the shared 10 GiB pool. Fixture settings are explicitly synthetic and provisional; they are never evidence for published registry entries.

The steps have separate inputs:

- `body-signals.sql`: the pinned `page_facts` reading, one per body, and page signals. It computes source-record, error, wrapper, feed and listing flags once per body.
- `locator-signals.sql`: distinct `(url, member_path)` values and URL/file-shape rules. A member's path takes precedence over its container URL for file shape.
- `placeholders.sql`: captures in every mode, counting distinct literal context addresses. More than 100 marks a placeholder.
- `record-roles.sql`: capture keys and scalar evidence joined to the three small flag relations. It applies DM §7.3's ordered roles and good-fetch/real-file conditions.

Body text and titles stay in the body-signal calculation; hash joins carry capture/body/locator keys, booleans and scalar evidence. With B bodies, U locators, C captures and R registry entries, signal work is O(B × R_body + U × R_locator), rather than repeating body patterns per capture. The role joins are expected O(C + B + U), with hash state bounded by their smaller inputs. Exact placeholder counting retains state proportional to distinct body/context pairs; its full-data memory still needs measurement.

The shared-body fixture proves that an error address excludes its capture while the ordinary address of the same HTML remains real. Other cases cover source XML, API JSON without a page reading, missing/rejected page readings, file-shaped HTML, member HTML, short real pages, wrappers, listings, feeds, incomplete attempts, provider retries, recovery mode and checked/unchecked PDFs.

Rejected drafts are retained: one comparison needed explicit parentheses around `IS DISTINCT FROM` before boolean operators, and DataFusion 53.1 did not lower correlated `EXISTS` inside `CASE`. The final body/locator flag relations use native joins and aggregates. A null-safe locator join also needs explicit comparison parentheses. Expected outcomes were unchanged throughout.
