(function(){var b=document.getElementById("menuBtn"),s=document.getElementById("side"),sc=document.getElementById("scrim");if(!b||!s)return;
function set(o){document.body.classList.toggle("menu-open",o);b.setAttribute("aria-expanded",String(o));b.setAttribute("aria-label",o?"Close menu":"Open menu");sc.hidden=!o;if(o){var a=s.querySelector("a");if(a)a.focus()}else b.focus()}
b.addEventListener("click",function(){set(!document.body.classList.contains("menu-open"))});
sc.addEventListener("click",function(){set(false)});
document.addEventListener("keydown",function(e){if(e.key==="Escape"&&document.body.classList.contains("menu-open"))set(false)});
s.addEventListener("click",function(e){if(e.target.closest("a"))set(false)});
})();
