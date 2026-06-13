"""Make the test suite hermetic.

Building the agent tree imports modules that call `load_dotenv()` and pull in
chromadb (whose settings auto-read a `.env`). Tests must not depend on real
credentials or a readable `.env`, so we neutralize dotenv, provide dummy env
vars, and run from a temp dir where no `.env` is found.
"""

import os
import tempfile

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: None

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_USER_ID", "1")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("TIMEZONE", "America/Denver")

os.chdir(tempfile.gettempdir())
