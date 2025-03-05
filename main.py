# -*- coding: utf-8 -*-
"""
Script to download, extract, and analyze ITU IFIC database files.
It fetches IFIC records within specified timeframes, downloads corresponding
zip files, extracts MDB databases, queries them for various statistics,
and generates Plotly charts for visualization.
"""

import os
import re
import zipfile
from datetime import datetime
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
import pyodbc
import pandas as pd
import plotly.express as px
import plotly.io as pio
import plotly.graph_objects as go
from typing import List, Dict, Tuple, Optional, Any

# --- Configuration ---

# Directories (Using raw strings for Windows paths)
DOWNLOAD_DIR = r"C:\Users\JamieParker\Documents\ITU\IFICS\downloads"
EXTRACT_DIR = r"C:\Users\JamieParker\Documents\ITU\IFICS\databases"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")

# ITU Website Configuration
BASE_URL = "https://www.itu.int/sns/wic/demowic{year}.html"
VALID_LINK_SUBSTRINGS = ["ific10", "converted-to-v10", "converted-to-v9.1", "converted-to-v9"]

# Default Time Frames for Analysis (Start Date, End Date)
# Dates should be in "dd.mm.yyyy" format
DEFAULT_TIME_FRAMES: List[Tuple[str, str]] = [
    ("01.01.2014", "31.12.2014"),
    ("01.01.2015", "31.12.2015"),
    ("01.01.2016", "31.12.2016"),
    ("01.01.2017", "31.12.2017"),
    ("01.01.2018", "31.12.2018"),
    ("01.01.2019", "31.12.2019"),
    ("01.01.2020", "31.12.2020"),
    ("01.01.2021", "31.12.2021"),
    ("01.01.2022", "31.12.2022"),
    ("01.01.2023", "31.12.2023"),
    ("01.01.2024", "31.12.2024"),
]

# Max workers for parallel downloads
MAX_DOWNLOAD_WORKERS = 5

# --- Helper Functions ---

def parse_date(date_str: str) -> datetime:
    """Parses a date string in 'dd.mm.yyyy' format."""
    return datetime.strptime(date_str, "%d.%m.%Y")

def fetch_page(url: str) -> Optional[requests.Response]:
    """Fetches a web page, returning the response object or None on error/non-200 status."""
    try:
        response = requests.get(url, timeout=15) # Increased timeout slightly
        response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
        return response
    except requests.exceptions.RequestException as e:
        print(f"[Warning] Failed to fetch {url}: {e}")
        return None

def get_file_basename(url_or_path: str) -> str:
    """Extracts the filename without extension from a URL or path."""
    parsed_path = urlparse(url_or_path).path
    filename = os.path.basename(parsed_path)
    return os.path.splitext(filename)[0]

# --- Data Fetching and Preparation ---

def get_ific_records_for_year(year: int) -> List[Dict[str, Any]]:
    """Scrapes the ITU WIC page for a given year to find IFIC download links."""
    year_short = str(year)[-2:]
    url = BASE_URL.format(year=year_short)
    response = fetch_page(url)
    if not response:
        print(f"[Info] Page for year {year} not found or inaccessible at {url}.")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    records = []
    seen_basenames = set() # Avoid duplicates based on filename

    for row in soup.find_all("tr"):
        text = row.get_text(" ", strip=True)
        # Find the date within the row text
        date_match = re.search(r"\b(\d{2}\.\d{2}\.\d{4})\b", text)
        if not date_match:
            continue

        try:
            record_date = parse_date(date_match.group(1))
        except ValueError:
            print(f"[Warning] Could not parse date '{date_match.group(1)}' found in row.")
            continue

        # Find the first valid download link matching preferred versions
        valid_link = None
        link_href = None
        for keyword in VALID_LINK_SUBSTRINGS:
            link_tag = row.find("a", href=lambda href: href and keyword in href.lower())
            if link_tag:
                valid_link = link_tag['href']
                break # Found the best available link for this row

        if valid_link:
            # Construct absolute URL if necessary
            full_link = urljoin(url, valid_link) if not valid_link.startswith("http") else valid_link
            basename = get_file_basename(full_link)

            if basename not in seen_basenames:
                seen_basenames.add(basename)
                records.append({
                    "date": record_date,
                    "url": full_link,
                    "basename": basename # Store basename for easier reference
                })

    print(f"[Info] Found {len(records)} unique IFIC records for {year}.")
    return records

def get_records_in_date_range(start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
    """Retrieves all IFIC records within a specified date range."""
    all_records = []
    print(f"[Info] Fetching records from {start_date:%d.%m.%Y} to {end_date:%d.%m.%Y}")
    for year in range(start_date.year, end_date.year + 1):
        year_records = get_ific_records_for_year(year)
        for record in year_records:
            # Filter records strictly within the requested date range
            if start_date <= record["date"] <= end_date:
                all_records.append(record)
    # Sort records by date, although scraping order might already be chronological
    all_records.sort(key=lambda x: x["date"])
    print(f"[Info] Total relevant records found: {len(all_records)}")
    return all_records

def filter_and_prepare_downloads(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Checks which records need downloading and prepares download paths."""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(EXTRACT_DIR, exist_ok=True)

    records_to_download = []
    extracted_files = {get_file_basename(f).lower()
                       for f in os.listdir(EXTRACT_DIR) if f.lower().endswith('.mdb')}

    for record in records:
        basename = record["basename"]
        zip_filename = basename + ".zip"
        zip_path = os.path.join(DOWNLOAD_DIR, zip_filename)
        mdb_filename = basename + ".mdb"
        mdb_path = os.path.join(EXTRACT_DIR, mdb_filename)

        record["zip_path"] = zip_path # Add path info for later use
        record["mdb_path"] = mdb_path

        # Skip if MDB already exists
        if basename.lower() in extracted_files:
            # print(f"[Info] Skipping download/extraction for {basename}: MDB exists.")
            continue

        # Skip if Zip exists (will be extracted later)
        if os.path.exists(zip_path):
            # print(f"[Info] Skipping download for {basename}: ZIP exists.")
            continue

        # If neither MDB nor ZIP exists, mark for download
        records_to_download.append(record)

    print(f"[Info] Determined {len(records_to_download)} files need downloading.")
    return records_to_download

def download_file(record: Dict[str, Any]):
    """Downloads a single file specified in the record dictionary."""
    url = record["url"]
    zip_path = record["zip_path"]
    basename = record["basename"]

    if os.path.exists(zip_path): # Double check just in case
        # print(f"[Debug] Download skipped, file already exists: {zip_path}")
        return

    print(f"[Download] Starting: {basename}.zip from {url}")
    try:
        # Use stream=True for potentially large files
        with requests.get(url, stream=True, timeout=60) as r: # Longer timeout for downloads
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192 * 8): # 64 KB chunks
                    f.write(chunk)
        print(f"[Download] Completed: {basename}.zip")
    except requests.exceptions.RequestException as e:
        print(f"[Error] Failed downloading {url}: {e}")
        # Clean up potentially incomplete file
        if os.path.exists(zip_path):
            os.remove(zip_path)
    except Exception as e:
        print(f"[Error] An unexpected error occurred downloading {url}: {e}")
        if os.path.exists(zip_path):
            os.remove(zip_path)

def download_files_parallel(records_to_download: List[Dict[str, Any]]):
    """Downloads multiple files in parallel using a ThreadPoolExecutor."""
    if not records_to_download:
        print("[Info] No new files to download.")
        return

    print(f"[Info] Starting parallel download of {len(records_to_download)} files...")
    with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as executor:
        # map will implicitly handle iterating through records_to_download
        # and calling download_file for each
        list(executor.map(download_file, records_to_download)) # Use list() to ensure execution completes
    print("[Info] Parallel downloads finished.")

def extract_zip_files(records: List[Dict[str, Any]]):
    """Extracts MDB files from downloaded ZIP archives."""
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    extracted_count = 0
    skipped_count = 0
    error_count = 0

    print("[Info] Starting extraction process...")
    for record in records:
        zip_path = record.get("zip_path")
        mdb_path = record.get("mdb_path")
        basename = record.get("basename")

        if not zip_path or not mdb_path or not basename:
            print(f"[Warning] Record missing path information, cannot extract: {record.get('url')}")
            error_count += 1
            continue

        # If MDB file already exists, skip extraction for this archive
        if os.path.exists(mdb_path):
            # print(f"[Info] Skipping extraction: {basename}.mdb already exists.")
            skipped_count += 1
            continue

        # If the corresponding ZIP file doesn't exist (e.g., failed download), skip
        if not os.path.exists(zip_path):
            print(f"[Warning] Skipping extraction: {basename}.zip not found at {zip_path}.")
            # Don't increment error count here, download issue handled elsewhere
            continue

        # Proceed with extraction
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                mdb_found_in_zip = False
                for member in z.namelist():
                    # Extract only files ending with .mdb (case-insensitive)
                    if member.lower().endswith('.mdb'):
                        # Ensure the extracted filename matches the expected MDB name based on the ZIP name
                        # This prevents extracting unrelated MDBs if the ZIP contains multiple.
                        if get_file_basename(member).lower() == basename.lower():
                            z.extract(member, EXTRACT_DIR)
                            # Rename if needed (zip might contain path structure)
                            extracted_member_path = os.path.join(EXTRACT_DIR, member)
                            if extracted_member_path != mdb_path:
                                os.rename(extracted_member_path, mdb_path)
                            print(f"[Extract] Extracted: {basename}.mdb from {os.path.basename(zip_path)}")
                            extracted_count += 1
                            mdb_found_in_zip = True
                            break # Assume only one relevant MDB per zip based on name match
                        else:
                             print(f"[Warning] Found unexpected MDB '{member}' in {os.path.basename(zip_path)}, expected '{basename}.mdb'. Skipping.")

                if not mdb_found_in_zip:
                    print(f"[Warning] No file named '{basename}.mdb' found inside {os.path.basename(zip_path)}.")
                    # Don't count as error, just didn't find the expected file.

        except zipfile.BadZipFile:
            print(f"[Error] Failed to extract {os.path.basename(zip_path)}: Bad ZIP file.")
            error_count += 1
        except FileNotFoundError:
             print(f"[Error] Failed to extract {os.path.basename(zip_path)}: File not found (should not happen after check).")
             error_count += 1
        except Exception as e:
            print(f"[Error] Failed extracting {os.path.basename(zip_path)}: {e}")
            error_count += 1

    print(f"[Info] Extraction summary: {extracted_count} extracted, {skipped_count} skipped, {error_count} errors.")


# --- Data Querying ---

def gather_query_data(records: List[Dict[str, Any]], query: str) -> pd.DataFrame:
    """
    Connects to MDB files specified in records, executes a query,
    and returns the combined results as a Pandas DataFrame.
    """
    all_data = []
    processed_mdb_paths = set() # Ensure each MDB is queried only once per call

    print(f"[Query] Starting data gathering with query: {query[:50]}...") # Log start and part of query

    for record in records:
        mdb_path = record.get("mdb_path")
        basename = record.get("basename", "Unknown")

        if not mdb_path:
            print(f"[Warning] Skipping record, missing mdb_path: {record.get('url')}")
            continue

        # Skip if this specific MDB file has already been processed in this run
        if mdb_path in processed_mdb_paths:
            continue

        # Skip if the MDB file doesn't actually exist (e.g., extraction failed)
        if not os.path.exists(mdb_path):
            # print(f"[Debug] Skipping query for non-existent file: {mdb_path}")
            continue

        processed_mdb_paths.add(mdb_path) # Mark as processed for this call

        try:
            # Construct the connection string for pyodbc
            # Ensure the driver name matches your installed Access driver
            # Common names: 'Microsoft Access Driver (*.mdb, *.accdb)' or just 'Microsoft Access Driver (*.mdb)'
            conn_str = (
                r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
                rf"DBQ={mdb_path};"
            )
            with pyodbc.connect(conn_str) as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                # Fetch column names correctly from cursor description
                columns = [col[0] for col in cursor.description]
                # Fetch all rows and convert to list of dictionaries
                rows = cursor.fetchall()
                for row in rows:
                    all_data.append(dict(zip(columns, row)))

        except pyodbc.Error as e:
            print(f"[Error] Database error processing {basename}.mdb: {e}")
        except FileNotFoundError: # Should be caught by os.path.exists, but as fallback
             print(f"[Error] File not found during connection attempt: {mdb_path}")
        except Exception as e:
            print(f"[Error] Unexpected error processing {basename}.mdb: {e}")

    print(f"[Query] Finished gathering data. Found {len(all_data)} rows from {len(processed_mdb_paths)} databases.")
    return pd.DataFrame(all_data)


# --- Specific Statistics Gathering Functions ---

# Decorator approach (optional) to reduce boilerplate in stats functions
# from functools import wraps
# def stats_gatherer(query: str, processing_func: Callable[[pd.DataFrame], pd.DataFrame]):
#     @wraps(processing_func)
#     def wrapper(records: List[Dict[str, Any]]) -> pd.DataFrame:
#         df = gather_query_data(records, query)
#         if df.empty:
#             return df
#         return processing_func(df)
#     return wrapper

# Decided against decorator for now to keep explicit calls clear.

def gather_ntc_id_stats(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Gathers statistics on ntc_id."""
    df = gather_query_data(records, "SELECT ntc_id FROM notice")
    if not df.empty:
        # Ensure ntc_id is treated consistently, handle potential NaNs before conversion
        df["ntc_id"] = pd.to_numeric(df["ntc_id"], errors='coerce').fillna(-1).astype(int)
        # Count occurrences of each ntc_id
        stats_df = df.groupby("ntc_id").size().reset_index(name="Count")
        return stats_df
    return df

def gather_admin_stats(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Gathers statistics on administration codes (adm)."""
    df = gather_query_data(records, "SELECT adm FROM notice")
    if not df.empty:
        # Clean up admin codes: strip whitespace, fill NaNs
        df["adm"] = df["adm"].astype(str).str.strip().fillna("Unknown")
        df.loc[df["adm"] == '', "adm"] = "Unknown" # Replace empty strings too
        # Count occurrences
        stats_df = df.groupby("adm").size().reset_index(name="Count")
        return stats_df
    return df

def gather_ntf_rsn_stats(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Gathers statistics on notification reasons (ntf_rsn)."""
    df = gather_query_data(records, "SELECT ntf_rsn FROM notice")
    if not df.empty:
        # Clean up notification reasons
        df["ntf_rsn"] = df["ntf_rsn"].astype(str).str.strip().fillna("Unknown")
        df.loc[df["ntf_rsn"] == '', "ntf_rsn"] = "Unknown"
        # Count occurrences
        stats_df = df.groupby("ntf_rsn").size().reset_index(name="Count")
        return stats_df
    return df

def gather_ntc_type_stats(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Gathers statistics on notification types (ntc_type)."""
    df = gather_query_data(records, "SELECT ntc_type FROM notice")
    if not df.empty:
        # Clean up notification types
        df["ntc_type"] = df["ntc_type"].astype(str).str.strip().fillna("Unknown")
        df.loc[df["ntc_type"] == '', "ntc_type"] = "Unknown"
        # Count occurrences
        stats_df = df.groupby("ntc_type").size().reset_index(name="Count")
        return stats_df
    return df

def gather_frequency_band_stats(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Gathers frequency range data (freq_min, freq_max)."""
    df = gather_query_data(records, "SELECT freq_min, freq_max FROM freq")
    if not df.empty:
        # Convert frequencies to numeric, coercing errors to NaN
        df['freq_min'] = pd.to_numeric(df['freq_min'], errors='coerce')
        df['freq_max'] = pd.to_numeric(df['freq_max'], errors='coerce')
        # Drop rows where either frequency is NaN
        df = df.dropna(subset=['freq_min', 'freq_max'])
        # Calculate mid-frequency for band analysis
        df['mid_freq'] = (df['freq_min'] + df['freq_max']) / 2.0
        return df[['mid_freq']] # Return only the necessary column
    return pd.DataFrame({'mid_freq': pd.Series(dtype=float)}) # Return empty df with correct column/type

def gather_antenna_pattern_stats(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Gathers distinct antenna pattern IDs from various tables."""
    # Query 1: Count distinct patterns from ant_type (considered the definition source)
    ant_type_df = gather_query_data(
        records,
        "SELECT pattern_id FROM ant_type"
    )
    # Count unique non-null pattern IDs from ant_type
    total_unique_patterns = ant_type_df['pattern_id'].dropna().nunique()

    # Query 2: Get distinct patterns actually used in s_beam (space stations)
    s_beam_df = gather_query_data(
        records,
        "SELECT DISTINCT pattern_id AS unique_space_pattern_ids FROM s_beam"
    )
    unique_space_ids = s_beam_df["unique_space_pattern_ids"].dropna().unique().tolist()

    # Query 3: Get distinct patterns actually used in e_as_stn (earth stations)
    e_as_stn_df = gather_query_data(
        records,
        "SELECT DISTINCT pattern_id AS unique_earth_pattern_ids FROM e_as_stn"
    )
    unique_earth_ids = e_as_stn_df["unique_earth_pattern_ids"].dropna().unique().tolist()

    # Combine results into a single-row DataFrame
    result_df = pd.DataFrame({
        "total_pattern_count": [total_unique_patterns],
        "unique_space_pattern_ids": [unique_space_ids],
        "unique_earth_pattern_ids": [unique_earth_ids],
    })
    return result_df


# --- Plotting Helper Functions ---

def save_plot(fig, filename: str, output_dir: Optional[str] = OUTPUT_DIR):
    """Saves a Plotly figure to an HTML file."""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)
    else:
        filepath = filename
    try:
        pio.write_html(fig, file=filepath, auto_open=False)
        print(f"[Chart] Saved: {filepath}")
    except Exception as e:
        print(f"[Error] Failed to save plot {filepath}: {e}")

def combine_stats_data(stats_list: List[Tuple[str, pd.DataFrame]],
                       value_col: str = 'Count',
                       group_col: Optional[str] = None) -> pd.DataFrame:
    """Combines list of (label, DataFrame) tuples into a single DataFrame."""
    combined_list = []
    for label, df in stats_list:
        if df is not None and not df.empty:
            df = df.copy()
            df["TimeFrame"] = label
            combined_list.append(df)

    if not combined_list:
        # Return empty DataFrame with expected columns if no data
        cols = [group_col, value_col, "TimeFrame"] if group_col else [value_col, "TimeFrame"]
        return pd.DataFrame(columns=cols)

    return pd.concat(combined_list, ignore_index=True)

def parse_label_year(label: str) -> Tuple[int, int]:
    """Extracts start and end year from a timeframe label like '01.01.2020 - 31.12.2020'."""
    try:
        start_str, end_str = label.split(" - ")
        start_year = int(start_str.split(".")[2])
        end_year = int(end_str.split(".")[2])
        return start_year, end_year
    except Exception as e:
        print(f"[Warning] Could not parse year from label '{label}': {e}")
        return 0, 0 # Return default/invalid years on error


# --- Plotting Functions ---

def plot_unique_ntc_id_count_per_year(stats_list: List[Tuple[str, pd.DataFrame]]):
    """Plots the count of unique ntc_ids per year."""
    combined_df = combine_stats_data(stats_list, value_col='Count', group_col='ntc_id')
    if combined_df.empty:
        print("[Warning] No ntc_id data found to plot.")
        return

    # Use label parsing to get the year for each timeframe
    combined_df["Year"] = combined_df["TimeFrame"].apply(lambda x: parse_label_year(x)[0]) # Use start year

    # Group by Year and count unique ntc_ids within that year's data
    df_yearly = combined_df.groupby("Year")["ntc_id"].nunique().reset_index(name="UniqueNotices")

    fig = px.bar(
        df_yearly,
        x="Year",
        y="UniqueNotices",
        text="UniqueNotices",
        title="Unique Notice Count per Year"
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(xaxis_type='category') # Treat year as category for distinct bars
    save_plot(fig, "unique_ntc_id_per_year.html")

def plot_admin_counts_multi(stats_list: List[Tuple[str, pd.DataFrame]]):
    """Plots admin counts grouped by timeframe."""
    combined = combine_stats_data(stats_list, group_col='adm')
    if combined.empty:
        print("[Warning] No admin data to plot.")
        return

    # Optional: Sort administrations by total count across all timeframes for better legend order
    total_counts = combined.groupby('adm')['Count'].sum().sort_values(ascending=False)
    combined['adm'] = pd.Categorical(combined['adm'], categories=total_counts.index, ordered=True)
    combined = combined.sort_values('adm')

    fig = px.bar(combined, x="adm", y="Count", color="TimeFrame", barmode="group",
                 title="Admin Counts by Time Frame")
    fig.update_layout(xaxis_title="Administration", yaxis_title="Notice Count")
    save_plot(fig, "admin_counts_multi.html")

def _prepare_percentage_data(stats_list: List[Tuple[str, pd.DataFrame]],
                             group_col: str,
                             group_definitions: Dict[str, Tuple[int, int]],
                             value_col: str = 'Count',
                             mapping: Optional[Dict[str, str]] = None,
                             cutoff_percentage: Optional[float] = None,
                             other_label_template: Optional[str] = None) -> pd.DataFrame:
    """Helper function to prepare data for stacked percentage plots with custom time groupings."""
    grouped_data = {label: [] for label in group_definitions}

    # 1. Assign dataframes to their respective groups based on year range
    for label, df in stats_list:
        if df is None or df.empty:
            continue
        start_year, end_year = parse_label_year(label)
        if start_year == 0: continue # Skip if label parsing failed

        for group_label, (min_year, max_year) in group_definitions.items():
            # Include if the data's start year falls within the defined range
            if min_year <= start_year <= max_year:
                grouped_data[group_label].append(df)

    # 2. Process each group
    combined_list = []
    for group_label, df_list in grouped_data.items():
        if not df_list:
            # Add a placeholder if the group is empty to ensure it appears in the plot
            placeholder = pd.DataFrame({
                group_col: [f"No Data for {group_label}"],
                value_col: [0],
                "TimeFrame": [group_label]
            })
            if cutoff_percentage is not None and other_label_template is not None:
                 placeholder[group_col] = [other_label_template.format(cutoff_percentage)]
            combined_list.append(placeholder)
            continue

        # Combine all dataframes within this time group
        group_df = pd.concat(df_list, ignore_index=True)

        # Apply mapping if provided (e.g., code to full name)
        if mapping:
            group_df[group_col] = group_df[group_col].map(mapping).fillna(group_df[group_col])

        # Aggregate counts within the group
        agg = group_df.groupby(group_col, as_index=False)[value_col].sum()

        # Apply cutoff percentage if specified
        if cutoff_percentage is not None and other_label_template is not None:
            total = agg[value_col].sum()
            if total > 0:
                agg["percentage"] = agg[value_col] / total * 100
            else:
                agg["percentage"] = 0

            major = agg[agg["percentage"] >= cutoff_percentage].copy()
            minor = agg[agg["percentage"] < cutoff_percentage]

            if not minor.empty and minor[value_col].sum() > 0:
                other_row = pd.DataFrame({
                    group_col: [other_label_template.format(cutoff_percentage)],
                    value_col: [minor[value_col].sum()]
                })
                major = pd.concat([major, other_row], ignore_index=True)
            agg = major[[group_col, value_col]] # Keep only needed columns

        agg["TimeFrame"] = group_label
        combined_list.append(agg)

    # 3. Final combined DataFrame and percentage calculation
    final_df = pd.concat(combined_list, ignore_index=True)

    if final_df.empty or final_df[value_col].sum() == 0:
        return pd.DataFrame() # Return empty if no valid data after processing

    final_df["TotalPerTimeFrame"] = final_df.groupby("TimeFrame")[value_col].transform("sum")
    final_df["Percentage"] = final_df.apply(
        lambda row: (row[value_col] / row["TotalPerTimeFrame"] * 100) if row["TotalPerTimeFrame"] > 0 else 0,
        axis=1
    )

    return final_df

def plot_admin_counts_stacked_percentage(stats_list: List[Tuple[str, pd.DataFrame]], cutoff_percentage: float = 3):
    """Plots admin counts as stacked percentages for specific time groupings."""
    group_definitions = {
        "2024": (2024, 2024),
        "2020-2024": (2020, 2024),
        "2015-2024": (2015, 2024),
    }
    other_label = f"Other Administrations (< {cutoff_percentage}%)"

    processed_df = _prepare_percentage_data(
        stats_list,
        group_col='adm',
        group_definitions=group_definitions,
        cutoff_percentage=cutoff_percentage,
        other_label_template=other_label
    )

    if processed_df.empty:
        print("[Warning] No admin data for percentage plot after processing.")
        return

    # Sort categories for consistent legend order (by overall contribution)
    total_counts = processed_df.groupby('adm')['Count'].sum().sort_values(ascending=False)
    category_order = total_counts.index.tolist()
    # Ensure 'Other' category is last if it exists
    if other_label in category_order:
        category_order.remove(other_label)
        category_order.append(other_label)

    fig = px.bar(
        processed_df,
        x="TimeFrame",
        y="Percentage",
        color="adm",
        barmode="stack",
        title=f"Administration Distribution ({cutoff_percentage}% Cutoff, Stacked Percentage)",
        category_orders={"adm": category_order, "TimeFrame": ["2015-2024", "2020-2024", "2024"]}, # Ensure timeframe order
        labels={"adm": "Administration", "Percentage": "Percentage of Notices (%)"}
    )
    save_plot(fig, "admin_counts_stacked_percentage.html")

def plot_ntf_rsn_stacked(stats_list: List[Tuple[str, pd.DataFrame]]):
    """Plots notification reasons as a stacked bar chart per timeframe."""
    mapping = {
        "N": "RR1488 / 11.2 / 11.12 / AP30/30A-Art 5 / AP30B-Art 8", # Combined for brevity
        "C": "RR1060 / 9.6 / 9.7A / 9.21",
        "D": "RR1107 / 9.17",
        "A": "9.1",
        "B": "AP30/30A-Arts 2A & 4",
        "P": "AP30B-Arts 6 & 7",
        "U": "Res49",
        "Unknown": "Unknown/Not Specified" # Make explicit
    }
    combined = combine_stats_data(stats_list, group_col='ntf_rsn')
    if combined.empty:
        print("[Warning] No ntf_rsn data to plot.")
        return

    combined["Reason"] = combined["ntf_rsn"].map(mapping).fillna(combined["ntf_rsn"])

    # Sort categories by total count
    total_counts = combined.groupby('Reason')['Count'].sum().sort_values(ascending=False)
    category_order = total_counts.index.tolist()

    fig = px.bar(combined, x="TimeFrame", y="Count", color="Reason", barmode="stack",
                 title="Notification Reasons Distribution (Stacked)",
                 category_orders={"Reason": category_order},
                 labels={"Reason": "Notification Reason Code/Rule"})
    fig.update_layout(xaxis_title="Time Frame", yaxis_title="Notice Count")
    save_plot(fig, "ntf_rsn_stacked.html")

def plot_ntf_rsn_stacked_percentage(stats_list: List[Tuple[str, pd.DataFrame]]):
    """Plots notification reasons as stacked percentages for specific time groupings."""
    # Mapping from codes to descriptive labels (same as the non-percentage version)
    mapping = {
        "N": "RR1488 / 11.2 / 11.12 / AP30/30A-Art 5 / AP30B-Art 8",
        "C": "RR1060 / 9.6 / 9.7A / 9.21",
        "D": "RR1107 / 9.17",
        "A": "9.1",
        "B": "AP30/30A-Arts 2A & 4",
        "P": "AP30B-Arts 6 & 7",
        "U": "Res49",
        "Unknown": "Unknown/Not Specified"
    }
    # Standard time groupings
    group_definitions = {
        "2024": (2024, 2024),
        "2020-2024": (2020, 2024),
        "2015-2024": (2015, 2024),
    }

    # Use the helper function to process the data
    processed_df = _prepare_percentage_data(
        stats_list,
        group_col='ntf_rsn',        # The column containing the codes
        group_definitions=group_definitions,
        mapping=mapping,           # Apply the descriptive labels
        value_col='Count'          # The column with counts to aggregate
        # No cutoff needed for these categories
    )

    if processed_df.empty:
        print("[Warning] No ntf_rsn data for percentage plot after processing.")
        return

    # Determine the column name for coloring. The helper function applies the
    # mapping to the values in the 'group_col' ('ntf_rsn').
    color_col = 'ntf_rsn' # The column name remains the same

    # Sort categories by overall contribution for a consistent legend
    # Use the mapped values for sorting calculation if possible
    # Need to remap here just for sorting calculation as helper doesn't return mapped df easily
    temp_df_for_sorting = processed_df.copy()
    temp_df_for_sorting['ReasonMapped'] = temp_df_for_sorting[color_col].map(mapping).fillna(temp_df_for_sorting[color_col])
    total_counts = temp_df_for_sorting.groupby('ReasonMapped')['Count'].sum().sort_values(ascending=False)
    # Get the *original* codes back in the sorted order based on the mapped totals
    category_order_map = {v: k for k, v in mapping.items()}
    category_order = [category_order_map.get(reason, reason) for reason in total_counts.index]


    fig = px.bar(
        processed_df,
        x="TimeFrame",
        y="Percentage",
        color=color_col,  # Use original column name; labels will be mapped values
        barmode="stack",
        title="Notification Reasons Distribution (Stacked Percentage)",
        category_orders={
            color_col: category_order,                  # Order the colors/legend
            "TimeFrame": ["2015-2024", "2020-2024", "2024"] # Order the x-axis groups
        },
        labels={
            color_col: "Notification Reason",          # Set a nice legend title
            "Percentage": "Percentage of Notices (%)"
        },
         # Optional: Explicitly set hover data to show the mapped reason easily
        hover_name=processed_df[color_col].map(mapping).fillna(processed_df[color_col]),
        hover_data={"Percentage": ":.2f%"} # Format percentage in hover
    )

    save_plot(fig, "ntf_rsn_stacked_percentage.html")

def plot_ntc_type_stacked(stats_list: List[Tuple[str, pd.DataFrame]]):
    """Plots notification types as a stacked bar chart per timeframe."""
    mapping = {
        "N": "Non-geostationary (NGSO)",
        "G": "Geostationary (GSO)",
        "S": "Specific Earth station",
        "R": "Radio astronomy station",
        "T": "Typical Earth station",
        "Unknown": "Unknown/Not Specified"
    }
    combined = combine_stats_data(stats_list, group_col='ntc_type')
    if combined.empty:
        print("[Warning] No ntc_type data to plot.")
        return

    combined["Type"] = combined["ntc_type"].map(mapping).fillna(combined["ntc_type"])

    # Sort categories by total count
    total_counts = combined.groupby('Type')['Count'].sum().sort_values(ascending=False)
    category_order = total_counts.index.tolist()

    fig = px.bar(combined, x="TimeFrame", y="Count", color="Type", barmode="stack",
                 title="Notice Types Distribution (Stacked)",
                 category_orders={"Type": category_order},
                 labels={"Type": "Notice Type"})
    fig.update_layout(xaxis_title="Time Frame", yaxis_title="Notice Count")
    save_plot(fig, "ntc_type_stacked.html")

def plot_ntc_type_stacked_percentage(stats_list: List[Tuple[str, pd.DataFrame]]):
    """Plots notice types as stacked percentages for specific time groupings."""
    mapping = {
        "N": "Non-geostationary (NGSO)",
        "G": "Geostationary (GSO)",
        "S": "Specific Earth station",
        "R": "Radio astronomy station",
        "T": "Typical Earth station",
        "Unknown": "Unknown/Not Specified"
    }
    group_definitions = {
        "2024": (2024, 2024),
        "2020-2024": (2020, 2024),
        "2015-2024": (2015, 2024),
    }

    processed_df = _prepare_percentage_data(
        stats_list,
        group_col='ntc_type',
        group_definitions=group_definitions,
        mapping=mapping
        # No cutoff needed for types, usually few categories
    )

    if processed_df.empty:
        print("[Warning] No ntc_type data for percentage plot after processing.")
        return

    # Use the mapped column name 'Type' if mapping was applied, else original 'ntc_type'
    color_col = 'Type' if 'Type' in processed_df.columns else 'ntc_type'
    if mapping: # Add mapped column if not already done by helper (it should be)
         processed_df[color_col] = processed_df['ntc_type'].map(mapping).fillna(processed_df['ntc_type'])


    # Sort categories by overall contribution
    total_counts = processed_df.groupby(color_col)['Count'].sum().sort_values(ascending=False)
    category_order = total_counts.index.tolist()

    fig = px.bar(
        processed_df,
        x="TimeFrame",
        y="Percentage",
        color=color_col,
        barmode="stack",
        title="Notice Types Distribution (Stacked Percentage)",
        category_orders={color_col: category_order, "TimeFrame": ["2015-2024", "2020-2024", "2024"]},
        labels={color_col: "Notice Type", "Percentage": "Percentage of Notices (%)"}
    )
    save_plot(fig, "ntc_type_stacked_percentage.html")

def plot_frequency_bands_stacked(stats_list: List[Tuple[str, pd.DataFrame]]):
    """Plots frequency band usage (based on mid-frequency) stacked by year."""
    # Define frequency bands (Label, lower bound MHz, upper bound MHz) - standard ITU bands
    # Note: Boundaries are approximate and common usage may vary slightly.
    bands = [
        ("HF (High Frequency)", 3, 30),
        ("VHF (Very High Frequency)", 30, 300),
        ("UHF (Ultra High Frequency)", 300, 1000), # Often split UHF/P-Band
        ("L-Band", 1000, 2000),
        ("S-Band", 2000, 4000),
        ("C-Band", 4000, 8000),
        ("X-Band", 8000, 12000), # Sometimes 8-12.4 GHz
        ("Ku-Band (Kürzer-under)", 12000, 18000),
        ("K-Band", 18000, 27000),
        ("Ka-Band (Kürzer-above)", 27000, 40000),
        ("V-Band", 40000, 75000),
        ("W-Band", 75000, 110000),
        ("mmWave (>110 GHz)", 110000, 300000), # Grouping higher frequencies
        ("Other (<3 MHz or >300 GHz)", 0, 3) # Catch frequencies outside main ranges
    ]
    # Ensure bands list covers from low to high without gaps for the function below
    bands.sort(key=lambda x: x[1])

    def get_band(freq_mhz: float) -> str:
        if freq_mhz < bands[0][1]: # Handle frequencies below the lowest defined band
             return bands[-1][0] # Assign to 'Other' or a specific low-freq band if defined
        for label, low, high in bands:
            # Check if frequency falls within the [low, high) range
            if low <= freq_mhz < high:
                return label
        # Handle frequencies above the highest defined band explicitly
        if freq_mhz >= bands[-2][2]: # Check against the upper bound of the last *real* band
             return bands[-2][0] # Assign to the highest band ('mmWave' in this case)
        return "Unknown Band" # Fallback


    combined = combine_stats_data(stats_list, value_col='mid_freq') # Initially combine with mid_freq
    if combined.empty:
        print("[Warning] No frequency data to plot.")
        return

    combined["Year"] = combined["TimeFrame"].apply(lambda x: str(parse_label_year(x)[0])) # Use start year as string
    combined["Band"] = combined["mid_freq"].apply(get_band)

    # Now, count occurrences per band per year
    band_counts = combined.groupby(["Year", "Band"]).size().reset_index(name="Count")

    # Sort bands based on typical frequency order for the legend
    # Create a mapping from band label to its lower frequency bound for sorting
    band_order_map = {label: low for label, low, high in bands}
    # Add Unknown/Other with a high sort value
    band_order_map["Unknown Band"] = float('inf')
    if bands[-1][0] not in band_order_map: # Ensure 'Other' band is in map if used
         band_order_map[bands[-1][0]] = -1 # Put 'Other' first or last based on preference


    # Get unique bands present in the data and sort them
    present_bands = band_counts["Band"].unique()
    sorted_bands = sorted(present_bands, key=lambda b: band_order_map.get(b, float('inf')))


    fig = px.bar(
        band_counts,
        x="Year",
        y="Count",
        color="Band",
        barmode="stack",
        title="Frequency Band Usage (Stacked by Year)",
        category_orders={"Band": sorted_bands, "Year": sorted(band_counts["Year"].unique())},
        labels={"Band": "Frequency Band", "Count": "Number of Frequency Assignments"}
    )
    fig.update_layout(xaxis_type='category')
    save_plot(fig, "frequency_bands_stacked.html")

def plot_frequency_bands_stacked_percentage(stats_list: List[Tuple[str, pd.DataFrame]]):
    """Plots frequency band usage as stacked percentages for specific time groupings."""
    # Same band definitions and function as the non-percentage plot
    bands = [
        ("HF", 3, 30), ("VHF", 30, 300), ("UHF", 300, 1000), ("L", 1000, 2000),
        ("S", 2000, 4000), ("C", 4000, 8000), ("X", 8000, 12000), ("Ku", 12000, 18000),
        ("K", 18000, 27000), ("Ka", 27000, 40000), ("V", 40000, 75000), ("W", 75000, 110000),
        ("mm (>110GHz)", 110000, 300000), ("Other", 0, 3) # Simplified labels for plot
    ]
    bands.sort(key=lambda x: x[1])

    def get_band(freq_mhz: float) -> str:
        if freq_mhz < bands[0][1]: return bands[-1][0] # Other
        for label, low, high in bands:
            if low <= freq_mhz < high: return label
        if freq_mhz >= bands[-2][2]: return bands[-2][0] # mm
        return "Unknown Band"

    group_definitions = {
        "2024": (2024, 2024),
        "2020-2024": (2020, 2024),
        "2015-2024": (2015, 2024),
    }

    # Need to process frequency data slightly differently before the helper
    processed_freq_list = []
    for label, df in stats_list:
        if df is not None and not df.empty and 'mid_freq' in df.columns:
            df = df.copy()
            df["Band"] = df["mid_freq"].apply(get_band)
            # Count occurrences *before* passing to the percentage helper
            band_counts_df = df.groupby("Band").size().reset_index(name="Count")
            processed_freq_list.append((label, band_counts_df))
        else:
            # Pass along empty dataframes or indicate missing data
            processed_freq_list.append((label, pd.DataFrame(columns=['Band', 'Count'])))


    processed_df = _prepare_percentage_data(
        processed_freq_list, # Use the pre-counted band data
        group_col='Band',
        group_definitions=group_definitions,
        value_col='Count' # We are now summing the pre-calculated counts
    )

    if processed_df.empty:
        print("[Warning] No frequency data for percentage plot after processing.")
        return

    # Sort bands by frequency
    band_order_map = {label: low for label, low, high in bands}
    band_order_map["Unknown Band"] = float('inf')
    band_order_map[bands[-1][0]] = -1 # Other

    present_bands = processed_df["Band"].unique()
    sorted_bands = sorted(present_bands, key=lambda b: band_order_map.get(b, float('inf')))

    fig = px.bar(
        processed_df,
        x="TimeFrame",
        y="Percentage",
        color="Band",
        barmode="stack",
        title="Frequency Band Usage Distribution (Stacked Percentage)",
        category_orders={"Band": sorted_bands, "TimeFrame": ["2015-2024", "2020-2024", "2024"]},
        labels={"Band": "Frequency Band", "Percentage": "Percentage of Assignments (%)"}
    )
    save_plot(fig, "frequency_bands_stacked_percentage.html")

def plot_antenna_pattern_count(stats_list: List[Tuple[str, pd.DataFrame]]):
    """Plots total defined patterns vs. used patterns (Earth/Space) per year."""
    # Combine the single-row dataframes from gather_antenna_pattern_stats
    combined_list = []
    for label, df in stats_list:
        if df is not None and not df.empty:
            df = df.copy()
            start_year, _ = parse_label_year(label)
            if start_year > 0:
                df['Year'] = start_year
                # Calculate counts of used unique patterns from the lists
                df['earth_used_count'] = df['unique_earth_pattern_ids'].apply(lambda x: len(x) if isinstance(x, list) else 0)
                df['space_used_count'] = df['unique_space_pattern_ids'].apply(lambda x: len(x) if isinstance(x, list) else 0)
                combined_list.append(df)

    if not combined_list:
        print("[Warning] No antenna pattern data to plot.")
        return

    combined_df = pd.concat(combined_list, ignore_index=True)

    # Aggregate counts per year (summing, as each yearly df should represent that year)
    df_yearly = combined_df.groupby("Year").agg(
        TotalPatterns=('total_pattern_count', 'sum'), # Sum distinct counts from each DB in that year
        EarthUsed=('earth_used_count', 'sum'),
        SpaceUsed=('space_used_count', 'sum')
    ).reset_index()

    # Ensure year is treated as a category for distinct bars
    df_yearly['Year'] = df_yearly['Year'].astype(str)

    # Create the grouped bar chart using Plotly Graph Objects for more control
    fig = go.Figure()

    # Bar group 1: Total Defined Patterns
    fig.add_trace(go.Bar(
        x=df_yearly["Year"],
        y=df_yearly["TotalPatterns"],
        name="Total Unique Patterns Defined (in ant_type)",
        marker_color='rgb(55, 83, 109)',
        offsetgroup=0, # Assign to group 0
    ))

    # Bar group 2, Trace 1: Earth Patterns Used (stacked base)
    fig.add_trace(go.Bar(
        x=df_yearly["Year"],
        y=df_yearly["EarthUsed"],
        name="Unique Earth Patterns Used (in e_as_stn)",
        marker_color='rgb(26, 118, 255)',
        offsetgroup=1, # Assign to group 1
        base=0 # Base for the first part of the stack in group 1
    ))

    # Bar group 2, Trace 2: Space Patterns Used (stacked on top)
    fig.add_trace(go.Bar(
        x=df_yearly["Year"],
        y=df_yearly["SpaceUsed"],
        name="Unique Space Patterns Used (in s_beam)",
        marker_color='rgb(118, 26, 255)', # Different color
        offsetgroup=1, # Assign to group 1
        base=df_yearly["EarthUsed"] # Stack on top of EarthUsed
    ))

    fig.update_layout(
        barmode="group", # Overall mode is grouped
        title="Antenna Patterns: Total Defined vs. Unique Used (Earth/Space) per Year",
        xaxis_title="Year",
        yaxis_title="Count of Unique Pattern IDs",
        xaxis={'type': 'category'}, # Ensure years are treated as categories
        legend_title="Pattern Type"
    )

    save_plot(fig, "pattern_count_stacked.html") # Filename kept as original


# === Main Execution Logic ===

def run_analysis_pipeline(time_frames: List[Tuple[str, str]]):
    """Executes the full analysis pipeline for the given time frames."""
    # Initialize lists to store results for each timeframe
    stats_ntc_id_list = []
    stats_admin_list = []
    stats_ntf_rsn_list = []
    stats_ntc_type_list = []
    stats_frequency_band_list = []
    stats_pattern_list = []

    all_records_processed = [] # Keep track of all records across timeframes

    # 1. Process each time frame
    for start_str, end_str in time_frames:
        start_date = parse_date(start_str)
        end_date = parse_date(end_str)
        timeframe_label = f"{start_date:%d.%m.%Y} - {end_date:%d.%m.%Y}"
        print(f"\n--- Processing Time Frame: {timeframe_label} ---")

        # Get records for the current timeframe
        records = get_records_in_date_range(start_date, end_date)
        if not records:
            print(f"[Info] No records found for {timeframe_label}.")
            # Append empty data to keep plot indices aligned if necessary
            stats_ntc_id_list.append((timeframe_label, pd.DataFrame()))
            stats_admin_list.append((timeframe_label, pd.DataFrame()))
            stats_ntf_rsn_list.append((timeframe_label, pd.DataFrame()))
            stats_ntc_type_list.append((timeframe_label, pd.DataFrame()))
            stats_frequency_band_list.append((timeframe_label, pd.DataFrame()))
            stats_pattern_list.append((timeframe_label, pd.DataFrame()))
            continue

        # Determine which files need downloading and add path info
        records_to_download = filter_and_prepare_downloads(records)

        # Download missing files
        if records_to_download:
            download_files_parallel(records_to_download)

        # Extract needed MDB files from ZIPs (handles existing MDBs)
        extract_zip_files(records) # Pass all records, it checks existence internally

        # Check if any MDB files actually exist for this timeframe before querying
        mdb_exists = any(os.path.exists(rec.get("mdb_path", "")) for rec in records)
        if not mdb_exists:
             print(f"[Warning] No MDB files available for querying in timeframe {timeframe_label}.")
             # Still append empty data
             stats_ntc_id_list.append((timeframe_label, pd.DataFrame()))
             stats_admin_list.append((timeframe_label, pd.DataFrame()))
             stats_ntf_rsn_list.append((timeframe_label, pd.DataFrame()))
             stats_ntc_type_list.append((timeframe_label, pd.DataFrame()))
             stats_frequency_band_list.append((timeframe_label, pd.DataFrame()))
             stats_pattern_list.append((timeframe_label, pd.DataFrame()))
             continue


        # Gather statistics for the current timeframe
        print(f"[Info] Gathering statistics for {timeframe_label}...")
        stats_ntc_id_list.append((timeframe_label, gather_ntc_id_stats(records)))
        stats_admin_list.append((timeframe_label, gather_admin_stats(records)))
        stats_ntf_rsn_list.append((timeframe_label, gather_ntf_rsn_stats(records)))
        stats_ntc_type_list.append((timeframe_label, gather_ntc_type_stats(records)))
        stats_frequency_band_list.append((timeframe_label, gather_frequency_band_stats(records)))
        stats_pattern_list.append((timeframe_label, gather_antenna_pattern_stats(records)))

        all_records_processed.extend(records) # Add to overall list if needed later

    # 2. Generate Plots using the collected statistics lists
    print("\n--- Generating Plots ---")
    if not any(not df.empty for _, df in stats_ntc_id_list):
         print("[Info] No data collected across all timeframes. Skipping plot generation.")
         return

    plot_unique_ntc_id_count_per_year(stats_ntc_id_list)
    plot_admin_counts_multi(stats_admin_list)
    plot_admin_counts_stacked_percentage(stats_admin_list) # Uses default cutoff=3%
    plot_ntf_rsn_stacked(stats_ntf_rsn_list)
    plot_ntf_rsn_stacked_percentage(stats_ntf_rsn_list)
    plot_ntc_type_stacked(stats_ntc_type_list)
    plot_ntc_type_stacked_percentage(stats_ntc_type_list)
    plot_frequency_bands_stacked(stats_frequency_band_list)
    plot_frequency_bands_stacked_percentage(stats_frequency_band_list)
    plot_antenna_pattern_count(stats_pattern_list)

    print("\n--- Analysis Complete ---")


if __name__ == "__main__":
    print("Starting ITU IFIC Analysis Script...")
    # Ensure base directories exist before starting
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(EXTRACT_DIR, exist_ok=True)

    run_analysis_pipeline(DEFAULT_TIME_FRAMES)

    print("Script finished.")