
import re
from datetime import datetime, timezone
from urllib.parse import (
    urlparse,
    urlunparse,
    parse_qsl,
    urlencode,
)

import pandas as pd
import requests
import streamlit as st


# ============================================================
# CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Bulk SERP Position Checker",
    page_icon="🔎",
    layout="wide",
)

API_URL = "https://google.serper.dev/search"
PAGE_SIZE = 10
MAX_PAGES = 10
REQUEST_TIMEOUT = 45

DEFAULT_URLS = """https://techbullion.com/silver-peak-markets-review-a-detailed-look-at-trading-conditions-and-
https://tsclistens.com/is-silver-peak-markets-legit-or-a-scam-the-facts-behind-the-brand/
https://revenueandprofit.net/trade-forex-with-silver-peak-markets/"""

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "gbraid",
    "wbraid",
    "msclkid",
    "mc_cid",
    "mc_eid",
}

RESULT_COLUMNS = [
    "Source URL",
    "Ključna reč",
    "Google pozicija",
    "Status",
    "Google naslov",
    "Pronađeni Google URL",
    "SERP rezultata",
    "Provera TOP 100",
    "Zemlja",
    "Jezik",
    "Datum provere",
]


# ============================================================
# HELPERS
# ============================================================

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

        path = re.sub(r"/+", "/", parsed.path or "/")
        path = path.rstrip("/") or "/"

        params = parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        params = [
            (key, val)
            for key, val in params
            if not key.lower().startswith("utm_")
            and key.lower() not in TRACKING_PARAMS
        ]

        return urlunparse(
            (
                "https",
                hostname,
                path,
                "",
                urlencode(sorted(params)),
                "",
            )
        )

    except (ValueError, TypeError):
        return ""


def unique_lines(text):
    return list(
        dict.fromkeys(
            line.strip()
            for line in text.splitlines()
            if line.strip()
        )
    )


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
    if value == "TOP 100":
        return "background-color:#fce5cd;color:#783f04"
    if value == "NIJE PRONAĐEN":
        return "background-color:#f4cccc;color:#990000"
    if value == "NEPOTPUNA PROVERA":
        return "background-color:#fce5cd;color:#783f04"
    return ""


# ============================================================
# SERPER API
# ============================================================

def fetch_serper_page(
    session,
    api_key,
    keyword,
    country,
    language,
    page_number,
):
    payload = {
        "q": keyword,
        "gl": country,
        "hl": language,
        "num": PAGE_SIZE,
        "page": page_number,
    }

    response = session.post(
        API_URL,
        headers={
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            "Serper nije vratio validan JSON odgovor."
        )

    if not isinstance(data, dict):
        raise RuntimeError(
            "Neočekivani format Serper odgovora."
        )

    if data.get("error"):
        raise RuntimeError(str(data["error"]))

    organic = data.get("organic")

    if not isinstance(organic, list):
        raise RuntimeError(
            "Serper odgovor ne sadrži validnu "
            "listu organskih rezultata."
        )

    return organic


def resolve_position(item, page_number, index):
    """
    Serper position može biti lokalna ili globalna
    pozicija, u zavisnosti od API odgovora.

    Za lokalnu poziciju 1-10 na narednim stranicama
    primenjujemo offset.

    Ako position nedostaje, koristimo redosled
    rezultata na zatraženoj stranici.

    Ovo je API-reported/inferred organic position,
    a ne nezavisno verifikovana Google pozicija.
    """
    raw = item.get("position")

    try:
        raw = int(raw)
    except (TypeError, ValueError):
        raw = None

    offset = (page_number - 1) * PAGE_SIZE

    if raw is None or raw < 1:
        return offset + index + 1

    if page_number > 1 and raw <= PAGE_SIZE:
        return offset + raw

    return raw


def fetch_keyword_results(
    session,
    api_key,
    keyword,
    country,
    language,
    progress_callback,
):
    results = []
    seen_urls = set()
    page_log = []

    for page_number in range(1, MAX_PAGES + 1):
        organic = fetch_serper_page(
            session,
            api_key,
            keyword,
            country,
            language,
            page_number,
        )

        added = 0
        duplicates = 0

        for index, item in enumerate(organic):
            if not isinstance(item, dict):
                continue

            link = item.get("link", "")
            normalized = normalize_url(link)

            if not normalized:
                continue

            if normalized in seen_urls:
                duplicates += 1
                continue

            seen_urls.add(normalized)
            added += 1

            position = resolve_position(
                item,
                page_number,
                index,
            )

            results.append({
                "position": position,
                "title": item.get("title", ""),
                "link": link,
                "normalized": normalized,
                "page": page_number,
            })

        page_log.append({
            "Ključna reč": keyword,
            "Stranica": page_number,
            "Vraćeno rezultata": len(organic),
            "Novih URL-ova": added,
            "Duplikata": duplicates,
        })

        progress_callback(page_number)

        if not organic:
            break

        if len(results) >= 100:
            break

        # Namerno ne prekidamo na jednoj stranici
        # sa duplikatima ili manje od 10 rezultata.

    results.sort(key=lambda x: x["position"])
    results = results[:100]

    positions = [r["position"] for r in results]

    # Konzervativno: kompletna provera zahteva
    # 100 jedinstvenih rezultata i sve pozicije
    # od 1 do 100 bez rupa ili preklapanja.
    complete = (
        len(results) == 100
        and sorted(positions) == list(range(1, 101))
    )

    return {
        "keyword": keyword,
        "results": results,
        "complete": complete,
        "page_log": page_log,
        "pages_requested": len(page_log),
    }


# ============================================================
# MATCHING
# ============================================================

def build_output(urls, keyword_data, country, language):
    rows = []
    checked_at = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    for data in keyword_data:
        keyword = data["keyword"]
        organic = data["results"]
        complete = data["complete"]

        lookup = {}

        for item in organic:
            key = item["normalized"]

            if (
                key not in lookup
                or item["position"] < lookup[key]["position"]
            ):
                lookup[key] = item

        for source_url in urls:
            normalized = normalize_url(source_url)
            match = lookup.get(normalized)

            if match:
                status = position_status(match["position"])
                position = match["position"]
                title = match["title"]
                found_url = match["link"]

            elif complete:
                status = "NIJE PRONAĐEN"
                position = None
                title = ""
                found_url = ""

            else:
                status = "NEPOTPUNA PROVERA"
                position = None
                title = ""
                found_url = ""

            rows.append({
                "Source URL": source_url,
                "Ključna reč": keyword,
                "Google pozicija": position,
                "Status": status,
                "Google naslov": title,
                "Pronađeni Google URL": found_url,
                "SERP rezultata": len(organic),
                "Provera TOP 100": (
                    "KOMPLETNA"
                    if complete
                    else "NEPOTPUNA"
                ),
                "Zemlja": country.upper(),
                "Jezik": language,
                "Datum provere": checked_at,
            })

    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


# ============================================================
# STREAMLIT UI
# ============================================================

st.title("🔎 Bulk SERP Position Checker")

st.write(
    "Proveri pozicije PR i link-building objava "
    "za više ključnih reči u Google organskim rezultatima."
)

st.subheader("1. Podešavanja pretrage")

c1, c2 = st.columns(2)

with c1:
    country = st.selectbox(
        "Google tržište",
        ["us", "rs", "me", "ba", "hr"],
        format_func=lambda x: {
            "us": "United States",
            "rs": "Serbia",
            "me": "Montenegro",
            "ba": "Bosnia and Herzegovina",
            "hr": "Croatia",
        }[x],
    )

with c2:
    language = st.selectbox(
        "Jezik rezultata",
        ["en", "sr", "hr"],
        format_func=lambda x: {
            "en": "English",
            "sr": "Serbian",
            "hr": "Croatian",
        }[x],
    )

keywords_input = st.text_area(
    "Ključne reči – jedna po redu",
    value="silver peak\nsilver peak markets",
    height=100,
)

st.subheader("2. URL-ovi objava")

urls_input = st.text_area(
    "Unesi URL-ove – jedan po redu",
    value=DEFAULT_URLS,
    height=180,
)

st.caption(
    "Za svaku ključnu reč alat preuzima do 10 stranica "
    "Google organskih rezultata i poredi ih sa svim "
    "unetim URL-ovima."
)

api_key = get_api_key()

if not api_key:
    st.warning(
        "SERPER_API_KEY nije podešen u Streamlit Secrets."
    )

if st.button(
    "🔎 Run SERP Check",
    type="primary",
    disabled=not bool(api_key),
):
    keywords = unique_lines(keywords_input)
    urls = unique_lines(urls_input)

    if not keywords:
        st.error("Unesi najmanje jednu ključnu reč.")
        st.stop()

    if not urls:
        st.error("Unesi najmanje jedan URL.")
        st.stop()

    invalid = [
        url for url in urls
        if not normalize_url(url)
    ]

    if invalid:
        st.error(
            "Neispravni URL-ovi: "
            + ", ".join(invalid[:5])
        )
        st.stop()

    st.info(
        f"Ključne reči: {len(keywords)} | "
        f"URL-ovi: {len(urls)} | "
        f"Maksimalno API zahteva: "
        f"{len(keywords) * MAX_PAGES}"
    )

    progress = st.progress(0)
    message = st.empty()

    keyword_data = []
    total_steps = len(keywords) * MAX_PAGES

    session = requests.Session()

    try:
        for keyword_index, keyword in enumerate(keywords):

            message.write(
                f"Proveravam: {keyword}"
            )

            def update_progress(page_number):
                completed = (
                    keyword_index * MAX_PAGES
                    + page_number
                )
                progress.progress(
                    min(completed / total_steps, 1.0)
                )

            data = fetch_keyword_results(
                session,
                api_key,
                keyword,
                country,
                language,
                update_progress,
            )

            keyword_data.append(data)

    except (requests.RequestException, RuntimeError) as exc:
        st.error(
            "API provera nije završena. "
            "Nepotpuni podaci se neće prikazati "
            "kao konačni rezultati. "
            f"Detalji: {exc}"
        )
        st.stop()

    finally:
        session.close()

    progress.progress(1.0)
    message.empty()

    df = build_output(
        urls,
        keyword_data,
        country,
        language,
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    st.subheader("3. Summary")

    found = df["Google pozicija"].notna()
    incomplete = df["Status"] == "NEPOTPUNA PROVERA"

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Uneti URL-ovi", len(urls))
    c2.metric("Ključne reči", len(keywords))
    c3.metric("Pronađene pozicije", int(found.sum()))
    c4.metric("Nepotvrđeni parovi", int(incomplete.sum()))

    c5, c6, c7, c8 = st.columns(4)

    c5.metric(
        "TOP 10",
        int((df["Google pozicija"] <= 10).sum()),
    )
    c6.metric(
        "TOP 20",
        int((df["Google pozicija"] <= 20).sum()),
    )
    c7.metric(
        "TOP 50",
        int((df["Google pozicija"] <= 50).sum()),
    )
    c8.metric(
        "TOP 100",
        int((df["Google pozicija"] <= 100).sum()),
    )

    # ========================================================
    # KEYWORD COVERAGE
    # ========================================================

    st.subheader("4. Pokrivenost SERP rezultata")

    coverage_rows = []

    for data in keyword_data:
        coverage_rows.append({
            "Ključna reč": data["keyword"],
            "Organski rezultati": len(data["results"]),
            "Preuzete stranice": data["pages_requested"],
            "TOP 100": (
                "KOMPLETNA"
                if data["complete"]
                else "NEPOTPUNA"
            ),
        })

    coverage_df = pd.DataFrame(coverage_rows)

    st.dataframe(
        coverage_df,
        use_container_width=True,
        hide_index=True,
    )

    if any(not x["complete"] for x in keyword_data):
        st.warning(
            "Za jednu ili više ključnih reči nije potvrđeno "
            "svih 100 jedinstvenih organskih pozicija. "
            "Pronađene pozicije se prikazuju, ali odsustvo "
            "URL-a ne znači automatski da nije u TOP 100."
        )
    else:
        st.success(
            "Za sve ključne reči prikupljeno je "
            "100 jedinstvenih organskih pozicija."
        )

    # ========================================================
    # MAIN RESULTS
    # ========================================================

    st.subheader("5. Results")

    display_df = df.copy()

    display_df["Google pozicija"] = (
        display_df["Google pozicija"]
        .astype("Int64")
    )

    styled = display_df.style.map(
        status_style,
        subset=["Status"],
    )

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=500,
        column_config={
            "Source URL": st.column_config.LinkColumn(
                "Source URL"
            ),
            "Pronađeni Google URL":
                st.column_config.LinkColumn(
                    "Pronađeni Google URL"
                ),
            "Google pozicija":
                st.column_config.NumberColumn(
                    "Google pozicija",
                    format="%d",
                ),
        },
    )

    # ========================================================
    # LINKS FOUND
    # ========================================================

    st.subheader("6. Pronađene pozicije")

    found_df = df[
        df["Google pozicija"].notna()
    ].copy()

    if found_df.empty:
        st.info(
            "Nijedan uneti URL nije pronađen "
            "u prikupljenim organskim rezultatima."
        )
    else:
        found_df = found_df.sort_values(
            ["Ključna reč", "Google pozicija"]
        )

        st.dataframe(
            found_df,
            use_container_width=True,
            hide_index=True,
        )

    # ========================================================
    # DIAGNOSTICS
    # ========================================================

    with st.expander(
        "Detalji paginacije – dijagnostika"
    ):
        logs = []

        for data in keyword_data:
            logs.extend(data["page_log"])

        st.dataframe(
            pd.DataFrame(logs),
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            "Ovde vidiš koliko je API vratio rezultata "
            "na svakoj stranici i da li je bilo duplikata."
        )

    # ========================================================
    # EXPORT
    # ========================================================

    st.subheader("7. Export")

    csv = df.to_csv(
        index=False
    ).encode("utf-8-sig")

    st.download_button(
        "⬇️ Download CSV",
        data=csv,
        file_name="bulk_serp_positions.csv",
        mime="text/csv",
    )
