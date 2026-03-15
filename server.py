"""protools-mcp — MCP server connecting Claude Code to Pro Tools via PTSL."""

import os
import sys

from dotenv import load_dotenv

# Add project root to path for local imports
sys.path.insert(0, os.path.dirname(__file__))

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from mcp.server.fastmcp import FastMCP
from ptsl_bridge import PTSLBridge
from transcript_watcher import TranscriptWatcher
from show_profiles import ShowProfileLoader

# Create the MCP server
mcp = FastMCP("protools-mcp")

# Shared instances
bridge = PTSLBridge()
transcript_watcher = TranscriptWatcher()
profile_loader = ShowProfileLoader()

# Register all tool groups
from tools.session import register_session_tools
from tools.tracks import register_track_tools
from tools.transcript import register_transcript_tools
from tools.navigation import register_navigation_tools
from tools.edit import register_edit_tools

register_session_tools(mcp, bridge, profile_loader)
register_track_tools(mcp, bridge)
register_transcript_tools(mcp, transcript_watcher, bridge, profile_loader)
register_navigation_tools(mcp, bridge)
register_edit_tools(mcp, bridge)

if __name__ == "__main__":
    mcp.run(transport="stdio")
