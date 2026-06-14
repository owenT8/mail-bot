from google.adk.agents.llm_agent import Agent

from orchestrator.constants import MODEL, WRITER_AGENT_PROMPT
from orchestrator.time_context import datetime_global_instruction


def build_writer_agent() -> Agent:
    """A composition-only agent: no tools, runs on the capable MODEL so the prose
    quality doesn't suffer from the lighter sub-agent model."""
    return Agent(
        model=MODEL,
        name="WriterAgent",
        description="Composes polished, well-written emails and messages from facts and intent.",
        instruction=WRITER_AGENT_PROMPT,
        global_instruction=datetime_global_instruction,
    )
