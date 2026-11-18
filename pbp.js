/* Play-by-play simulator for game pages.
   PBP.mount(element, {away, home, when, spread, total, targetAway, targetHome, players:[{n,t,min,proj:{...}}], sample})
   Plays one game possession by possession from the player projections, with shooting tuned so the
   average score matches the betting market. */
(function(){
var NICK={ATL:"Hawks",BOS:"Celtics",BKN:"Nets",CHA:"Hornets",CHI:"Bulls",CLE:"Cavaliers",DAL:"Mavericks",DEN:"Nuggets",DET:"Pistons",GSW:"Warriors",HOU:"Rockets",IND:"Pacers",LAC:"Clippers",LAL:"Lakers",MEM:"Grizzlies",MIA:"Heat",MIL:"Bucks",MIN:"Timberwolves",NOP:"Pelicans",NYK:"Knicks",OKC:"Thunder",ORL:"Magic",PHI:"76ers",PHX:"Suns",POR:"Trail Blazers",SAC:"Kings",SAS:"Spurs",TOR:"Raptors",UTA:"Jazz",WAS:"Wizards"};
var Q_LEN=720,OT_LEN=300;
var TWO=[["driving layup",0,4],["layup",0,3],["dunk",0,2],["floating jump shot",6,12],["pullup jump shot",12,19],["turnaround hook shot",4,9],["step back jump shot",14,20],["cutting layup",0,2],["jump shot",15,21]];
/* weights over TWO for bigs and for guards; everyone else picks evenly */
var BIG=[1,2,3,.4,.4,2.2,.2,2,.4],GUARD=[2.2,1,.5,1.6,2,.2,1.6,.5,1.4];
var CAT={"driving layup":"Layup","layup":"Layup","cutting layup":"Layup","dunk":"Dunk","floating jump shot":"Floater","pullup jump shot":"Jump shot","step back jump shot":"Jump shot","jump shot":"Jump shot","turnaround hook shot":"Hook shot"};
var THREE=[["three point jumper",24,27],["pullup three",25,28],["step back three",25,29],["corner three",22,23]];
function esc(x){return String(x==null?"":x).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function nick(t){return NICK[t]||t}
function rng(seed){var a=seed>>>0;return function(){a|=0;a=a+0x6D2B79F5|0;var t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
function pick(R,list,w){var s=0,i;for(i=0;i<list.length;i++)s+=w(list[i]);var x=R()*s;for(i=0;i<list.length;i++){x-=w(list[i]);if(x<=0)return list[i]}return list[list.length-1]}
function between(R,a,b){return a+Math.floor(R()*(b-a+1))}
function mmss(s){s=Math.max(0,Math.round(s));return Math.floor(s/60)+":"+("0"+s%60).slice(-2)}
function qName(p){return p<=4?["1st","2nd","3rd","4th"][p-1]+" quarter":(p===5?"overtime":(p-4)+"OT")}

function team(code,players){
  var P=players.filter(function(p){return p.t===code&&p.proj&&(p.min||0)>=1}).map(function(p){var j=p.proj;
    return{n:p.n,start:!!p.start,min:Math.min(p.min,40),pts:j.Points||0,reb:j.Rebounds||0,ast:j.Assists||0,tpm:j["3PM"]||0,stl:j.Steals||0,blk:j.Blocks||0,tov:j.Turnovers||0}})
    .sort(function(a,b){return b.min-a.min});
  var used=P.reduce(function(a,p){return a+p.min},0);
  if(used>240){P.forEach(function(p){p.min*=240/used});used=240}
  var left=240-used;
  if(left>2)P.push({n:"Bench",min:left,pts:.36*left,reb:.17*left,ast:.08*left,tpm:.04*left,stl:.03*left,blk:.02*left,tov:.05*left,bench:true});
  P.forEach(function(p){var m=Math.max(p.min,1);
    p.r={two:Math.max(.05,(p.pts-3*p.tpm)/m),three:Math.max(.005,p.tpm/m),reb:p.reb/m,ast:p.ast/m,stl:p.stl/m,blk:p.blk/m,tov:p.tov/m};
    p.kw=p.r.reb>.24&&p.r.three<.045?BIG:(p.r.ast>.15||p.r.three>.07?GUARD:null)});
  var st=P.filter(function(p){return p.start&&!p.bench});
  P.starters=(st.length>=5?st:P.filter(function(p){return!p.bench})).slice(0,5);
  var tov=P.reduce(function(a,p){return a+p.tov},0),tpm=P.reduce(function(a,p){return a+p.tpm},0);
  return{code:code,P:P,pTO:Math.min(.17,Math.max(.10,tov/100)),f3:Math.min(.5,Math.max(.32,(tpm/.36)/86)),k:1};
}

function Engine(cfg){
  var AWAY=cfg.away,HOME=cfg.home,T={};T[AWAY]=team(AWAY,cfg.players);T[HOME]=team(HOME,cfg.players);
  var TARGET={};TARGET[AWAY]=cfg.targetAway;TARGET[HOME]=cfg.targetHome;
  function play(seed,log,opt){opt=opt||{};
    var R=rng(seed),S={},ev=[],flow=[],line={},score={};line[AWAY]=[];line[HOME]=[];score[AWAY]=0;score[HOME]=0;
    [AWAY,HOME].forEach(function(c){T[c].P.forEach(function(p){S[c+"|"+p.n]={n:p.n,min:0,pts:0,reb:0,ast:0,stl:0,blk:0,tov:0,fgm:0,fga:0,tpm:0,tpa:0,ftm:0,fta:0,bench:p.bench}})});
    var tipHome=opt.tipHome==null?.5:opt.tipHome,on={},period=1,clock=Q_LEN,elapsed=0,nextSub=0,off=R()<tipHome?HOME:AWAY,firstOff=off,first=null;
    function st(c,p){return S[c+"|"+p.n]}
    function addPts(c,n){score[c]+=n;line[c][period-1]=(line[c][period-1]||0)+n}
    function say(c,text,scoring){if(log)ev.push({p:period,ck:clock,t:c,x:text,sc:!!scoring,a:score[AWAY],h:score[HOME]})}
    function rotate(force){var margin=Math.abs(score[HOME]-score[AWAY]);
      [AWAY,HOME].forEach(function(c){var P=T[c].P,choose,real=P.filter(function(p){return!p.bench});
        if(force&&(period===1||period===3)&&real.length>=5)choose=P.starters;
        else if(period>=4&&clock<=300&&margin<=10&&real.length>=5)choose=real.slice(0,5);
        else if(period>=4&&clock<=360&&margin>=22)choose=P.slice().sort(function(a,b){return(a.bench?-1:0)-(b.bench?-1:0)||a.min-b.min}).slice(0,5);
        else{var horizon=Math.min(elapsed+240,2880);choose=P.map(function(p){return{p:p,need:p.min*60*horizon/2880-st(c,p).min*60+R()*90}}).sort(function(a,b){return b.need-a.need}).slice(0,5).map(function(x){return x.p})}
        on[c]=choose});
      nextSub=elapsed+between(R,150,300)}
    rotate(true);
    if(log)ev.push({p:1,ck:Q_LEN,t:null,x:"Start of the 1st quarter. "+nick(firstOff)+" win the tip.",a:0,h:0});
    var guard=0;
    while(guard++<700){
      if(clock<=0){
        if(log)ev.push({p:period,ck:0,t:null,x:"End of "+qName(period)+". "+AWAY+" "+score[AWAY]+", "+HOME+" "+score[HOME],a:score[AWAY],h:score[HOME]});
        if(period>=4&&score[AWAY]!==score[HOME])break;
        period++;clock=period<=4?Q_LEN:OT_LEN;off=period%2===0?(firstOff===HOME?AWAY:HOME):firstOff;
        rotate(true);if(log)ev.push({p:period,ck:clock,t:null,x:"Start of "+qName(period),a:score[AWAY],h:score[HOME]});continue}
      if(elapsed>=nextSub&&period<=4&&clock>45)rotate(false);
      var def=off===HOME?AWAY:HOME,O=on[off],D=on[def],tm=T[off],second=false,evStart=ev.length,clock0=clock;
      var tPoss=Math.min(clock,between(R,6,22));
      if(clock<=24&&clock>2&&R()<.7)tPoss=Math.max(1,clock-between(R,0,2));
      for(;;){
        var r=R();
        if(!second&&r<tm.pTO){
          var to=pick(R,O,function(p){return p.r.tov+.01});st(off,to).tov++;
          if(R()<.55){var sp=pick(R,D,function(p){return p.r.stl+.005});st(def,sp).stl++;say(off,to.n+" bad pass ("+sp.n+" steals)")}
          else say(off,to.n+" "+["lost ball turnover","traveling","offensive foul","out of bounds"][between(R,0,3)]);
          break}
        if(!second&&r<tm.pTO+.105){
          var fs=pick(R,O,function(p){return p.r.two+p.r.three*1.5}),fl=pick(R,D,function(){return 1}),made=0;
          for(var f=0;f<2;f++){st(off,fs).fta++;if(R()<.78){made++;st(off,fs).ftm++;st(off,fs).pts++;addPts(off,1)}}
          say(off,fs.n+" makes "+made+" of 2 free throws (foul on "+fl.n+")",made>0);break}
        var isThree=R()<tm.f3,sh=pick(R,O,function(p){return isThree?p.r.three:p.r.two}),ss=st(off,sh);
        var lead=Math.max(-20,Math.min(20,score[def]-score[off]));
        var q=(isThree?.355:.535)*tm.k*(second?1.06:1)*(1+.006*lead),make=R()<q;
        var kind=isThree?THREE[between(R,0,THREE.length-1)]:(sh.kw?pick(R,TWO,function(k){return sh.kw[TWO.indexOf(k)]}):TWO[between(R,0,TWO.length-1)]),ft=between(R,kind[1],kind[2]);
        var desc=(ft>=3?ft+"-foot ":"")+kind[0];
        ss.fga++;if(isThree)ss.tpa++;
        if(make){var pts=isThree?3:2;ss.fgm++;if(isThree)ss.tpm++;ss.pts+=pts;addPts(off,pts);
          var helper=null;if(R()<(isThree?.82:.55)){helper=pick(R,O.filter(function(p){return p!==sh}),function(p){return p.r.ast+.003});st(off,helper).ast++}
          var txt=sh.n+" makes "+desc+(helper?" ("+helper.n+" assists)":"");
          if(!isThree&&R()<.035){ss.fta++;if(R()<.78){ss.ftm++;ss.pts++;addPts(off,1);txt+=", and one"}else txt+=", misses the and-one"}
          say(off,txt,true);
          if(opt.stopFirst){first={n:sh.n,t:off,bench:!!sh.bench,cat:isThree?"Three":(CAT[kind[0]]||"Jump shot"),desc:desc,assist:helper?helper.n:null,and1:/and one$/.test(txt)}}
          break}
        if(!isThree&&R()<.085){var bl=pick(R,D,function(p){return p.r.blk+.003});st(def,bl).blk++;say(off,bl.n+" blocks "+sh.n+"'s "+desc)}
        else say(off,sh.n+" misses "+desc);
        if(R()<.235){var orb=pick(R,O,function(p){return p.r.reb+.01});st(off,orb).reb++;say(off,orb.n+" offensive rebound");second=true;tPoss+=between(R,2,7);continue}
        var drb=pick(R,D,function(p){return p.r.reb+.01});st(def,drb).reb++;say(def,drb.n+" defensive rebound");break}
      tPoss=Math.min(tPoss,clock);clock-=tPoss;elapsed+=tPoss;
      O.forEach(function(p){st(off,p).min+=tPoss/60});D.forEach(function(p){st(def,p).min+=tPoss/60});
      if(log){var nE=ev.length-evStart;for(var j=0;j<nE;j++)ev[evStart+j].ck=Math.round(clock0-tPoss*(j+1)/nE)}
      flow.push([elapsed,score[HOME]-score[AWAY]]);
      if(first){first.ck=clock;first.p=period;break}
      off=def}
    return{seed:seed,score:score,line:line,ev:ev,flow:flow,S:S,periods:period,first:first,firstOff:firstOff}}
  function calibrate(){for(var it=0;it<4;it++){var sum={},n=300;sum[AWAY]=0;sum[HOME]=0;
    for(var i=0;i<n;i++){var g=play(1000+i+it*7919,false);sum[AWAY]+=g.score[AWAY];sum[HOME]+=g.score[HOME]}
    [AWAY,HOME].forEach(function(c){T[c].k*=Math.pow(TARGET[c]/(sum[c]/n),.85)})}}
  return{play:play,calibrate:calibrate,T:T,AWAY:AWAY,HOME:HOME}}

function mount(root,cfg){
  if(root._stop)root._stop();
  var E=Engine(cfg),A=cfg.away,H=cfg.home,G=null,qSel="all",boxT=A,timer=null;
  if(E.T[A].P.length<6||E.T[H].P.length<6){root.innerHTML='<p class="sub">The play-by-play sim appears once player projections for both teams are loaded.</p>';return}
  root.innerHTML='<p class="sub">One possible version of this game, played possession by possession from the player projections. Shooting is tuned so the average score matches the betting market ('+H+(cfg.spread>=0?" −":" +")+Math.abs(cfg.spread)+', total '+cfg.total+'). Every run plays out differently.</p>'
  +'<div class="ps-board" aria-live="polite"><div class="ps-tm ps-a"><div class="ps-ab">'+A+' &middot; '+esc(nick(A)).toUpperCase()+'</div><div class="ps-sc" data-r="sa">0</div></div>'
  +'<div class="ps-mid"><div class="ps-st" data-r="st">Setting up…</div><div data-r="lead"></div></div>'
  +'<div class="ps-tm ps-h"><div class="ps-ab">'+H+' &middot; '+esc(nick(H)).toUpperCase()+'</div><div class="ps-sc" data-r="sh">0</div></div></div>'
  +'<div class="ps-ls"><table data-r="ls"></table></div>'
  +'<div class="ps-ctl"><button class="btn" data-r="new" style="padding:8px 14px">Simulate a new game</button><button class="btn alt" data-r="watch" style="padding:8px 14px">Watch it play out</button>'
  +'<select data-r="spd" aria-label="Playback speed"><option value="90">Fast</option><option value="35" selected>Normal</option><option value="12">Slow</option></select><span class="tm" data-r="seed"></span></div>'
  +'<h3 class="tr3" style="margin-top:16px">Game flow</h3><div class="ps-flow"><div data-r="flow"></div><div class="ps-key"><span><i style="background:var(--home)"></i>'+esc(nick(H))+' lead</span><span><i style="background:var(--away)"></i>'+esc(nick(A))+' lead</span></div></div>'
  +'<h3 class="tr3" style="margin-top:16px">Play-by-play</h3><div class="seg" data-r="qtabs"></div>'
  +'<div class="ps-ctl"><label class="tm"><input type="checkbox" data-r="only"> Scoring plays only</label><select data-r="who" aria-label="Filter by player"></select></div>'
  +'<div class="ps-pbp" data-r="pbp"></div>'
  +'<h3 class="tr3" style="margin-top:16px">Sim box score</h3><div class="seg" data-r="btabs"><button data-t="'+A+'" aria-pressed="true">'+esc(nick(A))+'</button><button data-t="'+H+'" aria-pressed="false">'+esc(nick(H))+'</button></div>'
  +'<div class="tw"><table class="ps-box" data-r="box"></table></div>'
  +'<h3 class="tr3" style="margin-top:16px">Over 1,000 sims</h3><div class="ps-chk" data-r="chk"><div><span class="num">…</span>running</div></div>'
  +'<p class="sub" style="font-size:13px;margin-top:10px">'+(cfg.sample?"Sample data. ":"")+'Each possession puts five players on the floor using rotations that track projected minutes, with starters closing tight games and benches finishing blowouts. Who shoots, scores, rebounds, assists, steals and blocks is weighted by each player\'s projected per-minute numbers. A trailing team shoots slightly better than a leading one, as comebacks and garbage time tend to go. Players outside the projected rotation are grouped as "Bench." One simulated game is one possible outcome, not a prediction.</p>';
  function $(k){return root.querySelector('[data-r="'+k+'"]')}
  function header(a,h,txt){$("sa").textContent=a;$("sh").textContent=h;$("st").textContent=txt;var d=h-a;$("lead").textContent=d===0?"Tied":(d>0?H+" by "+d:A+" by "+(-d))}
  function flowSVG(g,upto){
    var W=900,Ht=220,top=16,bot=Ht-26,mid=(top+bot)/2,maxT=Math.max(2880,g.flow.length?g.flow[g.flow.length-1][0]:2880);
    var pts=upto==null?g.flow:g.flow.slice(0,upto),mx=Math.max(10,Math.ceil(Math.max.apply(null,g.flow.map(function(f){return Math.abs(f[1])}).concat([0]))/5)*5);
    function x(t){return 30+t/maxT*(W-40)}function y(v){return mid-v/mx*(bot-top)/2}
    var s='<svg viewBox="0 0 '+W+' '+Ht+'" role="img" aria-label="Score margin over the game">';
    [mx,mx/2,-mx/2,-mx].forEach(function(v){s+='<line x1="30" x2="'+(W-10)+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="var(--line)" stroke-dasharray="3 4"/><text x="24" y="'+(y(v)+4)+'" font-size="11" fill="var(--mute)" text-anchor="end">'+Math.abs(v)+'</text>'});
    for(var q=1;q<=4;q++){var xx=x(q*720);if(q<4||maxT>2880)s+='<line x1="'+xx+'" x2="'+xx+'" y1="'+top+'" y2="'+bot+'" stroke="var(--line)"/>';s+='<text x="'+x(q*720-360)+'" y="'+(Ht-8)+'" font-size="12" fill="var(--mute)" text-anchor="middle">Q'+q+'</text>'}
    if(maxT>2880)s+='<text x="'+x((2880+maxT)/2)+'" y="'+(Ht-8)+'" font-size="12" fill="var(--mute)" text-anchor="middle">OT</text>';
    s+='<line x1="30" x2="'+(W-10)+'" y1="'+mid+'" y2="'+mid+'" stroke="var(--mute)"/>';
    if(pts.length){var d="M"+x(0)+","+mid,prev=0,cid="c"+Math.floor(Math.random()*1e6);pts.forEach(function(f){d+=" L"+x(f[0]).toFixed(1)+","+y(prev).toFixed(1)+" L"+x(f[0]).toFixed(1)+","+y(f[1]).toFixed(1);prev=f[1]});
      var close=" L"+x(pts[pts.length-1][0]).toFixed(1)+","+mid+" Z";
      s+='<defs><clipPath id="'+cid+'u"><rect x="0" y="0" width="'+W+'" height="'+mid+'"/></clipPath><clipPath id="'+cid+'d"><rect x="0" y="'+mid+'" width="'+W+'" height="'+(Ht-mid)+'"/></clipPath></defs>';
      s+='<path d="'+d+close+'" fill="var(--home)" opacity=".25" clip-path="url(#'+cid+'u)"/><path d="'+d+close+'" fill="var(--away)" opacity=".25" clip-path="url(#'+cid+'d)"/>';
      s+='<path d="'+d+'" fill="none" stroke="var(--home)" stroke-width="2" clip-path="url(#'+cid+'u)"/><path d="'+d+'" fill="none" stroke="var(--away)" stroke-width="2" clip-path="url(#'+cid+'d)"/>';
      var lf=pts[pts.length-1];s+='<circle cx="'+x(lf[0])+'" cy="'+y(lf[1])+'" r="4" fill="'+(lf[1]>=0?"var(--home)":"var(--away)")+'"/>'}
    return s+'</svg>'}
  function partial(g,i){var L={},sc={},base={a:0,h:0},last={a:0,h:0},cur=0;L[A]=[];L[H]=[];
    for(var k=0;k<i;k++){var e=g.ev[k];if(e.p!==cur){base={a:last.a,h:last.h};cur=e.p}
      L[A][e.p-1]=e.a-base.a;L[H][e.p-1]=e.h-base.h;last={a:e.a,h:e.h}}
    sc[A]=last.a;sc[H]=last.h;return{line:L,score:sc}}
  function lineScore(g){var n=Math.max(4,g.line[A].length,g.line[H].length),hd='<tr><th></th>';for(var i=0;i<n;i++)hd+='<th>'+(i<4?"Q"+(i+1):(i===4?"OT":"OT"+(i-3)))+'</th>';hd+='<th>T</th></tr>';
    function row(c){var r='<tr><td class="num">'+c+'</td>';for(var i=0;i<n;i++)r+='<td>'+(g.line[c][i]==null?"":g.line[c][i])+'</td>';return r+'<td class="num">'+g.score[c]+'</td></tr>'}
    return'<thead>'+hd+'</thead><tbody>'+row(A)+row(H)+'</tbody>'}
  function drawAll(){var g=G;header(g.score[A],g.score[H],"Final"+(g.periods>4?(g.periods===5?"/OT":"/"+(g.periods-4)+"OT"):""));
    $("ls").innerHTML=lineScore(g);$("flow").innerHTML=flowSVG(g);$("seed").textContent="Game #"+g.seed;
    var qs=["all"];for(var p=1;p<=g.periods;p++)qs.push(p);
    $("qtabs").innerHTML=qs.map(function(q){return'<button data-q="'+q+'" aria-pressed="'+(String(qSel)===String(q))+'">'+(q==="all"?"Full game":(q<=4?"Q"+q:"OT"))+'</button>'}).join("");
    var who=$("who"),keep=who.value;
    who.innerHTML='<option value="">All players</option>'+[A,H].map(function(c){return'<optgroup label="'+esc(nick(c))+'">'+E.T[c].P.filter(function(p){return!p.bench}).map(function(p){return'<option'+(p.n===keep?" selected":"")+'>'+esc(p.n)+'</option>'}).join("")+'</optgroup>'}).join("");
    drawPBP();drawBox()}
  function drawPBP(limit){var g=G,only=$("only").checked,who=$("who").value;
    var L=(limit==null?g.ev:g.ev.slice(0,limit)).filter(function(e){return(qSel==="all"||e.p===+qSel)&&(!only||e.sc||!e.t)&&(!who||!e.t||e.x.indexOf(who)>=0)});
    var h="",lastP=null;L.forEach(function(e){if(e.p!==lastP&&qSel==="all"){h+='<div class="ps-pl ps-q">'+qName(e.p).toUpperCase()+'</div>';lastP=e.p}
      if(!e.t){h+='<div class="ps-pl"><span class="ps-ck">'+mmss(e.ck)+'</span><span></span><span class="ps-x" style="color:var(--mute)">'+esc(e.x)+'</span><span class="ps-s"></span></div>';return}
      h+='<div class="ps-pl '+(e.t===H?"ps-h":"ps-a")+(e.sc?" ps-scr":"")+'"><span class="ps-ck">'+mmss(e.ck)+'</span><span class="ps-t">'+e.t+'</span><span class="ps-x">'+esc(e.x)+'</span><span class="ps-s">'+e.a+'&ndash;'+e.h+'</span></div>'});
    var el=$("pbp");el.innerHTML=h||'<div class="ps-pl"><span></span><span></span><span class="ps-x">No plays match.</span></div>';if(limit!=null)el.scrollTop=el.scrollHeight}
  function drawBox(){var g=G,c=boxT,rows=E.T[c].P.map(function(p){return g.S[c+"|"+p.n]}),best={};
    ["pts","reb","ast"].forEach(function(k){best[k]=Math.max.apply(null,rows.map(function(r){return r.bench?0:r[k]}))});
    function cell(r,k){return'<td'+(r[k]===best[k]&&r[k]>0&&!r.bench?' class="ps-hi"':'')+'>'+r[k]+'</td>'}
    var h='<thead><tr><th>Player</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TO</th><th>FG</th><th>3PT</th><th>FT</th></tr></thead><tbody>';
    rows.forEach(function(r){h+='<tr><td class="nm">'+esc(r.n)+'</td><td>'+Math.round(r.min)+'</td>'+cell(r,"pts")+cell(r,"reb")+cell(r,"ast")+'<td>'+r.stl+'</td><td>'+r.blk+'</td><td>'+r.tov+'</td><td>'+r.fgm+'-'+r.fga+'</td><td>'+r.tpm+'-'+r.tpa+'</td><td>'+r.ftm+'-'+r.fta+'</td></tr>'});
    var t={};["pts","reb","ast","stl","blk","tov","fgm","fga","tpm","tpa","ftm","fta"].forEach(function(k){t[k]=rows.reduce(function(a,r){return a+r[k]},0)});
    h+='<tr class="ps-tot"><td>Team</td><td>240</td><td>'+t.pts+'</td><td>'+t.reb+'</td><td>'+t.ast+'</td><td>'+t.stl+'</td><td>'+t.blk+'</td><td>'+t.tov+'</td><td>'+t.fgm+'-'+t.fga+'</td><td>'+t.tpm+'-'+t.tpa+'</td><td>'+t.ftm+'-'+t.fta+'</td></tr>';
    $("box").innerHTML=h+'</tbody>'}
  function stop(){if(timer){clearInterval(timer);timer=null;$("watch").textContent="Watch it play out"}}
  root._stop=stop;
  function newGame(seed){stop();G=E.play(seed==null?Math.floor(Math.random()*90000)+10000:seed,true);qSel="all";drawAll()}
  $("new").onclick=function(){newGame()};
  $("watch").onclick=function(){if(!G)return;if(timer){stop();drawAll();return}
    var i=0,g=G;qSel="all";this.textContent="Skip to the final";
    timer=setInterval(function(){var step=+$("spd").value>50?3:1;i=Math.min(g.ev.length,i+step);var e=g.ev[i-1];
      header(e.a,e.h,(e.p<=4?"Q"+e.p:"OT")+" "+mmss(e.ck));
      var at=e.p<=4?(e.p-1)*720+(720-e.ck):2880+(e.p-5)*300+(300-e.ck);
      $("flow").innerHTML=flowSVG(g,g.flow.filter(function(f){return f[0]<=at}).length);drawPBP(i);
      var ps=partial(g,i);$("ls").innerHTML=lineScore({line:ps.line,score:ps.score});
      if(i>=g.ev.length){stop();drawAll()}},1000/(+$("spd").value))};
  $("qtabs").onclick=function(e){var b=e.target.closest("[data-q]");if(!b)return;stop();qSel=b.getAttribute("data-q");drawAll()};
  $("only").onchange=$("who").onchange=function(){stop();drawPBP()};
  $("btabs").onclick=function(e){var b=e.target.closest("[data-t]");if(!b)return;boxT=b.getAttribute("data-t");[].forEach.call(this.children,function(x){x.setAttribute("aria-pressed",String(x===b))});drawBox()};
  function check(){var n=1000,done=0,w=0,a=0,h=0,ot=0,tot=0,cl=0;
    (function chunk(){for(var k=0;k<100&&done<n;k++,done++){var g=E.play(500000+done,false);a+=g.score[A];h+=g.score[H];if(g.score[H]>g.score[A])w++;if(g.periods>4)ot++;if(g.score[H]+g.score[A]>cfg.total)tot++;if(Math.abs(g.score[H]-g.score[A])<=5)cl++}
      if(done<n){setTimeout(chunk,0);return}
      function box(v,l){return'<div><span class="num">'+v+'</span>'+l+'</div>'}
      $("chk").innerHTML=box((a/n).toFixed(1)+"&ndash;"+(h/n).toFixed(1),"average score, "+A+"&ndash;"+H+" (market "+cfg.targetAway.toFixed(1)+"&ndash;"+cfg.targetHome.toFixed(1)+")")
        +box(Math.round(w/n*100)+"%",esc(nick(H))+" win"+(cfg.winHome!=null?" (market "+Math.round(cfg.winHome*100)+"%)":""))
        +box(Math.round(tot/n*100)+"%","over "+cfg.total+" total points")+box(Math.round(cl/n*100)+"%","decided by 5 or fewer")+box(Math.round(ot/n*100)+"%","go to overtime")})()}
  setTimeout(function(){E.calibrate();newGame(10000+(Math.abs(String(A+H+cfg.total).split("").reduce(function(s,c){return s*31+c.charCodeAt(0)|0},7))%89999));setTimeout(check,50)},20);
}
window.PBP={mount:mount,Engine:Engine,nick:nick};
})();
