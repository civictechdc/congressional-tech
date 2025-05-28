# Project 5.1: Inflation Calculator for Google Sheets


## Provided Information:
### Problem: 
Manually calculating inflation across different years in spreadsheets is inefficient and prone to errors.

### Solution:
Create a custom formula for Google Sheets that leverages inflation data from the Bureau of Labor Statistics (BLS) or another reliable source to automatically calculate the inflation-adjusted value of a monetary amount.
* Formula Structure: The formula should take three inputs:
    * `source_cell`: The cell containing the original monetary amount.
    * `start_year_cell`: The cell containing the year of the original amount.
    * `end_year_cell`: The cell containing the year to which the amount should be adjusted.
* Example Formula: `=INFLATION(A2, B2, C2)` (where A2 contains the amount, B2 the start year, and C2 the end year).
* The formula should also be "drag-able" to automatically update references for a range of data, allowing the inflation calculations to be easily expanded down a column.

### Value:
* Congressional-Tech: A useful tool for staff performing economic analysis, cost adjustments, and budget projections in spreadsheets.
* Civic-Tech: A widely applicable utility for general users who need to perform inflation calculations in their spreadsheets, enhancing the functionality of Google Sheets.


## Technical Solution: 
contributors: [agurvich](https://github.com/agurvich)

[A template Google Sheet](https://docs.google.com/spreadsheets/d/1mhBVKwUEV-J53n7Jrwzc1BldqS5mWqIW5k0CxsDffHc/edit?usp=sharing), containing the function `INFLATION(source_cell, start_year_cell, end_year_cell)`. To use the function, the template sheet should be duplicated and any existing data should be imported. 

Within the Template Google Sheet there is
### 1 named range:

`BLS_CPI = CPIData!A1:M1000`
Which provides access to the hidden sheet `CPIData`, which loads the latest CPI data by reading a [csv file](https://raw.githubusercontent.com/agurvich/congressional-tech/refs/heads/main/projects/5.1-inflation-gsheets/data/historical-cpi.csv) that is automatically kept up-to-date by a Github Action.

On the 3rd of every month, the workflow will: 
1. Open the current .csv
2. Query the Bureau of Labor Statistics data API at `https://api.bls.gov/publicAPI/v2/timeseries/data/` with a `POST` request whose body contains:
    * `end_year = datetime.now().year`
    * `start_year = end_year - 9` (the API rate limits unauthenticated requests to 10 years at a time)
    * `seriesid = CUUR0000SA0` 
3. Appends the new data to the `.csv`
4. Commits and pushes the modified `.csv`

### 2 named functions:

`FLOATYEARDATE`, which converts a floating point year into a `DATE` object and

```
FLOATYEARDATE(input_year) = DATE(INT(input_year), 1, 1) + (input_year - INT(input_year)) * 365.25
```

`INFLATION`, which calculates the inflation adjusted dollar amount between two floating point years using the ratio of the corresponding Consumer Price Indices.

```
INFLATION(start_dollar_amount, start_year, end_year) = 
INDEX(BLS_CPI, DATEDIF(DATE(1913,1,1),FLOATYEARDATE(end_year),"Y")+2, MONTH(FLOATYEARDATE(end_year))+1) /
INDEX(BLS_CPI, DATEDIF(DATE(1913,1,1),FLOATYEARDATE(start_year),"Y")+2, MONTH(FLOATYEARDATE(start_year))+1) * start_dollar_amount
```

> NOTE: `INFLATION` could be "improved" if instead of ingesting years (as requested) it ingested `DATE` objects, then you could avoid the multiple calls to `FLOATYEARDATE`.