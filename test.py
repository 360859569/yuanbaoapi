"""API 测试脚本

用法：
    export YUANBAO_API_KEY=sk-your-api-key   # 需与 .env 中 API_KEYS 一致
    export YUANBAO_BASE_URL=http://localhost:8000/v1/   # 可选，默认本机
    python test.py
"""

import base64
import os

import requests
from openai import OpenAI

BASE_URL = os.environ.get("YUANBAO_BASE_URL", "http://localhost:8000/v1/")
API_KEY = os.environ.get("YUANBAO_API_KEY", "sk-test-api-key")

# ---------- 模型列表 ----------
client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
print("可用模型:", [m.id for m in client.models.list().data])

# ---------- 上传文件（可选） ----------
multimedia = []
try:
    with open("qrcode.png", "rb") as f:
        file_data = base64.b64encode(f.read()).decode("utf-8")
    resp = requests.post(
        BASE_URL + "upload",
        json={
            "file": {
                "file_name": "qrcode.png",
                "file_data": file_data,
                "file_type": "image",  # image、doc、excel、pdf 等
            }
        },
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=60,
    )
    if resp.status_code == 200:
        multimedia = [resp.json()]
        print("文件上传成功:", resp.json())
    else:
        print("文件上传失败:", resp.status_code, resp.text)
except FileNotFoundError:
    print("未找到测试文件，跳过上传")

# ---------- 流式对话 ----------
stream = client.chat.completions.create(
    model="deepseek-v3",
    messages=[{"role": "user", "content": "这是什么？"}],
    stream=True,
    extra_body={
        "chat_id": "",  # 可选，不传则自动创建新会话
        "should_remove_conversation": False,
        "multimedia": multimedia,
    },
)

print("\n回复：", end="")
for chunk in stream:
    delta = chunk.choices[0].delta
    if delta.reasoning_content:
        print(f"[思考] {delta.reasoning_content}", end="", flush=True)
    print(delta.content or "", end="", flush=True)
print("\n")
