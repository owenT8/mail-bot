"""Entry point: build the agent core, then run the Telegram frontend on top of it.

main.py owns the agent. Telegram is one frontend; a future scheduler would be
another caller of the same AgentService (see core/tasks.run_task).
"""

from pathlib import Path

from core.agent_service import AgentService
from frontends.telegram.client import TelegramFrontend

ROOT = Path(__file__).resolve().parent

agent = AgentService(data_dir=ROOT)
TelegramFrontend(agent=agent, data_dir=ROOT).run()