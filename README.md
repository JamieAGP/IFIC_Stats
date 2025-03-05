# ITU IFIC Database Processing Script

## Overview
This Python script automates the process of fetching, downloading, extracting, and analyzing ITU's **IFIC (International Frequency Information Circular)** databases. It performs the following tasks:

1. **Fetches IFIC record URLs** from ITU's official website.
2. **Downloads ZIP files** containing `.mdb` (Microsoft Access Database) files.
3. **Extracts the databases** into a local directory.
4. **Queries the databases** to analyze notice records.
5. **Generates interactive charts** using Plotly.

---

## Dependencies
Ensure you have the following Python libraries installed:

```bash
pip install requests beautifulsoup4 pyodbc plotly pandas concurrent.futures
```

---

## Directory Structure
- **`downloads/`** → Stores the downloaded IFIC ZIP files.
- **`databases/`** → Extracted `.mdb` database files.
- **Generated Charts:**
  - `admin_counts_horizontal.html` (Notice counts per administration)
  - `ntf_rsn_percentages.html` (Notification reasons distribution)
  - `ntc_type_distribution.html` (Notice type distribution)

---

## Script Components

### 1. **Fetching IFIC Records**
- Scrapes IFIC database links from ITU's website for a given year range.
- Extracts valid download links matching specific IFIC database formats (`converted-to-v9.1`, `converted-to-v10`, `ific10`).

### 2. **Downloading IFIC Files**
- Identifies which files need downloading and fetches them using `requests`.
- Uses **ThreadPoolExecutor** to download files concurrently.

### 3. **Extracting Databases**
- Unzips the `.mdb` files from downloaded archives.
- Checks for duplicate extractions to prevent redundant processing.

### 4. **Querying the Databases**
- Connects to each `.mdb` file using `pyodbc`.
- Retrieves and aggregates notice data, analyzing:
  - **Notices per administration**
  - **Notification reasons (`ntf_rsn`)**
  - **Notice types (`ntc_type`)**
- Outputs summary statistics and generates visualizations.

### 5. **Generating Charts**
- Uses **Plotly** to create interactive bar and pie charts.
- Saves charts as standalone HTML files for easy sharing.

---

## Usage Instructions
1. **Run the script:**
   ```bash
   python script.py
   ```
2. **Enter the date range** when prompted.
3. **Confirm downloads** if required.
4. **Extract and analyze** the databases.
5. **View the generated charts** in your browser.

---

## Notes
- Requires **Microsoft Access ODBC Driver** to read `.mdb` files.
- Can be modified to handle different IFIC formats.
- Improves efficiency with parallel downloads and structured queries.

---

### **Example Output**
```
Found 10 IFIC record(s) in the range:
 - 15.01.2024: IFIC_2024_01.zip
 - 29.01.2024: IFIC_2024_02.zip
...
3 file(s) need downloading.
Proceed with download? (y/n): y
[Downloading] https://www.itu.int/... -> IFIC_2024_01.zip
...
[Success] Downloaded: IFIC_2024_01.zip
Extracted IFIC_2024_01.mdb
...
Total notices processed: 150,000
Charts generated:
 - admin_counts_horizontal.html
 - ntf_rsn_percentages.html
 - ntc_type_distribution.html
```

---

## Future Improvements
- Automate database cleanup after processing.
- Enhance error handling for failed downloads.
- Add filtering options for more granular notice queries.

---

**Author:** Jamie Parker
**Last Updated:** March 2025