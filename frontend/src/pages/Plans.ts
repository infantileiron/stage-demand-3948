import {defineComponent,ref,onMounted,computed} from 'vue'
import {plans,loadPlans,planApi} from '../stores/plan'
import {reports,loadReports,reportApi} from '../stores/report'
import {rosters,loadMerges,mergeApi} from '../stores/merge'
import {canWrite,canApprove} from '../stores/auth'
import {REVIEW_STATUS} from '../constants/enums'
import {number} from '../utils/format'
import {useTask} from '../hooks/useTask'
import ForecastTable from '../components/common/ForecastTable'
import Notice from '../components/common/Notice'
import EmptyState from '../components/common/EmptyState'

export default defineComponent({components:{ForecastTable,Notice,EmptyState},setup(){
  const state=useTask(),expanded=ref(0),mergeOpen=ref(0)
  const form=ref({name:'三厅共用引导员编排',plan_ids:[] as number[],daily_capacity:12})
  const picked=computed(()=>plans.value.filter(plan=>form.value.plan_ids.includes(plan.id)))
  const duplicateVenue=computed(()=>{const seen=new Set<string>();for(const plan of picked.value){if(seen.has(plan.venue))return plan.venue;seen.add(plan.venue)}return ''})
  const rangeMismatch=computed(()=>{
    if(picked.value.length<2)return false
    const spans=picked.value.map(plan=>plan.days[0]?.date+'|'+plan.days[plan.days.length-1]?.date)
    return spans.some(span=>span!==spans[0])
  })
  const floor=computed(()=>2*Math.max(2,form.value.plan_ids.length))
  const capacityTooSmall=computed(()=>form.value.plan_ids.length>=2&&Number(form.value.daily_capacity)<floor.value)
  const canSubmit=computed(()=>form.value.name.trim().length>=2&&form.value.plan_ids.length>=2&&!duplicateVenue.value&&!rangeMismatch.value&&!capacityTooSmall.value)
  const demandTotal=computed(()=>picked.value.reduce((sum,plan)=>sum+plan.days.reduce((daySum,day)=>daySum+day.ushers,0),0))
  onMounted(()=>state.task(async()=>{await Promise.all([loadPlans(),loadReports(),loadMerges()])}))
  function togglePlan(id:number){const index=form.value.plan_ids.indexOf(id);if(index>=0)form.value.plan_ids.splice(index,1);else form.value.plan_ids.push(id)}
  function approvePlan(id:number){state.task(async()=>{await planApi.approve(id);await loadPlans();state.notice.value='编排已审批，可生成导出纪要'})}
  function makeReport(id:number){state.task(async()=>{await reportApi.create({title:'值班编排纪要 #'+id+' · '+new Date().toLocaleString('zh-CN'),plan_id:id});await loadReports();state.notice.value='纪要已归档，点击下载CSV'})}
  function download(id:number){state.task(()=>reportApi.exportReport(id))}
  function merge(){state.task(async()=>{
    const roster=await mergeApi.create({name:form.value.name,plan_ids:form.value.plan_ids,daily_capacity:Number(form.value.daily_capacity)})
    await loadMerges();mergeOpen.value=roster.id
    state.notice.value='共享池编排已生成：原预测与单厅编排保持不变，只新增合并记录'
  })}
  function exportRoster(id:number){state.task(()=>mergeApi.exportRoster(id))}
  function setCapacity(event:Event){const raw=Number((event.target as HTMLInputElement).value);form.value.daily_capacity=Number.isFinite(raw)?Math.max(1,Math.round(raw)):0}
  return {plans,reports,rosters,expanded,mergeOpen,form,picked,duplicateVenue,rangeMismatch,capacityTooSmall,canSubmit,demandTotal,floor,canWrite,canApprove,REVIEW_STATUS,number,...state,approvePlan,makeReport,download,merge,exportRoster,togglePlan,setCapacity}
},template:`<section><div class="page-title"><p class="eyebrow">05 / FRONT OF HOUSE</p><h1>值班编排</h1><p>把预测变成可复核的建议。主管确认之后，再分发给值班组。三个厅共用一个引导员池时，可在下方合并同日期范围的已完成预演。</p></div><Notice :error="error" :notice="notice"/><div class="section-line"><h2>单厅编排</h2><span>原预测与单厅建议保留</span></div><article class="plan-row" v-for="plan in plans" :key="plan.id"><header><div><p class="eyebrow">PLAN / {{String(plan.id).padStart(2,'0')}} · {{plan.venue}}</p><h2>{{plan.name}}</h2></div><span class="tag">{{REVIEW_STATUS[plan.status]}}</span></header><p>{{plan.days.length}} 天建议 · 最少2名引导员 · 以预演区间上界估算</p><div class="action-row"><button class="quiet" @click="expanded=expanded===plan.id?0:plan.id">{{expanded===plan.id?'收起明细 −':'展开明细 ＋'}}</button><button class="primary" v-if="canApprove&&plan.status==='draft'" :disabled="busy" @click="approvePlan(plan.id)">主管确认</button><button class="quiet" v-if="canWrite&&plan.status==='approved'" :disabled="busy" @click="makeReport(plan.id)">生成纪要 ↗</button><small v-if="plan.approved_by">确认人：{{plan.approved_by}}</small></div><ForecastTable v-if="expanded===plan.id" :days="plan.days"/></article><EmptyState v-if="!plans.length" title="还没有编排建议" text="先完成预演，在结果页为建议命名并生成。"/>

<div class="section-line"><h2>三厅共用引导员 · 合并编排</h2><span>同日期范围 / 每厅保底两人</span></div>
<template v-if="canWrite"><form class="merge-form" @submit.prevent="merge"><label>合并编排名称<input v-model="form.name" required minlength="2" maxlength="100" placeholder="如：11月第二周三厅共用编排"></label><label>每日人力容量（人）<input type="number" min="2" max="200" step="1" v-model.number="form.daily_capacity" @input="setCapacity($event)" required></label><p class="note-small">每厅至少保底 2 人；容量低于 {{floor}} 人时后端会拒绝生成。</p><fieldset class="merge-pick"><legend>选择同区间的已完成预演（每厅一份）</legend><label v-for="plan in plans" class="check" :key="plan.id"><input type="checkbox" :checked="form.plan_ids.includes(plan.id)" @change="togglePlan(plan.id)">{{plan.venue}} · {{plan.name}}<small>{{plan.days[0]?.date}} — {{plan.days[plan.days.length-1]?.date}} · {{REVIEW_STATUS[plan.status]}}</small></label><p v-if="!plans.length" class="note-small">尚无可合并的编排建议。</p></fieldset><p v-if="duplicateVenue" class="notice error">「{{duplicateVenue}}」被选择了不止一份编排，请每厅只保留一份。</p><p v-if="rangeMismatch" class="notice error">所选编排的预演日期范围不一致，请改选同区间编排。</p><p v-if="capacityTooSmall" class="notice error">每日容量至少需要 {{floor}} 人（每厅保底 {{2}} 人）。</p><p v-if="picked.length" class="note-small">已选 {{picked.length}} 厅：{{picked.map(p=>p.venue).join(' / ')}}；单厅建议合计 {{demandTotal}} 人次。</p><button class="primary" :disabled="busy||!canSubmit">生成合并编排 →</button></form></template>

<article class="plan-row" v-for="roster in rosters" :key="roster.id"><header><div><p class="eyebrow">SHARED POOL / {{String(roster.id).padStart(2,'0')}} · {{roster.venues.join(' + ')}}</p><h2>{{roster.name}}</h2></div><span class="tag">{{roster.reconciled?'已对账':'待核对'}}</span></header><p>{{roster.date_range.first}} — {{roster.date_range.last}} · {{roster.days.length}} 天 · 每日容量 {{roster.daily_capacity}} 人 · 每厅保底 {{roster.rules.min_per_venue}} 人</p><p>合计：需求 {{roster.totals.demand}} 名 · 实配 {{roster.totals.allocated}} 名 · 缺口 {{roster.totals.gap}} 名 · 闲置 {{roster.totals.unused}} 名 · 未覆盖 {{number(roster.totals.uncovered)}} 人时</p><div class="action-row"><button class="quiet" @click="mergeOpen=mergeOpen===roster.id?0:roster.id">{{mergeOpen===roster.id?'收起对账 −':'展开需求/实配/缺口/闲置 ＋'}}</button><button class="quiet" :disabled="busy" @click="exportRoster(roster.id)">下载对账 CSV ↓</button></div><div v-if="mergeOpen===roster.id" class="table-scroll"><table><thead><tr><th>日期</th><th>场馆</th><th>90%上界</th><th>每名承载</th><th>需求（名）</th><th>实配（名）</th><th>缺口（名）</th><th>闲置（名）</th><th>未覆盖人数</th></tr></thead><tbody><template v-for="day in roster.days" :key="day.date"><tr v-for="row in day.venues" :key="day.date+row.venue"><td>{{day.date}}</td><td>{{row.venue}}</td><td>{{number(row.upper)}}</td><td>{{row.people_per_usher}}</td><td>{{row.demand}}</td><td>{{row.allocated}}</td><td>{{row.gap}}</td><td></td><td>{{number(row.uncovered)}}</td></tr><tr class="chosen"><td>{{day.date}} 合计</td><td>{{day.venues.length}} 厅</td><td></td><td></td><td>{{day.demand}}</td><td>{{day.allocated}}</td><td>{{day.gap}}</td><td>{{day.unused}}</td><td>最大 {{number(day.uncovered_max)}}</td></tr></template><tr class="chosen"><td>总计</td><td></td><td></td><td></td><td>{{roster.totals.demand}}</td><td>{{roster.totals.allocated}}</td><td>{{roster.totals.gap}}</td><td>{{roster.totals.unused}}</td><td>{{number(roster.totals.uncovered)}}</td></tr></tbody></table></div><p v-if="mergeOpen===roster.id" class="note-small">对账口径：实配 + 缺口 = 需求；实配 + 闲置 = 每日容量；实配不超过每日总额与各厅原建议，且每厅不少于 {{roster.rules.min_per_venue}} 人。缺口与未覆盖人数反映共享池不足，不修改原预测。</p></article>
<EmptyState v-if="!rosters.length" title="尚未合并共享池" text="选择三厅同日期范围的已完成预演并给定每日容量，即可生成合并人力编排。"/>

<div class="section-line"><h2>已确认 · 分发纪要</h2><span>带口径的 CSV</span></div><div class="report-row" v-for="report in reports"><div><h3>{{report.title}}</h3><p>{{report.venue}} · {{report.days.length}} 天 · 编排 #{{report.plan_id}}</p></div><button class="quiet" :disabled="busy" @click="download(report.id)">下载 CSV ↓</button></div><EmptyState v-if="!reports.length" title="尚无可分发纪要" text="由主管审批建议后，分析员可生成纪要。"/></section>`})
