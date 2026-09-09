"""Member billing page (`/billing`): plan status, trial, checkout, cancel, Telegram link.

The page is a server-rendered shell; the browser reads the member session
token the member pages already store (``tradingagents.member.access_token``)
and calls the billing APIs. Checkout loads the PortOne browser SDK and asks it
to issue a billing key; activation then arrives through the webhook.
"""

from __future__ import annotations

import html
import json
from typing import Any

from .billing import PLANS, RESEARCH_TOOL_NOTICES, TRIAL_DAYS
from .home_page import HOME_CSS, HOME_JS, THEMES, THEME_LABELS
from .seo import canonical_url


def _h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


BILLING_CSS = """
.billing{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(300px,.8fr);gap:28px;align-items:start}
.card{border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:20px 22px;display:flex;flex-direction:column;gap:12px}
.card h2{font-size:20px}.card .sub{color:var(--muted);font-size:13px;margin:0}
.status-line{display:flex;justify-content:space-between;gap:12px;font-size:14px;padding:6px 0;border-bottom:1px dashed var(--line)}
.status-line:last-child{border-bottom:0}
.actions{display:flex;flex-wrap:wrap;gap:10px}
.msg{font-size:13px;color:var(--ink2);min-height:18px}
.msg.error{color:var(--gain)}
.code{font-family:"IBM Plex Mono",monospace;font-size:20px;letter-spacing:.08em;padding:8px 12px;border:1px dashed var(--line-strong);border-radius:6px;display:inline-block}
.events{font-size:13px;display:flex;flex-direction:column;gap:6px}
.events div{display:flex;justify-content:space-between;gap:12px;color:var(--ink2)}
@media (max-width:900px){.billing{grid-template-columns:1fr}}
"""

BILLING_JS = """
(function(){
  var TOKEN_KEY='tradingagents.member.access_token';
  function token(){try{return localStorage.getItem(TOKEN_KEY)||sessionStorage.getItem(TOKEN_KEY)||'';}catch(e){return '';}}
  function el(id){return document.getElementById(id);}
  function say(id,text,isError){var n=el(id);if(!n)return;n.textContent=text||'';n.className='msg'+(isError?' error':'');}
  async function api(path,options){
    var t=token();
    if(!t){throw new Error('로그인이 필요합니다. 내 공간에서 로그인한 뒤 다시 열어 주세요.');}
    var opts=Object.assign({headers:{}},options||{});
    opts.headers=Object.assign({'Authorization':'Bearer '+t,'Content-Type':'application/json'},opts.headers||{});
    var r=await fetch(path,opts);
    var body=null;try{body=await r.json();}catch(e){}
    if(!r.ok){var d=body&&body.detail;throw new Error(typeof d==='string'?d:(d&&d.message)||('요청 실패 ('+r.status+')'));}
    return body;
  }
  function fmtDate(v){if(!v)return '-';try{return new Date(v).toLocaleString('ko-KR');}catch(e){return v;}}
  async function refresh(){
    try{
      var me=await api('/api/billing/me');
      var a=me.access;
      el('plan-name').textContent=a.plan.name+' ('+a.plan.id+')';
      el('plan-status').textContent={anonymous:'비로그인',free:'무료',trialing:'체험 중',active:'이용 중',past_due:'결제 실패 · 무료로 전환',canceled:'해지됨'}[a.status]||a.status;
      el('plan-period').textContent=a.status==='trialing'?('체험 종료 '+fmtDate(a.trial_ends_at)):(a.period_end?('이용 기간 종료 '+fmtDate(a.period_end)):'-');
      var ev=el('events');ev.innerHTML='';
      (me.events||[]).forEach(function(e){var d=document.createElement('div');d.innerHTML='<span>'+e.event_type+(e.message?' · '+e.message:'')+'</span><span>'+fmtDate(e.created_at)+'</span>';ev.appendChild(d);});
      if(!(me.events||[]).length){ev.textContent='아직 결제 이력이 없습니다.';}
      el('btn-cancel').hidden=!(a.status==='active'||a.status==='trialing');
      el('btn-refund').hidden=!(a.status==='active');
      el('btn-trial').hidden=!(a.status==='free');
      say('billing-msg','');
    }catch(e){say('billing-msg',e.message,true);}
    try{
      var s=await api('/api/notifications/telegram/status');
      el('tg-status').textContent=s.linked?('연결됨 · '+(s.display_name||'')):'연결 안 됨';
      el('btn-tg-unlink').hidden=!s.linked;
    }catch(e){el('tg-status').textContent='로그인 필요';}
  }
  async function checkout(plan){
    say('billing-msg','결제창을 준비하는 중…');
    try{
      var cfg=await api('/api/billing/checkout',{method:'POST',body:JSON.stringify({plan:plan})});
      if(!window.PortOne){await new Promise(function(res,rej){var s=document.createElement('script');s.src=cfg.sdk;s.onload=res;s.onerror=function(){rej(new Error('결제 SDK를 불러오지 못했습니다.'));};document.head.appendChild(s);});}
      var p=cfg.params;
      var result=await window.PortOne.requestIssueBillingKey({storeId:p.storeId,channelKey:p.channelKey,billingKeyMethod:p.billingKeyMethod,issueId:p.issueId,issueName:p.issueName,customer:p.customer,customData:p.customData,redirectUrl:p.redirectUrl});
      if(result&&result.code){throw new Error(result.message||'결제수단 등록이 취소되었습니다.');}
      say('billing-msg','결제수단이 등록되었습니다. 첫 결제가 확인되면 플랜이 활성화됩니다(보통 1분 이내).');
      setTimeout(refresh,4000);
    }catch(e){say('billing-msg',e.message,true);}
  }
  document.addEventListener('click',async function(ev){
    var b=ev.target.closest('button[data-action]');if(!b)return;
    var action=b.getAttribute('data-action');
    try{
      if(action==='trial'){await api('/api/billing/trial',{method:'POST'});say('billing-msg','14일 체험이 시작되었습니다.');refresh();}
      else if(action==='checkout'){checkout(b.getAttribute('data-plan'));}
      else if(action==='cancel'){if(!confirm('기간 종료 시 해지됩니다. 계속할까요?'))return;await api('/api/billing/cancel',{method:'POST'});say('billing-msg','기간 종료 시 해지되도록 예약했습니다.');refresh();}
      else if(action==='refund'){if(!confirm('결제 후 7일 이내면 전액, 이후에는 남은 기간만큼 환불되며 유료 플랜은 즉시 종료됩니다. 계속할까요?'))return;var r=await api('/api/billing/refund',{method:'POST'});say('billing-msg','환불 처리: '+Number(r.refunded_amount).toLocaleString('ko-KR')+'원 ('+r.basis+'). 카드사 반영까지 3~5영업일이 걸릴 수 있습니다.');refresh();}
      else if(action==='tg-link'){var r=await api('/api/notifications/telegram/link',{method:'POST'});el('tg-code').textContent=r.code;var a=el('tg-open');if(r.link_url){a.href=r.link_url;a.hidden=false;}el('tg-help').textContent=r.instructions;}
      else if(action==='tg-unlink'){await api('/api/notifications/telegram/link',{method:'DELETE'});refresh();}
    }catch(e){say('billing-msg',e.message,true);}
  });
  var form=el('password-form');
  if(form){form.addEventListener('submit',async function(ev){
    ev.preventDefault();
    var p1=el('pw1').value,p2=el('pw2').value;
    if(p1.length<8){say('pw-msg','8자 이상 입력해 주세요.',true);return;}
    if(p1!==p2){say('pw-msg','두 비밀번호가 다릅니다.',true);return;}
    var cfgEl=document.getElementById('billing-config');var cfg={};try{cfg=JSON.parse(cfgEl.textContent||'{}');}catch(e){}
    if(!cfg.supabase_url||!cfg.supabase_anon_key){say('pw-msg','인증 설정이 없어 변경할 수 없습니다.',true);return;}
    try{
      var r=await fetch(cfg.supabase_url+'/auth/v1/user',{method:'PUT',headers:{'apikey':cfg.supabase_anon_key,'Authorization':'Bearer '+token(),'Content-Type':'application/json'},body:JSON.stringify({password:p1})});
      var body=null;try{body=await r.json();}catch(e){}
      if(!r.ok){throw new Error((body&&(body.msg||body.message||body.error_description))||('변경 실패 ('+r.status+')'));}
      el('pw1').value='';el('pw2').value='';say('pw-msg','비밀번호를 변경했습니다. 다음 로그인부터 새 비밀번호를 사용하세요.');
    }catch(e){say('pw-msg',e.message,true);}
  });}
  refresh();
  var params=new URLSearchParams(location.search);
  if(params.get('plan')==='daily'||params.get('plan')==='pro'){var btn=document.querySelector('button[data-action="checkout"][data-plan="'+params.get('plan')+'"]');if(btn){btn.focus();}}
})();
"""


def render_billing_page(*, site_base_url: str | None = None) -> str:
    from .web_pages import _public_supabase_config, _script_json

    config = _public_supabase_config()
    config_json = _script_json({"supabase_url": config.get("supabase_url"), "supabase_anon_key": config.get("supabase_anon_key")})
    theme_buttons = "".join(
        f'<button type="button" class="{name}" data-theme="{name}" aria-pressed="false" aria-label="{_h(THEME_LABELS[name])} 테마" title="{_h(THEME_LABELS[name])}"></button>'
        for name in THEMES
    )
    notices = "".join(f"<li>{_h(item)}</li>" for item in RESEARCH_TOOL_NOTICES)
    daily, pro = PLANS["daily"], PLANS["pro"]
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>구독 관리 | TradingAgents Korea</title>
<link rel="canonical" href="{_h(canonical_url('/billing', site_base_url=site_base_url))}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700&family=IBM+Plex+Sans+KR:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<script>(function(){{try{{var t=localStorage.getItem('ta-theme');if(t==='paper'||t==='dark'||t==='sepia'){{document.documentElement.setAttribute('data-theme',t);}}}}catch(e){{}}}})();</script>
<style>{HOME_CSS}{BILLING_CSS}</style>
</head>
<body>
<header class="masthead">
  <div class="shell">
    <a class="brand" href="/"><span class="brand-name">TradingAgents Korea</span><span class="brand-sub">구독 관리</span></a>
    <nav class="nav" aria-label="주요 메뉴"><a href="/">오늘</a><a href="/harness">일일 하네스</a><a href="/pricing">요금제</a><a href="/mypage">내 공간</a></nav>
    <div class="mast-right"><div class="theme-switch" role="group" aria-label="페이지 테마">{theme_buttons}</div><a class="btn" href="/mypage">내 공간</a></div>
  </div>
</header>
<main id="main-content">
<section class="block">
  <div class="shell billing">
    <div class="card">
      <h2>내 플랜</h2>
      <p class="sub">이 페이지는 로그인한 회원의 브라우저 세션을 사용합니다. 카드 정보는 결제사(포트원)에만 저장됩니다.</p>
      <div class="status-line"><span>플랜</span><strong id="plan-name">확인 중…</strong></div>
      <div class="status-line"><span>상태</span><span id="plan-status">-</span></div>
      <div class="status-line"><span>기간</span><span id="plan-period">-</span></div>
      <div class="actions">
        <button class="btn primary" type="button" id="btn-trial" data-action="trial" hidden>{TRIAL_DAYS}일 무료 체험 시작</button>
        <button class="btn primary" type="button" data-action="checkout" data-plan="daily">{_h(daily.name)} 구독 · 월 {daily.price_krw:,}원</button>
        <button class="btn" type="button" data-action="checkout" data-plan="pro">{_h(pro.name)} 구독 · 월 {pro.price_krw:,}원</button>
        <button class="btn" type="button" id="btn-cancel" data-action="cancel" hidden>기간 종료 시 해지</button>
        <button class="btn" type="button" id="btn-refund" data-action="refund" hidden>환불 요청</button>
      </div>
      <div class="msg" id="billing-msg"></div>
      <h3 style="font-size:16px;margin-top:6px">결제 이력</h3>
      <div class="events" id="events">불러오는 중…</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:18px">
      <div class="card">
        <h2>텔레그램 알림</h2>
        <p class="sub">평일 아침 하네스 호가 발행되면 알려드립니다. 데일리 패스는 종목과 등급까지, 무료는 발행 안내만 받습니다.</p>
        <div class="status-line"><span>연결 상태</span><span id="tg-status">확인 중…</span></div>
        <div class="actions">
          <button class="btn primary" type="button" data-action="tg-link">연결 코드 받기</button>
          <a class="btn" id="tg-open" href="#" target="_blank" rel="noopener" hidden>텔레그램에서 열기</a>
          <button class="btn" type="button" id="btn-tg-unlink" data-action="tg-unlink" hidden>연결 해제</button>
        </div>
        <div><span class="code" id="tg-code">------</span></div>
        <div class="msg" id="tg-help">코드는 30분 동안 유효합니다.</div>
      </div>
      <div class="card">
        <h2>비밀번호 변경</h2>
        <p class="sub">로그인 세션으로 바로 변경됩니다. 8자 이상을 권장합니다.</p>
        <form id="password-form" style="display:flex;flex-direction:column;gap:10px" autocomplete="off">
          <label style="font-size:13px;color:var(--ink2)">새 비밀번호<br><input id="pw1" type="password" minlength="8" required style="width:100%;padding:10px 12px;border:1px solid var(--line-strong);border-radius:6px;background:var(--panel);color:var(--ink);font:inherit"></label>
          <label style="font-size:13px;color:var(--ink2)">새 비밀번호 확인<br><input id="pw2" type="password" minlength="8" required style="width:100%;padding:10px 12px;border:1px solid var(--line-strong);border-radius:6px;background:var(--panel);color:var(--ink);font:inherit"></label>
          <div class="actions"><button class="btn primary" type="submit">비밀번호 변경</button></div>
          <div class="msg" id="pw-msg"></div>
        </form>
      </div>
      <div class="card">
        <h2>이용 원칙</h2>
        <ul style="margin:0;padding-left:18px;font-size:13px;color:var(--ink2);display:flex;flex-direction:column;gap:6px">{notices}</ul>
        <p class="sub"><a href="/terms">이용약관</a> · <a href="/pricing">요금제 비교</a></p>
      </div>
    </div>
  </div>
</section>
</main>
<footer><div class="shell"><span>© 2026 TradingAgents Korea</span><a href="/terms">약관</a><a href="/privacy">개인정보</a></div></footer>
<script id="billing-config" type="application/json">{config_json}</script>
<script>{HOME_JS}</script>
<script>{BILLING_JS}</script>
</body>
</html>"""
