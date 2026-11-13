import {request,download} from './client'
import type {MergeRoster} from '../types/domain'
export const list=()=>request<MergeRoster[]>('/merges')
export const create=(body:unknown)=>request<MergeRoster>('/merges',body)
export const exportRoster=(id:number)=>download('/merges/'+id+'/download','shared-pool-'+id+'.csv')
