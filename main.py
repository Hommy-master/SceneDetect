from fastapi import FastAPI
import router
import middlewares
from logger import logger


# 2. 创建FastAPI应用
app = FastAPI(title="SceneDetect API", description="视频场景分割服务")

# 3. 注册路由
app.include_router(router.router, prefix="/openapi", tags=["SceneDetect"])

# 4. 添加中间件
app.add_middleware(middlewares.PrepareMiddleware)
# 注册统一响应处理中间件（注意顺序，应该在其他中间件之后注册）
app.add_middleware(middlewares.ResponseMiddleware)

# 5. 打印所有路由
for r in app.routes:
    # 1. 取 HTTP 方法列表
    methods = getattr(r, "methods", None) or [getattr(r, "method", "WS")]
    # 2. 取路径
    path = r.path
    # 3. 取函数名
    name = r.name
    logger.info("Route: %s %s -> %s", ",".join(sorted(methods)), path, name)

if __name__ == "__main__":
    import uvicorn
    logger.info("Start SceneDetect Service ...")
    uvicorn.run(app, host="0.0.0.0", port=60000, lifespan="on")
    logger.info("SceneDetect Service stopped")
