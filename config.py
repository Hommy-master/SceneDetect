# 项目常量定义
import os


# 临时目录，用在缓存临时文件
TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp")
VIDEO_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "video")

# 将容器内的文件路径转成一个下载路径，执行替换操作，即将/app/ -> https://assets.jcaigc.cn/
DOWNLOAD_URL = os.getenv("DOWNLOAD_URL", "https://assets.jcaigc.cn/")

# 腾讯云对象存储配置
COS_SECRET_ID = os.getenv("COS_SECRET_ID", "")
COS_SECRET_KEY = os.getenv("COS_SECRET_KEY", "")
COS_BUCKET_NAME = os.getenv("COS_BUCKET_NAME", "")
COS_REGION = os.getenv("COS_REGION", "")