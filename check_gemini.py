"""Check the Gemini key alone, without Telegram: python check_gemini.py"""
import os

from google import genai
from google.genai import types

import ai_bot

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
answer = client.models.generate_content(
    model=ai_bot.MODEL,
    contents="Как называется школа и где она находится?",
    config=types.GenerateContentConfig(system_instruction=ai_bot.SYSTEM_PROMPT),
)
print(answer.text)
