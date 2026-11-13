import {ref} from 'vue'
import type {MergeRoster} from '../types/domain'
import * as api from '../api/merge'
export const rosters=ref<MergeRoster[]>([])
export async function loadMerges(){rosters.value=await api.list()}
export {api as mergeApi}
