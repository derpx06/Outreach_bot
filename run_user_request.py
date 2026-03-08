
import asyncio
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), 'fastapi/.env'))

# Ensure the project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'fastapi')))

from ml.ollama_deep_researcher.graph import graph as app
from langchain_core.runnables import RunnableConfig

async def run_user_request():
    title = "The Future of AI in Sales"
    writing_brief = {
        "title_hint": "Generate a strong title",
        "format": "Thought Leadership",
        "tone": "Insightful",
        "audience": "Founders and growth leaders",
        "target_words": 900,
        "keyword": "none",
        "article_intent": "Deliver an insightful thought leadership article on 'The Future of AI in Sales'.",
        "angle": "Explain the concept of AI agents and autonomous sales flows in simple language, then connect it to practical decisions for growth leaders.",
        "target_reader": "Founders and growth leaders",
        "style_direction": "Insightful, implementation-focused, concrete examples. BAN RHETORICAL QUESTIONS. Be authoritative.",
        "structure": "H1 title, deck line, Hook, Core Insights, Practical Framework, Action Plan, CTA."
    }
    
    print(f"\n\n==================================================")
    print(f"RUNNING USER REQUEST: '{title}'")
    print(f"==================================================\n")
    
    config = RunnableConfig(configurable={"thread_id": "user-request-sales-ai"})
    final_article = ""

    try:
        async for chunk in app.astream({
            "topic": title,
            "writing_brief": writing_brief
        }, config, stream_mode="updates"):
            for node, values in chunk.items():
                if "logs" in values:
                    for log in values["logs"]:
                        print(log)
                if "final_article" in values:
                    final_article = values["final_article"]

        print(f"\n--- FINAL ARTICLE ---\n")
        print(final_article)
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(run_user_request())
