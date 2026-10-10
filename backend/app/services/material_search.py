"""Selected current evidence only. Unicode FTS plus visible keyword fallback."""
import re
from sqlalchemy import select, text
from app.errors import ApiError
from app.models.material import Project,Material,MaterialVersion,MaterialChunk


def ids(value,field):
    if not isinstance(value,list) or len(value)>30 or any(type(v) is not int or v<=0 for v in value):
        raise ApiError(400,'VALIDATION_ERROR',f'{field} 必须是最多 30 个正整数 ID。')
    return sorted(set(value))


def selected_versions(session,context):
    if not isinstance(context,dict) or set(context)-{'project_ids','material_ids','exclude_material_ids'}:
        raise ApiError(400,'VALIDATION_ERROR','上下文选择无效。')
    project_ids=ids(context.get('project_ids',[]),'project_ids')
    material_ids=ids(context.get('material_ids',[]),'material_ids')
    exclude_ids=set(ids(context.get('exclude_material_ids',[]),'exclude_material_ids'))
    projects={p.id:p for p in session.scalars(select(Project))}
    for pid in project_ids:
        p=projects.get(pid)
        if p is None or p.archived_at or not p.is_active:
            raise ApiError(409,'CONTEXT_UNAVAILABLE','所选项目已停用、归档或不存在。')
    materials={m.id:m for m in session.scalars(select(Material))}
    def allowed(m):
        return m is not None and m.is_active and m.include_in_context and not m.archived_at and (
            m.project_id is None or m.project_id in projects and projects[m.project_id].is_active and not projects[m.project_id].archived_at)
    for mid in material_ids:
        if mid not in exclude_ids and not allowed(materials.get(mid)):
            raise ApiError(409,'CONTEXT_UNAVAILABLE','所选资料已关闭上下文、停用、归档或不存在。')
    picked=[m for m in materials.values() if (m.id in material_ids or m.project_id in project_ids)
            and m.id not in exclude_ids and allowed(m)]
    if len(picked)>30:raise ApiError(400,'CONTEXT_TOO_LARGE','请减少所选资料，单次最多 30 份。')
    result=[]
    for material in sorted(picked,key=lambda m:(not m.is_system_managed,m.id)):
        version=session.scalar(select(MaterialVersion).where(MaterialVersion.material_id==material.id).order_by(MaterialVersion.version_no.desc()).limit(1))
        if version:result.append((material,version))
    return result,{'project_ids':project_ids,'material_ids':material_ids,'exclude_material_ids':sorted(exclude_ids)}


def retrieve(session,versions,query,limit=8):
    if not versions:return []
    terms=list(dict.fromkeys(re.findall(r'[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}',query.lower())))[:24]
    version_ids=[v.id for _,v in versions]
    chunks=list(session.scalars(select(MaterialChunk).where(MaterialChunk.material_version_id.in_(version_ids)).order_by(MaterialChunk.ordinal,MaterialChunk.id)))
    fts_scores={}
    if terms:
        expression=' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
        rows=session.execute(text('SELECT rowid,bm25(material_chunk_fts) score FROM material_chunk_fts WHERE material_chunk_fts MATCH :query'),{'query':expression}).all()
        fts_scores={r[0]:r[1] for r in rows}
    def score(c):
        body=c.text.lower()
        return sum(body.count(term) for term in terms)
    matched=[c for c in chunks if c.id in fts_scores or score(c)>0]
    matched.sort(key=lambda c:(c.id not in fts_scores,fts_scores.get(c.id,0),-score(c),c.id))
    selected=matched[:limit]
    mode='fts' if selected and all(c.id in fts_scores for c in selected) else 'keyword_fallback' if selected else 'selected_excerpt'
    # No-hit fallback is deliberately labelled; it never claims high relevance.
    if not selected:
        selected=[next(c for c in chunks if c.material_version_id==v.id) for _,v in versions
                  if any(c.material_version_id==v.id for c in chunks)][:limit]
    catalogue={v.id:(m,v) for m,v in versions}
    result=[]
    for c in selected:
        material,version=catalogue[c.material_version_id]
        result.append({'chunk_id':c.id,'material_id':material.id,'material_version_id':version.id,
            'project_id':material.project_id,'title':material.title,'version_no':version.version_no,
            'sha256':version.sha256,'page_number':c.page_number,'text':c.text,
            'retrieval_method':'fts' if c.id in fts_scores else 'keyword_fallback' if score(c)>0 else 'selected_excerpt'})
    return result
