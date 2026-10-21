import json

import groq
import httpx
from langchain_core.messages import AIMessage

REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
TIMEOUT = groq.APITimeoutError(request=REQUEST)


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def bind(self, **kwargs):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return AIMessage(reply if isinstance(reply, str) else json.dumps(reply))
