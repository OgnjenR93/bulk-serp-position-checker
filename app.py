import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Bulk SERP Position Checker", page_icon="🔎", layout="wide")

API_URL = "https://google.serper.dev/search"
PAGE_SIZE = 10
TOP_LIMIT = 100
MAX_PAGES = 12  # Two additional pages for diagnostics; never call them TOP 100.
TIMEOUT = 40
TRACKING_PARAMS = {"fbclid", "gclid", "gbraid", "wbraid", "msclkid", "mc_cid", "mc_eid"}
DEFAULT_URLS = """https://techbullion.com/
https://tsclistens.com/is-silver-peak-markets-legit-or-a-scam-the-facts-behind-the-brand/
https://revenueandprofit.net/trade-forex-with-silver-peak-markets/"""


def normalize_url(value):
    value = str(value).strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return ""
        if host.startswith("www."):
            host = host[4:]
        if parsed.port and parsed.port not in (80, 443):
            host += f":{parsed.port}"
        path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
        params = [
            (key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
        ]
        return urlunparse(("https", host, path, "", urlencode(sorted(params)), ""))
    except (TypeError, ValueError):
        return ""


def unique_lines(text):
    return list(dict.fromkeys(x.strip() for x in text.splitlines() if x.strip()))


def api_key():
    try:
        return st.secrets.get("SERPER_API_KEY", "")
    except Exception:
        return ""


def get_page(session, key, keyword, country, language, page):
    response = session.post(
        API_URL,
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": keyword, "gl": country, "hl": language, "page": page, "num": PAGE_SIZE},
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Serper HTTP {response.status_code}: {response.text[:250]}")
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Serper nije vratio validan JSON.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("organic"), list):
        raise RuntimeError("Serper nije vratio očekivanu listu organskih rezultata.")
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data["organic"]


def parse_position(item, page, index):
    """Return the API-reported position when usable, otherwise page-slot estimate.

    The API can report global positions or page-local 1..10 positions.
    The source of the position is recorded; estimates are not labeled confirmed.
    """
    raw = item.get("position")
    try:
        raw = int(raw)
    except (TypeError, ValueError):
        raw = None
    offset = (page - 1) * PAGE_SIZE
    if raw is None or raw <= 0:
        return offset + index + 1, "PROCENA (redosled)"
    if page > 1 and raw <= PAGE_SIZE:
        return offset + raw, "PROCENA (lokalna pozicija)"
    return raw, "API pozicija"

