import os
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()

class LLM:
    def complete(self, messages: List[Dict[str, str]]) -> str:
        raise NotImplementedError

class OpenAILLM(LLM):
    def __init__(self, model: str=None):
        from openai import OpenAI
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model or os.getenv("MODEL_GPT", "gpt-4o-mini")

    def complete(self, messages):
        resp = self.client.chat.completions.create(model=self.model, messages=messages, temperature=0.2)
        return resp.choices[0].message.content.strip()

class AnthropicLLM(LLM):
    def __init__(self, model: str=None):
        import anthropic
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = model or os.getenv("CLAUDE_MODEL_ID", "claude-3-5-sonnet-20240620")

    def complete(self, messages):
        # Convert OpenAI-style messages to Anthropic format
        sys = ""
        turns = []
        for m in messages:
            if m["role"] == "system":
                sys += m["content"] + "\n"
            else:
                turns.append({"role": m["role"], "content": m["content"]})
        msg = self.client.messages.create(
            model=self.model,
            system=sys or None,
            max_tokens=300,
            temperature=0.2,
            messages=[{"role": t["role"], "content": t["content"]} for t in turns],
        )
        return msg.content[0].text.strip()
