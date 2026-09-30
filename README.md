# 反代腾讯元宝 YuanBao Free API

一个将**腾讯元宝**（yuanbao.tencent.com）封装为 **OpenAI 兼容 API** 的自部署反向代理服务。通过微信扫码登录一次，即可用标准 OpenAI SDK / 任意 OpenAI 兼容客户端调用元宝的 DeepSeek、混元系列大模型。

> ⚠️ 本项目仅供**学习研究**使用，请勿用于商业用途。使用非官方接口存在**账号被封禁的风险**，请知悉并自担风险。

## ✨ 核心特性

- 🔄 **完整兼容 OpenAI API**：`/v1/chat/completions`（流式 + 非流式）、`/v1/models`、`/v1/upload`
- 🚀 **支持主流元宝大模型**：DeepSeek V3 / R1、腾讯混元 / 混元 T1，各模型均有联网搜索变体
- 📝 **标准纯文本输出**：自动解析元宝数据块，思考过程走 `reasoning_content` 字段，搜索进度块自动过滤
- 🔐 **扫码登录一次，长期使用**：登录会话持久化到本地，重启服务无需重新扫码
- 🩹 **故障自愈**：浏览器进程崩溃自动重启、会话失效自动重新出码、认证头自动刷新
- 🖼️ **支持上传图片 / 文档**对话
- 📦 **开箱即用**：本地 / Docker / 宝塔面板均可部署

## 🧠 支持模型

| 模型名称            | 说明                          |
|---------------------|-------------------------------|
| deepseek-v3         | DeepSeek V3                   |
| deepseek-r1         | DeepSeek R1（深度思考）        |
| deepseek-v3-search  | DeepSeek V3 + 联网搜索         |
| deepseek-r1-search  | DeepSeek R1 + 联网搜索         |
| hunyuan             | 腾讯混元                       |
| hunyuan-t1          | 腾讯混元 T1（深度思考）        |
| hunyuan-search      | 腾讯混元 + 联网搜索            |
| hunyuan-t1-search   | 腾讯混元 T1 + 联网搜索         |

模型列表可通过 `GET /v1/models` 实时获取，新增模型只需在 `src/const.py` 的 `MODEL_MAPPING` 中添加。

## 🚀 快速开始

### 环境准备

```bash
# 克隆项目
git clone https://github.com/your-name/yuanbao-free-api.git
cd yuanbao-free-api

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

### 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，配置 API Keys（多个用英文逗号分隔，必填）
# API_KEYS=sk-your-api-key-1,sk-your-api-key-2
```

### 本地运行

```bash
python app.py
# 服务地址：http://localhost:8000
```

首次启动会在**终端打印二维码**，同时在项目目录保存 `qrcode.png`——用微信扫码完成登录。登录成功后会话自动持久化，之后重启不再需要扫码。

> 二维码约 100 秒过期，服务会自动刷新重新出码；项目目录下的 `qrcode.png` 始终是最新可扫的。服务器部署时终端看不到二维码，直接打开 `qrcode.png` 文件扫码即可。

## 🐳 Docker 部署

```bash
# 构建镜像
docker build -t yuanbao-free-api .

# 运行（挂载 data 目录以持久化登录会话）
docker run -d -p 8000:8000 \
  -e API_KEYS=sk-your-api-key \
  -v $(pwd)/data:/app/data \
  --name yuanbao-api yuanbao-free-api
```

登录会话保存在挂载的 `data/` 目录中，容器重建后无需重新扫码。

## 🖥️ 宝塔面板部署

1. 宝塔面板 → Python 项目 → 添加项目，选择项目目录与 Python 版本，安装依赖
2. 额外执行 `playwright install chromium` 安装浏览器
3. 配置 `.env` 后启动项目
4. 启动后打开项目目录下的 `qrcode.png` 扫码登录

> 💡 建议服务器配置 **2GB 以上 swap**：无头浏览器常驻内存，内存不足时浏览器进程可能被系统杀掉（服务会自动重启浏览器并重新出码，但重新扫码更省心）。

## 🔌 API 接口

### 聊天补全（流式）

```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v3",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

### 聊天补全（非流式）

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-r1",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
```

非流式返回标准 `chat.completion` 结构，思考模型额外返回 `reasoning_content` 字段。

### Python（OpenAI SDK）

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1/", api_key="sk-your-api-key")

# 模型列表
models = client.models.list()

# 流式对话
stream = client.chat.completions.create(
    model="deepseek-v3",
    messages=[{"role": "user", "content": "介绍一下你自己"}],
    stream=True,
)
for chunk in stream:
    delta = chunk.choices[0].delta
    print(delta.content or "", end="", flush=True)
```

### 文件上传（可选，配合对话使用）

```bash
curl http://localhost:8000/v1/upload \
  -H "Authorization: Bearer sk-your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "file": {
      "file_name": "test.png",
      "file_data": "<base64 编码的文件内容>",
      "file_type": "image"
    }
  }'
```

上传返回的 `multimedia` 数组可直接放入聊天请求的 `multimedia` 字段。完整示例见 `test.py`。

### 聊天请求扩展参数

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `stream` | bool | `true` | 是否流式返回 |
| `chat_id` | string | 无 | 复用元宝会话 ID（不传则自动创建新会话） |
| `should_remove_conversation` | bool | `false` | 请求结束后是否删除元宝会话 |
| `multimedia` | array | `[]` | 上传文件返回的多媒体引用 |

## 🔐 认证机制说明

本服务通过 Playwright 无头浏览器自动完成元宝的登录与鉴权：

1. **启动时**后台打开元宝页面，自动弹出微信扫码登录框，二维码实时保存为 `qrcode.png` 并打印到终端
2. **扫码后**服务在浏览器内发起真实请求验证会话，通过后将登录状态（`storage_state.json`）持久化
3. **每次对话**自动捕获页面构造的完整认证请求头（Cookie、`x-agentid` 等）并回放给元宝接口，剔除会干扰校验的请求体签名头
4. **故障自愈**：会话过期自动重新出码、浏览器崩溃自动重启、认证失效自动重新抓取

## ⚙️ 配置说明

在 `.env` 中配置（所有变量均有默认值，仅需配置 `API_KEYS`）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `API_KEYS` | 无（必填） | 允许的 API Key，多个用英文逗号分隔 |
| `AGENT_ID` | `naQivTmsDa` | 元宝 Agent ID，一般无需修改 |
| `PAGE_URL` | `https://yuanbao.tencent.com/chat/naQivTmsDa` | 元宝页面地址 |
| `UPLOAD_HOST` | `hunyuan-prod-1258344703.cos.accelerate.myqcloud.com` | 文件上传域名 |
| `LOGIN_TIMEOUT` | `300000` | 等待扫码超时（毫秒） |
| `QRCODE_PATH` | `qrcode.png` | 二维码保存路径 |
| `STORAGE_STATE_PATH` | `storage_state.json` | 登录会话持久化路径 |

## 📁 项目结构

```
yuanbao-free-api
├── app.py                     # FastAPI 入口（登录守护、生命周期管理）
├── requirements.txt
├── Dockerfile
├── test.py                    # API 测试示例
└── src
    ├── config.py              # 环境变量配置
    ├── const.py               # 模型映射表
    ├── routers/               # 路由：聊天 / 上传 / 模型列表
    ├── schemas/               # Pydantic 数据模型（OpenAI 兼容）
    ├── services/
    │   ├── browser/           # 浏览器管理：扫码登录 / 会话持久化 / 自愈
    │   ├── chat/              # 会话创建 / 聊天补全（流式 + 非流式）
    │   └── upload/            # 文件上传（COS）
    ├── dependencies/          # API Key 鉴权
    └── utils/                 # 流式转换 / 二维码 / 通用工具
```

## 👨‍💻 开发者

- **开发者**：lucky 博士
- **联系方式**：[360859569@qq.com](mailto:360859569@qq.com)

欢迎提交 Issue 反馈问题、Pull Request 贡献代码，也欢迎分享你的集成案例。

## 📜 开源协议

本项目基于 [MIT License](LICENSE) 开源。

## 🙏 致谢

- [Tencent YuanBao](https://yuanbao.tencent.com/) — 提供强大的 AI 能力
- [FastAPI](https://fastapi.tiangolo.com/) — 现代 Python Web 框架
- [Playwright](https://playwright.dev/) — 浏览器自动化
