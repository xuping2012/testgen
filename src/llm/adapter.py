#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM适配器层 - 支持多模型接入
支持: OpenAI, Qwen(通义千问), DeepSeek, KIMI, 智谱, Minimax, iFlow, UniAIX
"""

import os
import json
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import requests
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """LLM响应封装"""
    content: str
    usage: Dict[str, int]
    model: str
    success: bool
    error_message: str = ""


class BaseLLMAdapter(ABC):
    """LLM适配器基类"""
    
    def __init__(self, base_url: str, api_key: str, model_id: str, timeout: int = 120):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model_id = model_id
        self.timeout = timeout
    
    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """对话接口"""
        pass
    
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """生成接口"""
        pass


class OpenAIAdapter(BaseLLMAdapter):
    """OpenAI兼容格式适配器"""

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """对话接口 - OpenAI格式，带重试机制"""
        max_retries = kwargs.get('max_retries', 3)
        retry_delay = kwargs.get('retry_delay', 3)
        # 允许动态覆盖timeout
        timeout = kwargs.get('timeout', self.timeout)
        # 是否使用流式响应
        stream = kwargs.get('stream', False)

        for attempt in range(max_retries):
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }

                payload = {
                    "model": self.model_id,
                    "messages": messages,
                    "temperature": kwargs.get("temperature", 0.7),
                    "max_tokens": kwargs.get("max_tokens", 2000),
                    "stream": stream
                }

                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                    stream=stream
                )
                
                if response.status_code != 200:
                    print(f"LLM API错误 (尝试 {attempt+1}/{max_retries}): {response.status_code} - {response.text}")
                    print(f"请求URL: {self.base_url}/chat/completions")
                    print(f"请求模型: {self.model_id}")
                
                response.raise_for_status()

                # 流式处理
                if stream:
                    content = self._process_stream_response(response, timeout)
                    return LLMResponse(
                        content=content,
                        usage={},
                        model=self.model_id,
                        success=True
                    )

                data = response.json()
                
                # 检查响应是否包含choices字段
                if "choices" not in data:
                    error_msg = data.get("error", {}).get("message", str(data)) if isinstance(data.get("error"), dict) else str(data)
                    return LLMResponse(
                        content="",
                        usage={},
                        model=self.model_id,
                        success=False,
                        error_message=f"LLM API返回错误: {error_msg}"
                    )
                
                # 检查choices是否为空
                if not data["choices"] or len(data["choices"]) == 0:
                    return LLMResponse(
                        content="",
                        usage={},
                        model=self.model_id,
                        success=False,
                        error_message="LLM API返回空响应（choices为空）"
                    )
                
                return LLMResponse(
                    content=data["choices"][0]["message"]["content"],
                    usage=data.get("usage", {}),
                    model=self.model_id,
                    success=True
                )
            except requests.exceptions.Timeout as e:
                if attempt < max_retries - 1:
                    print(f"请求超时，{retry_delay}秒后重试 ({attempt+1}/{max_retries})...")
                    time.sleep(retry_delay)
                    continue
                return LLMResponse(
                    content="",
                    usage={},
                    model=self.model_id,
                    success=False,
                    error_message=f"请求超时（已重试{max_retries-1}次，超时={timeout}秒）: {str(e)}"
                )
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"请求失败，{retry_delay}秒后重试 ({attempt+1}/{max_retries}): {str(e)}")
                    time.sleep(retry_delay)
                    continue
                return LLMResponse(
                    content="",
                    usage={},
                    model=self.model_id,
                    success=False,
                    error_message=str(e)
                )
    
    def _process_stream_response(self, response, base_timeout: int = 120, callback=None) -> str:
        """处理流式响应 - 动态超时策略
        
        流式响应的核心优势：
        1. 首字节超时（TTFT）：如果30秒内没有收到任何数据，说明请求可能失败了
        2. 活跃连接超时：只要连接还在传输数据，就继续等待
        3. 总体超时：为了防止无限等待，设置一个最大总体超时时间
        
        Args:
            response: requests.Response对象（stream=True）
            base_timeout: 基础超时时间（秒）
            callback: 可选，每次收到chunk时调用的函数(chunk: str)
            
        Returns:
            str: 完整的响应内容
        """
        import datetime
        
        # 超时配置
        ttft_timeout = 30  # 首字节超时（Time To First Token）
        idle_timeout = 60  # 空闲超时（如果60秒内没有新数据，认为连接已断开）
        max_total_timeout = max(base_timeout * 3, 600)  # 最大总体超时（至少10分钟）
        
        content = []
        last_data_time = datetime.datetime.now()
        first_token_received = False
        start_time = datetime.datetime.now()
        
        try:
            for line in response.iter_lines():
                if not line:
                    continue
                
                # 检查总体超时
                elapsed = (datetime.datetime.now() - start_time).total_seconds()
                if elapsed > max_total_timeout:
                    print(f"[流式响应] 达到最大总体超时({max_total_timeout}秒)，停止接收")
                    break
                
                # 检查空闲超时
                idle_time = (datetime.datetime.now() - last_data_time).total_seconds()
                if idle_time > idle_timeout:
                    print(f"[流式响应] 连接空闲超过{idle_timeout}秒，可能已断开")
                    break
                
                line_str = line.decode('utf-8')
                
                # SSE格式处理
                if line_str.startswith('data: '):
                    data_str = line_str[6:]
                    
                    # 结束标记
                    if data_str.strip() == '[DONE]':
                        break
                    
                    try:
                        data = json.loads(data_str)
                        
                        # 提取内容
                        if 'choices' in data and len(data['choices']) > 0:
                            delta = data['choices'][0].get('delta', {})
                            if 'content' in delta:
                                chunk = delta['content']
                                content.append(chunk)
                                
                                # 调用回调函数
                                if callback:
                                    callback(chunk)
                                
                                # 标记已收到首字节
                                if not first_token_received:
                                    first_token_received = True
                                    ttft = (datetime.datetime.now() - start_time).total_seconds()
                                    print(f"[流式响应] 首字节到达时间: {ttft:.2f}秒")
                                
                                # 更新最后数据接收时间
                                last_data_time = datetime.datetime.now()
                    except json.JSONDecodeError:
                        continue
                
                # 检查首字节超时
                if not first_token_received:
                    elapsed = (datetime.datetime.now() - start_time).total_seconds()
                    if elapsed > ttft_timeout:
                        print(f"[流式响应] 首字节超时({ttft_timeout}秒)")
                        raise requests.exceptions.Timeout(f"首字节超时: {ttft_timeout}秒内未收到任何数据")
            
            full_content = ''.join(content)
            total_time = (datetime.datetime.now() - start_time).total_seconds()
            print(f"[流式响应] 接收完成，总耗时: {total_time:.2f}秒，内容长度: {len(full_content)}字符")
            return full_content
            
        except requests.exceptions.ChunkedEncodingError as e:
            # 连接意外断开
            if content:
                print(f"[流式响应] 连接断开，已接收内容: {len(''.join(content))}字符")
                return ''.join(content)
            raise requests.exceptions.Timeout(f"流式连接断开: {str(e)}")
    
    def chat_stream(self, messages: List[Dict[str, str]], **kwargs):
        """流式对话接口 - 返回生成器
        
        使用此方法可以实现真正的流式响应，逐chunk返回内容。
        
        Yields:
            str: 每次返回的内容片段
        """
        max_retries = kwargs.get('max_retries', 3)
        retry_delay = kwargs.get('retry_delay', 3)
        timeout = kwargs.get('timeout', self.timeout)
        
        for attempt in range(max_retries):
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }

                payload = {
                    "model": self.model_id,
                    "messages": messages,
                    "temperature": kwargs.get("temperature", 0.7),
                    "max_tokens": kwargs.get("max_tokens", 2000),
                    "stream": True
                }

                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                    stream=True
                )
                
                if response.status_code != 200:
                    print(f"LLM API错误 (尝试 {attempt+1}/{max_retries}): {response.status_code} - {response.text}")
                    response.raise_for_status()
                
                # 逐行读取并yield内容
                for line in response.iter_lines():
                    if not line:
                        continue
                    
                    line_str = line.decode('utf-8')
                    
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        
                        if data_str.strip() == '[DONE]':
                            break
                        
                        try:
                            data = json.loads(data_str)
                            
                            if 'choices' in data and len(data['choices']) > 0:
                                delta = data['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    yield delta['content']
                        except json.JSONDecodeError:
                            continue
                
                return  # 成功完成
                
            except requests.exceptions.Timeout as e:
                if attempt < max_retries - 1:
                    print(f"请求超时，{retry_delay}秒后重试 ({attempt+1}/{max_retries})...")
                    time.sleep(retry_delay)
                    continue
                yield f"\n[错误] 请求超时: {str(e)}"
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"请求失败，{retry_delay}秒后重试 ({attempt+1}/{max_retries}): {str(e)}")
                    time.sleep(retry_delay)
                    continue
                yield f"\n[错误] {str(e)}"
                return
    
    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """生成接口 - 转换为chat格式"""
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, **kwargs)


class QwenAdapter(OpenAIAdapter):
    """通义千问适配器 - 兼容OpenAI格式"""

    def __init__(self, api_key: str, model_id: str = "qwen-turbo", timeout: int = 120, base_url: str = ""):
        # 使用用户提供的base_url，如果为空则使用默认值
        url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        super().__init__(
            base_url=url,
            api_key=api_key,
            model_id=model_id,
            timeout=timeout
        )


class DeepSeekAdapter(OpenAIAdapter):
    """DeepSeek适配器 - 兼容OpenAI格式"""

    def __init__(self, api_key: str, model_id: str = "deepseek-chat", timeout: int = 120, base_url: str = ""):
        # 使用用户提供的base_url，如果为空则使用默认值
        url = base_url or "https://api.deepseek.com/v1"
        super().__init__(
            base_url=url,
            api_key=api_key,
            model_id=model_id,
            timeout=timeout
        )


class KimiAdapter(OpenAIAdapter):
    """KIMI(Moonshot)适配器"""

    def __init__(self, api_key: str, model_id: str = "moonshot-v1-8k", timeout: int = 120, base_url: str = ""):
        # 使用用户提供的base_url，如果为空则使用默认值
        url = base_url or "https://api.moonshot.cn/v1"
        super().__init__(
            base_url=url,
            api_key=api_key,
            model_id=model_id,
            timeout=timeout
        )
    
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """KIMI对话接口 - 处理特殊参数要求"""
        max_tokens = kwargs.get("max_tokens", 2000)
        if max_tokens > 4096:
            max_tokens = 4096
        kwargs["max_tokens"] = max_tokens
        
        temperature = kwargs.get("temperature", 0.7)
        if temperature > 1.0:
            temperature = 1.0
        kwargs["temperature"] = temperature
        
        return super().chat(messages, **kwargs)


class ZhipuAdapter(OpenAIAdapter):
    """智谱AI适配器"""

    def __init__(self, api_key: str, model_id: str = "glm-4", timeout: int = 120, base_url: str = ""):
        # 使用用户提供的base_url，如果为空则使用默认值
        url = base_url or "https://open.bigmodel.cn/api/paas/v4"
        super().__init__(
            base_url=url,
            api_key=api_key,
            model_id=model_id,
            timeout=timeout
        )


class MinimaxAdapter(OpenAIAdapter):
    """Minimax适配器"""

    def __init__(self, api_key: str, model_id: str = "abab6.5s-chat", timeout: int = 120, base_url: str = ""):
        # 使用用户提供的base_url，如果为空则使用默认值
        url = base_url or "https://api.minimax.chat/v1"
        super().__init__(
            base_url=url,
            api_key=api_key,
            model_id=model_id,
            timeout=timeout
        )


class IFlowAdapter(OpenAIAdapter):
    """iFlow适配器(26年4月17日停止服务)"""

    def __init__(self, api_key: str, base_url: str = "https://apis.iflow.cn/v1", model_id: str = "qwen3-coder-plus", timeout: int = 120):
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            model_id=model_id,
            timeout=timeout
        )


class UniAIXAdapter(BaseLLMAdapter):
    """UniAIX中转站适配器 - 使用Claude API格式"""

    def __init__(self, api_key: str, model_id: str = "claude-3-5-sonnet-20241022",
                 base_url: str = "https://www.uniaix.com", timeout: int = 120):
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            model_id=model_id,
            timeout=timeout
        )

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """Claude格式对话接口"""
        max_retries = kwargs.get('max_retries', 3)
        retry_delay = kwargs.get('retry_delay', 3)
        # 允许动态覆盖timeout
        timeout = kwargs.get('timeout', self.timeout)
        # 是否使用流式响应
        stream = kwargs.get('stream', False)

        for attempt in range(max_retries):
            try:
                headers = {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                }

                payload = {
                    "model": self.model_id,
                    "messages": messages,
                    "max_tokens": kwargs.get("max_tokens", 2048),
                    "temperature": kwargs.get("temperature", 0.7),
                    "stream": stream
                }

                response = requests.post(
                    f"{self.base_url}/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                    stream=stream
                )

                if response.status_code != 200:
                    print(f"UniAIX API错误 (尝试 {attempt+1}/{max_retries}): {response.status_code} - {response.text}")

                response.raise_for_status()

                # 流式处理
                if stream:
                    content = self._process_stream_response(response, timeout)
                    return LLMResponse(
                        content=content,
                        usage={},
                        model=self.model_id,
                        success=True
                    )

                data = response.json()
                content = ""
                if "content" in data and len(data["content"]) > 0:
                    content = data["content"][0].get("text", "")

                return LLMResponse(
                    content=content,
                    usage=data.get("usage", {}),
                    model=self.model_id,
                    success=True
                )
            except requests.exceptions.Timeout as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return LLMResponse(
                    content="",
                    usage={},
                    model=self.model_id,
                    success=False,
                    error_message=f"请求超时（已重试{max_retries}次）: {str(e)}"
                )
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return LLMResponse(
                    content="",
                    usage={},
                    model=self.model_id,
                    success=False,
                    error_message=str(e)
                )

    def _process_stream_response(self, response, base_timeout: int = 120) -> str:
        """处理流式响应 - 动态超时策略"""
        import datetime
        
        # 超时配置
        ttft_timeout = 30
        idle_timeout = 60
        max_total_timeout = max(base_timeout * 3, 600)
        
        content = []
        last_data_time = datetime.datetime.now()
        first_token_received = False
        start_time = datetime.datetime.now()
        
        try:
            for line in response.iter_lines():
                if not line:
                    continue
                
                # 检查总体超时
                elapsed = (datetime.datetime.now() - start_time).total_seconds()
                if elapsed > max_total_timeout:
                    print(f"[UniAIX流式响应] 达到最大总体超时({max_total_timeout}秒)，停止接收")
                    break
                
                # 检查空闲超时
                idle_time = (datetime.datetime.now() - last_data_time).total_seconds()
                if idle_time > idle_timeout:
                    print(f"[UniAIX流式响应] 连接空闲超过{idle_timeout}秒，可能已断开")
                    break
                
                line_str = line.decode('utf-8')
                
                # SSE格式处理
                if line_str.startswith('data: '):
                    data_str = line_str[6:]
                    
                    if data_str.strip() == '[DONE]':
                        break
                    
                    try:
                        data = json.loads(data_str)
                        
                        # Claude格式
                        if 'delta' in data:
                            delta = data['delta']
                            if 'text' in delta:
                                chunk = delta['text']
                                content.append(chunk)
                                
                                if not first_token_received:
                                    first_token_received = True
                                    ttft = (datetime.datetime.now() - start_time).total_seconds()
                                    print(f"[UniAIX流式响应] 首字节到达时间: {ttft:.2f}秒")
                                
                                last_data_time = datetime.datetime.now()
                    except json.JSONDecodeError:
                        continue
                
                # 检查首字节超时
                if not first_token_received:
                    elapsed = (datetime.datetime.now() - start_time).total_seconds()
                    if elapsed > ttft_timeout:
                        print(f"[UniAIX流式响应] 首字节超时({ttft_timeout}秒)")
                        raise requests.exceptions.Timeout(f"首字节超时: {ttft_timeout}秒内未收到任何数据")
            
            full_content = ''.join(content)
            total_time = (datetime.datetime.now() - start_time).total_seconds()
            print(f"[UniAIX流式响应] 接收完成，总耗时: {total_time:.2f}秒，内容长度: {len(full_content)}字符")
            return full_content
            
        except requests.exceptions.ChunkedEncodingError as e:
            if content:
                print(f"[UniAIX流式响应] 连接断开，已接收内容: {len(''.join(content))}字符")
                return ''.join(content)
            raise requests.exceptions.Timeout(f"流式连接断开: {str(e)}")

    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """生成接口"""
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, **kwargs)


class LLMManager:
    """LLM管理器 - 支持多配置管理"""

    # 支持的提供商列表
    SUPPORTED_PROVIDERS = {
        "openai": {"name": "OpenAI", "default_base_url": "https://api.openai.com/v1", "need_base_url": False},
        "qwen": {"name": "通义千问", "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "need_base_url": False},
        "deepseek": {"name": "DeepSeek", "default_base_url": "https://api.deepseek.com/v1", "need_base_url": False},
        "kimi": {"name": "KIMI", "default_base_url": "https://api.moonshot.cn/v1", "need_base_url": False},
        "zhipu": {"name": "智谱AI", "default_base_url": "https://open.bigmodel.cn/api/paas/v4", "need_base_url": False},
        "minimax": {"name": "Minimax", "default_base_url": "https://api.minimax.chat/v1", "need_base_url": False},
        "iflow": {"name": "iFlow", "default_base_url": "https://apis.iflow.cn/v1", "need_base_url": False},
        "uniaix": {"name": "UniAIX中转", "default_base_url": "https://www.uniaix.com", "need_base_url": False},
    }

    def __init__(self):
        self.adapters: Dict[str, BaseLLMAdapter] = {}
        self.default_adapter: Optional[str] = None
        self.config_infos: Dict[str, Dict[str, Any]] = {}

    def add_config(self, name: str, provider: str, api_key: str, model_id: str, 
                   base_url: str = "", timeout: int = 120, is_default: bool = False):
        """添加LLM配置"""
        provider = provider.lower()
        
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ValueError(f"不支持的LLM提供商: {provider}，支持的: {list(self.SUPPORTED_PROVIDERS.keys())}")

        provider_info = self.SUPPORTED_PROVIDERS[provider]
        url = base_url or provider_info["default_base_url"]
        
        if provider == "openai":
            adapter = OpenAIAdapter(url, api_key, model_id, timeout)
        elif provider == "qwen":
            adapter = QwenAdapter(api_key, model_id, timeout, base_url=url)
        elif provider == "deepseek":
            adapter = DeepSeekAdapter(api_key, model_id, timeout, base_url=url)
        elif provider == "kimi":
            adapter = KimiAdapter(api_key, model_id, timeout, base_url=url)
        elif provider == "zhipu":
            adapter = ZhipuAdapter(api_key, model_id, timeout, base_url=url)
        elif provider == "minimax":
            adapter = MinimaxAdapter(api_key, model_id, timeout, base_url=url)
        elif provider == "iflow":
            adapter = IFlowAdapter(api_key, url, model_id, timeout)
        elif provider == "uniaix":
            adapter = UniAIXAdapter(api_key, model_id, url, timeout)
        else:
            raise ValueError(f"不支持的提供商: {provider}")
        
        self.adapters[name] = adapter
        self.config_infos[name] = {
            "provider": provider,
            "model_id": model_id,
            "base_url": url
        }
        
        # 只在明确指定为默认，或还没有默认配置时才设置
        if is_default:
            self.default_adapter = name
        elif not self.default_adapter:
            # 如果还没有默认配置，将第一个添加的配置作为临时默认
            self.default_adapter = name
            print(f"  [警告] 未指定默认配置，将 '{name}' 设为临时默认")

    def set_default_config(self, name: str):
        """设置默认配置"""
        if name not in self.adapters:
            raise ValueError(f"配置不存在: {name}")
        self.default_adapter = name

    def get_adapter(self, name: Optional[str] = None) -> BaseLLMAdapter:
        """获取适配器"""
        adapter_name = name or self.default_adapter
        if not adapter_name:
            raise ValueError("未配置默认LLM，请先在AI配置中添加模型")
        if adapter_name not in self.adapters:
            raise ValueError(f"适配器不存在: {adapter_name}")
        return self.adapters[adapter_name]

    def delete_config(self, name: str):
        """删除配置"""
        if name not in self.adapters:
            raise ValueError(f"配置不存在: {name}")
        del self.adapters[name]
        del self.config_infos[name]
        if self.default_adapter == name:
            # 如果删除的是默认配置，选择第一个可用的作为默认
            self.default_adapter = next(iter(self.adapters)) if self.adapters else None

    def list_configs(self) -> Dict[str, Dict[str, Any]]:
        """获取所有配置名称"""
        return list(self.adapters.keys())

    def get_config_info(self, name: Optional[str] = None) -> Dict[str, Any]:
        """获取配置信息"""
        config_name = name or self.default_adapter
        if not config_name:
            return {}
        info = self.config_infos.get(config_name, {}).copy()
        info["name"] = config_name
        info["is_default"] = (config_name == self.default_adapter)
        return info

    def has_adapter(self, name: Optional[str] = None) -> bool:
        """检查是否存在适配器"""
        check_name = name or self.default_adapter
        return check_name in self.adapters

    @classmethod
    def get_supported_providers(cls) -> List[Dict[str, Any]]:
        """获取支持的提供商列表"""
        return [
            {"id": k, "name": v["name"], "need_base_url": v["need_base_url"]}
            for k, v in cls.SUPPORTED_PROVIDERS.items()
        ]
