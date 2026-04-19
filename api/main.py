from contextlib import asynccontextmanager
from fastapi import FastAPI
from api.routes import router
from core.logging import configure_logging, logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("app_starting")
    yield
    logger.info("app_stopping")


app = FastAPI(
    title="Test Generation Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
