import uvicorn

if __name__ == "__main__":
    # Note: Running with reload=True inside a script can fail in pip-less uv environments.
    # Prefer using 'make start' which calls 'uv run uvicorn ... --reload'
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
