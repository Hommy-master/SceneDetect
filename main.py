from fastapi import FastAPI
import router
import middlewares
from logger import logger
from fastapi import applications
from fastapi.openapi.docs import get_swagger_ui_html


# 1. 替换Swagger UI的JS和CSS文件为公共CDN链接
def swagger_monkey_patch(*args, **kwargs):
    return get_swagger_ui_html(
        *args, **kwargs,
        # 替换JS和CSS的URL为其他公共CDN链接
        swagger_js_url="https://cdn.staticfile.net/swagger-ui/5.9.0/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.staticfile.net/swagger-ui/5.9.0/swagger-ui.css"
    )

# 猴子补丁，替换默认的Swagger UI HTML生成函数
applications.get_swagger_ui_html = swagger_monkey_patch

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
