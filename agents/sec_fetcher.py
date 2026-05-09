import requests
import re
import time
from datetime import datetime


# Known CIK overrides for newly listed / re-listed companies that may not appear
# in the main company_tickers.json yet
KNOWN_CIKS = {
    "SNDK": "0002023554",  # Sandisk Corp (spin-off from WD, re-listed 2024)
}

def get_cik_from_ticker(ticker: str) -> str:
    """Convert ticker to SEC CIK number"""
    ticker_upper = ticker.upper()
    if ticker_upper in KNOWN_CIKS:
        cik = KNOWN_CIKS[ticker_upper]
        print("CIK from override table: " + cik + " (" + ticker_upper + ")")
        return cik
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    headers = {"User-Agent": "AI-Investment-HQ research@example.com"}

    try:
        resp = requests.get(tickers_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            tickers_data = resp.json()
            ticker_upper = ticker.upper()
            for key, company in tickers_data.items():
                if company.get("ticker", "").upper() == ticker_upper:
                    cik = str(company["cik_str"]).zfill(10)
                    print("CIK found: " + cik + " (" + company["title"] + ")")
                    return cik
    except Exception as e:
        print("CIK lookup failed: " + str(e))

    return None


def get_latest_filing_text(cik: str, form_type: str = "10-Q") -> str:
    """Fetch latest filing text from SEC EDGAR"""
    headers = {"User-Agent": "AI-Investment-HQ research@example.com"}
    submissions_url = "https://data.sec.gov/submissions/CIK" + cik + ".json"

    try:
        resp = requests.get(submissions_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return ""

        data = resp.json()
        company_name = data.get("name", "Unknown")
        filings = data.get("filings", {}).get("recent", {})

        forms = filings.get("form", [])
        accession_numbers = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])

        for i, form in enumerate(forms):
            if form == form_type:
                acc_num_clean = accession_numbers[i].replace("-", "")
                filing_date = filing_dates[i]
                primary_doc = primary_docs[i]

                print("Found " + form_type + ": " + filing_date)

                doc_url = ("https://www.sec.gov/Archives/edgar/data/"
                           + str(int(cik)) + "/" + acc_num_clean + "/" + primary_doc)

                time.sleep(0.5)
                doc_resp = requests.get(doc_url, headers=headers, timeout=30)

                if doc_resp.status_code == 200:
                    text = doc_resp.text
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"&nbsp;", " ", text)
                    text = re.sub(r"&amp;", "&", text)
                    text = re.sub(r"\s+", " ", text)

                    if len(text) > 15000:
                        mda_start = text.lower().find("management's discussion")
                        if mda_start == -1:
                            mda_start = text.lower().find("results of operations")
                        if mda_start > 0:
                            extract = text[mda_start:mda_start + 8000]
                        else:
                            extract = text[:8000]

                        risk_start = text.lower().find("risk factor")
                        if risk_start > 0:
                            extract += "\n\n[Risk Factors]\n" + text[risk_start:risk_start + 3000]
                    else:
                        extract = text

                    return "## " + company_name + " - " + form_type + " (" + filing_date + ")\n\n" + extract

                break

    except Exception as e:
        print("SEC filing fetch failed: " + str(e))

    return ""


def fetch_sec_filing(ticker: str, form_type: str = "10-Q") -> str:
    """Main entry: ticker -> latest filing text"""
    print("Fetching SEC " + form_type + " for $" + ticker + "...")

    cik = get_cik_from_ticker(ticker)
    if not cik:
        return "SEC data not found for " + ticker

    text = get_latest_filing_text(cik, form_type)
    if not text and form_type == "10-Q":
        print("10-Q not found, trying 10-K...")
        text = get_latest_filing_text(cik, "10-K")

    return text if text else "Unable to retrieve " + form_type + " for " + ticker


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "SNDK"
    result = fetch_sec_filing(t)
    print(result[:2000])
