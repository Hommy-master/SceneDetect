from fastapi import Request
from fastapi.responses import JSONResponse
from exceptions import CustomError, CustomException
from starlette.middleware.base import BaseHTTPMiddleware
from logger import logger
import json
import os
import config
import asyncio


class PrepareMiddleware(BaseHTTPMiddleware):
    """请求前的准备工作中间件
    功能：
    1. 创建临时目录
    2. 创建输出目录
    """

    async def dispatch(self, request: Request, call_next):
        # 递归创建目录，如果目录存在，就直接跳过创建
        os.makedirs(config.TEMP_DIR, exist_ok=True)
        os.makedirs(config.VIDEO_OUTPUT_DIR, exist_ok=True)

        # 继续处理请求
        response = await call_next(request)
        return response


class ResponseMiddleware(BaseHTTPMiddleware):
    """
    统一响应处理中间件
    功能：
    1. 统一处理业务正常响应，添加code和message字段
    2. 统一处理异常，返回标准错误格式
    """

    async def dispatch(self, request: Request, call_next):
        """
        中间件核心分发逻辑：统一处理请求响应和异常
        """
        # 获取用户语言偏好
        lang = self._get_language_from_request(request)
        
        try:
            # 执行请求处理
            response = await call_next(request)

            # 处理非200状态码的响应
            if response.status_code != 200:
                return await self._handle_non_200_response(response, lang)
                
            # 处理JSON响应
            if self._is_json_response(response):
                return await self._process_json_response(response, lang)
                
            return response
            
        except CustomException as e:
            return self._handle_custom_exception(e, lang)
        except Exception as e:
            return self._handle_generic_exception(e, lang)

    def _get_language_from_request(self, request: Request) -> str:
        """
        从请求头获取语言偏好，默认为中文
        
        Args:
            request: FastAPI请求对象
            
        Returns:
            str: 语言代码 ('zh' 或 'en')
        """
        accept_language = request.headers.get('Accept-Language', 'zh')
        lang = accept_language.split(',')[0].split('-')[0]
        return lang if lang in ['zh', 'en'] else 'zh'
    
    def _handle_422_error(self, body_str: str, lang: str) -> JSONResponse:
        """
        特殊处理422参数验证错误，提取详细的验证信息
        
        Args:
            body_str: 响应体字符串
            lang: 语言代码
            
        Returns:
            JSONResponse: 统一格式的错误响应
        """
        try:
            # 解析422错误的响应体
            error_data = json.loads(body_str)
            
            # 提取并格式化验证错误信息
            validation_messages = self._extract_validation_messages(error_data)

            # 构建统一的422错误响应
            error_message = "; ".join(validation_messages) if validation_messages else ""
            error_response = CustomError.PARAM_VALIDATION_FAILED.as_dict(detail=error_message, lang=lang)
            return JSONResponse(status_code=200, content=error_response)
            
        except json.JSONDecodeError:
            logger.warning(f"无法解析422响应体: {body_str}")
            
            error_response = CustomError.PARAM_VALIDATION_FAILED.as_dict(detail=body_str, lang=lang)
            return JSONResponse(status_code=200, content=error_response)
    
    def _extract_validation_messages(self, error_data: dict) -> list:
        """
        从验证错误数据中提取详细错误信息
        
        Args:
            error_data: 错误数据字典
            
        Returns:
            list: 格式化后的错误信息列表
        """
        validation_messages = []
        
        if "detail" in error_data:
            for error in error_data["detail"]:
                if "loc" in error and "msg" in error:
                    # 格式化错误信息为可读格式
                    field = ".".join(str(part) for part in error["loc"] if part != "body")
                    message = f"{field}: {error['msg']}"
                    validation_messages.append(message)
                    
        return validation_messages

    async def _handle_non_200_response(self, response, lang: str) -> JSONResponse:
        """
        处理非200状态码的响应，统一转换为标准错误格式
        
        Args:
            response: HTTP响应对象
            lang: 语言代码
            
        Returns:
            JSONResponse: 统一格式的错误响应
        """
        # 读取响应体内容
        body = await self._read_response_body(response)
        body_str = body.decode()

        # 特殊处理422参数验证错误
        if response.status_code == 422:
            return self._handle_422_error(body_str, lang)
        
        # 其他非200错误处理（不应该发生，每个错误都应该在前面被处理）
        logger.error(f"意外的非200响应: {response.status_code} - {body_str}")
        
        error_response = {
            "code": response.status_code,
            "message": f"HTTP Error {response.status_code}",
            "data": {"detail": body_str}
        }
        
        return JSONResponse(status_code=200, content=error_response)
    
    async def _read_response_body(self, response) -> bytes:
        """
        安全地读取响应体内容
        
        Args:
            response: HTTP响应对象
            
        Returns:
            bytes: 响应体字节数据
        """
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        return body

    def _is_json_response(self, response) -> bool:
        """
        检查是否为JSON响应，用于决定是否需要统一格式化
        
        Args:
            response: HTTP响应对象
            
        Returns:
            bool: 是否为JSON响应
        """
        return response.headers.get('content-type') == 'application/json'

    async def _process_json_response(self, response, lang: str):
        """
        处理JSON响应并统一格式，添加成功状态的code和message字段
        
        Args:
            response: HTTP响应对象
            lang: 语言代码
            
        Returns:
            JSONResponse: 统一格式的成功响应
        """
        # 读取响应体
        body = [section async for section in response.body_iterator]
        if not body:
            return response
            
        body_str = b''.join(body).decode()
        
        try:
            data = json.loads(body_str)
            
            # 如果响应已经有统一格式，重新构建响应
            if 'code' in data and 'message' in data:
                return JSONResponse(
                    status_code=response.status_code,
                    content=data
                )
                
            # 创建统一格式的成功响应
            unified_response = {
                'code': CustomError.SUCCESS.code,
                'message': CustomError.SUCCESS.as_dict(lang=lang)['message'],
                'data': data
            }
            
            return JSONResponse(
                status_code=response.status_code,
                content=unified_response
            )
            
        except json.JSONDecodeError:
            logger.warning(f"JSON解析失败: {body_str}")
            return response

    def _handle_custom_exception(self, e: CustomException, lang: str) -> JSONResponse:
        """
        处理自定义业务异常，返回标准错误格式
        
        Args:
            e: 自定义异常对象
            lang: 语言代码
            
        Returns:
            JSONResponse: 统一格式的错误响应
        """
        logger.warning(f"业务异常: {e.err.code} - {e.err.cn_message}" + 
                    (f" ({e.detail})" if e.detail else ""))
        
        # 获取错误信息并返回统一响应
        error_response = e.err.as_dict(detail=e.detail, lang=lang)
        return JSONResponse(status_code=200, content=error_response)

    def _handle_generic_exception(self, e: Exception, lang: str) -> JSONResponse:
        """
        处理通用异常，统一包装为内部服务器错误
        
        Args:
            e: 异常对象
            lang: 语言代码
            
        Returns:
            JSONResponse: 统一格式的错误响应
        """
        logger.warning(f"内部服务器错误: {str(e)}")
        
        # 获取错误信息并返回统一响应
        error_response = CustomError.INTERNAL_SERVER_ERROR.as_dict(detail=str(e), lang=lang)
        return JSONResponse(status_code=200, content=error_response)


class TimeoutMiddleware(BaseHTTPMiddleware):
    """超时中间件
    功能：
    1. 设置请求超时时间，默认600秒
    2. 当请求超时时，主动取消任务并返回超时错误
    """

    def __init__(self, app, timeout_seconds: int = 600):
        super().__init__(app)
        self.timeout_seconds = timeout_seconds

    async def dispatch(self, request: Request, call_next):
        try:
            # 使用 asyncio.wait_for 来设置超时
            response = await asyncio.wait_for(
                call_next(request), 
                timeout=self.timeout_seconds
            )
            return response
            
        except asyncio.TimeoutError:
            # 获取客户端语言偏好
            lang = self._get_language_from_request(request)
            
            logger.warning(f"Request timeout after {self.timeout_seconds} seconds: {request.url}")
            
            # 返回超时错误响应
            error_response = {
                "code": 408,
                "message": "请求超时" if lang == "zh" else "Request timeout",
                "detail": f"请求在 {self.timeout_seconds} 秒内未完成" if lang == "zh" else f"Request did not complete within {self.timeout_seconds} seconds"
            }
            
            return JSONResponse(status_code=200, content=error_response)
            
        except Exception as e:
            # 处理其他异常
            lang = self._get_language_from_request(request)
            logger.error(f"Unexpected error in timeout middleware: {str(e)}")
            
            error_response = CustomError.INTERNAL_SERVER_ERROR.as_dict(detail=str(e), lang=lang)
            return JSONResponse(status_code=200, content=error_response)

    def _get_language_from_request(self, request: Request) -> str:
        """从请求头获取语言偏好"""
        lang = request.headers.get('Accept-Language', 'zh').split(',')[0].split('-')[0]
        return lang if lang in ['zh', 'en'] else 'zh'