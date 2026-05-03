import os
from typing import Generator

PROVIDER = os.getenv("AI_PROVIDER", "claude").lower()  # "claude" | "openai"


def stream_response(messages: list[dict], db_context: str) -> Generator[str, None, None]:
    system = (
        "你是 PriceWise 的智慧助手，專門協助用戶分析商品價格趨勢。"
        "請根據以下資料庫摘要回答問題，回答請用繁體中文，保持簡潔專業。\n\n"
        + db_context
    )

    if PROVIDER == "openai":
        yield from _openai_stream(system, messages)
    else:
        yield from _claude_stream(system, messages)


def _claude_stream(system: str, messages: list[dict]) -> Generator[str, None, None]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


def _openai_stream(system: str, messages: list[dict]) -> Generator[str, None, None]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    full_messages = [{"role": "system", "content": system}] + messages

    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=full_messages,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
