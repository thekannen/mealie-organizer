import json
import os
import sys

import requests

from categorizer_core import REPO_ROOT, load_env_file, MealieCategorizer

load_env_file(REPO_ROOT / ".env")

MEALIE_URL = os.environ.get("MEALIE_URL", "http://your.server.ip.address:9000/api")
MEALIE_API_KEY = os.environ.get("MEALIE_API_KEY", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral:7b")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "2"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "3"))
REPLACE_EXISTING = "--recat" in sys.argv
CACHE_FILE = os.environ.get("CACHE_FILE", str(REPO_ROOT / "cache" / "results_ollama.json"))


def query_ollama(prompt_text):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt_text + "\n\nRespond only with valid JSON.",
        "options": {
            "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "1024")),
            "temperature": float(os.environ.get("OLLAMA_TEMPERATURE", "0.1")),
            "num_predict": int(os.environ.get("OLLAMA_NUM_PREDICT", "96")),
            "top_p": float(os.environ.get("OLLAMA_TOP_P", "0.8")),
            "num_thread": int(os.environ.get("OLLAMA_NUM_THREAD", "8")),
        },
    }
    try:
        response = requests.post(
            f"{OLLAMA_URL}/generate",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            stream=True,
            timeout=180,
        )
        response.raise_for_status()
        text = ""
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                chunk = json.loads(line)
                if "response" in chunk:
                    text += chunk["response"]
            except json.JSONDecodeError:
                continue
        return text.strip()
    except Exception as exc:
        print(f"Ollama request error: {exc}")
        return None


def main():
    if not MEALIE_API_KEY:
        raise RuntimeError("MEALIE_API_KEY is empty. Set it in .env or the environment.")

    categorizer = MealieCategorizer(
        mealie_url=MEALIE_URL,
        mealie_api_key=MEALIE_API_KEY,
        batch_size=BATCH_SIZE,
        max_workers=MAX_WORKERS,
        replace_existing=REPLACE_EXISTING,
        cache_file=CACHE_FILE,
        query_text=query_ollama,
        provider_name=f"Ollama ({OLLAMA_MODEL})",
    )
    categorizer.run()


if __name__ == "__main__":
    main()
