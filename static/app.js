const labels = {new:'جديدة', contacted:'تم التواصل', qualified:'مؤهلة', proposal:'عرض مقدم', won:'ناجحة', lost:'مغلقة'};
let opportunities = [];
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = n => new Intl.NumberFormat('ar', {maximumFractionDigits: 2}).format(n);
async function request(url, options) { const r = await fetch(url, options); if (!r.ok) { let e; try { e = (await r.json()).error; } catch {} throw new Error(e || 'تعذر إتمام الطلب'); } return r.json(); }
async function refresh() { try { opportunities = await request('/api/opportunities'); render(); } catch(e) { alert(e.message); } }
function render() {
 const active = opportunities.filter(x => !['won','lost'].includes(x.status));
 $('count').textContent = number(opportunities.length); $('active-count').textContent = number(active.length);
 $('weighted').textContent = number(active.reduce((sum,x) => sum + x.value*x.probability/100,0)); $('won').textContent = number(opportunities.filter(x=>x.status==='won').length);
 const query = $('search').value.trim().toLowerCase(), filter = $('filter').value;
 const visible = opportunities.filter(x => (!filter || x.status===filter) && [x.name,x.company,x.service].some(v=>v.toLowerCase().includes(query)));
 $('table-body').innerHTML = visible.map(x=>`<tr><td><div class="client"><span class="avatar">${esc(x.name.charAt(0))}</span><div><strong>${esc(x.name)}</strong><small>${esc(x.company || '—')}</small></div></div></td><td>${esc(x.service || '—')}</td><td><span class="badge ${esc(x.status)}">${esc(labels[x.status])}</span></td><td class="value">${number(x.value)}</td><td><div>${esc(x.next_action || '—')}</div><small>${esc(x.due_date)}</small></td><td><button class="row-button" data-edit="${x.id}" aria-label="تعديل">✎</button><button class="row-button delete" data-delete="${x.id}" aria-label="حذف">×</button></td></tr>`).join('');
 $('empty').hidden = visible.length > 0; $('demo').hidden = opportunities.length > 0;
 const today = new Date(); const localDate = [today.getFullYear(), String(today.getMonth()+1).padStart(2,'0'), String(today.getDate()).padStart(2,'0')].join('-');
 const overdue = active.filter(x=>x.due_date && x.due_date < localDate).length;
 const dueToday = active.filter(x=>x.due_date === localDate).length;
 const undated = active.filter(x=>!x.due_date).length;
 $('followup-summary').textContent = `${number(overdue)} متأخرة · ${number(dueToday)} اليوم · ${number(undated)} بلا موعد`;
 const follow = active.filter(x=>x.next_action || x.due_date).sort((a,b)=>(a.due_date || '9999').localeCompare(b.due_date || '9999')).slice(0,4);
 $('followups').innerHTML = follow.length ? follow.map(x=>`<button class="follow follow-button" data-follow-edit="${x.id}"><span class="follow-dot">◷</span><span><strong>${esc(x.next_action || 'متابعة العميل')}</strong><small>${esc(x.name)} ${x.due_date ? ' · '+esc(x.due_date) : ' · بلا موعد'} ${x.due_date && x.due_date < localDate ? ' · متأخرة' : ''}</small></span></button>`).join('') : '<div class="focus-empty"><span>☼</span><p>كل شيء هادئ هنا</p><small>أضف خطوة قادمة لتظهر في قائمة المتابعة.</small></div>';
}
function openForm(item) { $('form').reset(); $('form-error').textContent=''; $('form-title').textContent=item?'تعديل الفرصة':'فرصة جديدة'; $('form').elements.id.value=item?.id || ''; if(item) for(const [key,value] of Object.entries(item)) if($('form').elements[key]) $('form').elements[key].value=value; $('dialog').showModal(); }
['add','hero-add','table-add'].forEach(id=>$(id).onclick=()=>openForm());
$('close').onclick=$('cancel').onclick=()=>$('dialog').close();
$('search').oninput=render; $('filter').onchange=render;
$('followups').onclick=e=>{ const button=e.target.closest('[data-follow-edit]'); if(button) openForm(opportunities.find(x=>x.id===Number(button.dataset.followEdit))); };
$('table-body').onclick=async e=>{ const edit=e.target.closest('[data-edit]'), del=e.target.closest('[data-delete]'); if(edit) openForm(opportunities.find(x=>x.id===Number(edit.dataset.edit))); if(del && confirm('هل تريد حذف هذه الفرصة نهائيًا؟')) { try { await request('/api/opportunities/'+del.dataset.delete,{method:'DELETE'}); await refresh(); } catch(err) { alert(err.message); } } };
$('form').onsubmit=async e=>{ e.preventDefault(); const data=Object.fromEntries(new FormData(e.target)); const id=data.id; delete data.id; try { await request('/api/opportunities'+(id?'/'+id:''),{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); $('dialog').close(); await refresh(); } catch(err) { $('form-error').textContent=err.message; } };
$('demo').onclick=async()=>{ const examples=[{name:'سلمى',company:'متجر محلي',service:'صفحة هبوط',value:3000,probability:40,status:'qualified',next_action:'فهم احتياجات المتجر',due_date:'',notes:'بيانات تجريبية'}, {name:'ياسين',company:'استوديو إبداعي',service:'أتمتة المتابعة',value:5000,probability:25,status:'contacted',next_action:'تحديد موعد مكالمة',due_date:'',notes:'بيانات تجريبية'}]; try { for(const item of examples) await request('/api/opportunities',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(item)}); await refresh(); } catch(e) { alert(e.message); await refresh(); } };
refresh();
