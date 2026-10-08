from fastapi import FastAPI

from app.auth.dependencies import get_authentication_provider

# Build the authentication provider at import so unsafe or incomplete auth
# configuration (e.g. the development provider outside development) stops
# startup instead of surfacing per request.
get_authentication_provider()

app = FastAPI(
    title="HeroOS API",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
