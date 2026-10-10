"""Projects own one Profile; all evidence content changes append versions."""
from pathlib import Path

from sqlalchemy import func, select
from flask import current_app

from app.errors import ApiError
from app.models.material import Project,Material,MaterialVersion,MaterialChunk
from app.models.taxonomy import utc_now
from app.services.saved_answers import _timestamp
from app.services.question_relations import _begin_write
from app.services.material_files import ParsedMaterial,write_evidence,cleanup_failed_files

FACT_FIELDS = ('name','summary','tech_stack','personal_role','challenges','outcomes','highlights')
PROJECT_FIELDS = {*FACT_FIELDS,'notes','is_active'}
KINDS = {'resume','project_brief','readme','architecture_doc','other'}


def required(session, model, resource_id):
    row=session.get(model,resource_id)
    if row is None:
        raise ApiError(404,'NOT_FOUND','项目或资料不存在。')
    return row


def _text(value,field,limit=20000):
    if not isinstance(value,str) or len(value)>limit:
        raise ApiError(400,'VALIDATION_ERROR',f'{field} 必须是长度不超过 {limit} 的文字。')
    return value.strip()


def project_json(session,row):
    profile=session.scalar(select(Material).where(Material.project_id==row.id,Material.is_system_managed.is_(True)))
    result={field:getattr(row,field) for field in ('id',*FACT_FIELDS,'notes','is_active')}
    return {**result,'archived_at':_timestamp(row.archived_at),'created_at':_timestamp(row.created_at),
        'updated_at':_timestamp(row.updated_at),'profile_material_id':profile.id if profile else None,
        'profile_version_count':session.scalar(select(func.count()).select_from(MaterialVersion).where(MaterialVersion.material_id==profile.id)) if profile else 0}


def append_material_version(session,material,parsed,written):
    path,digest=write_evidence(parsed,written)
    number=(session.scalar(select(func.max(MaterialVersion.version_no)).where(MaterialVersion.material_id==material.id)) or 0)+1
    version=MaterialVersion(material_id=material.id,version_no=number,path=path,sha256=digest,
        original_filename=parsed.filename,byte_size=len(parsed.payload),parsed_at=utc_now())
    session.add(version);session.flush()
    ordinal=0
    for page,value in parsed.pages:
        for start in range(0,len(value),1200):
            body=value[start:start+1200]
            session.add(MaterialChunk(material_version_id=version.id,project_id=material.project_id,
                ordinal=ordinal,page_number=page,heading=body.split('\n',1)[0][:240],text=body))
            ordinal+=1
    material.original_filename=parsed.filename;material.updated_at=utc_now()
    session.flush()
    return version


def _profile(session,project,written):
    material=session.scalar(select(Material).where(Material.project_id==project.id,Material.is_system_managed.is_(True)))
    if material is None:
        material=Material(kind='project_profile',project_id=project.id,title=f'{project.name} · 项目事实',is_system_managed=True)
        session.add(material);session.flush()
    material.title=f'{project.name} · 项目事实'
    labels={'name':'项目','summary':'简介','tech_stack':'技术栈','personal_role':'个人职责','challenges':'难点','outcomes':'成果','highlights':'亮点'}
    body='\n\n'.join(f'{labels[field]}：{getattr(project,field)}' for field in FACT_FIELDS if getattr(project,field))
    parsed=ParsedMaterial('project-profile.txt',body.encode('utf-8'),[(None,body)])
    append_material_version(session,material,parsed,written)


def save_project(session,payload,project_id=None):
    if not isinstance(payload,dict) or not payload or set(payload)-PROJECT_FIELDS:
        raise ApiError(400,'VALIDATION_ERROR','项目表单包含不支持的字段。')
    values={}
    for field,value in payload.items():
        if field=='is_active':
            if type(value) is not bool:raise ApiError(400,'VALIDATION_ERROR','有效状态必须为布尔值。')
            values[field]=value
        else:values[field]=_text(value,field,240 if field=='name' else 20000)
    if ('name' in values and not values['name']) or (project_id is None and 'name' not in values):
        raise ApiError(400,'VALIDATION_ERROR','请填写项目名称。')
    written=[]
    try:
        with session.begin():
            _begin_write(session)
            row=required(session,Project,project_id) if project_id else Project()
            if row.archived_at is not None:raise ApiError(409,'CONFLICT','已归档项目为只读。')
            changed=project_id is None or any(getattr(row,f)!=values[f] for f in FACT_FIELDS if f in values)
            for field,value in values.items():setattr(row,field,value)
            row.updated_at=utc_now();session.add(row);session.flush()
            if changed:_profile(session,row,written)
        return row
    except BaseException:
        cleanup_failed_files(written);raise


def archive_project(session,project_id):
    with session.begin():
        _begin_write(session);row=required(session,Project,project_id)
        row.archived_at=row.archived_at or utc_now();row.updated_at=utc_now();session.flush()
    return row


def validate_project(session,value):
    if value is None:return None
    if type(value) is not int or value<=0:raise ApiError(400,'VALIDATION_ERROR','项目 ID 无效。')
    row=required(session,Project,value)
    if row.archived_at:raise ApiError(409,'CONFLICT','不能关联已归档项目。')
    return row.id


def upload_material(session,parsed,metadata,material_id=None):
    written=[]
    try:
        with session.begin():
            _begin_write(session)
            if material_id:
                material=required(session,Material,material_id)
                if material.is_system_managed or material.archived_at:
                    raise ApiError(409,'CONFLICT','系统 Profile 和已归档资料不能替换文件。')
            else:
                if not isinstance(metadata,dict) or set(metadata)-{'title','kind','project_id'}:
                    raise ApiError(400,'VALIDATION_ERROR','资料元数据包含不支持的字段。')
                kind=metadata.get('kind','other')
                if not isinstance(kind,str) or kind not in KINDS:raise ApiError(400,'VALIDATION_ERROR','资料类型无效，Project Profile 由项目表单自动维护。')
                title=_text(metadata.get('title') or parsed.filename,'title',240)
                material=Material(title=title,kind=kind,project_id=validate_project(session,metadata.get('project_id')))
                session.add(material);session.flush()
            append_material_version(session,material,parsed,written)
        return material
    except BaseException:
        cleanup_failed_files(written);raise


def patch_material(session,material_id,payload):
    fields={'title','kind','project_id','is_active','include_in_context'}
    if not isinstance(payload,dict) or not payload or set(payload)-fields:
        raise ApiError(400,'VALIDATION_ERROR','资料元数据包含不支持的字段。')
    with session.begin():
        _begin_write(session);row=required(session,Material,material_id)
        if row.archived_at:raise ApiError(409,'CONFLICT','已归档资料为只读。')
        if row.is_system_managed and set(payload)-{'is_active','include_in_context'}:
            raise ApiError(409,'CONFLICT','Profile 事实只能通过项目表单修改；可单独控制上下文开关。')
        for field,value in payload.items():
            if field in {'is_active','include_in_context'}:
                if type(value) is not bool:raise ApiError(400,'VALIDATION_ERROR','开关必须为布尔值。')
            elif field=='project_id':value=validate_project(session,value)
            elif field=='kind':
                if not isinstance(value,str) or value not in KINDS:raise ApiError(400,'VALIDATION_ERROR','资料类型无效。')
            else:
                value=_text(value,field,240)
                if not value:raise ApiError(400,'VALIDATION_ERROR','资料标题不能为空。')
            setattr(row,field,value)
        row.updated_at=utc_now();session.flush()
    return row


def archive_material(session,material_id):
    with session.begin():
        _begin_write(session);row=required(session,Material,material_id)
        if row.is_system_managed:raise ApiError(409,'CONFLICT','系统 Profile 随项目保留，可停用或关闭上下文。')
        row.archived_at=row.archived_at or utc_now();row.updated_at=utc_now();session.flush()
    return row


def versions(session,material_id):
    required(session,Material,material_id)
    return list(session.scalars(select(MaterialVersion).where(MaterialVersion.material_id==material_id).order_by(MaterialVersion.version_no.desc())))


def version_json(session,version,with_text=False):
    result={field:getattr(version,field) for field in ('id','material_id','version_no','original_filename','sha256','byte_size')}
    result.update(created_at=_timestamp(version.created_at),parsed_at=_timestamp(version.parsed_at),parse_status='ready',
        download_url=f'/api/v1/material-versions/{version.id}/file')
    if with_text:
        chunks=list(session.scalars(select(MaterialChunk).where(MaterialChunk.material_version_id==version.id).order_by(MaterialChunk.ordinal)))
        result['text']='\n\n'.join(c.text for c in chunks)
        result['chunks']=[{'id':c.id,'ordinal':c.ordinal,'page_number':c.page_number,'heading':c.heading} for c in chunks]
    return result


def material_json(session,row):
    current=session.scalar(select(MaterialVersion).where(MaterialVersion.material_id==row.id).order_by(MaterialVersion.version_no.desc()).limit(1))
    return {field:getattr(row,field) for field in ('id','kind','project_id','title','original_filename','is_active','include_in_context','is_system_managed')}|{
        'archived_at':_timestamp(row.archived_at),'created_at':_timestamp(row.created_at),'updated_at':_timestamp(row.updated_at),
        'version_count':session.scalar(select(func.count()).select_from(MaterialVersion).where(MaterialVersion.material_id==row.id)),
        'current_version':version_json(session,current) if current else None}
