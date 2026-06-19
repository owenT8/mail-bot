# TODO(decouple): invert ownership here. Build the agent core in main.py and inject
# it into the Telegram frontend, instead of TelegramClient constructing AgentService:
#     from pathlib import Path
#     from core.agent_service import AgentService
#     from frontends.telegram.client import TelegramFrontend
#     ROOT = Path(__file__).resolve().parent
#     agent = AgentService(data_dir=ROOT)
#     TelegramFrontend(agent=agent, data_dir=ROOT).run()
# Telegram then becomes one frontend; a future scheduler is another caller of the
# same agent core (see core/tasks.run_task).
from telegram_client import TelegramClient



client = TelegramClient()

client.run()