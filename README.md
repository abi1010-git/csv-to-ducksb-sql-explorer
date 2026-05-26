# CSV-to-DuckDB SQL Explorer

A lightweight local SQL workbench built with Streamlit, DuckDB, and pandas. Upload one or more CSV files, load each file into an in-memory DuckDB table, and run SQL queries across those tables in the same Streamlit session.

Live App: https://csv-to-duckdb.streamlit.app/

## Project Files

```text
csv_to_sql_explorer/
|-- app.py
|-- requirements.txt
`-- README.md
```

## Setup

From this project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run

```powershell
streamlit run app.py
```

Then open the local URL Streamlit prints in the terminal.

## How It Works

- The app creates an in-memory DuckDB database named `:memory:`.
- Uploaded CSV files are read with `pandas.read_csv()`.
- Each CSV becomes a DuckDB table for the current Streamlit session.
- The DuckDB connection, loaded table metadata, and file fingerprints are stored in `st.session_state`.
- Re-uploading the same file in the same session does not create a duplicate table.
- Tables reset when the Streamlit session ends because the database is intentionally in memory.

## Table Names

Table names are based on uploaded CSV filenames and cleaned into safe SQL identifiers:

- Converted to lowercase.
- Non-alphanumeric characters become underscores.
- Leading and trailing underscores are removed.
- Names that start with a number are prefixed with `table_`.
- Duplicate table names receive numeric suffixes such as `_2` or `_3`.

Examples:

```text
Traffic Accidents.csv -> traffic_accidents
2024 crashes.csv -> table_2024_crashes
city-data.csv -> city_data
city data.csv -> city_data_2
```

## Example SQL Queries

Preview one table:

```sql
SELECT * FROM traffic_accidents LIMIT 5;
```

Count rows:

```sql
SELECT COUNT(*) AS total_rows
FROM traffic_accidents;
```

Group and sort:

```sql
SELECT crash_severity, COUNT(*) AS crashes
FROM traffic_accidents
GROUP BY crash_severity
ORDER BY crashes DESC;
```

Join two uploaded CSV tables:

```sql
SELECT
    a.accident_id,
    a.crash_date,
    l.city,
    l.county
FROM traffic_accidents AS a
JOIN accident_locations AS l
    ON a.location_id = l.location_id
LIMIT 25;
```

## Notes

DuckDB can query all uploaded tables together, so multiple CSV files can be joined as long as they share useful key columns. Invalid SQL and unreadable CSV files are shown as clear Streamlit error messages.
