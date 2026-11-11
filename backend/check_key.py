import os
from dotenv import dotenv_values
from anthropic import Anthropic

folder = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(folder, ".env")
print(".env ka raasta:", env_path)
print(".env mili:", os.path.exists(env_path))

vals = dotenv_values(env_path)
k = (vals.get("ANTHROPIC_API_KEY") or "").strip().strip('"').strip("'")
print("Key ke shuru ke 10 harf:", k[:10])
print("Key ki lambai:", len(k))

try:
    c = Anthropic(api_key=k)
    r = c.messages.create(model="claude-sonnet-5-5", max_tokens=20,
                          messages=[{"role": "user", "content": "hi"}])
    print("KEY THEEK HAI:", r.content[0].text)
except Exception as e:
    print("ERROR:", e)