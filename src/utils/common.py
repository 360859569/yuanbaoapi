"""通用工具函数模块"""

from typing import Dict

from src.services.browser import browser_manager


async def generate_headers() -> Dict[str, str]:
    """生成请求头，从浏览器管理器获取最新的认证信息

    Returns:
        Dict[str, str]: 包含认证信息的请求头

    Raises:
        Exception: 未登录或无法获取请求头时抛出
    """
    if not browser_manager.is_logged_in:
        raise Exception("服务尚未完成登录：请用微信扫描项目目录下的 qrcode.png 后再试")

    headers = await browser_manager.get_headers()
    if not headers:
        raise Exception("无法获取请求头，请确保已登录")

    return dict(headers)
