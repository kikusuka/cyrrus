"""
cyrrus — working example.

Requires Ollama running locally:
    ollama serve
    ollama pull llama3.2

Or swap ollama() for openai(), anthropic(), or groq() from cyrrus.providers.
"""
import asyncio
from cyrrus import Projector
from cyrrus.providers import ollama

# --- Your slides config ---
# core_lamp is required — it's the base persona, always included.
# Everything else is optional and only injected when relevant.
# tokens and priority are auto-computed if you leave them out.

config = {
    "core_lamp": {
        "content": "You are a helpful assistant. Be concise and direct.",
    },
    "code_lens": {
        "content": "The user is asking about code. Output clean code blocks only, no filler.",
        "triggers": ["code", "script", "python", "function", "bug", "error"],
        "examples": ["write a function that does this", "fix this bug", "how do I parse JSON"],
    },
    "casual_lens": {
        "content": "This is casual conversation. Keep it short and natural.",
        "triggers": ["hey", "hi", "hello", "how are you", "what's up"],
    },
}

bot = Projector(config, llm_call=ollama("llama3.2"))


async def main():
    print("cyrrus example — type 'quit' to exit, 'trace' to see what was injected.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            break
        if user_input.lower() == "trace":
            t = bot.last_trace
            if not t:
                print("(no trace yet — send a message first)\n")
                continue
            msgs = t.get("messages", [])
            system = next((m["content"] for m in msgs if m["role"] == "system"), "")
            print(f"\n--- system message sent to LLM ---\n{system}\n---\n")
            print(f"routed: {t.get('routed_slide_ids')}")
            print(f"memory: {t.get('memory_slide_ids')}")
            print(f"dropped: {t.get('dropped_slide_ids')}")
            print(f"history turns: {t.get('stats', {}).get('history_turns', 0)}\n")
            continue

        try:
            reply = await bot.process(user_input, session_id="demo_user")
            print(f"Bot: {reply}\n")
        except Exception as e:
            print(f"Error: {e}")
            print("Is Ollama running? Try: ollama serve\n")


if __name__ == "__main__":
    asyncio.run(main())
