import { request } from './client';
export interface ProjectInput {name:string;summary:string;tech_stack:string;personal_role:string;challenges:string;outcomes:string;highlights:string;notes:string;is_active:boolean}
export interface Project extends ProjectInput {id:number;archived_at:string|null;created_at:string;updated_at:string;profile_material_id:number;profile_version_count:number}
export interface MaterialVersion {id:number;material_id:number;version_no:number;original_filename:string;sha256:string;byte_size:number;created_at:string;parsed_at:string;parse_status:string;download_url:string;text?:string;chunks?:Array<{id:number;ordinal:number;page_number:number|null;heading:string|null}>}
export interface Material {id:number;title:string;kind:string;project_id:number|null;original_filename:string|null;is_active:boolean;include_in_context:boolean;is_system_managed:boolean;archived_at:string|null;created_at:string;updated_at:string;version_count:number;current_version:MaterialVersion|null}
export const json=(method:string,body:unknown)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
export const getProjects=(archived=false)=>request<Project[]>(`/api/v1/projects${archived?'?include_archived=1':''}`);
export const getProject=(id:number)=>request<Project>(`/api/v1/projects/${id}`);
export const saveProject=(input:ProjectInput,id?:number)=>request<Project>(id?`/api/v1/projects/${id}`:'/api/v1/projects',json(id?'PATCH':'POST',input));
export const archiveProject=(id:number)=>request<Project>(`/api/v1/projects/${id}/archive`,{method:'POST'});
export const getProjectMaterials=(id:number)=>request<Material[]>(`/api/v1/projects/${id}/materials`);
export const getMaterials=(archived=false,system=false)=>request<Material[]>(`/api/v1/materials?include_archived=${archived?1:0}&include_system=${system?1:0}`);
export const getMaterial=(id:number)=>request<Material>(`/api/v1/materials/${id}`);
export const patchMaterial=(id:number,input:Partial<Material>)=>request<Material>(`/api/v1/materials/${id}`,json('PATCH',input));
export const archiveMaterial=(id:number)=>request<Material>(`/api/v1/materials/${id}/archive`,{method:'POST'});
export const getMaterialVersions=(id:number)=>request<MaterialVersion[]>(`/api/v1/materials/${id}/versions`);
export const getMaterialVersion=(id:number)=>request<MaterialVersion>(`/api/v1/material-versions/${id}`);
export function uploadMaterial(file:File,metadata:{title?:string;kind?:string;project_id?:number|null}={},id?:number){const data=new FormData();data.append('file',file);data.append('metadata',JSON.stringify(metadata));return request<Material>(id?`/api/v1/materials/${id}/versions`:'/api/v1/materials',{method:'POST',body:data});}
export const materialLabels:Record<string,string>={resume:'简历',project_profile:'项目事实 Profile',project_brief:'项目说明',readme:'README',architecture_doc:'架构文档',other:'其他资料'};
