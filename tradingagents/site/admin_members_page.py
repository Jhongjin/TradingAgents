"""Operator page `/admin/members`: members, plans, remaining days, roles."""

from __future__ import annotations

import html
from typing import Any

from .home_page import HOME_CSS, HOME_JS, THEMES, THEME_LABELS
from .seo import canonical_url


def _h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


MEMBERS_CSS = """
.stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:18px}
.stat{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:12px 14px}
.stat .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.stat .v{font-family:"IBM Plex Mono",monospace;font-size:22px}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.toolbar input{padding:9px 12px;border:1px solid var(--line-strong);border-radius:6px;background:var(--panel);color:var(--ink);font:inherit;min-width:260px}
.members{width:100%;border-collapse:collapse;font-size:13px;min-width:960px}
.members th{text-align:left;font-size:11px;letter-spacing:.04em;color:var(--muted);font-weight:600;padding:0 8px 8px;border-bottom:1px solid var(--line-strong)}
.members td{padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.members .mono{font-size:12px}
.pill{display:inline-block;font-size:11px;font-weight:600;padding:2px 7px;border-radius:4px;background:var(--bg2);color:var(--ink2);border:1px solid var(--line)}
.pill.paid{background:var(--accent-soft);color:var(--accent-ink);border-color:transparent}
.pill.trial{background:var(--brass-soft);color:var(--brass);border-color:transparent}
.pill.admin{background:var(--ink);color:var(--bg);border-color:transparent}
.row-actions{display:flex;flex-wrap:wrap;gap:6px}
.row-actions button{font:inherit;font-size:12px;padding:5px 8px;border-radius:5px;border:1px solid var(--line-strong);background:var(--panel);color:var(--ink);cursor:pointer}
.row-actions button.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.msg{font-size:13px;color:var(--ink2);min-height:18px;margin:8px 0}
.msg.error{color:var(--gain)}
@media (max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}}
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
  var members=[];
  function render(){
    var q=(el('search').value||'').trim().toLowerCase();
    var rows=members.filter(function(m){return !q||String(m.email||'').toLowerCase().indexOf(q)>=0||m.user_id.indexOf(q)>=0;});
    var tb=el('members-body');tb.innerHTML='';
    rows.forEach(function(m){
      var tr=document.createElement('tr');
      var planClass=m.status==='trialing'?'trial':(m.status==='active'&&m.plan!=='free'?'paid':'');
      var statusText={free:'무료',trialing:'체험 중',active:'이용 중',past_due:'결제 실패',canceled:'해지',anonymous:'-'}[m.status]||m.status;
      tr.innerHTML=
        '<td>'+esc(m.email||'-')+'<br><span class="mono" style="color:var(--muted)">'+m.user_id.slice(0,8)+'…</span></td>'+
        '<td>'+(m.role==='admin'?'<span class="pill admin">관리자</span>':'<span class="pill">회원</span>')+'</td>'+
        '<td><span class="pill '+planClass+'">'+esc(m.plan_name)+'</span><br><small>'+statusText+'</small></td>'+
        '<td class="mono">'+(m.remaining_days==null?'-':m.remaining_days+'일')+'<br><small>'+fmt(m.period_end)+'</small></td>'+
        '<td class="mono">'+fmt(m.created_at)+'<br><small>최근 '+fmt(m.last_sign_in_at)+'</small></td>'+
        '<td>'+(m.telegram_linked?'연결':'-')+(m.has_billing_key?'<br><small>결제수단 등록</small>':'')+(m.failure_count?'<br><small style="color:var(--gain)">실패 '+m.failure_count+'</small>':'')+'</td>'+
        '<td><div class="row-actions">'+
          '<button data-act="plan" data-plan="daily" data-days="30" data-user="'+m.user_id+'" class="primary">데일리 30일</button>'+
          '<button data-act="plan" data-plan="pro" data-days="30" data-user="'+m.user_id+'">프로 30일</button>'+
          '<button data-act="plan" data-plan="free" data-days="0" data-user="'+m.user_id+'">무료로</button>'+
          (m.role==='admin'?'<button data-act="role" data-role="member" data-user="'+m.user_id+'">관리자 해제</button>':'<button data-act="role" data-role="admin" data-user="'+m.user_id+'">관리자 지정</button>')+
        '</div></td>';
      tb.appendChild(tr);
    });
    if(!rows.length){tb.innerHTML='<tr><td colspan="7">표시할 회원이 없습니다.</td></tr>';}
  }
  function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
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


def render_admin_members_page(*, site_base_url: str | None = None) -> str:
    theme_buttons = "".join(
        f'<button type="button" class="{name}" data-theme="{name}" aria-pressed="false" aria-label="{_h(THEME_LABELS[name])} 테마" title="{_h(THEME_LABELS[name])}"></button>'
        for name in THEMES
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>회원 관리 | TradingAgents Korea</title>
<link rel="canonical" href="{_h(canonical_url('/admin/members', site_base_url=site_base_url))}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700&family=IBM+Plex+Sans+KR:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<script>(function(){{try{{var t=localStorage.getItem('ta-theme');if(t==='paper'||t==='dark'||t==='sepia'){{document.documentElement.setAttribute('data-theme',t);}}}}catch(e){{}}}})();</script>
<style>{HOME_CSS}{MEMBERS_CSS}</style>
</head>
<body>
<header class="masthead">
  <div class="shell">
    <a class="brand" href="/"><span class="brand-name">TradingAgents Korea</span><span class="brand-sub">회원 관리</span></a>
    <nav class="nav" aria-label="운영 메뉴"><a href="/admin">운영 콘솔</a><a href="/admin/members" aria-current="page">회원 관리</a><a href="/harness">일일 하네스</a><a href="/billing">내 구독</a></nav>
    <div class="mast-right"><div class="theme-switch" role="group" aria-label="페이지 테마">{theme_buttons}</div><a class="btn" href="/mypage">내 공간</a></div>
  </div>
</header>
<main id="main-content">
<section class="block">
  <div class="shell">
    <div class="block-head"><h2>회원과 플랜</h2><p class="meta">관리자 계정(app_metadata.role=admin) 세션 또는 운영 토큰이 필요합니다. 플랜 부여는 결제 없이 기간을 여는 운영자 조치이며 이력에 남습니다.</p></div>
    <div class="stats">
      <div class="stat"><div class="k">회원</div><div class="v" id="stat-members">-</div></div>
      <div class="stat"><div class="k">유료 이용 중</div><div class="v" id="stat-paid">-</div></div>
      <div class="stat"><div class="k">체험 중</div><div class="v" id="stat-trial">-</div></div>
      <div class="stat"><div class="k">관리자</div><div class="v" id="stat-admin">-</div></div>
      <div class="stat"><div class="k">텔레그램 연결</div><div class="v" id="stat-tg">-</div></div>
    </div>
    <div class="toolbar"><input id="search" type="search" placeholder="이메일 또는 ID 검색"><button class="btn" type="button" id="reload">새로고침</button></div>
    <div class="msg" id="members-msg"></div>
    <div class="ledger-wrap">
      <table class="members">
        <thead><tr><th>회원</th><th>역할</th><th>플랜 · 상태</th><th>남은 기간</th><th>가입 · 최근 로그인</th><th>연결</th><th>조치</th></tr></thead>
        <tbody id="members-body"><tr><td colspan="7">불러오는 중…</td></tr></tbody>
      </table>
    </div>
  </div>
</section>
</main>
<footer><div class="shell"><span>© 2026 TradingAgents Korea · 운영자 전용</span></div></footer>
<script>{HOME_JS}</script>
<script>{MEMBERS_JS}</script>
</body>
</html>"""
