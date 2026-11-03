import json
import logging
import re
from typing import Any

from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)


class ChatCursor(BaseChatModel):
    """LangChain chat model backed by a one-shot Cursor SDK agent run."""

    api_key: str
    model: str = "composer-2.5"
    cwd: str

    @property
    def _llm_type(self) -> str:
        return "cursor-sdk"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        prompt = "\n\n".join(f"[{m.type.upper()}]\n{m.content}" for m in messages)
        result = Agent.prompt(
            prompt,
            AgentOptions(api_key=self.api_key, model=self.model, local=LocalAgentOptions(cwd=self.cwd)),
        )
        if result.status != "finished":
            raise RuntimeError(f"Cursor run {result.id} ended with {result.status}: {result.error_message}")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=result.result))])


def get_llm(settings) -> ChatCursor:
    settings.sandbox_dir.mkdir(exist_ok=True)
    return ChatCursor(
        api_key=settings.cursor_api_key,
        model=settings.section("llm").get("model", "composer-2.5"),
        cwd=str(settings.sandbox_dir),
    )


def _extract_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        return text
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return text[start:end + 1]


def ask_json(settings, system: str, user: str, schema: type[BaseModel], retries: int = 1) -> BaseModel:
    """Ask the LLM for JSON matching `schema`, retrying once with the validation error."""
    llm = get_llm(settings)
    instructions = (
        "\n\nReply with ONLY valid JSON matching this JSON schema. No prose, no markdown, no LaTeX. "
        "Do not read or edit any files.\n" + json.dumps(schema.model_json_schema())
    )
    messages = [SystemMessage(content=system + instructions), HumanMessage(content=user)]
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        reply = llm.invoke(messages).content
        try:
            return schema.model_validate_json(_extract_json(reply))
        except (ValidationError, ValueError) as e:
            last_error = e
            log.warning("LLM JSON invalid (attempt %d): %s", attempt + 1, str(e)[:300])
            messages.append(HumanMessage(content=f"Your JSON was invalid: {str(e)[:500]}. Return corrected JSON only."))
    raise ValueError(f"LLM did not return valid JSON: {last_error}")
