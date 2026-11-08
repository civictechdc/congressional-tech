# Congress Explorer 0.6.4

This release improves browsing unfiltered ballot results. It reduces repeated date conversion and selects each page before fetching complete rows. Vote dates, row ordering, saved cursors and response-size limits retain their existing meaning. Filtered queries keep their existing behavior.

The update uses the same published archive and keeps the saved-PDF and citation repairs from 0.6.3. It requires no archive rebuild or local data refresh. Deep-page offsets and broad filtered queries remain outside this performance improvement.
