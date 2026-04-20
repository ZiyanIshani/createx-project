# test_authorship_debug.py
import json
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "mistral"

# paste whatever prompt your authorship agent builds
prompt = """
You are a code authorship analyst. Analyze the following file and return ONLY a JSON object.
No explanation, no markdown, no preamble.

File: src/cfg_constructor/utils/log_utils.py

Return this exact shape:
{
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "reason": "one sentence explanation"
}
"""

response = requests.post(OLLAMA_URL, json={
    "model": MODEL,
    "prompt": prompt,
    "stream": False
})

raw = response.json()["response"]
print("=== RAW RESPONSE ===")
print(raw)
print("=== ATTEMPTING PARSE ===")

try:
    parsed = json.loads(raw)
    print("SUCCESS:", parsed)
except json.JSONDecodeError as e:
    print("FAILED:", e)
    # try stripping markdown fences
    cleaned = raw.strip()
    if "```" in cleaned:
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        parsed = json.loads(cleaned.strip())
        print("SUCCESS after stripping fences:", parsed)
    except:
        print("Still failed after stripping. Raw was:\n", raw)