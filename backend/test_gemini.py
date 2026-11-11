
from ocr import client, model_name

print("Testing Gemini connection...")
print("Model:", model_name())

response = client().models.generate_content(
    model=model_name(),
    contents="Reply with exactly: Gemini is working"
)

print("Response:", response.text)
print("SUCCESS: Gemini connection is working!")
