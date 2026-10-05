import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.router import router

app = FastAPI(title="軍儀 API", version="0.1.0")

allowed_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001,https://gungi-app.vercel.app",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def warmup_fast_engine():
    # 高速 AI エンジンのコンパイル（約 45 秒）をバックグラウンドで済ませる
    from logic.ai import fast
    fast.start_background_warmup()


@app.get("/")
def health():
    from logic.ai import fast
    return {"status": "ok", "fast_engine": fast.status()}
