from flask import Blueprint,jsonify,request,current_app
from app.db import get_session
from app.errors import ApiError
from app.services import assistant as service
from app.services.llm_provider import provider,validate_base_url
from app.services.provider_settings import public_provider_settings,save_provider_settings

blueprint=Blueprint('assistant_v1',__name__,url_prefix='/api/v1')


@blueprint.get('/llm/config')
def config():return jsonify(public_provider_settings(current_app._get_current_object()))


@blueprint.patch('/llm/config')
def update_config():
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict) or not payload or set(payload)-{'base_url','model','api_key','clear_api_key'}:
        raise ApiError(400,'VALIDATION_ERROR','模型配置字段无效。')
    normalized={}
    if 'base_url' in payload:normalized['base_url']=validate_base_url(payload['base_url'])
    if 'model' in payload:
        model=payload['model']
        if not isinstance(model,str) or not model.strip() or len(model)>120:
            raise ApiError(400,'VALIDATION_ERROR','请填写有效模型名称。')
        normalized['model']=model.strip()
    if 'api_key' in payload:
        key=payload['api_key']
        if not isinstance(key,str) or not key.strip() or len(key)>2000:
            raise ApiError(400,'VALIDATION_ERROR','API Key 无效，留空时应省略字段以保留当前凭据。')
        normalized['api_key']=key.strip()
    if 'clear_api_key' in payload and type(payload['clear_api_key']) is not bool:
        raise ApiError(400,'VALIDATION_ERROR','清除密钥选项必须为布尔值。')
    if 'clear_api_key' in payload:normalized['clear_api_key']=payload['clear_api_key']
    try:
        return jsonify(save_provider_settings(current_app._get_current_object(),normalized))
    except ValueError as error:
        raise ApiError(409,'LLM_SETTING_ENV_OVERRIDE',str(error)) from error


@blueprint.post('/llm/test')
def test_connection():
    adapter=provider();reply=adapter.complete([{'role':'user','content':'Reply only OK.'}])
    return jsonify({'connected':True,'provider':adapter.provider,'model':adapter.model,'has_response':bool(reply)})


@blueprint.post('/assistant/context-preview')
def context_preview():return jsonify(service.context_preview(get_session(),request.get_json(silent=True)))


@blueprint.post('/assistant/polish')
def polish():return jsonify(service.generate(get_session(),request.get_json(silent=True),'polish'))


@blueprint.post('/assistant/reference-answer')
def reference():return jsonify(service.generate(get_session(),request.get_json(silent=True),'reference_answer'))


@blueprint.post('/assistant/analyze')
def analyze():return jsonify(service.generate(get_session(),request.get_json(silent=True),'analyze'))


@blueprint.post('/assistant/previews/<string:key>/save')
def save(key):return jsonify(service.save_preview(get_session(),key,request.get_json(silent=True))),201


@blueprint.get('/questions/<int:question_id>/assistant-outputs')
def outputs(question_id):return jsonify(service.list_outputs(get_session(),question_id))


@blueprint.post('/assistant-outputs/<int:output_id>/saved-answer')
def output_answer(output_id):
    return jsonify(service.save_output_answer(get_session(),output_id,request.get_json(silent=True))),201
