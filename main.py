from fastapi import FastAPI
import router
import middlewares
from logger import logger


# 创建FastAPI应用实例
app = FastAPI(title="SceneDetect API", description="视频场景分割服务")

# 注册业务路由
app.include_router(router.router, prefix="/openapi", tags=["SceneDetect"])

# 添加中间件（注意注册顺序：后注册的中间件先执行）
app.add_middleware(middlewares.TraceMiddleware)  # 追踪ID中间件（最先执行）
app.add_middleware(middlewares.PrepareMiddleware)  # 请求准备中间件
app.add_middleware(middlewares.ResponseMiddleware)  # 统一响应处理中间件
app.add_middleware(middlewares.TimeoutMiddleware, timeout_seconds=600)  # 超时处理中间件

# 打印所有已注册的路由信息
for r in app.routes:
    # 获取HTTP方法列表
    methods = getattr(r, "methods", None) or [getattr(r, "method", "WS")]
    # 获取路径
    path = getattr(r, "path", "N/A")
    # 获取处理函数名称
    name = getattr(r, "name", "Unknown")
    logger.info("Registered route: %s %s -> %s", ",".join(sorted(methods)), path, name)

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting SceneDetect service...")
    uvicorn.run(app, host="0.0.0.0", port=60000, lifespan="on")
    logger.info("SceneDetect service stopped")
