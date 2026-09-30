"""聊天完成服务模块"""

import asyncio
import time
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from src.schemas.chat import (
    ChatCompletionResponse,
    ChatMessageOut,
    ChoiceOut,
    YuanBaoChatCompletionRequest,
)
from src.services.browser import browser_manager
from src.services.chat.conversation import remove_conversation
from src.utils.chat import iter_response_deltas, process_response_stream

CHAT_URL = "https://yuanbao.tencent.com/api/chat/{}"

DEFAULT_TIMEOUT = 120


class ChatCompletionError(Exception):
    """聊天完成异常"""

    pass


# 持有后台任务引用，避免被垃圾回收导致不执行
_background_tasks: set = set()


def _spawn_background(coro):
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def build_chat_body(chat_request: YuanBaoChatCompletionRequest) -> Dict:
    """构建元宝聊天接口请求体"""
    multimedia = [m.model_dump() for m in chat_request.multimedia]
    body = {
        "model": "gpt_175B_0404",
        "prompt": chat_request.prompt,
        "plugin": "Adaptive",
        "displayPrompt": chat_request.prompt,
        "displayPromptType": 1,
        "options": {"imageIntention": {"needIntentionModel": True, "backendUpdateFlag": 2, "intentionStatus": True}},
        "multimedia": multimedia,
        "agentId": chat_request.agent_id,
        "supportHint": 1,
        "version": "v2",
        "chatModelId": chat_request.chat_model_id,
    }
    if chat_request.support_functions:
        body["supportFunctions"] = chat_request.support_functions
    return body


async def _ensure_ok_status(response: httpx.Response):
    """校验上游响应状态，401/403 时清理认证缓存"""
    if response.status_code in (401, 403):
        browser_manager.invalidate_headers()
        _spawn_background(browser_manager.revalidate())
        error_body = (await response.aread()).decode("utf-8", errors="ignore")[:300]
        raise ChatCompletionError(f"上游认证失败({response.status_code})，请重试: {error_body}")
    if response.status_code != 200:
        error_body = (await response.aread()).decode("utf-8", errors="ignore")[:300]
        raise ChatCompletionError(f"上游请求失败({response.status_code}): {error_body}")


async def create_completion_stream(
    chat_request: YuanBaoChatCompletionRequest,
    headers: Dict[str, str],
    should_remove_conversation: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    model_name: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """创建聊天完成流

    Args:
        chat_request: 聊天请求
        headers: 认证请求头
        should_remove_conversation: 是否删除会话
        timeout: 超时时间
        model_name: 返回给客户端的模型名称

    Yields:
        str: SSE 格式的数据块

    Raises:
        ChatCompletionError: 聊天完成失败时抛出
    """
    body = build_chat_body(chat_request)

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                CHAT_URL.format(chat_request.chat_id),
                json=body,
                headers=headers,
                timeout=timeout,
            ) as response:
                await _ensure_ok_status(response)
                async for chunk in process_response_stream(
                    response, model_name or chat_request.chat_id
                ):
                    yield chunk

    except Exception as e:
        raise ChatCompletionError(e)

    finally:
        if should_remove_conversation:
            await remove_conversation(chat_request.chat_id, headers)


async def create_completion(
    chat_request: YuanBaoChatCompletionRequest,
    headers: Dict[str, str],
    should_remove_conversation: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    model_name: Optional[str] = None,
) -> ChatCompletionResponse:
    """非流式聊天完成：聚合上游流式结果为完整响应

    Returns:
        ChatCompletionResponse: OpenAI 兼容的完整响应
    """
    body = build_chat_body(chat_request)
    content_parts: List[str] = []
    reasoning_parts: List[str] = []
    finish_reason = "stop"

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                CHAT_URL.format(chat_request.chat_id),
                json=body,
                headers=headers,
                timeout=timeout,
            ) as response:
                await _ensure_ok_status(response)
                async for content, reasoning, finish in iter_response_deltas(response):
                    if content:
                        content_parts.append(content)
                    if reasoning:
                        reasoning_parts.append(reasoning)
                    if finish:
                        finish_reason = finish

    except Exception as e:
        raise ChatCompletionError(e)

    finally:
        if should_remove_conversation:
            await remove_conversation(chat_request.chat_id, headers)

    message = ChatMessageOut(
        content="".join(content_parts),
        reasoning_content="".join(reasoning_parts) or None,
    )
    return ChatCompletionResponse(
        created=int(time.time()),
        model=model_name or chat_request.chat_id,
        choices=[ChoiceOut(message=message, finish_reason=finish_reason)],
    )
