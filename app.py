from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import streamlit as st


DATABASE_NAME = ":memory:"


def quote_identifier(identifier: str) -> str:
    """Safely quote a generated DuckDB identifier."""
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def clean_table_name(filename: str) -> str:
    """Turn a CSV filename into a safe SQL table name."""
    stem = Path(filename).stem.lower()
    table_name = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")

    if not table_name:
        table_name = "table"
    if table_name[0].isdigit():
        table_name = f"table_{table_name}"

    return table_name


def unique_table_name(base_name: str, existing_tables: dict[str, dict[str, Any]]) -> str:
    if base_name not in existing_tables:
        return base_name

    counter = 2
    while f"{base_name}_{counter}" in existing_tables:
        counter += 1
    return f"{base_name}_{counter}"


def upload_key(filename: str, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"{filename}:{digest}"


def init_session_state() -> None:
    # Streamlit reruns the script on every interaction, so app state belongs here.
    if "duckdb_connection" not in st.session_state:
        st.session_state.duckdb_connection = duckdb.connect(database=DATABASE_NAME)
    if "tables" not in st.session_state:
        st.session_state.tables = {}
    if "loaded_files" not in st.session_state:
        st.session_state.loaded_files = {}
    if "sql_query" not in st.session_state:
        st.session_state.sql_query = ""
    if "last_auto_query" not in st.session_state:
        st.session_state.last_auto_query = ""


def get_connection() -> duckdb.DuckDBPyConnection:
    return st.session_state.duckdb_connection


def describe_table(table_name: str) -> list[dict[str, str]]:
    rows = get_connection().execute(f"DESCRIBE {quote_identifier(table_name)}").fetchall()
    return [{"name": row[0], "type": row[1]} for row in rows]


def load_csv(uploaded_file: Any) -> tuple[str, dict[str, Any]]:
    content = uploaded_file.getvalue()
    key = upload_key(uploaded_file.name, content)

    if key in st.session_state.loaded_files:
        table_name = st.session_state.loaded_files[key]
        return "skipped", {
            "file_name": uploaded_file.name,
            "table_name": table_name,
            "message": f"{uploaded_file.name} is already loaded as {table_name}.",
        }

    try:
        uploaded_file.seek(0)
        dataframe = pd.read_csv(uploaded_file)
    except Exception as exc:
        return "error", {
            "file_name": uploaded_file.name,
            "message": f"Could not read {uploaded_file.name}: {exc}",
        }

    base_name = clean_table_name(uploaded_file.name)
    table_name = unique_table_name(base_name, st.session_state.tables)
    temp_view = f"_upload_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"

    try:
        connection = get_connection()
        connection.register(temp_view, dataframe)
        connection.execute(
            f"CREATE OR REPLACE TABLE {quote_identifier(table_name)} AS "
            f"SELECT * FROM {quote_identifier(temp_view)}"
        )
    except Exception as exc:
        return "error", {
            "file_name": uploaded_file.name,
            "message": f"Could not load {uploaded_file.name} into DuckDB: {exc}",
        }
    finally:
        try:
            get_connection().unregister(temp_view)
        except Exception:
            pass

    st.session_state.tables[table_name] = {
        "source_name": uploaded_file.name,
        "rows": len(dataframe),
        "columns": describe_table(table_name),
    }
    st.session_state.loaded_files[key] = table_name

    return "success", {
        "file_name": uploaded_file.name,
        "table_name": table_name,
        "rows": len(dataframe),
        "columns": len(dataframe.columns),
    }


def process_uploads(uploaded_files: list[Any] | None) -> list[tuple[str, dict[str, Any]]]:
    if not uploaded_files:
        return []
    return [load_csv(uploaded_file) for uploaded_file in uploaded_files]


def render_upload_messages(messages: list[tuple[str, dict[str, Any]]]) -> None:
    for status, details in messages:
        if status == "success":
            st.success(
                f"Loaded {details['file_name']} as table {details['table_name']} "
                f"({details['rows']:,} rows, {details['columns']:,} columns)."
            )
        elif status == "skipped":
            st.info(details["message"])
        else:
            st.error(details["message"])


def render_sidebar() -> str | None:
    tables = list(st.session_state.tables.keys())

    with st.sidebar:
        st.header("Database")
        st.metric("Name", DATABASE_NAME)
        st.caption("Uploaded CSVs stay available for this Streamlit session.")

        st.divider()
        st.subheader("Tables")

        if not tables:
            st.warning("Upload CSV files to create tables.")
            return None

        st.write(", ".join(tables))
        selected_table = st.selectbox("Selected table", tables)
        metadata = st.session_state.tables[selected_table]

        st.caption(
            f"Source: {metadata['source_name']} | "
            f"{metadata['rows']:,} rows | {len(metadata['columns']):,} columns"
        )

        st.subheader("Columns")
        st.dataframe(
            pd.DataFrame(metadata["columns"]),
            hide_index=True,
            width="stretch",
        )

    return selected_table


def set_default_query(selected_table: str | None) -> None:
    if not selected_table:
        if not st.session_state.sql_query:
            st.session_state.sql_query = "-- Upload one or more CSV files to start querying."
        return

    default_query = f"SELECT * FROM {selected_table} LIMIT 5;"
    current_query = st.session_state.sql_query.strip()

    if not current_query or current_query == st.session_state.last_auto_query or current_query.startswith("-- Upload"):
        st.session_state.sql_query = default_query
        st.session_state.last_auto_query = default_query


def render_query_workspace(selected_table: str | None) -> None:
    set_default_query(selected_table)

    st.subheader("SQL Editor")
    st.text_area(
        "Write SQL against your uploaded CSV tables",
        key="sql_query",
        height=180,
        label_visibility="collapsed",
    )

    run_query = st.button("Run SQL", type="primary", width="content")

    if not run_query:
        return

    query = st.session_state.sql_query.strip()
    if not query or query.startswith("-- Upload"):
        st.error("Enter a SQL query before running.")
        return

    try:
        result = get_connection().execute(query).fetchdf()
    except Exception as exc:
        st.error(f"SQL error: {exc}")
        return

    st.success(f"Query returned {len(result):,} rows and {len(result.columns):,} columns.")
    st.dataframe(result, width="stretch", hide_index=True)


def render_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1180px;
            padding-top: 2rem;
        }
        div[data-testid="stFileUploader"] section {
            border-radius: 8px;
        }
        div[data-testid="stMetric"] {
            background: #f6f8fb;
            border: 1px solid #e3e8ef;
            border-radius: 8px;
            padding: 0.75rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="CSV-to-DuckDB SQL Explorer", layout="wide")
    init_session_state()
    render_styles()

    st.title("CSV-to-DuckDB SQL Explorer")
    st.caption("Upload CSV files, turn them into DuckDB tables, and query them with SQL.")

    uploaded_files = st.file_uploader(
        "Upload one or more CSV files",
        type=["csv"],
        accept_multiple_files=True,
        help="Each CSV becomes a separate DuckDB table for this session.",
    )

    if not uploaded_files:
        st.warning("No CSV files uploaded yet.")

    messages = process_uploads(uploaded_files)
    render_upload_messages(messages)

    selected_table = render_sidebar()
    render_query_workspace(selected_table)


if __name__ == "__main__":
    main()
