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
TIMEOUT = 40

DEFAULT_URLS = """https://tsclistens.com/is-silver-peak-markets-legit-or-a-scam-the-facts-behind-the-brand/
https://revenueandprofit.net/trade-forex-with-silver-peak-markets/"""

TRACKING = {"fbclid", "gclid", "gbraid", "wbraid", "msclkid", "mc_cid", "mc_eid"}


def normalize_url(value):
    value = str(value).strip()
    if not value:
        return ""
    if not value.startswith(("https://", "http://")):
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
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in TRACKING
        ]
        return urlunparse(("https", host, path, "", urlencode(sorted(params)), ""))
    except (ValueError, TypeError):
        return ""


def unique_lines(value):
    return list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))


def status_for_position(position):
    if position <= 10:
        return "TOP 10"
    if position <= 20:
        return "TOP 20"
    if position <= 50:
        return "TOP 50"
    if position <= 100:
        return "TOP 100"
    return "VAN TOP 100"


def fetch_keyword(session, api_key, keyword, country, language, progress_callback):
    found = {}
    diagnostics = []
    for page in range(1, MAX_PAGES + 1):
        payload = {
            "q": keyword,
            "gl": country,
            "hl": language,
            "page": page,
            "num": PAGE_SIZE,
        }
        response = session.post(
            API_URL,
            json=payload,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Upit '{keyword}', stranica {page}: API HTTP "
                f"{response.status_code}: {response.text[:250]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Neispravan JSON za '{keyword}', strana {page}") from exc
        if data.get("error"):
            raise RuntimeError(f"Serper: {data['error']}")
        organic = data.get("organic")
        if not isinstance(organic, list):
            raise RuntimeError(f"Nedostaje lista organskih rezultata za '{keyword}', strana {page}")

        new_count = 0
        duplicate_count = 0
