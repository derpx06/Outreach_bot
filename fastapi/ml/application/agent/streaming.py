"""
Efficient streaming implementation for agent responses.
"""
import json
import re
from typing import AsyncGenerator, Dict, List
from loguru import logger
from langsmith import traceable

from .schemas import AgentStreamChunk
from ml.settings import settings


def _format_multi_channel_output(drafts: dict) -> str:
    """Format multi-channel drafts into a single Markdown string."""
    if not drafts:
        return ""
    parts = []
    for channel, content in drafts.items():
        title = channel.replace("_", " ").title()
        parts.append(f"## {title}\n{content}")
    return "\n\n".join(parts).strip()


def _state_get(state, key, default=None):
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


def _infer_outreach_preference(message: str) -> List[str]:
    """
    Infer a clean outreach channel preference from user text.
    Output is intentionally constrained to outreach-only channels.
    """
    text = (message or "").lower()
    wants_email = bool(re.search(r"\b(email|mail|e-mail)\b", text))
    wants_linkedin = "linkedin" in text
    wants_whatsapp = bool(re.search(r"\b(whatsapp|whats app|sms|text)\b", text))
    generic_outreach_msg = bool(re.search(r"\b(outreach message|dm|message)\b", text))

    requested: List[str] = []
    if wants_email:
        requested.append("email")
    if wants_linkedin:
        requested.append("linkedin_dm")
    if wants_whatsapp:
        requested.append("whatsapp")

    if not requested and generic_outreach_msg:
        requested = ["email", "whatsapp"]
    elif not requested:
        requested = ["email"]

    if "email" not in requested:
        requested.insert(0, "email")

    return list(dict.fromkeys(requested))


def _sanitize_outreach_output(message: str, drafts: Dict[str, str]) -> Dict[str, str]:
    """
    Keep only: email + one outreach message channel.
    Drops non-outreach/meta channels (general_response, reports, etc.).
    """
    if not isinstance(drafts, dict):
        return {}

    normalized: Dict[str, str] = {}
    for key, val in drafts.items():
        if not val:
            continue
        if key == "linkedin":
            normalized["linkedin_dm"] = val
        else:
            normalized[key] = val

    preferred = _infer_outreach_preference(message)
    output: Dict[str, str] = {}

    if "email" in normalized:
        output["email"] = normalized["email"]

    outreach_choice = None
    for ch in preferred:
        if ch != "email" and ch in normalized:
            outreach_choice = ch
            break

    if outreach_choice is None:
        for fallback in ("whatsapp", "linkedin_dm"):
            if fallback in normalized:
                outreach_choice = fallback
                break

    if outreach_choice:
        output[outreach_choice] = normalized[outreach_choice]

    if not output:
        return {
            "email": "Please share who to contact and what outreach goal you want."
        }

    return output


@traceable(name="Agent SSE Stream")
async def stream_agent_response(
    message: str,
    model: str = settings.LLM_MODEL,
    user_email: str = None,
    conversation_history: list = None,
    max_iterations: int = 10
) -> AsyncGenerator[str, None]:
    """
    Stream agent responses as Server-Sent Events.
    Emits only copy-ready outreach response chunks + done.
    """
    del model, max_iterations  # Reserved for compatibility.

    try:
        logger.info(f"Starting agent stream for message: {message[:50]}...")

        from .graph import stream_agent

        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, message)

        if urls:
            target_url = urls[0]
            user_instruction = message.replace(target_url, "").strip() or "Analyze this"
        else:
            target_url = None
            user_instruction = message

        iteration_count = 0
        final_sent = False

        async for state_update in stream_agent(
            user_instruction=user_instruction,
            target_url=target_url,
            user_email=user_email,
            conversation_history=conversation_history
        ):
            final_output = _state_get(state_update, "final_output")
            iteration_count += 1

            if final_output and not final_sent:
                if isinstance(final_output, dict):
                    clean_output = _sanitize_outreach_output(message, final_output)
                    final_text = _format_multi_channel_output(clean_output)
                else:
                    final_text = str(final_output)

                chunk = AgentStreamChunk(
                    type="response",
                    content=final_text
                )
                yield f"data: {chunk.model_dump_json()}\n\n"

                done_chunk = AgentStreamChunk(
                    type="done",
                    content=final_text,
                    metadata={"iterations": iteration_count}
                )
                yield f"data: {done_chunk.model_dump_json()}\n\n"
                final_sent = True
                break

    except Exception as e:
        logger.error("Error during agent streaming: {err}", err=str(e))

        error_content = str(e)
        if isinstance(e, dict):
            error_content = json.dumps(e)
        elif hasattr(e, "message"):
            error_content = e.message

        yield f"data: {json.dumps({'type': 'error', 'content': error_content})}\n\n"


def format_final_response(events: list) -> dict:
    """
    Extract and format the final response from agent events.
    """
    final_response = ""
    tool_calls = []
    iterations = 0

    for event in events:
        if "agent" in event:
            messages = event["agent"].get("messages", [])
            if messages:
                last_message = messages[-1]
                if hasattr(last_message, "content") and last_message.content:
                    final_response = last_message.content

                if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                    for tc in last_message.tool_calls:
                        tool_calls.append({
                            "name": tc.get("name"),
                            "input": tc.get("args")
                        })

            iterations = event["agent"].get("iterations", iterations)

    return {
        "response": final_response,
        "tool_calls": tool_calls,
        "iterations": iterations
    }
