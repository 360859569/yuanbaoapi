"""YuanBao API Proxy 主应用"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.routers import chat, upload
from src.services.browser import browser_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def login_caretaker():
    """后台登录守护：未登录或会话失效时自动出码等待扫码"""
    while True:
        try:
            if not browser_manager.is_logged_in:
                result = await browser_manager.login()
                logger.info(f"[Login] 登录流程结果: {result}")
            await asyncio.sleep(30 if browser_manager.is_logged_in else 10)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[Login] 登录流程异常: {e}")
            await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期事件处理器"""
    logger.info("[Startup] 启动登录守护任务（后台扫码，不阻塞服务）...")
    login_task = asyncio.create_task(login_caretaker())

    yield

    logger.info("[Shutdown] 正在关闭浏览器...")
    login_task.cancel()
    try:
        await browser_manager.close()
        logger.info("[Shutdown] 浏览器已关闭")
    except Exception as e:
        logger.error(f"[Shutdown] 关闭浏览器失败: {e}")


app = FastAPI(title="YuanBao API Proxy", version="1.0.0", lifespan=lifespan)

app.include_router(chat.router)
app.include_router(upload.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
