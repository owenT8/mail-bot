"""Read-only iCloud Contacts over CardDAV.

There's no high-level CardDAV client for Python the way `caldav` covers
calendars, so this is a small purpose-built client: discover the address book
(principal -> addressbook-home-set -> addressbook collection), pull all vCards
with a REPORT, parse them with `vobject`, and match client-side. Reuses the
calendar's Apple ID + app-specific password.

Steps are logged at INFO so a failed discovery against a real iCloud account
points at the exact request that broke.
"""

import logging
import os
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests
import vobject
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

logger = logging.getLogger(__name__)

ICLOUD_CONTACTS_URL = "https://contacts.icloud.com"
DAV = "DAV:"
CARD = "urn:ietf:params:xml:ns:carddav"
NS = {"d": DAV, "card": CARD}

_PROP_PRINCIPAL = (
    '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/>'
    "</d:prop></d:propfind>"
)
_PROP_HOME = (
    '<d:propfind xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">'
    "<d:prop><card:addressbook-home-set/></d:prop></d:propfind>"
)
_PROP_COLLECTIONS = (
    '<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:displayname/>'
    "</d:prop></d:propfind>"
)
_REPORT_ALL = (
    '<card:addressbook-query xmlns:d="DAV:" '
    'xmlns:card="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag/>'
    "<card:address-data/></d:prop></card:addressbook-query>"
)


class ContactsClient:
    def __init__(self):
        # Reuse the calendar's Apple ID + app-specific password by default.
        self.username = os.getenv("CARDDAV_USERNAME") or os.getenv("CALDAV_USERNAME")
        self.password = os.getenv("CARDDAV_PASSWORD") or os.getenv("CALDAV_PASSWORD")
        self.base_url = os.getenv("CARDDAV_URL", ICLOUD_CONTACTS_URL)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _auth(self) -> HTTPBasicAuth:
        if not self.username or not self.password:
            raise RuntimeError(
                "CARDDAV/CALDAV credentials are not set; cannot connect to iCloud "
                "Contacts. CALDAV_PASSWORD must be an Apple app-specific password."
            )
        return HTTPBasicAuth(self.username, self.password)

    def _dav(self, method: str, url: str, body: str, depth: str) -> requests.Response:
        response = requests.request(
            method,
            url,
            data=body.encode("utf-8"),
            auth=self._auth(),
            headers={
                "Depth": depth,
                "Content-Type": "application/xml; charset=utf-8",
            },
            timeout=60,
        )
        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _first_href(xml_text: str, namespace: str, tag: str) -> str:
        root = ET.fromstring(xml_text)
        for container in root.iter(f"{{{namespace}}}{tag}"):
            href = container.find(f"{{{DAV}}}href")
            if href is not None and href.text:
                return href.text.strip()
        raise RuntimeError(f"CardDAV discovery: no <{tag}> href in response.")

    def _discover_addressbook(self) -> str:
        logger.info("CardDAV: discovering principal at %s", self.base_url)
        r = self._dav("PROPFIND", self.base_url, _PROP_PRINCIPAL, depth="0")
        principal_url = urljoin(
            r.url, self._first_href(r.text, DAV, "current-user-principal")
        )

        logger.info("CardDAV: discovering addressbook-home-set at %s", principal_url)
        r = self._dav("PROPFIND", principal_url, _PROP_HOME, depth="0")
        home_url = urljoin(
            r.url, self._first_href(r.text, CARD, "addressbook-home-set")
        )

        logger.info("CardDAV: listing collections at %s", home_url)
        r = self._dav("PROPFIND", home_url, _PROP_COLLECTIONS, depth="1")
        ab_href = self._first_addressbook_href(r.text)
        ab_url = urljoin(r.url, ab_href)
        logger.info("CardDAV: using addressbook %s", ab_url)
        return ab_url

    def _first_addressbook_href(self, xml_text: str) -> str:
        root = ET.fromstring(xml_text)
        for resp in root.iter(f"{{{DAV}}}response"):
            rtype = resp.find(f".//{{{DAV}}}resourcetype")
            if rtype is not None and rtype.find(f"{{{CARD}}}addressbook") is not None:
                href = resp.find(f"{{{DAV}}}href")
                if href is not None and href.text:
                    return href.text.strip()
        raise RuntimeError("CardDAV: no addressbook collection found.")

    # ------------------------------------------------------------------
    # Fetch + parse
    # ------------------------------------------------------------------

    def _fetch_vcards(self) -> list[str]:
        ab_url = self._discover_addressbook()
        r = self._dav("REPORT", ab_url, _REPORT_ALL, depth="1")
        root = ET.fromstring(r.text)
        cards = []
        for data in root.iter(f"{{{CARD}}}address-data"):
            if data.text and data.text.strip():
                cards.append(data.text)
        logger.info("CardDAV: fetched %d vCards", len(cards))
        return cards

    @staticmethod
    def _parse_vcard(text: str) -> dict | None:
        try:
            card = vobject.readOne(text)
        except Exception:
            return None
        name = ""
        if hasattr(card, "fn") and card.fn.value:
            name = str(card.fn.value)
        emails = [str(e.value) for e in card.contents.get("email", []) if e.value]
        phones = [str(t.value) for t in card.contents.get("tel", []) if t.value]
        org = ""
        if hasattr(card, "org") and card.org.value:
            org_val = card.org.value
            org = ", ".join(org_val) if isinstance(org_val, list) else str(org_val)
        if not (name or emails or phones):
            return None
        return {"name": name, "emails": emails, "phones": phones, "org": org}

    def _all_contacts(self) -> list[dict]:
        contacts = [self._parse_vcard(v) for v in self._fetch_vcards()]
        return [c for c in contacts if c]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_contacts(self, query: str) -> list[dict]:
        """Return contacts whose name, email, org, or phone matches `query`."""
        q = (query or "").strip().lower()
        contacts = self._all_contacts()
        if not q:
            return contacts
        matches = []
        for c in contacts:
            haystack = " ".join(
                [c["name"], c["org"], *c["emails"], *c["phones"]]
            ).lower()
            if q in haystack:
                matches.append(c)
        return matches

    def list_contacts(self, limit: int = 100) -> list[dict]:
        """Return up to `limit` contacts (name + email/phone)."""
        contacts = self._all_contacts()
        contacts.sort(key=lambda c: c["name"].lower())
        return contacts[: max(1, limit)]
