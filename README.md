# **ITU IFIC Database Statistics**

## **Overview**
The **Space International Frequency Information Circular (IFIC)**, published by the **ITU**, provides a comprehensive dataset on satellite network filings, frequency assignments, and coordination requests. It is a critical resource for **spectrum management, interference analysis, and regulatory compliance**.

This document presents an analysis of **trends and statistics** extracted from the IFIC database using scripts in this repository and IFIC datasets from the [ITU IFIC Database](https://www.itu.int/sns/wic/demowic25.html).

---


# ITU IFIC Database Statistics

## 1. Annual Filing Trends & Spectrum Management

### 1.1 Overall Filing Activity
- **Yearly Active Filings:** In the last 10 years, ~3000 new filings are made every year. Filing activity has [generally increased](README_plots/unique_ntc_id_per_year.html) in the last 10 years, while there are small dips in specific years.
- **Administration Contributions:** [China, USA, France and Russa are the most prominent single contributors](README_plots/admin_counts_stacked_percentage.html). Together they make up nearly half of all filings. The UAE have increased their filing in the last year relative to the last decade, while Germany have decreased their presence.

### 1.2 Orbit Type & Frequency Trends
- **GSO vs. NGSO Split:** Non-Geostationary filings are steadiliy increasing in [count](README_plots/ntc_type_stacked.html) and [proportion](README_plots/ntc_type_stacked_percentage.html) of filings. In 2024, NGSO filings represent 43% of all submissions, compared to 38% for GSO, marking a shift in orbital deployment strategy.
- **Frequency Band Usage:** K, Ka and Ku bands are the most widely used bands, together [making up ~60% of total filings](README_plots/frequency_bands_stacked_percentage.html). L-band usage has grown steadily, along with UHF-band amd V-band. Legacy bands such as C and X show a gradual decline. [Actual counts](README_plots/frequency_bands_stacked.html).

### 1.3 Notification Reason
- The group comprising RR1488 / 11.2 / 11.12 / AP30/30A-Art 5 / AP30B-Art 8, which governs the formal notification and recording of assignments, especially for planned services like BSS and FSS, has consistently made up [approximately 44% of filings](README_plots/ntf_rsn_stacked_percentage.html), reflecting a stable and procedural use of spectrum resources.
- The RR1060 / 9.6 / 9.7A / 9.21 group, which covers coordination requirements to avoid interference, [peaked in 2017 and has steadily declined](README_plots/ntf_rsn_stacked.html), indicating reduced reliance on coordination procedures, possibly due to shifts toward planned band usage or more simplified regulatory environments.
- Article 9.1 filings, which represent advance publication for planned satellite networks, show a strong upward trend from their lowest point in 2016. This suggests a shift toward more proactive spectrum planning, likely driven by the rise of large NGSO constellations.

## 2. Antenna Radiation Patterns

- **Yearly Increase:** Although the total number of antenna patterns has [steadily increased](README_plots/pattern_count_stacked.html) over the last 10 years, the number of patterns actually in use has remained signficantly lower. The patterns here are counted via their pattern ID.

---
# How to Use

1. **Setup Environment**
   ```
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

2. **Directories**
   - Adjust `DOWNLOAD_DIR`, `EXTRACT_DIR`, `OUTPUT_DIR` in the script as needed.

3. **Run Script**
   - Simply run: `python your_script.py`
   - The script downloads, extracts MDB files, runs queries, and saves charts in `OUTPUT_DIR`.
