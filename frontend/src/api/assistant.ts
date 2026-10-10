import { request } from './client';
import { json } from './materials';
import type { SavedAnswer,AnswerVersion } from './saved-answers';
export type AssistantOperation='polish'|'reference_answer'|'analyze';
export interface ContextSelection {project_ids:number[];material_ids:number[];exclude_material_ids:number[]}
export interface AssistantSource {label?:string;material_id:number;material_version_id:number;project_id:number|null;title:string;version_no:number;sha256:string;chunk_ids?:number[];chunks?:Array<{chunk_id:number;page_number:number|null;text:string;retrieval_method:string}>;source_deleted_at?:string|null}
export interface AssistantInput {question_id:number;operation:AssistantOperation;draft?:string;source_saved_answer_version_id?:number;context:ContextSelection;context_token?:string}
export interface ContextPreview {context_token:string;sources:AssistantSource[];no_personal_materials:boolean;notice:string;selected_version_ids:number[]}
export interface AssistantPreview {preview_id:string;question_id:number;operation:AssistantOperation;content:string;sources:AssistantSource[];provider:string;model:string;source_saved_answer_version_id:number|null}
export interface AssistantOutput {id:number;question_id:number;output_type:AssistantOperation;origin_kind:string;content:string;sources:AssistantSource[];model:string;created_at:string;source_saved_answer_version_id:number|null}
export interface SaveAssistantInput {save_kind:'output'|'new_answer'|'answer_version';content?:string;saved_answer_id?:number;self_rating?:number|null;source_session_item_id?:number;source_practice_review_id?:number}
export interface SaveAssistantResult {output:AssistantOutput;answer:SavedAnswer|null;version:AnswerVersion|null}
export interface LLMConfig {base_url:string;model:string;has_api_key:boolean;configured:boolean;configuration_scope:string}
export const getLLMConfig=()=>request<LLMConfig>('/api/v1/llm/config');
export const saveLLMConfig=(input:{base_url:string;model:string;api_key?:string})=>request<LLMConfig>('/api/v1/llm/config',json('PATCH',input));
export const testLLMConnection=()=>request<{connected:boolean;model:string}>('/api/v1/llm/test',{method:'POST'});
export const previewContext=(input:AssistantInput)=>request<ContextPreview>('/api/v1/assistant/context-preview',json('POST',input));
export const generateAssistant=(input:AssistantInput)=>request<AssistantPreview>(`/api/v1/assistant/${input.operation.replace('_','-')}`,json('POST',input));
export const saveAssistant=(id:string,input:SaveAssistantInput)=>request<SaveAssistantResult>(`/api/v1/assistant/previews/${id}/save`,json('POST',input));
export const getAssistantOutputs=(id:number)=>request<AssistantOutput[]>(`/api/v1/questions/${id}/assistant-outputs`);

export const saveOutputAnswer=(id:number,input:SaveAssistantInput)=>request<SaveAssistantResult>(`/api/v1/assistant-outputs/${id}/saved-answer`,json('POST',input));
