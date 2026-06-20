from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


# POSTリクエストのスキーマ定義
class TextInput(BaseModel):
    text: str


@app.get("/")
async def root():
    return {"message": "Hello World"}


# 検証用の GET エンドポイント (Traefikによって /api が剥がされ /data に到達)
@app.get("/data")
async def get_data():
    return {
        "items": [
            "FastAPIより: データの取得に成功しました (Item A)",
            "FastAPIより: データの取得に成功しました (Item B)"
        ]
    }


# 検証用の POST エンドポイント (Traefikによって /api が剥がされ /process に到達)
@app.post("/process")
async def process_data(payload: TextInput):
    # 送信されたテキストを大文字に加工して返す
    processed_text = f"PROCESSED ON BACKEND: {payload.text.upper()}"
    return {"processed": processed_text}
