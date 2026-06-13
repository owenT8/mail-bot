from google.adk.agents.llm_agent import Agent
from orchestrator.constants import MODEL, SEARCH_AGENT_PROMPT
from google.adk.tools import AgentTool
from google.adk.tools.google_search_tool import GoogleSearchTool

search_agent = AgentTool(Agent(
            model=MODEL,
            name="ResearchAgent",
            description="Searches the web and synthesizes findings to answer research questions.",
            instruction=SEARCH_AGENT_PROMPT,
            tools=[GoogleSearchTool(bypass_multi_tools_limit=True)]
        ))