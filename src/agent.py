The user wants me to apply a suggested edit to the original code. The edit is to fix the TOOLS list by removing stray commas after each Tool instantiation. I need to output the complete modified file with only the code, no explanations.

Let me apply the fix and output the entire file```
"""
Minimal self‑aware agent prototype (LangChain).

Run the file as a module with a user query, e.g.:

    python -m src.agent "Show me the 955 data file."

It will:
  1. Load the system prompt from src/system_prompt.md.
  2. Use the tool list defined below.
  3. Prefix each turn with a JSON of the current state.
  4. Enforce a <self_reflection> block before any tool usage.
"""

# Dependencies: langchain-openai, langchain

import os
import json
from pathlib import Path
from typing import List, Dict, Any

from langchain_openai import ChatOpenAI
from langchain.agents import ZeroShotAgent, AgentExecutor
from langchain.tools import Tool
from langchain.schema import SystemMessage, HumanMessage

# ---------------------------------------------------------------------------
# Load the prompt file
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = Path("src/system_prompt.md").read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Define exposed tools (only a few are shown; add more as needed)
# ---------------------------------------------------------------------------

def read_file(path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).parent.parent / p
    if not p.exists():
        raise FileNotFoundError
    return p.read_text(encoding="utf-8")


def run_terminal_command(cmd: str) -> str:
    from subprocess import run, PIPE, STDOUT
    res = run(cmd, shell=True, cwd=Path(__file__).parent.parent, stdout=PIPE, stderr=STDOUT, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed:{cmd}\n{res.stdout}")
    return res.stdout


def edit_existing_file(filepath: str, changes: str) -> str:
    Path(filepath).write_text(changes, encoding="utf-8")
    return f"Updated {filepath}"

TOOLS: List[Tool] = [
    Tool(name="read_file", func=read_file, description="Read file contents."),
    Tool(name="run_terminal_command", func=run_terminal_command, description="Run a shell command."),
    Tool(name="edit_existing_file", func=edit_existing_file, description="Write content to a file.")
]

# ---------------------------------------------------------------------------
# Build the agent
# ---------------------------------------------------------------------------
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)

system_msg = SystemMessage(content=SYSTEM_PROMPT)

agent = ZeroShotAgent(
    llm=llm,
    tools=[t.name for t in TOOLS],
    system_message=system_msg,
)

exe = AgentExecutor.from_agent_and_tools(
    agent=agent,
    tools=[t for t in TOOLS],
    handle_parsing_errors=True,
    max_iterations=5,
)

# ---------------------------------------------------------------------------
# Helper to embed runtime state
# ---------------------------------------------------------------------------
def build_prompt(msg: str):
    state = {
        "working_directory": str(Path.cwd()),
        "os": os.uname().sysname,
        "user": os.getenv("USER") or "unknown",
        "available_tools": [t.name for t in TOOLS],
    }
    return [
        SystemMessage(content=json.dumps(state, indent=2)),
        HumanMessage(content=msg),
    ]

# ---------------------------------------------------------------------------
# Entry‑point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.agent \"user query\"")
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    res = exe.invoke(build_prompt(query))
    print(json.dumps(res, indent=2))

