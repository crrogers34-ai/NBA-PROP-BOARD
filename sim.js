/* Shared math and sample data for Pick & Roll Analytics. Sample players are made up. */
function erf(x){var s=x<0?-1:1;x=Math.abs(x);var t=1/(1+0.3275911*x);return s*(1-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*Math.exp(-x*x))}
function cdf(z){return .5*(1+erf(z/Math.SQRT2))}
function imp(o){return o<0?-o/(-o+100):100/(o+100)}
function fo(o){return o>0?"+"+o:""+o}
function fx(o){return o>-100&&o<100?-100:o}
var MSD=12,TSD=18,SSD=10.8;
var MB=[],TB=[],i0;for(i0=-30;i0<=30;i0+=3)MB.push(i0);for(i0=180;i0<=270;i0+=6)TB.push(i0);
function bins(E,mu,sd){var o=[],i;for(i=0;i<E.length-1;i++){var lo=i===0?0:cdf((E[i]-mu)/sd),hi=i===E.length-2?1:cdf((E[i+1]-mu)/sd);o.push(hi-lo)}return o}
function hist(a,E,mark,colorFn,lab){var W=420,H=120,B=H-22,mx=Math.max.apply(null,a),bw=W/a.length;
var s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="'+lab+'" style="width:100%;max-width:460px;height:auto">';
a.forEach(function(v,i){var h=v/mx*(B-8);s+='<rect x="'+(i*bw+1).toFixed(1)+'" y="'+(B-h).toFixed(1)+'" width="'+(bw-2).toFixed(1)+'" height="'+h.toFixed(1)+'" fill="'+colorFn(E[i])+'"/>'});
s+='<line x1="0" x2="'+W+'" y1="'+B+'" y2="'+B+'" stroke="var(--line)"/>';
if(mark!=null){var x=(mark-E[0])/(E[E.length-1]-E[0])*W;s+='<line x1="'+x.toFixed(1)+'" x2="'+x.toFixed(1)+'" y1="4" y2="'+B+'" stroke="var(--flag)" stroke-width="3"/>'}
return s+'<text x="2" y="'+(H-6)+'" font-size="11" fill="var(--mute)">'+E[0]+'</text><text x="'+(W-2)+'" y="'+(H-6)+'" font-size="11" fill="var(--mute)" text-anchor="end">'+E[E.length-1]+'+</text></svg>'}
function gameStats(m,t){return{exp_home:(t+m)/2,exp_away:(t-m)/2,win_home:cdf(m/MSD),win_away:1-cdf(m/MSD),close:cdf((5.5-m)/MSD)-cdf((-5.5-m)/MSD),hi230:1-cdf((229.5-t)/TSD),margin_hist:bins(MB,m,MSD),total_hist:bins(TB,t,TSD)}}
/* [home, away, home spread (positive = home favored), total, id, tip] */
var GAMES0=[["BOS","NYK",4.5,224.5,"s1","Tue 7:30 PM ET"],["DEN","LAL",4,229.5,"s2","Tue 10:00 PM ET"],["OKC","HOU",7,218.5,"s3","Wed 8:00 PM ET"],["MIL","IND",1.5,231.5,"s4","Wed 8:00 PM ET"],["PHX","GSW",-1.5,226,"s5","Wed 10:00 PM ET"],["CLE","ORL",5.5,214.5,"s6","Wed 7:00 PM ET"]];
function sampleGames(){return GAMES0.map(function(g){var o=gameStats(g[2],g[3]);o.id=g[4];o.home=g[0];o.away=g[1];o.when=g[5];o.spread=g[2];o.total=g[3];return o})}
var STATS=["Points","Rebounds","Assists","3PM","Steals","Blocks","Turnovers"];
function sdOf(m,v){return m==="Points"?Math.max(4,.3*v):m==="Rebounds"?Math.max(1.6,.36*v):m==="Assists"?Math.max(1.3,.38*v):m==="3PM"?Math.max(.9,.55*v+.2):m==="PRA"?.22*v+3:Math.max(.7,.6*v)}
function ddtd(j){var q=["Points","Rebounds","Assists"].map(function(m){var v=j[m]||0;return 1-cdf((9.5-v)/sdOf(m,v))}),a=q[0],b=q[1],c=q[2];return{dd:a*b+a*c+b*c-2*a*b*c,td:a*b*c}}
var SPL=(function(){
var FN=["Malik","Desmond","Corey","Terrance","Rashad","Devonte","Quinn","Elijah","Trey","Andre","Darnell","Xavier","Kofi","Brandon","Lamar","Tobias","Nate","Jerome","Cedric","Amari","Rowan","Dante","Marquis","Felix","Omari","Kendall","Silas","Reggie","Tavian","Bryce","Isaac","Leon"];
var LN=["Ashford","Pemberton","Castellan","Whitlock","Holloway","Sinclair","Mercer","Thibault","Rourke","Vickers","Delacroix","Fairbanks","Hargis","Marchetti","Brannigan","Calloway","Pryor","Kincaid","Ellery","Radcliffe","Moreland","Bascombe","Haverford","Lindqvist","Abernathy","Quarles","Seabrook","Prescott","Wexler","Dunmore","Ravenel","Stanhope","Corrigan","Ashby","Merriweather","Belcourt","Pendergast","Okeke","Tremaine","Galloway","Rutledge","Sorensen","Achebe","Faulkner","Iverly","Navarro","Keswick","Dorsey"];
var TPL={PG:[34,21,4.6,7.6,2.6,1.3,.3,3],SG:[32,18,4.2,3.6,2.8,1.1,.4,1.9],SF:[31,15.5,6,3,1.9,1.1,.6,1.6],PF:[29,13.5,7.6,2.6,1.2,.8,.9,1.4],C:[28,14,10.6,2.4,.4,.7,1.8,1.7]};
var ROWS=[["PG","PG",0],["SG","SG",0],["SF","SF/PF",0],["PF","PF",0],["C","C",0],["PG","PG/SG",1],["SF","SF/PF",1],["C","PF/C",1]];
var out=[],k=0;
GAMES0.forEach(function(g){[[g[0],g[1]],[g[1],g[0]]].forEach(function(tt){var t=tt[0],h=0,i;for(i=0;i<t.length;i++)h=h*31+t.charCodeAt(i);h=h%9973;var star=h%5;
ROWS.forEach(function(r,j){var T=TPL[r[0]],f=r[2]?(.5+(h*(j+2))%11/100):(j===star?1.24+(h%17)/100:(.8+((h*(j+3))%23)/100)),proj={};
STATS.forEach(function(s,q){proj[s]=Math.round(T[q+1]*f*10)/10});
var min=r[2]?16+(h+j)%6:Math.round(T[0]*Math.min(1.1,.78+.22*f));
var pos=r[1];if(!r[2]&&r[0]==="SG"&&h%2)pos="PG/SG";
var p={n:FN[k%32]+" "+LN[(k*13)%48],t:t,o:tt[1],pos:pos,min:min,proj:proj,bench:!!r[2],inj:k%17===5?"Questionable":"",role:k%11===3?"Role up":k%13===7?"Role down":""};
var x=ddtd(proj);p.dd=x.dd;p.td=x.td;out.push(p);k++})})});return out})();
function gameOf(t){return GAMES0.filter(function(g){return g[0]===t||g[1]===t})[0]}
function sampleBoard(){var out=[],BK=["DK","FD","MGM","CZR"];
SPL.forEach(function(p,i){if(p.bench)return;var j=p.proj,ms=[];
if(j.Points>=12)ms.push("Points");if(j.Rebounds>=6.5)ms.push("Rebounds");if(j.Assists>=4.5)ms.push("Assists");if(j["3PM"]>=1.8)ms.push("3PM");if(j.Points>=24)ms.push("PRA");
ms.forEach(function(m,q){var v=m==="PRA"?j.Points+j.Rebounds+j.Assists:j[m],sd=sdOf(m,v),off=(((i*7+q*5)%7)-3)*sd*.05,line=Math.max(.5,Math.floor(v+off)+.5);
var gm=gameOf(p.t),opps=["MIA","CHI","DAL","SAC","ATL"],l5=opps.map(function(o,k){var z=Math.sin((i+1)*12.9898+(q+1)*78.233+k*37.719)*43758.5453;z=(z-Math.floor(z))*2-1;
return{d:"2026-11-"+("0"+(14-k*2)).slice(-2),o:o,h:k%2===0,min:Math.round(p.min+z*4),v:Math.max(0,Math.round(v+z*sd*1.3))}});
out.push({n:p.n,t:p.t,o:p.o,m:m,g:gm[1]+"@"+gm[0],when:gm[5],proj:+v.toFixed(1),last5:l5,sd:+sd.toFixed(2),inj:p.inj,role:p.role,books:BK.map(function(k,b){var l=line+((m==="Points"||m==="PRA")&&((i+b*3+q)%5===0)?(((i+b)%2)?1:-1):0);if(l<.5)l=.5;
return{bk:k,line:l,ov:fx(-110+(((i*7+b*13+q)%5)-2)*5),un:fx(-110+(((i*5+b*11+q)%5)-2)*5)}})})})});return out}
function fpts(p,plat){var j=p.proj||{},pts=j.Points||0,r=j.Rebounds||0,a=j.Assists||0,t3=j["3PM"]||0,s=j.Steals||0,b=j.Blocks||0,to=j.Turnovers||0;
if(plat==="dk")return pts+.5*t3+1.25*r+1.5*a+2*s+2*b-.5*to+1.5*(p.dd||0)+3*(p.td||0);
return pts+1.2*r+1.5*a+3*s+3*b-to}
/* Edge math (same as build_nba.py): widen the range for projection error, then blend the
   model's chance with the book's no-vig price. MW is the share given to the model. */
var MW=0.2,PE=0.12;   /* defaults; the live board.json carries the fitted values */
function wsd(d){return Math.sqrt(d.sd*d.sd+Math.pow(PE*d.proj,2))}
function blend(d,b,sd){var io=imp(b.ov),iu=imp(b.un),pm=1-cdf((b.line-d.proj)/(sd||wsd(d))),po=MW*pm+(1-MW)*(io/(io+iu)),eo=po-io,eu=(1-po)-iu,o=eo>=eu;
return{bk:b.bk,line:b.line,ov:b.ov,un:b.un,side:o?"Over":"Under",odds:o?b.ov:b.un,p:o?po:1-po,e:Math.max(eo,eu)*100}}
function get(u){return fetch(u,{cache:"no-store",credentials:"same-origin"}).then(function(r){if(!r.ok)throw 0;return r.json()}).catch(function(){return null})}

