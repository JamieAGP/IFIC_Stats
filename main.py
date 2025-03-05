import os
import re
import zipfile
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import pyodbc
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# Constants
DOWNLOAD_DIR = r"C:\Users\JamieParker\Documents\ITU\IFICS\downloads"
EXTRACT_DIR  = r"C:\Users\JamieParker\Documents\ITU\IFICS\databases"
BASE_URL     = "https://www.itu.int/sns/wic/demowic{year}.html"
VALID_VERSIONS = ("converted-to-v9.1", "converted-to-v10", "ific10")

def parse_date(date_str):
    return datetime.strptime(date_str, "%d.%m.%Y")

def fetch_page(url):
    try:
        r = requests.get(url)
        return r if r.status_code == 200 else None
    except Exception:
        return None

def get_ific_records_for_year(year):
    year_suffix = str(year)[-2:]
    url = BASE_URL.format(year=year_suffix)
    resp = fetch_page(url)
    if not resp:
        print(f"[Warning] Page for {year} not found: {url}")
        return []
    soup = BeautifulSoup(resp.text, 'html.parser')
    records = []
    for tr in soup.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        m = re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", text)
        if not m:
            continue
        try:
            rec_date = parse_date(m.group(0))
        except Exception:
            continue
        valid_link = None
        for a in tr.find_all("a", href=True):
            if any(ver in a['href'] for ver in VALID_VERSIONS):
                valid_link = a
                break
        if valid_link:
            link = valid_link['href']
            full_link = link if link.startswith("http") else urljoin(url, link)
            records.append({"date": rec_date, "url": full_link})
    return records

def get_date_range_records(start_date, end_date):
    records = []
    for yr in range(start_date.year, end_date.year + 1):
        year_suffix = str(yr)[-2:]
        url = BASE_URL.format(year=year_suffix)
        if not fetch_page(url):
            print(f"[Warning] Page for {yr} not found: {url}")
            continue
        for rec in get_ific_records_for_year(yr):
            if start_date <= rec["date"] <= end_date:
                records.append(rec)
    return records

def prompt_for_download(records):
    to_download = []
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    for rec in records:
        zip_name = os.path.basename(rec["url"])
        zip_path = os.path.join(DOWNLOAD_DIR, zip_name)
        rec["zip_path"] = zip_path
        if not os.path.exists(zip_path):
            to_download.append(rec)
    return to_download

def download_file(rec):
    """Download a single ZIP file with a larger chunk size for efficiency."""
    zip_path = rec["zip_path"]
    url = rec["url"]

    if os.path.exists(zip_path):
        print(f"[Info] Already downloaded: {zip_path}")
        return

    print(f"[Downloading] {url} -> {zip_path}")
    try:
        session = requests.Session()
        with session.get(url, stream=True, timeout=10) as r:
            if r.status_code == 200:
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
                print(f"[Success] Downloaded: {zip_path}")
            else:
                print(f"[Error] Failed: {url} (Status {r.status_code})")
    except Exception as e:
        print(f"[Error] Downloading {url}: {e}")

def download_files_parallel(files, max_workers=5):
    """Download multiple files concurrently using ThreadPoolExecutor."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(download_file, files)

def extract_zip_files(records):
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    for rec in records:
        try:
            with zipfile.ZipFile(rec["zip_path"], 'r') as z:
                mdb_files = [f for f in z.namelist() if f.lower().endswith('.mdb')]
                if not mdb_files:
                    print(f"[Warning] No .mdb file in {os.path.basename(rec['zip_path'])}")
                for file in mdb_files:
                    target_path = os.path.join(EXTRACT_DIR, os.path.basename(file))
                    if os.path.exists(target_path):
                        print(f"[Info] {os.path.basename(file)} already extracted, skipping.")
                        continue
                    z.extract(file, EXTRACT_DIR)
                    print(f"Extracted {file} from {os.path.basename(rec['zip_path'])}")
        except Exception as e:
            print(f"[Error] Extracting {os.path.basename(rec['zip_path'])}: {e}")

def select_date(prompt_text, default):
    s = input(f"{prompt_text} (default {default}): ").strip()
    return s if s else default

def interactive_date_input():
    current_year = datetime.now().year
    available = [yr for yr in range(1998, current_year + 2)
                 if fetch_page(BASE_URL.format(year=str(yr)[-2:]))]
    print("Available years:", available)
    start_str = select_date("Enter start date (dd.mm.yyyy)", "01.01.2024")
    end_str   = select_date("Enter end date (dd.mm.yyyy)", "01.01.2026")
    try:
        start_date = parse_date(start_str)
        end_date = parse_date(end_str)
    except Exception:
        print("Invalid date format. Exiting.")
        exit(1)
    if start_date > end_date:
        print("Start date must be before end date. Exiting.")
        exit(1)
    return start_date, end_date

def query_databases():
    admin_counts = {}
    ntf_rsn_counts = {}
    ntc_type_counts = {}
    total_notices = 0
    valid_ntc_types = {"G", "N", "S", "T", "R"}

    for file in os.listdir(EXTRACT_DIR):
        if file.lower().endswith('.mdb'):
            mdb_path = os.path.join(EXTRACT_DIR, file)
            try:
                conn_str = r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + mdb_path
                conn = pyodbc.connect(conn_str)
                cursor = conn.cursor()
                cursor.execute("SELECT adm, ntf_rsn, ntc_type FROM notice")
                for row in cursor.fetchall():
                    total_notices += 1
                    adm = row.adm.strip() if row.adm else "Unknown"
                    ntf_rsn = row.ntf_rsn.strip() if row.ntf_rsn else "Unknown"
                    ntc_type = row.ntc_type.strip().upper() if row.ntc_type else "Unknown"
                    admin_counts[adm] = admin_counts.get(adm, 0) + 1
                    ntf_rsn_counts[ntf_rsn] = ntf_rsn_counts.get(ntf_rsn, 0) + 1
                    if ntc_type in valid_ntc_types:
                        ntc_type_counts[ntc_type] = ntc_type_counts.get(ntc_type, 0) + 1
                conn.close()
            except Exception as e:
                print(f"[Error] Processing {mdb_path}: {e}")

    # Administration Horizontal Bar Chart (sorted descending)
    sorted_admin = sorted(admin_counts.items(), key=lambda x: x[1], reverse=True)
    df_admin = pd.DataFrame(sorted_admin, columns=["Administration", "Count"])
    fig_admin = px.bar(df_admin, x="Count", y="Administration", orientation="h",
                       title="Notice Counts per Administration",
                       text="Count")
    fig_admin.update_traces(textposition="outside")
    fig_admin.update_layout(yaxis={'categoryorder':'total ascending'})
    pio.write_html(fig_admin, file="admin_counts_horizontal.html", auto_open=False)

    # ntf_rsn Pie Chart
    ntf_rsn_mapping = {
        "N": "RR1488 / 11.2 / 11.12 / AP30/30A-Article 5 / AP30B-Article 8",
        "C": "RR1060 / 9.6 / 9.7A / 9.21",
        "D": "RR1107 / 9.17",
        "A": "9.1",
        "B": "AP30/30A-Articles 2A & 4",
        "P": "AP30B-Articles 6 & 7",
        "U": "Res49"
    }
    df_ntf = pd.DataFrame(list(ntf_rsn_counts.items()), columns=["Reason", "Count"])
    df_ntf["Reason"] = df_ntf["Reason"].map(ntf_rsn_mapping)
    df_ntf["Percentage"] = df_ntf["Count"] / df_ntf["Count"].sum() * 100
    fig_ntf = px.pie(df_ntf, names="Reason", values="Percentage",
                     title="Notification Reasons Distribution (ntf_rsn)",
                     hover_data=["Count"])
    fig_ntf.update_traces(textposition='inside', textinfo='label+percent')
    pio.write_html(fig_ntf, file="ntf_rsn_percentages.html", auto_open=False)

    # ntc_type Pie Chart
    ntc_type_mapping = {
        "N": "Non-geostationary",
        "G": "Geostationary",
        "S": "Specific Earth station",
        "R": "Radio astronomy station",
        "T": "Typical Earth station"
    }
    df_ntc = pd.DataFrame([
        {"Type": key, "Count": ntc_type_counts.get(key, 0)} for key in sorted(valid_ntc_types)
    ])
    df_ntc["Type"] = df_ntc["Type"].map(ntc_type_mapping)
    df_ntc["Percentage"] = df_ntc["Count"] / total_notices * 100 if total_notices else 0
    fig_ntc = px.pie(df_ntc, names="Type", values="Percentage",
                     title="Notice Type Distribution (ntc_type)",
                     hover_data=["Count"])
    fig_ntc.update_traces(textposition='inside', textinfo='label+percent')
    pio.write_html(fig_ntc, file="ntc_type_distribution.html", auto_open=False)

    print("\nCharts generated:")
    print(" - admin_counts_horizontal.html")
    print(" - ntf_rsn_percentages.html")
    print(" - ntc_type_distribution.html")
    print(f"\nTotal notices processed: {total_notices}")

def main():
    start_date, end_date = interactive_date_input()
    records = get_date_range_records(start_date, end_date)
    if not records:
        print("No IFIC records found for the given range in available pages.")
        return
    print(f"\nFound {len(records)} IFIC record(s) in the range:")
    for rec in records:
        print(f" - {rec['date'].strftime('%d.%m.%Y')}: {os.path.basename(rec['url'])}")

    to_download = prompt_for_download(records)
    if to_download:
        print(f"\n{len(to_download)} file(s) need downloading.")
        if input("Proceed with download? (y/n): ").lower() != "y":
            print("Aborted by user.")
            return
        # Use concurrent downloads to speed up the process
        download_files_parallel(to_download, max_workers=5)
    else:
        print("\nAll files already downloaded.")

    extract_zip_files(records)
    print("\nDatabases ready for queries.")

    if input("Run queries on the IFIC databases? (y/n): ").lower() == "y":
        query_databases()

if __name__ == "__main__":
    main()
