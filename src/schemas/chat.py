"""聊天相关数据模型模块"""

from typing import List, Optional

from pydantic import BaseModel, field_validator

from src.const import MODEL_MAPPING
from src.schemas.common import Media


class Message(BaseModel):
    """消息模型"""

    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """聊天完成请求模型"""

    messages: List[Message]
    model: str
    stream: bool = True
    chat_id: Optional[str] = None
    should_remove_conversation: bool = False
    multimedia: List[Media] = []

    @field_validator("messages")
    def check_messages_not_empty(cls, value):
        if not value:
            raise ValueError("messages cannot be an empty list")
        return value

    @field_validator("model")
    def validate_model(cls, value):
        if value not in MODEL_MAPPING:
            raise ValueError(f"model must be one of {list(MODEL_MAPPING.keys())}")
        return value


class YuanBaoChatCompletionRequest(BaseModel):
    """腾讯元宝聊天完成请求模型"""

    agent_id: str
    chat_id: str
    prompt: str
    chat_model_id: str
    multimedia: List[Media] = []
    support_functions: Optional[List[str]]


class ChoiceDelta(BaseModel):
    """选择增量模型"""

    role: str = "assistant"
    content: str = ""
    reasoning_content: Optional[str] = None


class Choice(BaseModel):
    """选择模型"""

    index: int = 0
    delta: ChoiceDelta
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    """聊天完成数据块模型"""

    id: str = ""
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[Choice]


class ChatMessageOut(BaseModel):
    """非流式响应的消息模型"""

    role: str = "assistant"
    content: str = ""
    reasoning_content: Optional[str] = None


class ChoiceOut(BaseModel):
    """非流式响应的选择模型"""

    index: int = 0
    message: ChatMessageOut
    finish_reason: Optional[str] = None


class ChatCompletionResponse(BaseModel):
    """非流式聊天完成响应模型"""

    id: str = ""
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChoiceOut]
