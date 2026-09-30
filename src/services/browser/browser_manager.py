"""浏览器管理器模块"""

import asyncio
import logging
import os
from typing import Dict, Optional

from playwright.async_api import Browser, Page, async_playwright

from src.config import settings
from src.services.chat.conversation import create_conversation
from src.utils.qr_utils import print_qr_to_terminal

logger = logging.getLogger(__name__)

# 微信扫码登录 iframe（新版元宝页面登录框自动弹出，二维码位于该 iframe 内）
QR_IFRAME_SELECTOR = 'iframe[src*="qrconnect"]'

# 回放请求头时需要剔除的字段：
# x-bus-params-md5 / x-timestamp / x-hy* 等是页面按“当次请求体”计算的签名，
# 回放到不同的请求体上会被上游判定为无效（部分接口直接返回 23000 并吊销会话）
VOLATILE_HEADER_KEYS = {
    "x-bus-params-md5",
    "x-timestamp",
    "x-hy92",
    "x-hy93",
    "x-hy106",
    "x-webdriver",
    "x-ybuitest",
    "accept",
    "accept-encoding",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "content-length",
    "host",
}


class BrowserManager:
    """浏览器管理器 - 单例模式"""

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"):
            self.browser: Optional[Browser] = None
            self.page: Optional[Page] = None
            self.playwright = None
            self._is_logged_in = False
            self._cached_headers: Optional[Dict] = None
            self._headers_lock = asyncio.Lock()
            self._revalidating = False
            self._initialized = True

    @property
    def is_logged_in(self) -> bool:
        return self._is_logged_in

    def mark_session_invalid(self):
        """标记会话失效，由守护循环重新出码"""
        self._is_logged_in = False
        self._cached_headers = None

    def invalidate_headers(self):
        """认证失效时清除缓存，下次请求重新抓取"""
        self._cached_headers = None

    @staticmethod
    def _is_connection_dead(error: Exception) -> bool:
        """判断是否为浏览器进程崩溃/驱动连接断开"""
        msg = str(error)
        return any(
            key in msg
            for key in ("Connection closed", "Target closed", "Browser closed", "Target page, context or browser has been closed")
        )

    async def reset_browser(self):
        """浏览器进程崩溃后强制重置，下次使用时重新拉起"""
        logger.warning("[Browser] 浏览器连接已断开，重置浏览器状态以便重新拉起...")
        self._cached_headers = None
        self._is_logged_in = False
        try:
            await self.close()
        except Exception:
            pass
        self.page = None
        self.browser = None
        self.playwright = None

    async def revalidate(self):
        """重新验证会话有效性（上游返回 401/403 时触发）"""
        if self._revalidating or not self._is_logged_in:
            return
        self._revalidating = True
        try:
            self.invalidate_headers()
            if await self._verify_login():
                logger.info("[Browser] 会话仍然有效（上游 401 可能是临时问题）")
            else:
                self.invalidate_headers()
                self._is_logged_in = False
                logger.warning("[Browser] 会话已失效，需要重新扫码")
        finally:
            self._revalidating = False

    async def ensure_browser(self):
        """确保浏览器已初始化"""
        async with self._lock:
            if self.browser is None or self.page is None:
                await self._init_browser()

    async def _init_browser(self):
        """初始化浏览器"""
        if self.playwright is None:
            self.playwright = await async_playwright().start()

        if self.browser is None:
            self.browser = await self.playwright.chromium.launch(headless=True)

        if self.page is None:
            # locale 用 zh-CN：中文版页面会自动弹出登录框，且与认证接口行为一致
            context_kwargs = {"locale": "zh-CN"}
            if os.path.exists(settings.storage_state_path):
                logger.info("[Browser] 检测到历史登录状态，尝试恢复会话...")
                context_kwargs["storage_state"] = settings.storage_state_path
            self.page = await self.browser.new_page(**context_kwargs)
            await self._load_page()

    async def _save_state(self):
        """持久化登录状态，避免重启后重新扫码"""
        try:
            if self.page:
                await self.page.context.storage_state(path=settings.storage_state_path)
                logger.info("[Browser] 登录状态已保存")
        except Exception as e:
            logger.warning(f"[Browser] 保存登录状态失败: {e}")

    def _remove_saved_state(self):
        """删除已持久化的登录状态（匿名会话不应保留）"""
        try:
            if os.path.exists(settings.storage_state_path):
                os.remove(settings.storage_state_path)
        except Exception:
            pass

    async def _verify_login(self) -> bool:
        """验证当前会话是否真正已登录

        匿名状态下的页面请求也会携带 x-uskey，因此捕获到请求头不代表已登录，
        必须用真实接口（创建会话）验证。

        Returns:
            bool: 会话是否有效
        """
        headers = await self.get_headers()
        if not headers:
            return False
        try:
            await create_conversation(settings.agent_id, headers)
            return True
        except Exception as e:
            logger.info(
                f"[Browser] 会话验证未通过（未登录或已过期）: {e} | 捕获头字段: {','.join(sorted(headers.keys()))}"
            )
            return False

    async def _load_page(self):
        """预加载页面"""
        logger.info("[Browser] 预加载 Yuanbao 页面...")
        try:
            await self.page.goto(settings.page_url, timeout=settings.page_timeout)
            await self.page.wait_for_timeout(3000)
            logger.info("[Browser] 页面加载完成")
        except Exception as e:
            logger.error(f"[Browser] 页面加载失败: {e}")
            raise

    async def _wait_for_scan(self, qr_locator, show_qrcode) -> bool:
        """轮询等待扫码完成，保持二维码新鲜

        - 二维码 iframe 被移除 => 扫码成功
        - 微信端二维码 src 变化（自动刷新）=> 重新截图 qrcode.png
        - 二维码长时间（100 秒）无变化 => 重载页面强制出新码
        - 每轮操作限时 20 秒，防止页面卡死拖挂整个流程

        Returns:
            bool: 是否检测到扫码成功（弹窗关闭）
        """
        logger.info("[Browser] 等待扫码完成（二维码会保持刷新）...")
        loop = asyncio.get_event_loop()
        deadline = loop.time() + settings.login_timeout / 1000
        last_src = None
        last_capture = loop.time()

        while loop.time() < deadline:
            try:
                if not await asyncio.wait_for(
                    self.page.query_selector(QR_IFRAME_SELECTOR), timeout=20
                ):
                    logger.info("[Browser] 扫码成功，登录弹窗已关闭")
                    return True
                try:
                    src = await asyncio.wait_for(qr_locator.get_attribute("src"), timeout=10)
                except Exception:
                    src = None
            except Exception as e:
                if self._is_connection_dead(e):
                    raise
                logger.warning(f"[Browser] 扫码轮询异常: {e}")
                await self.page.wait_for_timeout(3000)
                continue

            now = loop.time()
            if src and src != last_src:
                if last_src is not None:
                    logger.info("[Browser] 检测到二维码已更新，重新截图")
                last_src = src
                try:
                    await show_qrcode()
                    last_capture = now
                except Exception as e:
                    logger.warning(f"[Browser] 二维码截图失败: {e}")
            elif now - last_capture > 100:
                logger.info("[Browser] 二维码长时间未更新，刷新页面获取新码...")
                try:
                    await self.page.reload(timeout=30000, wait_until="domcontentloaded")
                except Exception:
                    pass
                await self._open_login_dialog()
                try:
                    await show_qrcode()
                    last_capture = loop.time()
                except Exception as e:
                    logger.warning(f"[Browser] 二维码截图失败: {e}")

            await self.page.wait_for_timeout(2000)
        return False

    async def _open_login_dialog(self) -> bool:
        """确保登录弹窗（二维码 iframe）已打开

        新版元宝页面会自动弹出登录框；若未弹出则尝试点击登录入口。

        Returns:
            bool: 二维码 iframe 是否已出现
        """
        try:
            await self.page.wait_for_selector(QR_IFRAME_SELECTOR, timeout=8000)
            return True
        except Exception:
            pass

        logger.info("[Browser] 登录框未自动弹出，尝试点击登录入口...")
        for locator in (
            self.page.get_by_role("button", name="登录"),
            self.page.get_by_text("登录", exact=True),
            self.page.get_by_text("Log In", exact=True),
            self.page.get_by_role("img").first,
        ):
            try:
                await locator.click(timeout=5000)
                break
            except Exception:
                continue

        try:
            await self.page.wait_for_selector(QR_IFRAME_SELECTOR, timeout=10000)
            return True
        except Exception:
            return False

    async def login(self) -> Dict:
        """执行登录流程，返回二维码信息

        Returns:
            Dict: 登录结果字典
        """
        await self.ensure_browser()

        try:
            # 已有有效会话（含恢复的历史登录状态）则无需扫码
            if await self._verify_login():
                self._is_logged_in = True
                await self._save_state()
                logger.info("[Browser] 会话有效，跳过扫码登录")
                return {
                    "success": True,
                    "message": "已登录，无需扫码",
                }

            # 未登录：丢弃匿名会话的请求头缓存与持久化状态，进入扫码流程
            self.invalidate_headers()
            self._remove_saved_state()

            if not await self._open_login_dialog():
                logger.error("[Browser] 未找到登录入口或二维码")
                return {
                    "success": False,
                    "message": "未找到登录入口，页面可能已改版",
                }

            qr_locator = self.page.frame_locator(QR_IFRAME_SELECTOR).get_by_role("img").first

            async def _show_qrcode():
                await qr_locator.wait_for(state="visible", timeout=15000)
                await qr_locator.screenshot(path=settings.qrcode_path)
                logger.info(f"[Browser] 二维码已保存至 {settings.qrcode_path}")
                print_qr_to_terminal(settings.qrcode_path)

            await _show_qrcode()
            scan_completed = await self._wait_for_scan(qr_locator, _show_qrcode)

            # 扫码后浏览器才持有登录 Cookie，丢弃扫码前可能缓存的匿名请求头
            if scan_completed:
                self.invalidate_headers()

            # 最终以真实接口验证作为登录成功的判定标准（重试等待会话就绪）
            verified = False
            for _ in range(3):
                if await self._verify_login():
                    verified = True
                    break
                self.invalidate_headers()
                await self.page.wait_for_timeout(3000)

            if verified:
                self._is_logged_in = True
                await self._save_state()
                message = "登录成功" if scan_completed else "会话有效"
                return {
                    "success": True,
                    "message": message,
                    "qrcode_path": settings.qrcode_path,
                }

            logger.warning("[Browser] 扫码超时或未检测到登录成功")
            return {
                "success": False,
                "message": "扫码超时，请重启服务重新扫码",
                "qrcode_path": settings.qrcode_path,
            }
        except Exception as e:
            logger.error(f"[Browser] 登录失败: {e}")
            if self._is_connection_dead(e):
                await self.reset_browser()
            return {
                "success": False,
                "message": f"登录失败: {str(e)}",
            }

    async def get_headers(self) -> Optional[Dict]:
        """获取请求头：优先使用缓存，否则让页面在浏览器内发起真实请求后捕获

        页面自己发出的请求带有完整的会话 Cookie、x-uskey、x-agentid 等，
        直接捕获这类请求头可避免手工拼装遗漏。

        Returns:
            Optional[Dict]: 请求头字典，失败返回 None
        """
        if self._cached_headers:
            return self._cached_headers

        async with self._headers_lock:
            if self._cached_headers:
                return self._cached_headers

            try:
                await self.ensure_browser()
            except Exception as e:
                if self._is_connection_dead(e):
                    await self.reset_browser()
                raise
            captured_headers: Dict = {}

            async def handle_route(route, request):
                nonlocal captured_headers
                url = request.url

                if (
                    not captured_headers
                    and settings.header_api_pattern in url
                    and "x-uskey" in request.headers
                ):
                    captured_headers = await request.all_headers()
                    logger.info(f"[Browser] 捕获到请求头 from {url}")

                await route.continue_()

            await self.page.route("**/*", handle_route)
            try:
                # 让页面自己调用一次创建会话接口，其请求头由页面 JS 构造，最完整可靠
                try:
                    page_result = await asyncio.wait_for(
                        self.page.evaluate(
                            """async (agentId) => {
                                try {
                                    const r = await fetch('/api/user/agent/conversation/create', {
                                        method: 'POST',
                                        credentials: 'include',
                                        headers: {'content-type': 'application/json'},
                                        body: JSON.stringify({agentId})
                                    });
                                    let body = null;
                                    try { body = await r.json(); } catch (e) {}
                                    return {status: r.status, body};
                                } catch (e) {
                                    return {status: 0, body: String(e)};
                                }
                            }""",
                            settings.agent_id,
                        ),
                        timeout=30,
                    )
                    logger.info(f"[Browser] 页面内创建会话返回: {page_result}")
                except Exception as e:
                    logger.warning(f"[Browser] 页面内请求异常: {e}")
                    page_result = None

                # 兜底：若未捕获到（如页面未发出请求），重载页面嗅探
                if not captured_headers.get("x-uskey"):
                    try:
                        await self.page.reload(timeout=30000, wait_until="domcontentloaded")
                    except Exception as e:
                        logger.warning(f"[Browser] 页面重载异常（继续等待请求）: {e}")

                    start_time = asyncio.get_event_loop().time()
                    while (asyncio.get_event_loop().time() - start_time) < settings.header_timeout:
                        if captured_headers.get("x-uskey"):
                            break
                        await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"[Browser] 获取请求头失败: {e}")
                if self._is_connection_dead(e):
                    await self.reset_browser()
            finally:
                try:
                    await self.page.unroute("**/*", handle_route)
                except Exception:
                    pass

            if captured_headers.get("x-uskey"):
                headers = {
                    k: v for k, v in captured_headers.items() if k.lower() not in VOLATILE_HEADER_KEYS
                }
                # 兜底补齐关键头（旧版接口校验 X-Agentid / Origin / Referer）
                headers.setdefault("x-agentid", settings.agent_id)
                headers.setdefault("origin", "https://yuanbao.tencent.com")
                headers.setdefault("referer", settings.page_url)
                self._cached_headers = headers
                return headers
            return None

    async def get_cookies(self) -> Dict[str, str]:
        """获取 Cookie

        Returns:
            Dict[str, str]: Cookie 字典
        """
        await self.ensure_browser()

        if not self.page:
            return {}

        cookies = await self.page.context.cookies()
        return {c["name"]: c["value"] for c in cookies}

    async def close(self):
        """关闭浏览器"""
        async with self._lock:
            tasks = []
            if self.page:
                tasks.append(self.page.close())
                self.page = None
            if self.browser:
                tasks.append(self.browser.close())
                self.browser = None
            if self.playwright:
                tasks.append(self.playwright.stop())
                self.playwright = None
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


# 全局单例
browser_manager = BrowserManager()
