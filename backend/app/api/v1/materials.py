import json
from flask import Blueprint,jsonify,request,send_file
from sqlalchemy import select,func,delete
from app.db import get_session
from app.errors import ApiError
from app.models.material import Project,Material,MaterialVersion,MaterialChunk
from app.models.assistant import AssistantOutputSource
from app.services import materials as service
from app.services.material_files import parse_upload,resolve_material_file
from app.services.material_search import selected_versions,retrieve
from app.services.question_relations import _begin_write

blueprint=Blueprint('materials_v1',__name__,url_prefix='/api/v1')


def include_archived():
    return request.args.get('include_archived') in {'1','true'}


@blueprint.get('/projects')
def projects():
    s=get_session();query=select(Project).order_by(Project.updated_at.desc(),Project.id)
    if not include_archived():query=query.where(Project.archived_at.is_(None))
    return jsonify([service.project_json(s,p) for p in s.scalars(query)])


@blueprint.post('/projects')
def create_project():
    s=get_session();row=service.save_project(s,request.get_json(silent=True))
    return jsonify(service.project_json(s,row)),201


@blueprint.get('/projects/<int:project_id>')
def project(project_id):
    s=get_session();return jsonify(service.project_json(s,service.required(s,Project,project_id)))


@blueprint.patch('/projects/<int:project_id>')
def update_project(project_id):
    s=get_session();row=service.save_project(s,request.get_json(silent=True),project_id)
    return jsonify(service.project_json(s,row))


@blueprint.post('/projects/<int:project_id>/archive')
def archive_project(project_id):
    s=get_session();return jsonify(service.project_json(s,service.archive_project(s,project_id)))


@blueprint.get('/projects/<int:project_id>/materials')
def project_materials(project_id):
    s=get_session();service.required(s,Project,project_id)
    return jsonify([service.material_json(s,m) for m in s.scalars(select(Material).where(Material.project_id==project_id).order_by(Material.id))])


@blueprint.get('/materials')
def materials():
    s=get_session();query=select(Material).order_by(Material.updated_at.desc(),Material.id)
    if not include_archived():query=query.where(Material.archived_at.is_(None))
    # System Profile is shown read-only in project detail, never as a duplicate editable file.
    if request.args.get('include_system')!='1':query=query.where(Material.is_system_managed.is_(False))
    return jsonify([service.material_json(s,m) for m in s.scalars(query)])


@blueprint.post('/materials')
def upload_material():
    parsed=parse_upload(request.files.get('file'))
    try:metadata=json.loads(request.form.get('metadata','{}'))
    except (ValueError,TypeError):raise ApiError(400,'VALIDATION_ERROR','资料元数据 JSON 无效。')
    s=get_session();row=service.upload_material(s,parsed,metadata)
    return jsonify(service.material_json(s,row)),201


@blueprint.get('/materials/<int:material_id>')
def material(material_id):
    s=get_session();return jsonify(service.material_json(s,service.required(s,Material,material_id)))


@blueprint.patch('/materials/<int:material_id>')
def update_material(material_id):
    s=get_session();return jsonify(service.material_json(s,service.patch_material(s,material_id,request.get_json(silent=True))))


@blueprint.post('/materials/<int:material_id>/archive')
def archive_material(material_id):
    s=get_session();return jsonify(service.material_json(s,service.archive_material(s,material_id)))


@blueprint.get('/materials/<int:material_id>/versions')
def versions(material_id):
    s=get_session();return jsonify([service.version_json(s,v) for v in service.versions(s,material_id)])


@blueprint.post('/materials/<int:material_id>/versions')
def append_version(material_id):
    parsed=parse_upload(request.files.get('file'));s=get_session()
    row=service.upload_material(s,parsed,{},material_id)
    return jsonify(service.material_json(s,row)),201


@blueprint.get('/material-versions/<int:version_id>')
def version(version_id):
    s=get_session();return jsonify(service.version_json(s,service.required(s,MaterialVersion,version_id),True))


@blueprint.get('/material-versions/<int:version_id>/file')
def version_file(version_id):
    s=get_session();v=service.required(s,MaterialVersion,version_id);path=resolve_material_file(v.path)
    if not path.is_file():raise ApiError(404,'MATERIAL_FILE_MISSING','原始资料文件已不可用。')
    return send_file(path,as_attachment=True,download_name=v.original_filename,max_age=0)


@blueprint.post('/materials/search')
def search():
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict) or set(payload)-{'query','context'} or not isinstance(payload.get('query'),str) or len(payload['query'])>1000:
        raise ApiError(400,'VALIDATION_ERROR','请提供不超过 1000 字的 query 和 context。')
    s=get_session();selected,_=selected_versions(s,payload.get('context',{}))
    return jsonify({'results':retrieve(s,selected,payload['query'])})


def _impact(s,material_id):
    row=service.required(s,Material,material_id)
    references=s.scalar(select(func.count()).select_from(AssistantOutputSource).where(AssistantOutputSource.material_id_snapshot==material_id))
    return {'material_id':row.id,'assistant_output_references':references,'can_delete':not row.is_system_managed and references==0,
            'message':'存在历史引用，请归档资料。' if references else '系统 Profile 不能单独删除。' if row.is_system_managed else '无历史引用，可明确确认后永久删除。'}


@blueprint.get('/materials/<int:material_id>/deletion-impact')
def impact(material_id):return jsonify(_impact(get_session(),material_id))


@blueprint.delete('/materials/<int:material_id>')
def delete_material(material_id):
    if request.get_json(silent=True)!={'confirm':True}:raise ApiError(400,'VALIDATION_ERROR','永久删除需要 confirm=true。')
    s=get_session();paths=[]
    with s.begin():
        _begin_write(s);impact=_impact(s,material_id)
        if not impact['can_delete']:raise ApiError(409,'MATERIAL_HAS_HISTORY',impact['message'])
        versions=service.versions(s,material_id);version_ids=[v.id for v in versions]
        paths=[resolve_material_file(v.path) for v in versions]
        s.execute(delete(MaterialChunk).where(MaterialChunk.material_version_id.in_(version_ids)))
        s.execute(delete(MaterialVersion).where(MaterialVersion.id.in_(version_ids)))
        s.delete(service.required(s,Material,material_id))
    for path in paths:path.unlink(missing_ok=True)
    return jsonify({'deleted':True})
