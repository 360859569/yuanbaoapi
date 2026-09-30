"""聊天相关工具函数模块"""

import json
import time
from typing import AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from src.const import MODEL_MAPPING
from src.schemas.chat import ChatCompletionChunk, Choice, ChoiceDelta, Message


def get_model_info(model_name: str) -> Optional[Dict]:
    """获取模型信息

    Args:
        model_name: 模型名称

    Returns:
        Optional[Dict]: 模型映射信息，不存在返回 None
    """
    return MODEL_MAPPING.get(model_name.lower(), None)


def parse_messages(messages: List[Message]) -> str:
    """解析消息列表为提示词

    Args:
        messages: 消息列表

    Returns:
        str: 解析后的提示词
    """
    only_user_message = True
    for m in messages:
        if m.role != "user":
            only_user_message = False
            break
    if only_user_message:
        prompt = "\n".join([f"{m.role}: {m.content}" for m in messages])
    else:
        prompt = "\n".join([f"{m.content}" for m in messages])
    return prompt


def extract_delta(chunk_data: Dict) -> Tuple[str, str]:
    """从元宝数据块中提取正文与思考增量

    元宝数据块形如：
        {"type": "text", "msg": "回答内容"}
        {"type": "think", "msg": "思考内容"}
        {"type": "step", "msg": "正在搜索资料", ...}  # 搜索/工具进度，忽略

    Args:
        chunk_data: 元宝返回的数据块

    Returns:
        Tuple[str, str]: (正文增量, 思考增量)
    """
    chunk_type = chunk_data.get("type")
    msg = chunk_data.get("msg") or ""

    if chunk_type == "text":
        return msg, ""
    if chunk_type in ("think", "reasoning"):
        return "", msg
    return "", ""


async def iter_response_deltas(
    response: httpx.Response,
) -> AsyncGenerator[Tuple[str, str, Optional[str]], None]:
    """迭代上游流，产出 (正文增量, 思考增量, finish_reason)

    Args:
        response: 上游 HTTP 响应对象

    Yields:
        Tuple[str, str, Optional[str]]: 增量内容与结束原因（非结束时为 None）
    """
    start_word = "data: "
    finish_reason = "stop"

    async for line in response.aiter_lines():
        if not line or not line.startswith(start_word):
            continue
        data: str = line[len(start_word) :]

        if data == "[DONE]":
            yield "", "", finish_reason
            return
        if not data.startswith("{"):
            continue

        try:
            chunk_data: Dict = json.loads(data)
        except ValueError:
            continue

        if chunk_data.get("stopReason"):
            finish_reason = chunk_data["stopReason"]

        content, reasoning = extract_delta(chunk_data)
        if content or reasoning:
            yield content, reasoning, None


async def process_response_stream(response: httpx.Response, model_id: str) -> AsyncGenerator[str, None]:
    """处理响应流，转换为 OpenAI SSE 格式

    Args:
        response: HTTP 响应对象
        model_id: 模型 ID

    Yields:
        str: SSE 格式的数据块
    """

    def _create_chunk(content: str = "", reasoning: str = "", finish_reason: Optional[str] = None) -> str:
        delta_kwargs: Dict = {"content": content}
        if reasoning:
            delta_kwargs["reasoning_content"] = reasoning
        choice_delta = ChoiceDelta(**delta_kwargs)
        choice = Choice(delta=choice_delta, finish_reason=finish_reason)
        chunk = ChatCompletionChunk(created=int(time.time()), model=model_id, choices=[choice])
        return chunk.model_dump_json(exclude_unset=True)

    async for content, reasoning, finish in iter_response_deltas(response):
        yield _create_chunk(content=content, reasoning=reasoning, finish_reason=finish)

    yield "[DONE]"
