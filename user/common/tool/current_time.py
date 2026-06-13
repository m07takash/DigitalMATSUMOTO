"""
Sample tool plugin: return the current wall-clock time.

Drop any *.py file under TOOL_FOLDER (default: user/common/tool/) and call
`DigiM_ToolRegistry.register_tool(...)` at module level to expose a new
tool. The loader in DigiM_Tool.py picks the file up at startup; no edits
to DigiM_Tool.py required.

Files starting with '_' are skipped by the loader so private helper
modules (e.g. _shared.py) can sit next to plugins without being treated
as tools themselves.
"""
from datetime import datetime

import pytz

import DigiM_ToolRegistry as dmtr


def current_time(service_info, user_info, session_id, session_name,
                 agent_file, input, import_contents=[], add_info={}):
    """Return the current time as an ISO 8601 string."""
    tz_name = (add_info or {}).get("timezone", "Asia/Tokyo")
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz)
    response_text = now.isoformat()
    return service_info, user_info, response_text, []


dmtr.register_tool(
    "current_time",
    description=(
        "Return the current wall-clock time as an ISO 8601 string. "
        "Default timezone is Asia/Tokyo; override via args.timezone "
        "(any IANA tz name like 'UTC' or 'America/Los_Angeles'). "
        "Use when the request depends on the actual current time and a "
        "session-provided timestamp is not available."
    ),
    schema={
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "Unused; accepted for uniform signature compatibility.",
            },
            "timezone": {
                "type": "string",
                "description": "IANA timezone name (e.g. 'Asia/Tokyo', 'UTC').",
                "default": "Asia/Tokyo",
            },
        },
        "required": [],
    },
    func=current_time,
    example="/current_time",
)
