import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Bulk SERP Position Checker", page_icon="🔎", layout="wide")

API_URL = "https://google.serper.dev/search"
PAGE_SIZE = 10
MAX_PAGES = 10
REQUEST_TIMEOUT = 45
DEFAULT_URLS = """https://techbullion.com/silver-peak-markets-review-a-detailed-look-at-trading-conditions-and-
https://tsclistens.com/is-silver-peak-markets-legit-or-a-scam-the-facts-behind-the-brand/
https://revenueandprofit.net/trade-forex-with-silver-peak-markets/"""
TRACKING_PARAMS = {"fbclid", "gclid", "gbraid", "wbraid", "msclkid", "mc_cid", "mc_eid"}
RESULT_COLUMNS = ["Source URL", "Ključna reč", "Google pozicija", "Status", "Google naslov", "Pronađeni Google URL", "SERP rezultata", "Provera TOP 100", "Zemlja", "Jezik", "Datum provere"]


def normalize_url(value):
    value = str(value).strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    try:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if not hostname:
            return ""
        if hostname.startswith("www."):
            hostname = hostname[4:]
        port = parsed.port
        if port and port not in (80, 443):
            hostname += f":{port}"
        path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
        params = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                  if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS]
        return urlunparse(("https", hostname, path, "", urlencode(sorted(params)), ""))
    except (ValueError, TypeError):
        return ""


def unique_lines(value):
    return list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))


def get_api_key():
    try:
        return st.secrets.get("SERPER_API_KEY", "")
    except Exception:
        return ""


def position_status(position):
    if position <= 10:
        return "TOP 10"
    if position <= 20:
        return "TOP 20"
    if position <= 50:
        return "TOP 50"
    return "TOP 100"


def status_style(value):
    if value == "TOP 10":
        return "background-color:#d9ead3;color:#274e13"
    if value in ("TOP 20", "TOP 50"):
        return "background-color:#fff2cc;color:#7f6000"
    if value in ("TOP 100", "NEPOTPUNA PROVERA"):
        return "background-color:#fce5cd;color:#783f04"
    if value == "NIJE PRONAĐEN":
        return "background-color:#f4cccc;color:#990000"
    return ""


def fetch_serper_page(session, api_key, keyword, country, language, page_number):
    response = session.post(
        API_URL,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": keyword, "gl": country, "hl": language, "num": PAGE_SIZE, "page": page_number},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("Serper nije vratio validan JSON odgovor.")
    if not isinstance(data, dict):
        raise RuntimeError("Neočekivani format Serper odgovora.")
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    organic = data.get("organic")
