"""Make the test suite hermetic.

Building the agent tree imports modules that call `load_dotenv()`. Tests must not
depend on real credentials or a readable `.env`, so we neutralize dotenv, provide
dummy env vars, and run from a temp dir where no `.env` is found.
"""

import os
import tempfile

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: None

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_USER_ID", "1")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("TIMEZONE", "America/Denver")
# Memory lives under NOTES_DIR; point it at a temp dir so constructing AgentService
# in tests never writes into a real ~/my-stuff/Notes.
os.environ.setdefault("NOTES_DIR", tempfile.mkdtemp(prefix="mailbot_notes_"))

os.chdir(tempfile.gettempdir())
