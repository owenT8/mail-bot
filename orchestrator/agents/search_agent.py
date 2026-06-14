from google.adk.agents.llm_agent import Agent
from google.adk.tools.google_search_tool import GoogleSearchTool

from orchestrator.constants import MODEL, SEARCH_AGENT_PROMPT
from orchestrator.time_context import datetime_global_instruction


def build_search_agent() -> Agent:
    return Agent(
        model=MODEL,
        name="ResearchAgent",
        description="Searches the web and synthesizes findings to answer research questions.",
        instruction=SEARCH_AGENT_PROMPT,
        global_instruction=datetime_global_instruction,
        tools=[GoogleSearchTool(bypass_multi_tools_limit=True)],
    )
