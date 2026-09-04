from fastapi import FastAPI

app = FastAPI(
    title="F.A.M.A. Backend API",
    description="Backend API for F.A.M.A. (Fauna Audio Monitoring & Analysis)",
    version="1.0.0",
)


@app.get("/health")
def health_check():
    return {"status": "ok"}
