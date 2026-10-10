"""Small OpenAI-compatible adapter. Never log requests, keys or provider bodies."""
import json
import socket
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from flask import current_app
from app.errors import ApiError


def validate_base_url(value):
    if not isinstance(value,str) or len(value)>1000:
        raise ApiError(400,'VALIDATION_ERROR','Base URL 无效。')
    parsed=urlsplit(value)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ApiError(400,'VALIDATION_ERROR','Base URL 需为不含凭据或查询参数的 HTTP(S) 地址。')
    return value.rstrip('/')


class CompatibleProvider:
    provider='openai_compatible'
    def __init__(self,config):
        if not config.get('LLM_BASE_URL') or not config.get('LLM_API_KEY') or not config.get('LLM_MODEL'):
            raise ApiError(503,'LLM_NOT_CONFIGURED','请先在模型设置中配置 Provider，或设置本机环境变量。')
        self.base=validate_base_url(config.get('LLM_BASE_URL',''))
        self.key=config.get('LLM_API_KEY','')
        self.model=config.get('LLM_MODEL','')
        self.timeout=float(config.get('LLM_TIMEOUT_SECONDS',60))
        if not self.key or not self.model:
            raise ApiError(503,'LLM_NOT_CONFIGURED','请先在模型设置中配置 Provider，或设置本机环境变量。')

    def complete(self,messages):
        body=json.dumps({'model':self.model,'messages':messages,'max_tokens':2200,'stream':False}).encode()
        req=urllib.request.Request(self.base+'/chat/completions',data=body,
            headers={'Content-Type':'application/json','Authorization':'Bearer '+self.key})
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as response:
                raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise ValueError('Response too large')
            data=json.loads(raw);result=data['choices'][0]['message']['content']
            if not isinstance(result,str) or not result.strip() or len(result)>50000:raise ValueError('Invalid content')
            return result
        except urllib.error.HTTPError as error:
            if error.code in {401,403}:message='Provider 认证失败，请检查 API Key。'
            elif error.code in {400,404,422}:message='模型或 Chat Completions 接口不兼容，请检查设置。'
            elif error.code==429:message='Provider 请求达到限制，请稍后重试。'
            else:message='Provider 暂时无法完成请求，请稍后重试。'
            raise ApiError(502,'LLM_PROVIDER_ERROR',message) from None
        except (TimeoutError,socket.timeout):raise ApiError(504,'LLM_TIMEOUT','模型请求超时，输入已保留，可重试。') from None
        except urllib.error.URLError:raise ApiError(502,'LLM_CONNECTION_ERROR','无法连接 Provider，请检查服务和网络。') from None
        except (ValueError,KeyError,IndexError,TypeError):raise ApiError(502,'LLM_RESPONSE_INVALID','Provider 未返回可用的 Chat Completions 文本。') from None


def provider():
    factory=current_app.config.get('LLM_PROVIDER_FACTORY')
    return factory(current_app.config) if factory else CompatibleProvider(current_app.config)


def public_config():
    config=current_app.config
    return {'base_url':config.get('LLM_BASE_URL',''),'model':config.get('LLM_MODEL',''),
        'has_api_key':bool(config.get('LLM_API_KEY')),
        'configured':bool(config.get('LLM_PROVIDER_FACTORY') or config.get('LLM_BASE_URL') and config.get('LLM_API_KEY') and config.get('LLM_MODEL')),
        'configuration_scope':'environment_or_current_process'}
