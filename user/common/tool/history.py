"""Tool plugin: session-history control tools.

Migrated from DigiM_Tool.py — see that file for the historical implementation.
"""
import DigiM_Session as dms
import DigiM_ToolRegistry as dmtr


_INPUT_TEXT = {
    "type": "string",
    "description": "Free-form text — typically the user's query or relevant input for this tool.",
}


# Reply with a fixed message
def fixed_message(service_info, user_info, session_id, session_name, agent_file,
                  input, import_contents=[], add_info={}):
    session = dms.DigiMSession(session_id)
    session.get_history()  # touch to validate session

    response = input
    export_contents = []
    return service_info, user_info, response, export_contents


# Delete the session's chat history
def forget_history(service_info, user_info, session_id, session_name, agent_file,
                   input, import_contents=[], add_info={}):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    for seq in chat_history_dict.keys():
        session.chg_seq_history(seq, "N")

    response = "All conversation history has been forgotten."
    export_contents = []
    return service_info, user_info, response, export_contents


# Restore the session's chat history
def remember_history(service_info, user_info, session_id, session_name, agent_file,
                     input, import_contents=[], add_info={}):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    for seq in chat_history_dict.keys():
        session.chg_seq_history(seq, "Y")

    response = "All conversation history has been restored."
    export_contents = []
    return service_info, user_info, response, export_contents


# ----- registrations ---------------------------------------------------------

dmtr.register_tool(
    "fixed_message",
    description=(
        "Return the supplied text verbatim as the assistant's response. "
        "Use for canned replies where no LLM generation is needed."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=fixed_message,
    example="/fixed_message Hello, this is a canned message.",
)

dmtr.register_tool(
    "forget_history",
    description=(
        "Mark the current session's entire chat history as 'forgotten' so it is "
        "excluded from future memory context. Use when the user explicitly asks "
        "to erase or ignore prior turns in this session."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    func=forget_history,
    example="/forget_history",
)

dmtr.register_tool(
    "remember_history",
    description=(
        "Restore (un-forget) the current session's chat history so previously "
        "hidden turns are visible to memory again. Inverse of forget_history."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    func=remember_history,
    example="/remember_history",
)
