from fastapi import FastAPI
from agentpark import build_morning_summary

app = FastAPI()


@app.get("/Agent-Park")
def morning_summary():
    """Return the full morning summary as JSON."""
    summary = build_morning_summary()
    return {"summary": summary}
