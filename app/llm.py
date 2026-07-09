import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def call_llm(prompt: str) -> str:
    """
    Send a prompt to Gemini, return the text response.
    Single function used everywhere in the app.
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"LLM call failed: {e}")
        return ""