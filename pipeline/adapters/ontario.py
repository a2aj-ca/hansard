from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

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
DATE_IN_URL_RE = re.compile(r"/(\d{4}-\d{2}-\d{2})/hansard")

# regex to match speaker lines, match start of a line that has characters (2 to 200 for instance) except for :, which ends with a :
SPEAKER_LABEL_RE = re.compile(r"^\s*([^:]{2,200}):")

#in order to be able to differentitate between procedure and continuition of a speaker's speech, i've created regex that match common procedures. 
PROCEDURAL_START_RE = re.compile(
    r"^(interjections|applause|laughter|prayers|a voice|"
    r"the House adjourned at|the assembly|the committee|the clerk|"
    r"motion (agreed to|carried|negatived)|"
    r"the speaker|the acting speaker|"
    r"it being|pursuant to|ordered that)\b",
    re.I,
)
PROCEDURAL_END_RE = re.compile(r"pleased to retire\.\s*$", re.I)

UPSTREAM_LICENSE = (
    "See upstream license, including non-commercial use and other restrictions: "
    "https://perma.cc/D5TN-9RX6. Note: This is an unofficial reproduction of "
    "materials made available by the Legislative Assembly of Ontario, without "
    "endorsement by or affiliation with the Legislative Assembly of Ontario."
)


def _looks_procedural(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    if PROCEDURAL_START_RE.match(t):
        return True
    if PROCEDURAL_END_RE.search(t):
        return True
    return False

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
    # must look like "Speaker Name:"
    if not raw.endswith(":"):
        return None
    raw = raw[:-1].strip() # remove trailing colon
    return raw or None


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
        if not date_iso:
            # you can parse from canonical URL if needed
            canonical = soup.find("link", rel="canonical")
            if canonical and canonical.get("href"):
                m = re.search(r"/(\d{4}-\d{2}-\d{2})/hansard", canonical["href"])
                date_iso = m.group(1) if m else None

        logger.info("Starting transcript parse | date=%s", date_iso)

        transcript = soup.find("div", id="transcript") or soup.find("article") #gets the transcript container by its id
        if not transcript:
            logger.warning("Transcript container missing | date=%s", date_iso)
            return []

        toc = transcript.find("div", id="toc")
        if toc:
            toc.decompose()

        #fields get reset with new call to this function for each day's html 
        current_order: Optional[str] = None # OrderofBusiness 
        current_subject: Optional[str] = None # SubjectofBusiness 
        current_person: Optional[str] = None # PersonSpeaking
        buffer_lines: list[str] = [] # temporary buffer to accumulate lines of the current speech/intervention
        rows: list[Dict[str, Optional[str]]] = [] # list of output rows
        seq = 0 # for ID generation

        jurisdiction = self.jurisdiction 
        chamber = self.chamber

        def flush() -> None:
            nonlocal buffer_lines, seq
            if not buffer_lines:
                return
            text = clean_text(" ".join(buffer_lines))
            buffer_lines = []
            if not text:
                return

            seq += 1
            is_procedural = current_person is None or current_person == "Procedure"
            rows.append({
                "ID": make_id(date_iso, seq),
                "Date": date_iso,
                "jurisdiction": jurisdiction,
                "chamber": chamber,
                "language": language,
                "OrderofBusiness": current_order,
                "SubjectofBusiness": current_subject,
                "PersonSpeaking": None if is_procedural else current_person,
                "intervention_type": "procedural" if is_procedural else "speech",
                "Intervention": text,
                "upstream_license": UPSTREAM_LICENSE,
            })

        #get the headings and paragraphs in the transcript
        for el in transcript.find_all(["h2", "h3", "h4", "p"], recursive=True):
            if not isinstance(el, Tag):
                continue
            
            # in files from the 32nd, 37th, 38th and 39th parliament, there are some paragraphs at the top of the file that contain links to different sections of the hansard. these are not actual interventions and cause parsing issues, so we skip any paragraph that contains links.
            if el.name == "p" and el.find("a", href=True):
                continue

            tag = el.name.lower()

            # Order tracking
            if tag == "h2":
                flush()
                current_order = clean_text(el.get_text(" ", strip=True)) or current_order
                current_subject = None
                continue
            
            # subject tracking
            if tag in {"h3", "h4"}:
                flush()
                current_subject = clean_text(el.get_text(" ", strip=True)) or current_subject
                continue
            
            # Paragraph handling
            if tag == "p":
                text = clean_text(el.get_text(" ", strip=True))
                if not text:
                    continue
                
                #skip lines that only show the time
                if re.fullmatch(r"\d{3,4}", text):
                    continue

                classes = el.get("class") or []

                # older Ontario format (e.g. 32nd/37th/39th parliaments):
                # <p class="td"> = OrderofBusiness heading, <p class="th"> = SubjectofBusiness heading
                if "th" in classes:
                    flush()
                    current_order = text or current_order
                    current_subject = None
                    current_person = None
                    continue
                if "td" in classes:
                    flush()
                    current_subject = text or current_subject
                    current_person = None
                    continue

                speaker_label = None

                if "Procedure" in classes:
                    flush()
                    saved_person = current_person
                    current_person = "Procedure"
                    buffer_lines.append(text)
                    flush()
                    current_person = saved_person
                    continue

                if "speakerStart" in classes:
                    speaker_label = _parse_speaker(el)
                if not speaker_label:
                    speaker_label = _extract_strong_speaker_label(el)

                is_speaker_start = bool(speaker_label) or ("speakerStart" in classes)

                # update speaker context if we actually detected one
                if is_speaker_start:
                    flush()
                    if speaker_label:
                        current_person = speaker_label
                        # strip "Label:" from the start of THIS paragraph only
                        text = re.sub(
                            r"^\s*" + re.escape(speaker_label) + r"\s*:\s*",
                            "",
                            text,
                        )
                        # if strong tag still caused duplicate label in text, remove it directly from HTML text source
                        strong = el.find("strong")
                        if strong:
                            strong.extract()
                            text = clean_text(el.get_text(" ", strip=True))
                    else:
                        logger.warning(
                            "speakerStart detected but speaker not parsed | date=%s | text=%s",
                            date_iso,
                            text[:80],
                        )
                    if text:
                        buffer_lines.append(text)
                else:
                    # Continuation paragraph: same person/procedure continues
                    # If we have no speaker context at all, treat as Procedure
                    if current_person is None:
                        buffer_lines.append(text)
                    else:
                        if _looks_procedural(text):
                            # temporarily emit this line as Procedure without killing speaker context
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
        logger.info("Finished transcript parse | date=%s | rows=%d", date_iso, len(rows))
        return rows
