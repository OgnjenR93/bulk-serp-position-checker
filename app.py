
import streamlit as st
import requests
import pandas as pd
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

st.set_page_config(
    page_title="Bulk SERP Position Checker",
    page_icon="🔎",
    layout="wide",
)

st.title("🔎 Bulk SERP Position Checker")
st.write(
    "Proveri pozicije objavljenih PR tekstova u Google "
    "organskim rezultatima za zadatu ključnu reč."
)

API_URL = "https://google.serper.dev/search"

DEFAULT_URLS = """https://portal1.rs/tekst-o-silver-peaks/
https://portal2.rs/silver-peaks-vest/
https://portal3.rs/intervju-silver-peaks/"""

COLUMNS = [
    "Source URL",
    "Google pozicija",
    "Status",
    "Google naslov",
    "Pronađeni Google URL",
    "Ključna reč",
    "Datum provere",
]

TRACKING_PARAMS = {
    "fbclid", "gclid", "gbraid", "wbraid",
    "msclkid", "mc_cid", "mc_eid",
}


def normalize_url(url):
    """
    Normalizuje URL za poređenje:
    - uklanja www
    - ignoriše http/https razliku
    - uklanja završni /
    - uklanja fragment
    - uklanja poznate tracking parametre

    Ostale query parametre čuva, jer mogu
    označavati različite stranice.
    """
    url = str(url).strip()

    if not url:
        return ""

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)

        host = (parsed.hostname or "").lower().rstrip(".")

        if host.startswith("www."):
            host = host[4:]

        if not host:
            return ""

        port = parsed.port
        if port and port not in (80, 443):
            host = f"{host}:{port}"

        path = re.sub(r"/+", "/", parsed.path or "/")
        path = path.rstrip("/") or "/"

        query_pairs = parse_qsl(
            parsed.query,
            keep_blank_values=True
        )

        query_pairs = [
            (key, value)
            for key, value in query_pairs
            if not key.lower().startswith("utm_")
            and key.lower() not in TRACKING_PARAMS
        ]

        query = urlencode(sorted(query_pairs))

        return urlunparse(
            ("https", host, path, "", query, "")
        )

    except (ValueError, TypeError):
        return ""


def read_api_key():
    try:
        return st.secrets.get("SERPER_API_KEY", "")
    except Exception:
        return ""


def get_serp_page(api_key, keyword, page, country, language):
    payload = {
        "q": keyword,
        "gl": country,
        "hl": language,
        "page": page,
        "num": 10,
    }

    response = requests.post(
        API_URL,
        headers={
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45,
    )

    if response.status_code != 200:
        detail = response.text[:350]
        raise RuntimeError(
            f"SERP API HTTP {response.status_code}: {detail}"
        )

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            "API nije vratio očekivani JSON objekat."
        )

    if data.get("error"):
        raise RuntimeError(str(data["error"]))

    organic = data.get("organic")

    if not isinstance(organic, list):
        raise RuntimeError(
            "API odgovor ne sadrži validnu organic listu."
        )

    return organic


def fetch_top_100(api_key, keyword, country, language,
                  progress_bar, progress_text):
    """
    Preuzima do 10 stranica po 10 rezultata.

    Pozicije preuzima iz API odgovora kada su
    validne, a u suprotnom računa offset stranice.

    Ne tvrdi da je TOP 100 proveren ako API
    nije vratio 100 različitih organskih rezultata.
    """
    collected = []
    seen = set()
    pages_fetched = 0

    for page_number in range(1, 11):
        progress_text.write(
            f"Preuzimam Google rezultate: "
            f"stranica {page_number}/10"
        )

        organic = get_serp_page(
            api_key,
            keyword,
            page_number,
            country,
            language,
        )

        pages_fetched += 1

        if not organic:
            break

        new_results = 0

        for index, item in enumerate(organic):
            link = item.get("link", "")

            if not link:
                continue

            normalized = normalize_url(link)

            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            new_results += 1

            # Serper obično daje position kao globalnu
            # poziciju, ali proveravamo da nije resetovana
            # na 1-10 na narednoj stranici.
            raw_position = item.get("position")

            try:
                raw_position = int(raw_position)
            except (ValueError, TypeError):
                raw_position = None

            expected_position = (
                (page_number - 1) * 10 + index + 1
            )

            if (
                raw_position is not None
                and raw_position >= 1
                and (
                    page_number == 1
                    or raw_position > 10
                )
            ):
                position = raw_position
            else:
                position = expected_position

            collected.append({
                "position": position,
                "title": item.get("title", ""),
                "link": link,
                "normalized": normalized,
            })

        progress_bar.progress(page_number / 10)

        if new_results == 0:
            break

        if len(collected) >= 100:
            break

    collected.sort(key=lambda x: x["position"])

    return collected[:100], pages_fetched


def classify_position(position):
    if position <= 10:
        return "TOP 10"
    if position <= 20:
        return "TOP 20"
    if position <= 50:
        return "TOP 50"
    return "TOP 100"


def build_results(urls, organic_results, keyword, checked_at):
    lookup = {}

    for item in organic_results:
        key = item["normalized"]

        if (
            key not in lookup
            or item["position"] < lookup[key]["position"]
        ):
            lookup[key] = item

    rows = []

    for source_url in urls:
        normalized = normalize_url(source_url)
        match = lookup.get(normalized)

        if match:
            rows.append({
                "Source URL": source_url,
                "Google pozicija": match["position"],
                "Status": classify_position(match["position"]),
                "Google naslov": match["title"],
                "Pronađeni Google URL": match["link"],
                "Ključna reč": keyword,
                "Datum provere": checked_at,
            })
        else:
            rows.append({
                "Source URL": source_url,
                "Google pozicija": None,
                "Status": "NIJE U PROVERENIM REZULTATIMA",
                "Google naslov": "",
                "Pronađeni Google URL": "",
                "Ključna reč": keyword,
                "Datum provere": checked_at,
            })

    return pd.DataFrame(rows, columns=COLUMNS)


def color_status(value):
    if value == "TOP 10":
        return "background-color:#d9ead3;color:#274e13"
    if value in ("TOP 20", "TOP 50"):
        return "background-color:#fff2cc;color:#7f6000"
    if value == "TOP 100":
        return "background-color:#fce5cd;color:#783f04"
    if value == "NIJE U PROVERENIM REZULTATIMA":
        return "background-color:#f4cccc;color:#990000"
    return ""


st.subheader("1. Podešavanja pretrage")

col1, col2, col3 = st.columns(3)

with col1:
    keyword = st.text_input(
        "Ključna reč",
        value="silver peak",
    )

with col2:
    country = st.selectbox(
        "Google tržište",
        options=["rs", "me", "ba", "hr", "us"],
        format_func=lambda x: {
            "rs": "Srbija",
            "me": "Crna Gora",
            "ba": "Bosna i Hercegovina",
            "hr": "Hrvatska",
            "us": "SAD",
        }[x],
    )

with col3:
    language = st.selectbox(
        "Jezik rezultata",
        options=["sr", "en", "hr"],
        format_func=lambda x: {
            "sr": "Srpski",
            "en": "Engleski",
            "hr": "Hrvatski",
        }[x],
    )

st.caption(
    "Pretraga se odnosi na organske rezultate. "
    "Plaćeni oglasi, mape i drugi SERP elementi "
    "ne računaju se kao organske pozicije."
)

st.subheader("2. URL-ovi objava")

urls_input = st.text_area(
    "Unesi URL-ove, jedan po redu",
    value=DEFAULT_URLS,
    height=180,
)

api_key = read_api_key()

if not api_key:
    st.warning(
        "SERPER_API_KEY nije podešen u Streamlit Secrets. "
        "Dodaj API ključ pre pokretanja provere."
    )

run = st.button(
    "🔎 Run SERP Check",
    type="primary",
    disabled=not bool(api_key),
)

if run:
    keyword = keyword.strip()

    urls = list(dict.fromkeys(
        line.strip()
        for line in urls_input.splitlines()
        if line.strip()
    ))

    if not keyword:
        st.error("Unesi ključnu reč.")
        st.stop()

    if not urls:
        st.error("Unesi najmanje jedan URL.")
        st.stop()

    invalid_urls = [
        url for url in urls
        if not normalize_url(url)
    ]

    if invalid_urls:
        st.error(
            "Neispravni URL-ovi: "
            + ", ".join(invalid_urls[:5])
        )
        st.stop()

    progress_bar = st.progress(0)
    progress_text = st.empty()

    try:
        organic_results, pages_fetched = fetch_top_100(
            api_key,
            keyword,
            country,
            language,
            progress_bar,
            progress_text,
        )

    except (requests.RequestException, RuntimeError,
            ValueError) as exc:
        progress_text.empty()
        st.error(
            "Provera nije završena. Rezultati se ne mogu "
            "smatrati pouzdanim. Detalji: " + str(exc)
        )
        st.stop()

    progress_text.empty()

    checked_at = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    result_df = build_results(
        urls,
        organic_results,
        keyword,
        checked_at,
    )

    found_df = result_df[
        result_df["Google pozicija"].notna()
    ].copy()

    not_found_df = result_df[
        result_df["Google pozicija"].isna()
    ].copy()

    st.subheader("3. Summary")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Uneti URL-ovi", len(urls))
    c2.metric("Pronađeni URL-ovi", len(found_df))
    c3.metric("Nisu pronađeni", len(not_found_df))
    c4.metric("Organski rezultati", len(organic_results))

    c5, c6, c7 = st.columns(3)

    c5.metric(
        "Objave u TOP 10",
        int((found_df["Google pozicija"] <= 10).sum()),
    )
    c6.metric(
        "Objave u TOP 20",
        int((found_df["Google pozicija"] <= 20).sum()),
    )
    c7.metric(
        "Objave u TOP 50",
        int((found_df["Google pozicija"] <= 50).sum()),
    )

    if len(organic_results) < 100:
        st.warning(
            f"API je vratio {len(organic_results)} "
            f"različitih organskih rezultata sa "
            f"{pages_fetched} preuzetih stranica. "
            "Zato odsustvo URL-a ne dokazuje da "
            "nije u TOP 100."
        )
    else:
        st.success(
            "Preuzeto je 100 organskih rezultata "
            "za izabranu pretragu."
        )

    st.caption(
        f"Upit: {keyword} | Zemlja: {country.upper()} | "
        f"Jezik: {language} | Datum: {checked_at}"
    )

    st.subheader("4. Results")

    display_df = result_df.copy()
    display_df["Google pozicija"] = (
        display_df["Google pozicija"]
        .astype("Int64")
    )

    styled_df = display_df.style.map(
        color_status,
        subset=["Status"],
    )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        height=450,
        column_config={
            "Source URL": st.column_config.LinkColumn(
                "Source URL"
            ),
            "Pronađeni Google URL": st.column_config.LinkColumn(
                "Pronađeni Google URL"
            ),
            "Google pozicija": st.column_config.NumberColumn(
                "Google pozicija",
                format="%d",
            ),
        },
    )

    st.subheader("5. Links Found")

    if found_df.empty:
        st.info(
            "Nijedan uneti URL nije pronađen "
            "među preuzetim organskim rezultatima."
        )
    else:
        st.dataframe(
            found_df.sort_values("Google pozicija"),
            use_container_width=True,
            hide_index=True,
        )

    csv_data = result_df.to_csv(
        index=False
    ).encode("utf-8-sig")

    st.download_button(
        "⬇️ Download CSV",
        data=csv_data,
        file_name="bulk_serp_positions.csv",
        mime="text/csv",
    )
