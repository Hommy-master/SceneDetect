# 1. 简介
根据视频镜头切分视频

# 2. 运行方法
## 2.1 安装依赖
```bash
# 安装uv
pip install uv

# 安装ffmpeg，安装完成后，将ffmpeg添加到环境变量中，建议使用6.x版本
https://ffmpeg.org/download.html

# 安装依赖
uv sync
```

## 2.2 运行服务
```bash
uv run main.py
```

# 3. 部署（Linux）
```bash
cd SceneDetect
docker-compose pull && docker-compose up -d
```

# 4. 接口
## 4.1 视频场景分割
- **URL**: `/openapi/v1/video/scene-split`
- **方法**: `POST`
- **请求参数**:
  - `video_url` (string, required): 视频文件URL
  - `min_scene_length` (float, optional, default=2): 最小切分长度，单位：秒
- **响应参数**:
  - `scene_list` (list of string): 视频切分列表，每个元素为场景的URL
- **请求示例**:
  ```json
  {
    "video_url": "https://t.jcaigc.cn/test1.mp4",
    "min_scene_length": 2
  }
  ```

- **响应示例**:
  ```json
  {
    "code": 0,
    "msg": "success",
    "scene_list": [
      "https://assets.jcaigc.cn/video/scene/2023082416928838880.mp4",
      "https://assets.jcaigc.cn/video/scene/2023082416928838881.mp4"
    ]
  }
  ```
