"""统一的 LLM 调用接口。

支持两类 SDK：
    openai_compatible : DeepSeek / 智谱 GLM / 火山方舟 / OpenAI（都是 OpenAI 兼容协议）
    anthropic         : Claude（system prompt 是独立参数）

要点：
    - 密钥只从环境变量读取，绝不落盘、绝不写进日志。
    - 重试只针对网络错误、限流与 5xx；4xx（除 429）直接失败，避免把请求错误当网络抖动。
    - 返回结构统一为 LLMResponse，采集脚本不需要关心是哪家厂商。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from .config import get_env, load_env, require_env

# 需要重试的 HTTP 状态码
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}
RETRYABLE_EXCEPTION_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "InternalServerError",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "RemoteProtocolError",
    "TimeoutException",
}

# 允许透传给 OpenAI 兼容接口的采样参数
_OPENAI_PASSTHROUGH_KEYS = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "n",
    "presence_penalty",
    "frequency_penalty",
    "stop",
    "seed",
    "logprobs",
    "top_logprobs",
)


@dataclass
class LLMResponse:
    text: str
    reasoning_content: str | None = None
    model_returned: str | None = None
    response_id: str | None = None
    system_fingerprint: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    created: int | None = None
    attempts: int = 1
    endpoint_host: str | None = None


class LLMCallError(RuntimeError):
    """所有重试都失败后的统一异常，便于采集脚本分类记录。"""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        status_code: int | None = None,
        retryable: bool = False,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code
        self.retryable = retryable
        self.attempts = attempts


# --- 端点解析 ---------------------------------------------------------------


def resolve_endpoint(model_config: Mapping[str, Any]) -> tuple[str | None, str]:
    """返回 (base_url, api_key)。api_key 只在此处读取，不进入任何日志。"""
    load_env()
    base_url_env = model_config.get("base_url_env")
    base_url = get_env(str(base_url_env)) if base_url_env else None
    if not base_url:
        base_url = model_config.get("base_url_default")
    if model_config.get("sdk") == "anthropic":
        base_url = model_config.get("base_url_default") or base_url
    api_key_env = model_config.get("api_key_env")
    if not api_key_env:
        raise RuntimeError("模型配置缺少 api_key_env")
    return base_url, require_env(str(api_key_env))


def _endpoint_host(base_url: str | None) -> str | None:
    if not base_url:
        return None
    return base_url.split("//")[-1].split("/")[0]


def request_model_name(model_key: str, model_config: Mapping[str, Any]) -> str:
    """实际发给服务端的 model 名（火山方舟等需要传 endpoint id）。"""
    return str(model_config.get("model_name_override") or model_key)


# --- 重试判定 ---------------------------------------------------------------


def _status_code_of(exc: BaseException) -> int | None:
    for attribute in ("status_code", "http_status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _is_retryable(exc: BaseException) -> bool:
    if type(exc).__name__ in RETRYABLE_EXCEPTION_NAMES:
        return True
    status = _status_code_of(exc)
    if status is not None:
        return status in RETRYABLE_STATUS
    # httpx / socket 层错误
    return isinstance(exc, (ConnectionError, TimeoutError))


# --- 具体调用 ---------------------------------------------------------------


def _chat_openai_compatible(
    model_key: str,
    model_config: Mapping[str, Any],
    api_config: Mapping[str, Any],
    system_prompt: str,
    user_prompt: str,
) -> LLMResponse:
    from openai import OpenAI

    base_url, api_key = resolve_endpoint(model_config)
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=float(api_config.get("timeout_s", 180)),
        max_retries=0,  # 重试由本模块统一控制，避免两层重试叠加
    )

    params = dict(model_config.get("params") or {})
    payload: dict[str, Any] = {
        "model": request_model_name(model_key, model_config),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    for key in _OPENAI_PASSTHROUGH_KEYS:
        if key in params and params[key] is not None:
            payload[key] = params[key]

    response = client.chat.completions.create(**payload)
    if not response.choices:
        raise LLMCallError(
            "服务端返回空 choices", error_type="empty_choices", retryable=True
        )
    choice = response.choices[0]
    message = choice.message
    usage: dict[str, Any] = {}
    if getattr(response, "usage", None) is not None:
        try:
            usage = response.usage.model_dump()
        except AttributeError:
            usage = dict(response.usage)  # type: ignore[arg-type]

    return LLMResponse(
        text=(message.content or "").strip(),
        # 思维链字段仅在开启 reasoner 时可能出现；本轮不使用思维链（Q13），
        # 但仍保留该列，避免将来启用时数据格式不一致。
        reasoning_content=getattr(message, "reasoning_content", None),
        model_returned=getattr(response, "model", None),
        response_id=getattr(response, "id", None),
        system_fingerprint=getattr(response, "system_fingerprint", None),
        finish_reason=getattr(choice, "finish_reason", None),
        usage=usage,
        created=getattr(response, "created", None),
        endpoint_host=_endpoint_host(base_url),
    )


def _chat_anthropic(
    model_key: str,
    model_config: Mapping[str, Any],
    api_config: Mapping[str, Any],
    system_prompt: str,
    user_prompt: str,
) -> LLMResponse:
    import anthropic

    base_url, api_key = resolve_endpoint(model_config)
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": float(api_config.get("timeout_s", 180)),
        "max_retries": 0,
    }
    if base_url:
        kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**kwargs)

    params = dict(model_config.get("params") or {})
    request_kwargs: dict[str, Any] = {
        "model": request_model_name(model_key, model_config),
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        "max_tokens": int(params.pop("max_tokens", 512)),
    }
    for key in ("temperature", "top_p", "stop_sequences"):
        if key in params and params[key] is not None:
            request_kwargs[key] = params[key]

    response = client.messages.create(**request_kwargs)
    blocks = getattr(response, "content", []) or []
    text = "".join(
        getattr(block, "text", "") for block in blocks if getattr(block, "type", "") == "text"
    )
    usage = {}
    if getattr(response, "usage", None) is not None:
        try:
            usage = response.usage.model_dump()
        except AttributeError:
            usage = dict(response.usage)  # type: ignore[arg-type]

    return LLMResponse(
        text=text.strip(),
        model_returned=getattr(response, "model", None),
        response_id=getattr(response, "id", None),
        finish_reason=getattr(response, "stop_reason", None),
        usage=usage,
        endpoint_host=_endpoint_host(base_url),
    )


# --- 对外接口 ---------------------------------------------------------------


def chat(
    model_key: str,
    model_config: Mapping[str, Any],
    api_config: Mapping[str, Any],
    system_prompt: str,
    user_prompt: str,
) -> LLMResponse:
    """调用一次模型，带指数退避重试。全部失败时抛 LLMCallError。"""
    sdk = str(model_config.get("sdk", "openai_compatible"))
    max_retries = int(api_config.get("max_retries", 5))
    base_delay = float(api_config.get("retry_backoff_base_s", 2.0))
    max_delay = float(api_config.get("retry_backoff_max_s", 60.0))

    attempts = 0
    delay = base_delay
    last_error: BaseException | None = None
    while attempts < max(1, max_retries):
        attempts += 1
        try:
            if sdk == "anthropic":
                response = _chat_anthropic(
                    model_key, model_config, api_config, system_prompt, user_prompt
                )
            elif sdk == "openai_compatible":
                response = _chat_openai_compatible(
                    model_key, model_config, api_config, system_prompt, user_prompt
                )
            else:
                raise ValueError(f"不支持的 sdk：{sdk}")
            response.attempts = attempts
            return response
        except LLMCallError:
            raise
        except Exception as exc:  # noqa: BLE001 - 需要把所有厂商异常统一分类
            last_error = exc
            retryable = _is_retryable(exc)
            if not retryable or attempts >= max_retries:
                raise LLMCallError(
                    f"{type(exc).__name__}: {exc}",
                    error_type=type(exc).__name__,
                    status_code=_status_code_of(exc),
                    retryable=retryable,
                    attempts=attempts,
                ) from exc
            # 抖动避免多个进程同时重试
            time.sleep(min(delay, max_delay) * (0.5 + random.random()))
            delay = min(delay * 2, max_delay)

    raise LLMCallError(
        f"重试 {attempts} 次后仍失败：{last_error}",
        error_type="retries_exhausted",
        retryable=True,
        attempts=attempts,
    )


def usage_field(usage: Mapping[str, Any], *names: str) -> int | None:
    """从不同厂商的 usage 结构里取同一含义的字段。"""
    for name in names:
        value = usage.get(name)
        if isinstance(value, int):
            return value
    # DeepSeek 把缓存命中放在 prompt_cache_hit_tokens / prompt_tokens_details.cached_tokens
    details = usage.get("prompt_tokens_details")
    if isinstance(details, Mapping):
        for name in names:
            value = details.get(name)
            if isinstance(value, int):
                return value
    return None
