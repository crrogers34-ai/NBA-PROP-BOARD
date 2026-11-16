/* Membership check and free-preview wall. The real lock is on the server (functions/_middleware.js);
   this script only shows the right buttons and the "subscribe to continue" box. */
(function(){
var C=window.OT||{},LIM=(C.preview&&C.preview.seconds)||120,K="nba_preview_s",wall=document.currentScript&&document.currentScript.hasAttribute("data-wall");
function rd(){try{return+localStorage.getItem(K)||0}catch(e){return 0}}
function wr(v){try{localStorage.setItem(K,String(v))}catch(e){}}
fetch("/api/me",{cache:"no-store",credentials:"same-origin"}).then(function(r){return r.ok?r.json():null}).catch(function(){return null}).then(function(m){
if(!m||!m.enforce)return;
var lg=document.querySelector(".acct a[href='login.html']");
if(m.member){if(lg){lg.textContent="Log out";lg.setAttribute("href","/api/logout")}return}
if(!wall)return;
var used=rd(),shown=false;
function show(){if(shown)return;shown=true;
var d=document.createElement("div");d.id="otwall";d.setAttribute("role","dialog");d.setAttribute("aria-modal","true");d.setAttribute("aria-labelledby","otwt");
d.style.cssText="position:fixed;inset:0;z-index:1000;background:rgba(15,23,36,.82);display:flex;align-items:center;justify-content:center;padding:16px";
var nx=encodeURIComponent(location.pathname),li=m.loggedIn;
d.innerHTML='<div style="background:var(--card);color:var(--ink);border-radius:12px;max-width:420px;width:100%;padding:24px;box-shadow:0 10px 40px rgba(0,0,0,.4)">'+
'<h2 id="otwt" style="font:700 28px/1 \'Barlow Condensed\',\'Arial Narrow\',sans-serif;margin:0 0 8px">'+(li?"No active membership":"Keep going with a membership")+'</h2>'+
'<p style="color:var(--mute);margin:0 0 16px">'+(li?"You are logged in, but this account does not have an active plan. Pick one to unlock the Prop Board, Most Probable, Parlay Builder and DFS Optimizer.":"You have used your free preview. Subscribe to unlock the Prop Board, Most Probable, Parlay Builder and DFS Optimizer. Checkout creates your account.")+'</p>'+
'<a class="btn" href="pricing.html" style="display:block;text-align:center;text-decoration:none">See plans</a>'+
'<p style="margin:14px 0 0;text-align:center;font-size:14px">'+(li?'<a href="/api/login?next='+nx+'">Just subscribed? Refresh my access</a>':'Already a member? <a href="/api/login?next='+nx+'">Log in with Whop</a>')+'</p>'+
'<p style="margin:12px 0 0;text-align:center;font-size:13px"><a href="index.html">Back to the homepage</a></p></div>';
document.body.appendChild(d);document.body.style.overflow="hidden";var b=d.querySelector("a");if(b)b.focus()}
if(used>=LIM||m.loggedIn){show();return}
var t=setInterval(function(){if(document.hidden)return;used+=1;wr(used);if(used>=LIM){clearInterval(t);show()}},1000);
});
})();
