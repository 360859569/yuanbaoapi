"""认证依赖模块"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import validate_api_key
from src.utils.common import generate_headers

bearer_scheme = HTTPBearer(auto_error=False)


async def require_api_key(
    authorization: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """仅校验 API Key（不要求浏览器已登录），用于模型列表等轻量接口

    Raises:
        HTTPException: 认证失败时抛出
    """
    if not authorization or not authorization.credentials:
        raise HTTPException(status_code=401, detail="need token")

    if not validate_api_key(authorization.credentials):
        raise HTTPException(status_code=403, detail="invalid api_key")


async def get_authorized_headers(
    authorization: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """获取授权的请求头

    Args:
        authorization: Bearer token 认证信息

    Returns:
        dict: 包含认证信息的请求头

    Raises:
        HTTPException: 认证失败时抛出
    """
    if not authorization or not authorization.credentials:
        raise HTTPException(status_code=401, detail="need token")

    token = authorization.credentials

    if not validate_api_key(token):
        raise HTTPException(status_code=403, detail="invalid api_key")

    try:
        headers = await generate_headers()
    except HTTPException:
        raise
    except Exception as e:
        # 未登录/二维码未扫等状态，返回明确提示而非通用 500
        raise HTTPException(status_code=503, detail=str(e))

    return headers
