"""Member billing page (`/billing`): plan status, trial, checkout, cancel, Telegram link.

The page is a server-rendered shell; the browser reads the member session
token the member pages already store (``tradingagents.member.access_token``)
and calls the billing APIs. Checkout loads the PortOne browser SDK and asks it
to issue a billing key; activation then arrives through the webhook.
"""

from __future__ import annotations

from .billing import PLANS, RESEARCH_TOOL_NOTICES, TRIAL_DAYS
from .design_system import badge, h, icon, icon_tile, render_shell

BILLING_CSS = """
.billing-head { padding: 26px 0 18px; }
.billing-head h1 { font-size: 24px; }
.plan-hero { display: flex; justify-content: space-between; gap: 16px; align-items: flex-end; flex-wrap: wrap; }
.plan-hero .big { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.code { font-family: "Pretendard Variable", Pretendard, monospace; font-size: 22px; letter-spacing: .12em; padding: 8px 14px; border: 1px dashed var(--line-strong); border-radius: 8px; display: inline-block; font-variant-numeric: tabular-nums; }
.events { display: grid; gap: 0; font-size: 13px; }
.events > div { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--line); color: var(--ink2); }
.events > div:last-child { border-bottom: 0; }
.pw-form { display: grid; gap: 10px; }
.pw-form label { font-size: 12px; color: var(--muted); display: grid; gap: 6px; }
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
  function daysLeft(v){if(!v)return null;var d=Math.ceil((new Date(v)-new Date())/86400000);return d<0?0:d;}
  async function refresh(){
    try{
      var me=await api('/api/billing/me');
      var a=me.access;
      var statusText={anonymous:'비로그인',free:'무료',trialing:'체험 중',active:'이용 중',past_due:'결제 실패 · 무료로 전환',canceled:'해지됨'}[a.status]||a.status;
      el('plan-name').textContent=a.plan.name;
      var badge=el('plan-status');badge.textContent=statusText;badge.className='badge '+(a.status==='trialing'?'b-amber':(a.status==='active'&&a.plan.id!=='free'?'b-teal':'b-grey'));
      var end=a.status==='trialing'?a.trial_ends_at:a.period_end;var left=daysLeft(end);
      el('plan-days').textContent=left==null?'–':left;
      el('plan-period').textContent=a.status==='trialing'?('체험 종료 '+fmtDate(a.trial_ends_at)):(a.period_end?('이용 기간 종료 '+fmtDate(a.period_end)):'기간 없음 · 무료 플랜');
      var bar=el('plan-bar');if(bar){bar.style.width=(left==null?0:Math.max(0,Math.min(100,left/30*100)))+'%';}
      var ev=el('events');ev.innerHTML='';
      (me.events||[]).forEach(function(e){var d=document.createElement('div');d.innerHTML='<span>'+e.event_type+(e.message?' · '+e.message:'')+'</span><span class="num">'+fmtDate(e.created_at)+'</span>';ev.appendChild(d);});
      if(!(me.events||[]).length){ev.textContent='아직 결제 이력이 없습니다.';}
      el('btn-cancel').hidden=!(a.status==='active'||a.status==='trialing');
      el('btn-refund').hidden=!(a.status==='active');
      el('btn-trial').hidden=!(a.status==='free');
      if(me.is_admin){document.querySelectorAll('[data-admin-only]').forEach(function(n){n.hidden=false;});}
      say('billing-msg','');
    }catch(e){say('billing-msg',e.message,true);}
    try{
      var s=await api('/api/notifications/telegram/status');
      var tg=el('tg-status');tg.textContent=s.linked?('연결됨 · '+(s.display_name||'')):'연결 안 됨';tg.className='badge '+(s.linked?'b-teal':'b-grey');
      el('btn-tg-unlink').hidden=!s.linked;
    }catch(e){var tg2=el('tg-status');tg2.textContent='로그인 필요';tg2.className='badge b-grey';}
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
    notices = "".join(f"<li>{h(item)}</li>" for item in RESEARCH_TOOL_NOTICES)
    daily, pro = PLANS["daily"], PLANS["pro"]
    body = f"""
<section class="hero billing-head">
  <div class="shell row between wrap">
    <div>{badge("내 공간 · 구독 관리", "b-teal")}<h1 style="margin-top: 8px;">구독 관리</h1><p class="small ink2" style="margin-top: 4px;">로그인한 회원의 브라우저 세션을 사용합니다. 카드 정보는 결제사(포트원)에만 저장됩니다.</p></div>
    <div class="row"><a class="btn sm" href="/mypage">{icon("users", 14)}내 공간</a><a class="btn sm" href="/pricing">요금제 비교</a></div>
  </div>
</section>
<section class="block" style="padding-bottom: 28px;">
  <div class="shell grid-main">
    <div class="stack">
      <div class="card">
        <div class="card-h"><h2>{icon_tile("card", "b-teal", small=True)}내 플랜</h2><span class="badge b-grey" id="plan-status">확인 중…</span></div>
        <div class="card-b">
          <div class="plan-hero">
            <div><p class="label">플랜</p><p class="big" id="plan-name">확인 중…</p><p class="tiny muted" id="plan-period">-</p></div>
            <div style="text-align: right;"><p class="label">남은 기간</p><p class="big num"><span id="plan-days">–</span><span class="muted" style="font-size: 13px; font-weight: 500;">일</span></p></div>
          </div>
          <div class="bar" style="margin-top: 12px;"><i id="plan-bar" style="width: 0%;"></i></div>
          <div class="actions" style="margin-top: 16px;">
            <button class="btn primary" type="button" id="btn-trial" data-action="trial" hidden>{TRIAL_DAYS}일 무료 체험 시작</button>
            <button class="btn primary" type="button" data-action="checkout" data-plan="daily">{h(daily.name)} 구독 · 월 {daily.price_krw:,}원</button>
            <button class="btn" type="button" data-action="checkout" data-plan="pro">{h(pro.name)} 구독 · 월 {pro.price_krw:,}원</button>
            <button class="btn" type="button" id="btn-cancel" data-action="cancel" hidden>기간 종료 시 해지</button>
            <button class="btn" type="button" id="btn-refund" data-action="refund" hidden>환불 요청</button>
          </div>
          <div class="msg" id="billing-msg" style="margin-top: 10px;"></div>
        </div>
      </div>
      <div class="card">
        <div class="card-h"><h2>{icon_tile("clock", "b-grey", small=True)}결제 이력</h2></div>
        <div class="card-b" style="padding-top: 6px;"><div class="events" id="events">불러오는 중…</div></div>
      </div>
    </div>
    <div class="stack">
      <div class="card">
        <div class="card-h"><h2>{icon_tile("send", "b-blue", small=True)}텔레그램 알림</h2><span class="badge b-grey" id="tg-status">확인 중…</span></div>
        <div class="card-b">
          <p class="small ink2">평일 아침 하네스가 발행되면 알려드립니다. 데일리 패스는 종목과 등급까지, 무료는 발행 안내만 받습니다.</p>
          <div class="actions" style="margin-top: 12px;">
            <button class="btn primary sm" type="button" data-action="tg-link">연결 코드 받기</button>
            <a class="btn sm" id="tg-open" href="#" target="_blank" rel="noopener" hidden>텔레그램에서 열기</a>
            <button class="btn sm" type="button" id="btn-tg-unlink" data-action="tg-unlink" hidden>연결 해제</button>
          </div>
          <div style="margin-top: 12px;"><span class="code" id="tg-code">------</span></div>
          <div class="msg" id="tg-help" style="margin-top: 6px;">코드는 30분 동안 유효합니다.</div>
        </div>
      </div>
      <div class="card">
        <div class="card-h"><h2>{icon_tile("lock", "b-violet", small=True)}비밀번호 변경</h2></div>
        <div class="card-b">
          <form id="password-form" class="pw-form" autocomplete="off">
            <label>새 비밀번호<input class="field" id="pw1" type="password" minlength="8" required></label>
            <label>새 비밀번호 확인<input class="field" id="pw2" type="password" minlength="8" required></label>
            <div class="actions"><button class="btn primary sm" type="submit">비밀번호 변경</button></div>
            <div class="msg" id="pw-msg"></div>
          </form>
        </div>
      </div>
      <div class="soft" style="padding: 14px 16px;">
        <p class="label">이용 원칙</p>
        <ul style="margin: 8px 0 0; padding-left: 18px; font-size: 12px; color: var(--ink2); display: grid; gap: 4px;">{notices}</ul>
        <p class="tiny" style="margin-top: 8px;"><a class="link" href="/terms">이용약관</a> · <a class="link" href="/pricing">요금제 비교</a></p>
      </div>
    </div>
  </div>
</section>
"""
    return render_shell(
        title="구독 관리 | TradingAgents Korea",
        body=body,
        canonical_path="/billing",
        site_base_url=site_base_url,
        noindex=True,
        extra_css=BILLING_CSS,
        extra_head=f'<script id="billing-config" type="application/json">{config_json}</script>',
        extra_js=BILLING_JS,
    )
