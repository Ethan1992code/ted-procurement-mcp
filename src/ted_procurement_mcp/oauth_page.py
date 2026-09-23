"""Browser consent UI for the managed Supabase authorization server."""
from starlette.responses import HTMLResponse

PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TED Procurement · 登录授权</title>
<style>body{font:16px system-ui;background:#f3f6fa;color:#172434;margin:0}main{max-width:520px;margin:8vh auto;padding:32px;background:white;border-radius:18px}h1{font-size:25px}p{line-height:1.7}input,button{box-sizing:border-box;padding:12px;border:1px solid #b8c4d4;border-radius:8px;font:inherit}input{width:100%;margin:8px 0}button{cursor:pointer;background:#143d69;color:white;margin:8px 8px 8px 0}button:disabled{opacity:.5}#status{white-space:pre-wrap}label{display:block}small{color:#526173}</style>
<main><h1>TED Procurement Intelligence</h1><p>登录后，确认是否允许应用使用采购查询与供应商机会工具。</p>
<p id="status" role="status">正在检查授权请求…</p>
<form id="login" hidden><label>登录邮箱<input id="email" type="email" autocomplete="email" required></label><button id="send">发送登录邮件</button><p><small>请在本浏览器打开邮件中的登录链接。不要把链接发送给其他人。</small></p></form>
<section id="consent" hidden><h2 id="client"></h2><p id="scopes"></p><p>授权后，该应用可以查询 TED 公告、采购机构与中标信息，读取和更新供应商档案，并同步采购数据。</p><button id="approve">同意授权</button><button id="deny">拒绝</button></section>
<button id="logout" hidden>退出登录</button></main>
<script type="module">
import {createClient} from 'https://esm.sh/@supabase/supabase-js@2.116.0';
const auth=createClient('https://tpbzknktxuodulcxencf.supabase.co','sb_publishable_fdqGcmseceLNU3GuoLV6fg_0kBsTOtY',{auth:{storage:sessionStorage,persistSession:true,detectSessionInUrl:true}}).auth;
const el=id=>document.getElementById(id), status=message=>el('status').textContent=message;
const id=new URL(location.href).searchParams.get('authorization_id');
let details;
function redirect(url){const target=new URL(url);if(target.protocol!=='https:')throw Error('授权返回地址不安全');location.assign(target.href)}
async function load(){
 if(!id||!/^[a-zA-Z0-9_-]{8,128}$/.test(id)){status('授权页面已就绪。请从 ChatGPT 发起连接，不要直接在此登录。');return}
 const {data,error}=await auth.getUser();
 if(error||!data.user){el('login').hidden=false;status('请登录以继续授权。');return}
 el('logout').hidden=false;
 if(data.user.email?.toLowerCase()!=='starsealand02@aliyun.com'||!data.user.email_confirmed_at){status('当前账号未获准使用此服务，请退出并使用项目所有者邮箱登录。');return}
 el('login').hidden=true;
 const result=await auth.oauth.getAuthorizationDetails(id);
 if(result.error)throw result.error;
 details=result.data;
 if(details.redirect_url){status('此应用已获授权，正在返回…');redirect(details.redirect_url);return}
 el('client').textContent=details.client?.name||details.client?.client_name||'应用授权请求';
 el('scopes').textContent='请求权限：'+(details.scope||'未提供');
 el('consent').hidden=false;status('请核对应用和权限后选择。');
}
el('login').onsubmit=async event=>{event.preventDefault();el('send').disabled=true;try{
 const email=el('email').value.trim().toLowerCase();
 if(email!=='starsealand02@aliyun.com')throw Error('请使用项目所有者邮箱。');
 const redirectTo=location.origin+'/oauth/consent?authorization_id='+encodeURIComponent(id);
 const {error}=await auth.signInWithOtp({email,options:{emailRedirectTo:redirectTo,shouldCreateUser:true}});
 if(error)throw error;status('邮件请求已发送。请检查收件箱及垃圾邮件，并在本浏览器打开登录链接。');
 }catch(error){status(error.message||'发送失败，请稍后重试')}finally{el('send').disabled=false}};
async function decide(approve){el('approve').disabled=el('deny').disabled=true;try{
 const result=approve?await auth.oauth.approveAuthorization(id,{skipBrowserRedirect:true}):await auth.oauth.denyAuthorization(id,{skipBrowserRedirect:true});
 if(result.error)throw result.error;redirect(result.data.redirect_url);
 }catch(error){status(error.message||'授权失败');el('approve').disabled=el('deny').disabled=false}}
el('approve').onclick=()=>decide(true);el('deny').onclick=()=>decide(false);
el('logout').onclick=async()=>{await auth.signOut({scope:'local'});location.replace(location.pathname+location.search)};
load().catch(error=>status(error.message||'无法加载授权请求'));
</script></html>'''


async def consent_page(_request):
    return HTMLResponse(PAGE, headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline' https://esm.sh; style-src 'unsafe-inline'; connect-src https://tpbzknktxuodulcxencf.supabase.co; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    })
