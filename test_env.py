from dotenv import load_dotenv
import os
load_dotenv()
print("Mistral:", "OK" if os.getenv("MISTRAL_API_KEY") else "MISSING")
print("Speechmatics:", "OK" if os.getenv("SPEECHMATICS_API_KEY") else "MISSING")
print("Gemini:", "OK" if os.getenv("GEMINI_API_KEY") else "MISSING")