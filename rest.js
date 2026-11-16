/* Rest & travel cards, shared by the Rest & Travel page and game pages. */
window.REST=(function(){
function burden(r,visitorAlt){var s=0;if(!r)return 0;if(r.b2b)s+=2;else if(r.three_in_four)s+=1;if(r.miles>=1500)s+=1;if(Math.abs(r.tz||0)>=2)s+=1;if(visitorAlt)s+=1;return s}
function sev(g){var a=g.away_rest,h=g.home_rest;if(!a||!h)return{n:0,t:"No schedule data",side:null};
var sa=burden(a,g.altitude),sh=burden(h,false),e=Math.abs(sa-sh);if(!a.opener&&!h.opener&&Math.abs((a.rest||0)-(h.rest||0))>=2)e+=1;
var side=sa>sh||(sa===sh&&h.rest>a.rest)?g.home:(sh>sa||a.rest>h.rest)?g.away:null;
if(e>=3)return{n:3,t:"Big rest edge",side:side};if(e>=2)return{n:2,t:"Rest edge",side:side};if(e>=1)return{n:1,t:"Slight edge",side:side};return{n:0,t:"Even rest",side:null}}
function sg(v){return(v>=0?"+":"")+v}
function days(n){return n===1?"1 day":n+" days"}
function restTxt(r){return r.opener?"Opener":days(r.rest)}
function script(g){var s=[],A=g.away_rest,H=g.home_rest;if(!A||!H)return"No schedule data for this game.";
[[g.away,A],[g.home,H]].forEach(function(x){var t=x[0],r=x[1];
if(r.b2b)s.push(t+" is on the second night of a back-to-back. Tired legs tend to show up in shooting and late-game defense, and teams sometimes rest a starter.");
else if(r.three_in_four)s.push(t+" is playing its third game in four nights.");
if(r.miles>=1500)s.push(t+" traveled about "+r.miles.toLocaleString("en-US")+" miles since its last game"+(Math.abs(r.tz||0)>=2?" and crossed "+Math.abs(r.tz)+" time zones":"")+".");
if(r.opener)s.push(t+" is playing its first game of the season.");else if(r.rest>=4)s.push(t+" has had "+days(r.rest)+" off, which can mean fresh legs but also some early rust.")});
if(g.altitude)s.push(g.away+" is visiting "+g.home+", where the altitude makes the second night of a road trip harder for visitors.");
if(!s.length)return"Both teams come in on similar rest, so the matchup should matter more than the schedule.";
s.push("Check the injury report close to tip-off, since rest decisions are often announced late.");return s.join(" ")}
function hl(label,s,b){if(!s||!s.n)return"";return"<li><b>"+label+"</b> ("+s.n.toLocaleString("en-US")+" past games): covered the spread "+Math.round(s.cover*100)+"% of the time, "+sg(s.ats)+" points vs. the spread on average; the game went under the total "+Math.round(s.under*100)+"% of the time.</li>"}
function chips(t,r){var c=[];if(!r)return"";if(r.b2b)c.push('<span class="chip hot">'+t+': back-to-back</span>');else if(r.three_in_four)c.push('<span class="chip hot">'+t+': 3 in 4 nights</span>');if(r.miles>=1500)c.push('<span class="chip">'+t+': long trip</span>');return c.join("")}
function card(g,H){H=H||{};var v=sev(g),A=g.away_rest,Hr=g.home_rest,h="";
if(A&&A.b2b)h+=hl(g.away+" on a back-to-back: teams on the second night",H.b2b);
if(Hr&&Hr.b2b)h+=hl(g.home+" on a back-to-back: teams on the second night",H.b2b);
if(A&&!A.b2b&&A.three_in_four)h+=hl(g.away+" on 3 in 4: teams on their third game in four nights",H.three_in_four);
if(g.altitude)h+=hl("Visitors in Denver and Utah",H.altitude);
if(A&&Hr&&!A.opener&&!Hr.opener&&Math.abs(A.rest-Hr.rest)>=2)h+=hl("Teams with 2+ more days of rest than their opponent",H.rest_adv);
if(A&&A.miles>=1500)h+=hl("Teams traveling 1,500+ miles",H.travel);
return'<article class="cc"><div class="ch"><div><h3>'+g.away+' at '+g.home+'</h3><div class="tm">'+g.when+(g.arena?" &middot; "+g.arena:"")+'</div></div><span class="sv s'+v.n+'">'+v.t+(v.side&&v.n?": "+v.side:"")+'</span></div>'
+'<div class="chips">'+chips(g.away,A)+chips(g.home,Hr)+(g.altitude?'<span class="chip">Altitude</span>':"")+'</div>'
+(A&&Hr?'<div class="wx"><div><span class="num">'+restTxt(A)+'</span>'+g.away+' rest</div><div><span class="num">'+restTxt(Hr)+'</span>'+g.home+' rest</div><div><span class="num">'+A.miles.toLocaleString("en-US")+' mi</span>'+g.away+' travel'+(A.tz?", "+Math.abs(A.tz)+" time zone"+(Math.abs(A.tz)>1?"s":""):"")+'</div></div>':"")
+'<p><b>What to expect:</b> '+script(g)+'</p>'+(h?'<ul class="hl">'+h+'</ul>':"")+'</article>'}
var HIST={baseline:{n:7380,ats:0,cover:.5,under:.5},b2b:{n:1460,ats:-1.1,cover:.47,under:.52},three_in_four:{n:690,ats:-.6,cover:.48,under:.51},altitude:{n:330,ats:-1.4,cover:.46,under:.48},rest_adv:{n:1020,ats:.9,cover:.52,under:.5},travel:{n:560,ats:-.6,cover:.48,under:.51}};
var SR={s1:[{rest:0,b2b:true,miles:190,tz:0},{rest:1}],s2:[{rest:0,b2b:true,miles:830,tz:1},{rest:2}],s3:[{rest:1,miles:340,tz:0},{rest:1}],s4:[{rest:1,three_in_four:true,miles:270,tz:0},{rest:2}],s5:[{rest:1,miles:650,tz:1},{rest:3}],s6:[{rest:1,miles:1630,tz:0},{rest:1}]};
function fill(r){r=Object.assign({miles:0,tz:0,b2b:false,three_in_four:false},r);return r}
function sample(g){var r=SR[g.id]||[{rest:1},{rest:1}];return{id:g.id,away:g.away,home:g.home,when:g.when,arena:"",altitude:g.home==="DEN"||g.home==="UTA",away_rest:fill(r[0]),home_rest:fill(r[1])}}
return{card:card,sev:sev,sample:sample,HIST:HIST}})();
