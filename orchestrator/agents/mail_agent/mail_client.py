import os
from dotenv import load_dotenv
from imap_tools import MailBox, AND
from dataclasses import dataclass

load_dotenv()

@dataclass
class Email:
    uid: str
    sender: str
    subject: str
    body: str

class MailClient:
    def __init__(self):
        self.user = os.getenv("GOOGLE_USER")
        self.password = os.getenv("GOOGLE_PASSWORD")
        self.mail_box = MailBox(host="imap.gmail.com", port=993).login(self.user, self.password)

    def getUnreadEmails(self) -> list:
        # Reset the mail box to ensure we get the latest emails
        self.mail_box = MailBox(host="imap.gmail.com", port=993).login(self.user, self.password)
        messages = self.mail_box.fetch(criteria=AND(seen=False))
        processed_emails = []

        for message in messages:
            processed_emails.append(Email(message.uid, message.from_, message.subject, message.text))

        return processed_emails

    def moveToFolder(self, email_uid: str, folder: str):
        self.mail_box.move(email_uid, folder)
