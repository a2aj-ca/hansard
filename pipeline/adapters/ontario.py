from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag, NavigableString

from ..common.http import build_proxies, fetch, sleep
from ..common.schema import DayPage
from ..common.text import clean_text, make_id
from .base import HansardAdapter

logger = logging.getLogger(__name__)


ROOT = "https://www.ola.org/en/legislative-business/house-documents"
#this matches the hansard session pages and the hansard day pages
SESSION_RE = re.compile(
    r"^/en/legislative-business/house-documents/parliament-\d+/session-\d+/?$"
)
HANSARD_DAY_RE = re.compile(
    r"^/en/legislative-business/house-documents/parliament-\d+/session-\d+/"
    r"\d{4}-\d{2}-\d{2}/hansard(-\d+)?/?$"
)
# the sitting date is embedded in every day URL, e.g. .../2024-03-21/hansard
# Ontario publishes the first sitting of a day at ".../<date>/hansard" and each
# additional sitting at ".../<date>/hansard-1", ".../<date>/hansard-2", ...
# The site labels them "vol. A", "vol. B", ...
DATE_IN_URL_RE = re.compile(r"/(\d{4}-\d{2}-\d{2})/hansard(?:-(\d+))?/?$")

# Speaker label at the start of a paragraph: 2-200 non-colon characters followed by a colon, e.g. "Mr. Speaker:"
SPEAKER_LABEL_RE = re.compile(r"^\s*([^:]{2,200}):")

# Some sittings publish speaker names as plain text -- no <strong>, no speakerStart class
# Detect by an honorific or chair title, then at most 120 non-colon chars, then the colon. 
SPEAKER_PLAIN_RE = re.compile(
    r"^(?P<label>"
    r"(?:L'hon\.?|Hon\.?|Mr\.?|Mrs\.?|Ms\.?|Miss|Dr\.?|M\.|M\s*me|Mme|Mlle|"
    r"Clerk\s+(?:at\s+the\s+Table|of\s+the\s+House)|"
    r"The\s+(?:Acting\s+|Deputy\s+)?(?:Speaker|Chair|Chairman|Chairperson|Clerk))"
    r"[^:]{0,120}?)\s*:"
)

# Common procedural openings, used to tell a procedural note apart from the continuation of a speaker's speech.
PROCEDURAL_START_RE = re.compile(
    r"^(interjections|applause|laughter|prayers|a voice|"
    r"the House (adjourned|recessed|met|resumed|divided|is divided|prorogued|observed)\b|the division bells?|"
    r"the committee (divided|rose)\b|"
    r"motion (agreed to|carried|negatived)|"
    r"the speaker|the acting speaker|"
    r"it being|pursuant to|ordered that)\b",
    re.I,
)
PROCEDURAL_END_RE = re.compile(r"pleased to retire\.\s*$", re.I)

# A few sittings repeat the bilingual date line just below the contents list.
DATE_LINE_RE = re.compile(r"^(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\s+\d{1,2}\s+\w+\s+\d{4}", re.I)

# --- recorded divisions (votes) ---
# A division opens with a marker paragraph naming one side: the side alone ("Ayes"),
# or the side with its count attached ("Ayes - 52", "Nays: 31").
VOTE_MARKER_RE = re.compile(r"^(?P<side>ayes?|nays?|yeas?)\b\W{0,6}(?P<count>\d+)?$", re.I)
# Some pre-1990s transcripts print both counts together after the names ("Ayes 52; nays 31.", sometimes "Ayes, 52;...").
# Such a line ends the name list. It is not a marker.
VOTE_TALLY_RE = re.compile(r"^(?:the\s+)?(?:ayes?|yeas?),?\s+\d+\s*[;,]", re.I)
# A comma-separated part that is only initials ("J. R."), i.e. the tail of "Last name, initials".
INITIALS_RE = re.compile(r"^(?:[A-Z]\.?\s*)+$")

UPSTREAM_LICENSE = (
    "See upstream license, including non-commercial use and other restrictions: "
    "https://perma.cc/D5TN-9RX6. Note: This is an unofficial reproduction of "
    "materials made available by the Legislative Assembly of Ontario, without "
    "endorsement by or affiliation with the Legislative Assembly of Ontario."
)

# "hansard" -> ("1991-12-19", "A"), "hansard-1" -> ("1991-12-19", "B"), ...
def _day_url_parts(url: str) -> tuple[Optional[str], Optional[str]]:
    m = DATE_IN_URL_RE.search(url or "")
    if not m:
        return None, None
    idx = int(m.group(2)) if m.group(2) else 0
    # A..Z covers far more sittings per day than Ontario has ever held; past that we fall back to the raw number so the label stays unique.
    sitting = chr(ord("A") + idx) if idx < 26 else str(idx)
    return m.group(1), sitting


# check if a paragraph matches a procedural opening or closing, or a vote tally line.
def _looks_procedural(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    if PROCEDURAL_START_RE.match(t) or VOTE_TALLY_RE.match(t):
        return True
    if PROCEDURAL_END_RE.search(t):
        return True
    return False

def _extract_plain_speaker_label(p: Tag) -> Optional[str]:
    m = SPEAKER_PLAIN_RE.match(clean_text(p.get_text(" ", strip=True)))
    return clean_text(m.group("label")) if m else None

"""
From <p class="speakerStart"><strong>Mr. Speaker:</strong> ...</p>
Extract:
    speaker_label: 'Mr. Speaker' (full label before colon)
"""
def _parse_speaker(p: Tag) -> Optional[str]:
    full = clean_text(p.get_text(" ", strip=True))
    if not full:
        return None
    m = SPEAKER_LABEL_RE.match(full)
    if not m:
        return None
    return clean_text(m.group(1)) #gets the speaker label before the colon, e.g. "Mr. Speaker (Leader of the Opposition)"

# helper for some files where speakerStart tag is not present, but strong tag is used to indicate speaker labels.
def _extract_strong_speaker_label(p: Tag) -> Optional[str]:
    strong = p.find("strong")
    if not strong:
        return None
    raw = clean_text(strong.get_text(" ", strip=True))
    # must look like "Speaker Name:" -- the colon is usually inside the <strong>, but a few pages put it just after: "<strong>The Speaker</strong>:"
    if raw.endswith(":"):
        raw = raw[:-1].strip() # remove trailing colon
    else:
        after = strong.next_sibling
        if not (isinstance(after, NavigableString) and after.lstrip().startswith(":")):
            return None
    return raw or None

# Some day pages have been re-exported by OLA with their <h2>/<h3> headings dropped and section headings survive only as a bold, all-caps paragraph. 
NOT_A_HEADING = {"AYES", "NAYS", "INTERJECTION", "INTERJECTIONS", "APPLAUSE", "LAUGHTER"}
BOLD_TIME_RE = re.compile(r"[\d:.\s]*(a\.?m\.?|p\.?m\.?)?$", re.I)


def _bold_fills_paragraph(p: Tag) -> bool:
    """True when the paragraph's entire visible text sits inside <strong>/<b>."""
    bolds = p.find_all(["strong", "b"])
    if not bolds:
        return False
    text = clean_text(p.get_text(" ", strip=True))
    bold_text = clean_text(" ".join(b.get_text(" ", strip=True) for b in bolds))
    return bool(text) and bold_text == text


def _caps_heading_text(p: Tag) -> Optional[str]:
    """Return the heading text if this paragraph is a bare ALL-CAPS heading, else None."""
    if p.find("a", href=True):
        return None
    text = clean_text(p.get_text(" ", strip=True))
    if not text or text != text.upper() or len(text) > 200:
        return None
    if text.endswith(":") or BOLD_TIME_RE.fullmatch(text):
        return None
    if text.strip(" .'\u2019") in NOT_A_HEADING:
        return None
    classes = {c.lower() for c in (p.get("class") or [])}
    if classes & {"votedirection", "votetext", "procedure", "speakerstart", "th", "td"}:
        return None
    return text


def _heading_key(text: str) -> str:
    """Normalise heading text so contents-list entries and body headings compare equal."""
    return re.sub(r"[^A-Z0-9]+", " ", clean_text(text).replace("’", "'").upper()).strip()


def _contents_list_names(transcript: Tag) -> tuple:
    """(order_names, subject_names) from the contents list at the top of the transcript.
    Most sittings open with a list of internal links, one per heading, bold for OrderofBusiness and plain for SubjectofBusiness."""
    order, subject = set(), set()
    for a in transcript.find_all("a", href=True):
        if not a["href"].strip().startswith("#"):
            continue
        key = _heading_key(a.get_text(" ", strip=True))
        if key:
            (order if a.find(["b", "strong"]) else subject).add(key)
    return order, subject


def _is_order_heading(text: str, order_names: set, subject_names: set, markup_says_order: bool) -> bool:
    """Decide a heading's level: the contents list first, body markup is the fallback.
    A heading absent from both sets is kept, not discarded, falling back to what the body markup implies.
    A name listed at both levels is ambiguous and also falls back to the markup"""
    key = _heading_key(text)
    in_order, in_subject = key in order_names, key in subject_names
    if in_order and not in_subject:
        return True
    if in_subject and not in_order:
        return False
    return markup_says_order


def _page_needs_bold_headings(transcript: Tag) -> bool:
    """Only fire where the page carries no heading markup at all."""
    if transcript.find_all(["h2", "h3"]):
        return False
    if transcript.find_all("p", class_=re.compile(r"^(th|td)$", re.I)):
        return False
    return True


def _vote_marker(el: Tag) -> Optional[tuple]:
    """(side, count) if this element introduces a division, else None.

    side is "aye" or "nay" ("yea" counts as aye). count is None unless the marker prints it.
    Matches on the marker text, or on class="voteDirection" for pages whose marker text is unusual.
    """
    text = clean_text(el.get_text(" ", strip=True))
    m = VOTE_MARKER_RE.match(text)
    if m:
        side = "nay" if m.group("side").lower().startswith("na") else "aye"
        return side, (int(m.group("count")) if m.group("count") else None)
    if "votedirection" in {c.lower() for c in (el.get("class") or [])}:
        return ("nay" if text[:2].lower() == "na" else "aye"), None
    return None


def _names_from_paragraph(text: str) -> List[str]:
    """Split one paragraph of voters' names.

    Pages put one name per paragraph, or join many names with commas or semicolons.
    A ";" always separates voters ("Peterson; Reed, J.; Riddell"); some comma lists also end with a stray semicolon.
    Within each ";" piece, a comma separates voters ("Breaugh, Cureatz"), except that a part made only of
    initials ("J. M.") is the tail of "Last name, initials" and is glued back onto the name before it.
    """
    names: List[str] = []
    for chunk in text.split(";"):
        parts = [p.strip() for p in chunk.split(",") if p.strip()]
        for i, part in enumerate(parts):
            # reattach any part that's just initials (matched by INITIALS_RE) onto the previous name
            if i and INITIALS_RE.match(part):
                names[-1] += ", " + part
            else:
                names.append(part)       
    return names


# Strip trailing punctuation without stripping a real initial's period
def _clean_voter_name(name: str) -> str:
    name = name.strip().rstrip(";,")
    # keep the period on a trailing initial, drop a sentence-final one
    if name.endswith(".") and not re.search(r"\b[A-Z]\.$", name):
        name = name[:-1]
    return name.strip()


def _collect_table_column_voters(el: Tag) -> Optional[tuple]:
    """(names, consumed_elements) when the marker at `el` heads a column of a vote table, else None.

    Some 1970s pages lay a division out as a table: a first row of markers ("Ayes" | "Nays"), then the
    names in the same column below, as a <ul>, one <p> per name, or one name per row.
    """
    cell = el.find_parent("td")
    if cell is None:
        return None
    row = cell.find_parent("tr")
    table = row.find_parent("table")
    # returns cells of a row 
    cells_of = lambda tr: [c for c in tr.find_all(["td", "th"]) if c.find_parent("tr") is tr]
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    col = cells_of(row).index(cell)
    names: List[str] = []
    consumed: List[Tag] = []
    for tr in rows[rows.index(row) + 1:]:
        cells = cells_of(tr)
        if col >= len(cells):
            continue
        below = cells[col]
        consumed.append(below) 
        items = below.find_all(["li", "p", "h4"])
        if not items:
            text = clean_text(below.get_text(" ", strip=True))
            names += _names_from_paragraph(text) if text else []
            continue
        for item in items:
            text = clean_text(item.get_text(" ", strip=True))
            if not text or _vote_marker(item):
                continue
            names += [text] if item.name == "li" else _names_from_paragraph(text) 
    return names, consumed


def _collect_division_voters(el: Tag) -> tuple:
    """(names, consumed_elements) for the division marker at `el`.

    Walks forward over el's siblings, reading names from <ul> items, table cells and plain
    <p>s, and stops at the next marker (the other side), a heading, a tally line, a speaker
    label or procedural text. Consumed elements are
    returned so the caller can skip them: <p class="votetext"> lives inside the table and
    would otherwise be revisited by the main loop and appended to the text a second time.
    """
    names: List[str] = []
    consumed: List[Tag] = []
    for sib in el.next_siblings:
        if getattr(sib, "name", None) is None:
            continue
        text = clean_text(sib.get_text(" ", strip=True))
        if _vote_marker(sib) or sib.name in ("h2", "h3", "h4"):
            break                                    # the other side, or a new section
        if sib.name == "ul":
            names += [clean_text(li.get_text(" ", strip=True)) for li in sib.find_all("li")]
        elif sib.name == "table":
            cells = sib.find_all("p", class_="votetext") or sib.find_all("td")
            names += [clean_text(c.get_text(" ", strip=True)) for c in cells]
        elif sib.name == "p":
            if not text:
                consumed.append(sib)                 # blank <p> between marker and names
                continue
            if VOTE_TALLY_RE.match(text) or SPEAKER_LABEL_RE.match(text) or _looks_procedural(text):
                break                                # dialogue resumes
            names += _names_from_paragraph(text)
        else:
            break
        consumed.append(sib)
    # in some cases the names may sit in the column below the marker
    if not names:
        column = _collect_table_column_voters(el)
        if column is not None:
            names, consumed = column
    return [_clean_voter_name(n) for n in names if n], consumed


class OntarioHansardAdapter(HansardAdapter):
    name = "ontario"
    jurisdiction = "ontario"
    chamber = "legislative_assembly"
    supported_languages = ["en"]

    # ------------- discovery -------------

    def discover(self, mode: str = "full") -> List[DayPage]:
        if mode == "full":
            return self._discover_full()
        # "refresh" reuses incremental's recent-only discovery scope; the runner
        # decides whether to re-fetch days it already has.
        if mode in ("incremental", "refresh"):
            return self._discover_incremental()
        raise ValueError(f"Unknown discover mode: {mode!r}")

    @staticmethod
    def _day_from_url(url: str) -> DayPage:
        m = DATE_IN_URL_RE.search(url)
        return DayPage(url=url, language="en", date=m.group(1) if m else None)

    def _discover_full(self) -> List[DayPage]:
        proxies = build_proxies()
        logger.info("Fetching root: %s", ROOT)
        root_r = fetch(ROOT, proxies=proxies)
        if not root_r.ok or not root_r.content:
            raise RuntimeError(f"Failed to fetch root: {ROOT}")

        sessions = self._discover_session_urls(root_r.content)
        logger.info("Discovered %d session URLs", len(sessions))

        day_urls: list[str] = []
        for i, session_url in enumerate(sessions, start=1):
            sleep()
            logger.info("(%d/%d) Fetch session: %s", i, len(sessions), session_url)
            sr = fetch(session_url, proxies=proxies)
            if not sr.ok or not sr.content:
                logger.warning("Failed session: %s", session_url)
                continue
            day_urls.extend(self._discover_hansard_day_urls(sr.content))

        # dedupe day URLs
        day_urls = sorted(set(day_urls))
        logger.info("Total unique hansard day URLs: %d", len(day_urls))
        return [self._day_from_url(u) for u in day_urls]

    def _discover_incremental(self) -> List[DayPage]:
        proxies = build_proxies()
        root_r = fetch(ROOT, proxies=proxies)
        if not root_r.ok or not root_r.content:
            raise RuntimeError(f"Failed to fetch root: {ROOT}")

        recent_url = self._discover_recent_house_documents(root_r.content)
        sr = fetch(recent_url, proxies=proxies)
        if not sr.ok or not sr.content:
            raise RuntimeError(f"Failed to fetch recent session page: {recent_url}")

        day_urls = sorted(set(self._discover_hansard_day_urls(sr.content)))
        logger.info("Discovered %d day URLs on recent session page", len(day_urls))
        return [self._day_from_url(u) for u in day_urls]

    @staticmethod
    def _discover_session_urls(root_html: bytes) -> list[str]:
        soup = BeautifulSoup(root_html, "html.parser")
        out = set() #create a set for results to avoid duplicates
        for a in soup.find_all("a", href=True):
            href = a["href"].strip() #gets the clickable link that matches the regex
            if SESSION_RE.match(href):
                out.add(urljoin(ROOT, href))
        return sorted(out)

    @staticmethod
    def _discover_hansard_day_urls(session_html: bytes) -> list[str]:
        soup = BeautifulSoup(session_html, "html.parser")
        out = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if HANSARD_DAY_RE.match(href):
                out.add(urljoin(ROOT, href))
        return sorted(out)
    
    # find the recent house documents page url from the root page
    @staticmethod
    def _discover_recent_house_documents(root_html: bytes) -> str:
        soup = BeautifulSoup(root_html, "html.parser")
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True).lower()
            if "recent house documents" in text:
                return urljoin(ROOT, a["href"])
        raise RuntimeError("Could not find Recent House documents link on root page")

    # ------------- PDFs -------------

    def extract_pdf_links(self, html: bytes, day_url: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        pdfs = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = (a.get_text() or "").strip().lower()
            abs_url = urljoin(day_url, href)
            if abs_url.lower().endswith(".pdf"):
                pdfs.add(abs_url)
            elif "pdf" in text and "/pdf" in abs_url.lower():
                pdfs.add(abs_url)
        return sorted(pdfs)

    # ------------- extra sittings on the same day -------------

    # Session index pages list only one link per sitting date. 
    # When the House sat twice that day, the evening sitting lives at ".../<date>/hansard-1" 
    # and is linked only from the day page itself, in the "Hansard Transcripts vol. A / vol. B" nav. 
    def extract_related_day_urls(self, html: bytes, day_url: str) -> List[str]:
        date_iso, _ = _day_url_parts(day_url)
        if not date_iso:
            return []

        soup = BeautifulSoup(html, "html.parser")
        out = set()
        # The day page also links to the previous/next sitting day. Keep only same-date links.
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not HANSARD_DAY_RE.match(href):
                continue
            abs_url = urljoin(day_url, href)
            if abs_url == day_url:
                continue
            sib_date, _ = _day_url_parts(abs_url)
            if sib_date == date_iso:
                out.add(abs_url)
        return sorted(out)

    # ------------- parsing -------------

    def parse(self, html: bytes, language: str = "en") -> List[Dict[str, Optional[str]]]:
        if isinstance(html, (bytes, bytearray)):
            html_str = html.decode("utf-8", errors="ignore")
        else:
            html_str = html

        soup = BeautifulSoup(html_str, "html.parser")
        
        # getting the date of the hansard
        date_iso = None
        time_element = soup.find("time", class_="datetime")
        if time_element and time_element.get("datetime"):
            date_iso = time_element["datetime"].split("T")[0].strip()

        # The canonical URL is the only in-page signal of which sitting this is since
        # <time class="datetime"> is identical on both the afternoon and evening page
        canonical_date = sitting = None
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            canonical_date, sitting = _day_url_parts(canonical["href"])
        if not date_iso:
            date_iso = canonical_date

        logger.info("Starting transcript parse | date=%s | sitting=%s", date_iso, sitting)

        transcript = soup.find("div", id="transcript") or soup.find("article") #gets the transcript container by its id
        if not transcript:
            logger.warning("Transcript container missing | date=%s", date_iso)
            return []

        # Get the contents list before dropping the toc
        order_names, subject_names = _contents_list_names(transcript)
        contents_names = order_names | subject_names

        toc = transcript.find("div", id="toc")
        if toc:
            toc.decompose()

        use_bold_headings = _page_needs_bold_headings(transcript)
        if use_bold_headings:
            logger.warning("No heading markup on page (no h2/h3/th/td). Falling back to ALL-CAPS paragraphs and contents-list matches for headings.| date=%s | sitting=%s", date_iso, sitting)

        #fields get reset with new call to this function for each day's html 
        current_order: Optional[str] = None # OrderofBusiness 
        current_subject: Optional[str] = None # SubjectofBusiness 
        current_person: Optional[str] = None # PersonSpeaking
        buffer_lines: list[str] = [] # temporary buffer to accumulate lines of the current speech/intervention
        rows: list[Dict[str, Optional[str]]] = [] # list of output rows
        seq = 0 # for ID generation

        jurisdiction = self.jurisdiction 
        chamber = self.chamber

        def emit_row(text: str, *, person: Optional[str], intervention_type: str, vote_direction: Optional[str] = None, vote_count: Optional[int] = None, voters: Optional[List[str]] = None) -> None:
            nonlocal seq
            seq += 1
            rows.append({
                "ID": make_id(date_iso, seq, sitting),
                "Date": date_iso,
                "sitting": sitting,
                "jurisdiction": jurisdiction,
                "chamber": chamber,
                "language": language,
                "OrderofBusiness": current_order,
                "SubjectofBusiness": current_subject,
                "PersonSpeaking": person,
                "intervention_type": intervention_type,
                "Intervention": text,
                "vote_direction": vote_direction,
                "vote_count": vote_count,
                "voters": voters or [],
                "upstream_license": UPSTREAM_LICENSE,
            })

        def flush() -> None:
            nonlocal buffer_lines
            if not buffer_lines:
                return
            text = clean_text(" ".join(buffer_lines))
            buffer_lines = []
            if not text:
                return

            is_procedural = current_person is None or current_person == "Procedure"
            emit_row(text, person=None if is_procedural else current_person, intervention_type="procedural" if is_procedural else "speech")

        # Everything above the contents list is masthead. drop them. 
        elements = transcript.find_all(["h2", "h3", "h4", "p"], recursive=True)
        start_at = 0
        for i, el in enumerate(elements):
            if el.name == "p":
                a = el.find("a", href=True)
                if a and a["href"].strip().startswith("#"):
                    start_at = i + 1
        # A contents list always sits in the first fifth of the document. If the last internal link is further in it is a cross-reference, not a contents entry. 
        if start_at > len(elements) // 5:
            start_at = 0

        # Skip a repeated date line sitting just below the contents list.
        while start_at < len(elements):
            el = elements[start_at]
            if el.name == "p" and DATE_LINE_RE.match(clean_text(el.get_text(" ", strip=True))):
                start_at += 1
                continue
            break

        consumed_ids: set = set()

        #get the headings and paragraphs in the transcript
        for el in elements[start_at:]:
            if not isinstance(el, Tag):
                continue
            if id(el) in consumed_ids:               # already taken by a division
                continue
            
            # In files from the 32nd, 37th, 38th and 39th parliaments, some paragraphs near the top link to sections of the hansard (the contents list).
            # They are not interventions, so any paragraph that contains a link is skipped.
            if el.name == "p" and el.find("a", href=True):
                continue

            # Recorded division: one row per side, carrying the voters' names.
            # Checked before heading/speaker handling so "AYES"/"NAYS" never become headings or speech.
            marker = _vote_marker(el)
            if marker is not None:
                side, count = marker
                flush()
                voters, used = _collect_division_voters(el)
                for sib in used:
                    consumed_ids.add(id(sib))
                    consumed_ids.update(id(d) for d in sib.find_all(True))
                emit_row("; ".join(voters),           # ";" -- names contain commas
                        person=None,
                        intervention_type="division",
                        vote_direction=side,
                        vote_count=count,
                        voters=voters)
                continue

            tag = el.name.lower()

            # Order tracking
            if tag == "h2":
                flush()
                current_order = clean_text(el.get_text(" ", strip=True)) or current_order
                current_subject = None
                current_person = None      # a heading ends the previous turn
                continue
            
            # subject tracking
            if tag in {"h3", "h4"}:
                flush()
                current_subject = clean_text(el.get_text(" ", strip=True)) or current_subject
                current_person = None   # a heading ends the previous turn
                continue
            
            # Paragraph handling
            if tag == "p":
                text = clean_text(el.get_text(" ", strip=True))
                if not text:
                    continue
                
                #skip lines that only show the time
                if re.fullmatch(r"\d{3,4}", text):
                    continue

                # Compare class names case-insensitively
                classes = {c.lower() for c in (el.get("class") or [])}

                # older Ontario format (32nd/37th/39th parliaments): <p class="th"> = OrderofBusiness heading, <p class="td"> = SubjectofBusiness heading
                # however the classes do not encode level consistently. The page's own nav is the reliable level signal
                if classes & {"th", "td"}:
                    flush()
                    # class="th" is the only level hint the body carries, and it is missing on the 37th-s2/38th, so let the contents list decide first.
                    if _is_order_heading(text, order_names, subject_names, "th" in classes):
                        current_order = text or current_order
                        current_subject = None
                    else:
                        current_subject = text or current_subject
                    current_person = None
                    continue

                if use_bold_headings:
                    heading = _caps_heading_text(el)
                    # Some pages have no heading markup at all and mixed-case subjects
                    if not heading and not (classes & {"votedirection", "votetext", "procedure", "speakerstart"}):
                        if _heading_key(text) in contents_names:
                            heading = text
                    if heading:
                        flush()
                        # with no markup to go on, bold marks the order level
                        if _is_order_heading(heading, order_names, subject_names, _bold_fills_paragraph(el)):
                            current_order = heading
                            current_subject = None
                        else:
                            current_subject = heading
                        current_person = None
                        continue

                speaker_label = None

                if "procedure" in classes:
                    flush()
                    saved_person = current_person
                    current_person = "Procedure"
                    buffer_lines.append(text)
                    flush()
                    current_person = saved_person
                    continue

                if "speakerstart" in classes:
                    speaker_label = _parse_speaker(el)
                if not speaker_label:
                    speaker_label = _extract_strong_speaker_label(el)
                # only where there is no <strong> to trust
                if not speaker_label and not el.find("strong"):
                    speaker_label = _extract_plain_speaker_label(el)

                is_speaker_start = bool(speaker_label) or ("speakerstart" in classes)

                # update speaker context if we actually detected one
                if is_speaker_start:
                    flush()
                    if speaker_label:
                        current_person = speaker_label
                        # strip "Label:" from the start of THIS paragraph only
                        text = re.sub(r"^\s*" + re.escape(speaker_label) + r"\s*:\s*", "", text)
                        # if strong tag still caused duplicate label in text, remove it directly from HTML text source
                        strong = el.find("strong")
                        if strong:
                            strong.extract()
                            text = clean_text(el.get_text(" ", strip=True))
                            text = re.sub(r"^:\s*", "", text)   # colon left behind in case it sat outside the <strong>
                    else:
                        logger.warning("speakerStart detected but speaker not parsed | date=%s | text=%s", date_iso, text[:80],)
                    if text:
                        buffer_lines.append(text)
                else:
                    # Continuation paragraph: the current speaker continues (or, with no speaker yet, it is flushed as procedural)
                    if _looks_procedural(text):
                        # emit this line as Procedure without killing speaker context
                        flush()
                        saved = current_person
                        current_person = "Procedure"
                        buffer_lines.append(text)
                        # restore speaker context after procedural line
                        flush()
                        current_person = saved
                    else:
                        buffer_lines.append(text)

        flush()
        logger.info("Finished transcript parse | date=%s | sitting=%s | rows=%d", date_iso, sitting, len(rows))
        return rows
