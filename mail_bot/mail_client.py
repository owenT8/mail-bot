import os
from dotenv import load_dotenv
from imap_tools import MailBox, AND
from dataclasses import dataclass
from mail_bot.constants import TEST_EMAILS

load_dotenv()

@dataclass
class Email:
    sender: str
    subject: str
    body: str

class MailClient:
    def __init__(self):
        user = os.getenv("GOOGLE_USER")
        password = os.getenv("GOOGLE_PASSWORD")
        self.mail_box = MailBox(host="imap.gmail.com", port=993).login(user, password)

    def getUnreadEmails(self) -> list:
        messages = self.mail_box.fetch(criteria=AND(seen=False))
        processed_emails = []

        for message in messages:
            processed_emails.append(Email(message.from_, message.subject, message.text))

        return processed_emails
