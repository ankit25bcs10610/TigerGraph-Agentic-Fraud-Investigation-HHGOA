from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os

# Tests never call a real model or read local secrets: pin these before any
# module (such as backend.main) loads .env, which never overrides set values.
os.environ["LLM_PROVIDER"] = "disabled"
os.environ["LLM_PLANNER"] = "off"
os.environ["OPENAI_API_KEY"] = ""
os.environ["TRANSACTIONS_PATH"] = ""
os.environ["CLOSED_CASES_PATH"] = ""
os.environ["DATA_SOURCE"] = "csv"
