# 【简创AIGC】SceneDetect - 视频镜头智能分割服务

把一个视频按照镜头分割成多个视频片段，并返回下载链接。

## ✨ 应用场景介绍
- 添加转场：先根据镜头切割视频，然后再根据不同镜头添加转场
- 打乱镜头顺序：先根据镜头分割视频，然后再随机打乱
- 添加视频蒙版：需要为不同视频镜头添加蒙版

## ✨ 功能特性

- 🎬 **智能场景检测**：自动识别视频中的场景切换点
- ⚡ **高效处理**：基于 FFmpeg 和 PySceneDetect 的高性能处理
- 🔑 **API 密钥认证**：安全的用户认证和积分计费系统
- 📊 **灵活配置**：支持自定义场景检测灵敏度
- 🌐 **RESTful API**：简洁易用的 HTTP 接口
- 🐳 **容器化部署**：支持 Docker 一键部署

## 📋 系统要求

- Python 3.11+
- FFmpeg 6.x+
- PySceneDetect
- 8GB+ RAM（推荐）
- 足够的磁盘空间用于临时文件存储

## 🚀 快速开始

### 1. 环境准备

#### 安装 FFmpeg

访问 [FFmpeg 官网](https://ffmpeg.org/download.html) 下载并安装 FFmpeg 6.x 版本，确保添加到系统环境变量。

验证安装：
```bash
ffmpeg -version
```

#### 安装 PySceneDetect

```bash
pip install scenedetect[opencv]
```

验证安装：
```bash
scenedetect version
```

### 2. 项目安装

```bash
# 克隆项目
git clone git@github.com:Hommy-master/SceneDetect.git
cd SceneDetect

# 安装依赖管理工具
pip install uv

# 安装项目依赖
uv sync
```

### 3. 配置环境

创建 `.env` 文件（可选）：
```bash
# 下载 URL 前缀（用于生成最终下载链接）
DOWNLOAD_URL=https://scene-detect.jcaigc.cn/
```

### 4. 启动服务

```bash
# 开发环境启动
uv run main.py

# 或使用 uvicorn 直接启动
uv run uvicorn main:app --host 0.0.0.0 --port 60000
```

## 🐳 Docker 部署

### 快速部署

```bash
cd SceneDetect
docker-compose pull && docker-compose up -d
```

## 📖 API 文档

### 视频场景分割

**接口地址**：`POST https://scene-detect.jcaigc.cn/openapi/v1/video/scene-split`

**功能说明**：根据视频内容变化自动分割场景，返回切分后的视频片段下载链接。

#### 请求参数

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|----- |
| `apiKey` | string | ✅ | - | 用户 API 密钥 |
| `video_url` | string | ✅ | - | 视频文件 URL 地址 |
| `threshold` | int | ❌ | 27 | 检测敏感度阈值，值越小，越灵敏，取值范围：(0, 255) |

#### 请求示例

```json
{
  "apiKey": "your-api-key", // 用户 apiKey，从官网：https://www.jcaigc.cn/ 获取
  "video_url": "https://t.jcaigc.cn/scenedetect.mp4"
}
```

#### 响应参数

| 参数名 | 类型 | 说明 |
|--------|------|----- |
| `code` | int | 响应状态码，0 表示成功 |
| `message` | string | 响应消息 |
| `data.scene_list` | array | 分割后的视频片段下载链接列表 |

#### 成功响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "scene_list": [
      "https://scene-detect.jcaigc.cn/output/video/20251009021840435c83ac-Scene-001.mp4",
      "https://scene-detect.jcaigc.cn/output/video/20251009021840435c83ac-Scene-002.mp4",
      "https://scene-detect.jcaigc.cn/output/video/20251009021840435c83ac-Scene-003.mp4"
    ]
  }
}
```

#### 错误响应示例

```json
{
  "code": 2005,
  "message": "无效的apiKey"
}
```

### 健康检查

**接口地址**：`GET https://scene-detect.jcaigc.cn/openapi/v1/health`

**功能说明**：检查服务运行状态。

#### 响应示例

```json
{
  "code": 0,
  "message": "VideoDetect Service is running"
}
```

## 💡 使用示例

### Python 示例

```python
import requests

# 发送场景分割请求
response = requests.post(
    f"https://scene-detect.jcaigc.cn/openapi/v1/video/scene-split",
    json={
        "apiKey": "your-api-key", # 用户 apiKey，从官网：https://www.jcaigc.cn/ 获取
        "video_url": "https://assets.jcaigc.cn/test.mp4"
    }
)

if response.status_code == 200:
    result = response.json()
    if result["code"] == 0:
        print(f"分割成功，共生成 {len(result['data']['scene_list'])} 个场景")
        for i, scene_url in enumerate(result["data"]["scene_list"], 1):
            print(f"场景 {i}: {scene_url}")
    else:
        print(f"分割失败：{result['message']}")
else:
    print(f"请求失败：HTTP {response.status_code}")
```

### cURL 示例

```bash
curl -X POST "https://scene-detect.jcaigc.cn/openapi/v1/video/scene-split" \
  -H "Content-Type: application/json" \
  -d '{
    "apiKey": "your-api-key",
    "video_url": "https://assets.jcaigc.cn/test.mp4",
    "threshold": 27
  }'
```

## ⚙️ 配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DOWNLOAD_URL` | `https://assets.jcaigc.cn/` | 下载链接前缀 |

### 计费规则

- 按视频时长计费：**0.01 积分/秒**
- 处理前会验证用户积分余额
- 处理成功后自动扣除相应积分


## 🔧 开发说明

### 项目结构

```
SceneDetect/
├── main.py              # 应用入口
├── router.py            # 路由定义
├── service.py           # 业务逻辑
├── schemas.py           # 数据模型
├── helper.py            # 工具函数
├── config.py            # 配置文件
├── logger.py            # 日志配置
├── middlewares.py       # 中间件
├── exceptions.py        # 异常定义
├── temp/                # 临时文件目录
├── output/              # 输出文件目录
├── docker-compose.yaml  # Docker 配置
├── Dockerfile           # Docker 镜像构建
└── pyproject.toml       # 项目配置
```

### 核心组件

- **FastAPI**：Web 框架
- **PySceneDetect**：场景检测核心
- **FFmpeg**：视频处理工具
- **Uvicorn**：ASGI 服务器

## 🛠️ 故障排除

### 常见问题

1. **FFmpeg 未找到**
   ```bash
   # 检查 FFmpeg 是否正确安装
   ffmpeg -version
   # 检查环境变量配置
   echo $PATH
   ```

2. **PySceneDetect 安装失败**
   ```bash
   # 安装依赖
   pip install opencv-python
   pip install scenedetect[opencv]
   ```

3. **内存不足**
   - 确保系统有足够内存（推荐 8GB+）
   - 调整场景检查灵敏度以减少输出片段数量

4. **API 密钥无效**
   - 检查 API 密钥格式是否正确
   - 确认用户积分余额是否充足

### 日志查看

```bash
# Docker 环境查看日志
docker logs -f scenedetect
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📞 支持

如有问题，请联系：taohongmin51@gmail.com

微信：

  ![微信](./assets/wechat.png)
