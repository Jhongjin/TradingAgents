"""Operator page `/admin/members`: members, plans, remaining days, roles."""

from __future__ import annotations

from .design_system import badge, h, icon, icon_tile, render_shell

MEMBERS_CSS = """
.members-head { padding: 26px 0 18px; }
.members-head h1 { font-size: 24px; }
.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.toolbar .field { width: 280px; }
.members { min-width: 960px; }
.row-actions { display: flex; flex-wrap: wrap; gap: 6px; }
"""

MEMBERS_JS = """
(function(){
  var TOKEN_KEY='tradingagents.member.access_token', WORKER_KEY='tradingagents.admin.worker_token';
  function el(id){return document.getElementById(id);}
  function say(text,isError){var n=el('members-msg');n.textContent=text||'';n.className='msg'+(isError?' error':'');}
  function headers(){
    var h={'Content-Type':'application/json'};
    var t='';try{t=localStorage.getItem(TOKEN_KEY)||sessionStorage.getItem(TOKEN_KEY)||'';}catch(e){}
    var w='';try{w=sessionStorage.getItem(WORKER_KEY)||localStorage.getItem(WORKER_KEY)||'';}catch(e){}
    if(w){h['X-TradingAgents-Worker-Token']=w;}
    if(t){h['Authorization']='Bearer '+t;}
    return h;
  }
  async function api(path,options){
    var opts=Object.assign({headers:headers()},options||{});
    var r=await fetch(path,opts);var body=null;try{body=await r.json();}catch(e){}
    if(!r.ok){var d=body&&body.detail;throw new Error(typeof d==='string'?d:('요청 실패 ('+r.status+')'));}
    return body;
  }
  function fmt(v){if(!v)return '-';try{return new Date(v).toLocaleDateString('ko-KR');}catch(e){return v;}}
  function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  var members=[];
  function render(){
    var q=(el('search').value||'').trim().toLowerCase();
    var rows=members.filter(function(m){return !q||String(m.email||'').toLowerCase().indexOf(q)>=0||m.user_id.indexOf(q)>=0;});
    var tb=el('members-body');tb.innerHTML='';
    rows.forEach(function(m){
      var tr=document.createElement('tr');
      var planTone=m.status==='trialing'?'b-amber':(m.status==='active'&&m.plan!=='free'?'b-teal':'b-grey');
      var statusText={free:'무료',trialing:'체험 중',active:'이용 중',past_due:'결제 실패',canceled:'해지',anonymous:'-'}[m.status]||m.status;
      var initial=esc((m.email||'?').slice(0,1).toUpperCase());
      tr.innerHTML=
        '<td><div class="row" style="gap:10px"><span class="avatar b-navy">'+initial+'</span><div><b style="font-weight:700">'+esc(m.email||'-')+'</b><br><span class="tiny muted num">'+m.user_id.slice(0,8)+'…</span></div></div></td>'+
        '<td>'+(m.role==='admin'?'<span class="badge b-navy">관리자</span>':'<span class="badge b-grey">회원</span>')+'</td>'+
        '<td><span class="badge '+planTone+'">'+esc(m.plan_name)+'</span><br><small class="muted">'+statusText+'</small></td>'+
        '<td class="num">'+(m.remaining_days==null?'<span class="muted">-</span>':'<b style="font-weight:700">'+m.remaining_days+'일</b>')+'<br><small class="muted">'+fmt(m.period_end)+'</small>'+(m.remaining_days==null?'':'<div class="bar" style="width:72px;margin-top:5px"><i style="width:'+Math.max(0,Math.min(100,m.remaining_days/30*100))+'%"></i></div>')+'</td>'+
        '<td class="num">'+fmt(m.created_at)+'<br><small class="muted">최근 '+fmt(m.last_sign_in_at)+'</small></td>'+
        '<td>'+(m.telegram_linked?'<span class="badge b-teal">텔레그램</span>':'<span class="muted">-</span>')+(m.has_billing_key?'<br><small class="muted">결제수단 등록</small>':'')+(m.failure_count?'<br><small class="up">실패 '+m.failure_count+'</small>':'')+'</td>'+
        '<td><div class="row-actions">'+
          '<button data-act="plan" data-plan="daily" data-days="30" data-user="'+m.user_id+'" class="btn sm primary">데일리 30일</button>'+
          '<button data-act="plan" data-plan="pro" data-days="30" data-user="'+m.user_id+'" class="btn sm">프로 30일</button>'+
          '<button data-act="plan" data-plan="free" data-days="0" data-user="'+m.user_id+'" class="btn sm">무료로</button>'+
          (m.role==='admin'?'<button data-act="role" data-role="member" data-user="'+m.user_id+'" class="btn sm ghost">관리자 해제</button>':'<button data-act="role" data-role="admin" data-user="'+m.user_id+'" class="btn sm ghost">관리자 지정</button>')+
        '</div></td>';
      tb.appendChild(tr);
    });
    if(!rows.length){tb.innerHTML='<tr><td colspan="7" class="muted" style="text-align:center;padding:24px">표시할 회원이 없습니다.</td></tr>';}
  }
  async function load(){
    say('불러오는 중…');
    try{
      var d=await api('/api/admin/members');
      members=d.items||[];
      var s=d.summary||{};
      el('stat-members').textContent=s.member_count||0;el('stat-paid').textContent=s.paid_count||0;el('stat-trial').textContent=s.trial_count||0;el('stat-admin').textContent=s.admin_count||0;el('stat-tg').textContent=s.telegram_linked_count||0;
      render();say('');
    }catch(e){say(e.message+' — 관리자 계정으로 로그인했거나 운영 토큰이 저장되어 있어야 합니다.',true);}
  }
  document.addEventListener('click',async function(ev){
    var b=ev.target.closest('button[data-act]');if(!b)return;
    var user=b.getAttribute('data-user');
    try{
      if(b.getAttribute('data-act')==='plan'){
        var plan=b.getAttribute('data-plan');var days=parseInt(b.getAttribute('data-days')||'30',10);
        if(!confirm((plan==='free'?'무료 플랜으로 되돌립니다.':plan+' 플랜을 '+days+'일 부여합니다.')+' 계속할까요?'))return;
        await api('/api/admin/members/'+user+'/plan',{method:'POST',body:JSON.stringify({plan:plan,days:days})});
      }else{
        var role=b.getAttribute('data-role');
        if(!confirm('역할을 '+(role==='admin'?'관리자':'회원')+'로 바꿉니다. 계속할까요?'))return;
        await api('/api/admin/members/'+user+'/role',{method:'POST',body:JSON.stringify({role:role})});
      }
      say('적용했습니다.');load();
    }catch(e){say(e.message,true);}
  });
  el('search').addEventListener('input',render);
  el('reload').addEventListener('click',load);
  load();
})();
"""


def _tile(icon_name: str, tone: str, label: str, stat_id: str) -> str:
    return f'<div class="card tile">{icon_tile(icon_name, tone)}<div><p class="label">{h(label)}</p><p class="v num" id="{stat_id}">-</p></div></div>'


def render_admin_members_page(*, site_base_url: str | None = None) -> str:
    body = f"""
<section class="hero members-head">
  <div class="shell row between wrap">
    <div>{badge("운영자 전용", "b-navy", icon_name="shield")}<h1 style="margin-top: 8px;">회원 관리</h1><p class="small ink2" style="margin-top: 4px;">관리자 계정 세션 또는 운영 토큰이 필요합니다. 플랜 부여는 결제 없이 기간을 여는 운영자 조치이며 이력에 남습니다.</p></div>
    <div class="row"><a class="btn sm" href="/admin">{icon("settings", 14)}운영 콘솔</a><a class="btn sm" href="/harness">선별 기록</a></div>
  </div>
</section>
<section class="block" style="padding-bottom: 28px;">
  <div class="shell stack">
    <div class="grid-4" style="grid-template-columns: repeat(5, minmax(0, 1fr));">
      {_tile("users", "b-navy", "회원", "stat-members")}
      {_tile("card", "b-teal", "유료 이용 중", "stat-paid")}
      {_tile("zap", "b-amber", "체험 중", "stat-trial")}
      {_tile("shield", "b-violet", "관리자", "stat-admin")}
      {_tile("send", "b-blue", "텔레그램 연결", "stat-tg")}
    </div>
    <div class="card">
      <div class="card-h"><h2>{icon_tile("users", "b-navy", small=True)}회원과 플랜</h2><div class="toolbar"><input id="search" class="field" type="search" placeholder="이메일 또는 ID 검색" style="height: 34px;"><button class="btn sm" type="button" id="reload">새로고침</button></div></div>
      <div class="msg" id="members-msg" style="padding: 8px 18px 0;"></div>
      <div class="table-wrap">
        <table class="members">
          <thead><tr><th>회원</th><th>역할</th><th>플랜 · 상태</th><th>남은 기간</th><th>가입 · 최근 로그인</th><th>연결</th><th>조치</th></tr></thead>
          <tbody id="members-body"><tr><td colspan="7" class="muted" style="text-align:center;padding:24px">불러오는 중…</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>
</section>
"""
    return render_shell(
        title="회원 관리 | TradingAgents Korea",
        body=body,
        canonical_path="/admin/members",
        site_base_url=site_base_url,
        noindex=True,
        extra_css=MEMBERS_CSS,
        extra_js=MEMBERS_JS,
        search=False,
    )
