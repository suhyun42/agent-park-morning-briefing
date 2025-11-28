from fastapi import FastAPI
from agentpark import build_morning_summary

app = FastAPI()


@app.get("/")
def root():
    """Simple health check endpoint."""
    return {"message": "Agent Park is running"}

@app.get("/morning-briefing")
def morning_summary():
    """Return the full morning summary as JSON."""
    summary = build_morning_summary()
    return {"summary": summary}
