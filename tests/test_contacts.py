"""Tests for vCard parsing (no network)."""

from orchestrator.agents.messaging_agent.contacts_client import ContactsClient

SAMPLE = """BEGIN:VCARD
VERSION:3.0
N:Taylor;Sarah;;;
FN:Sarah Taylor
EMAIL;type=INTERNET;type=HOME;type=pref:sarah@example.com
EMAIL;type=INTERNET;type=WORK:sarah.work@acme.com
TEL;type=CELL:+1-555-123-4567
ORG:Acme Inc.
END:VCARD"""


def test_parse_vcard_extracts_fields():
    c = ContactsClient._parse_vcard(SAMPLE)
    assert c["name"] == "Sarah Taylor"
    assert "sarah@example.com" in c["emails"]
    assert "sarah.work@acme.com" in c["emails"]
    assert c["phones"] == ["+1-555-123-4567"]
    assert "Acme" in c["org"]


def test_parse_vcard_minimal():
    c = ContactsClient._parse_vcard(
        "BEGIN:VCARD\nVERSION:3.0\nFN:No Contact Info\nEND:VCARD"
    )
    assert c["name"] == "No Contact Info"
    assert c["emails"] == [] and c["phones"] == []


def test_parse_vcard_empty_returns_none():
    # A vCard with no name/email/phone is dropped.
    assert ContactsClient._parse_vcard("BEGIN:VCARD\nVERSION:3.0\nEND:VCARD") is None


def test_parse_vcard_garbage_returns_none():
    assert ContactsClient._parse_vcard("not a vcard") is None
