(function(){
"use strict";
var d=document,$=function(s,r){return(r||d).querySelector(s)},$$=function(s,r){return[].slice.call((r||d).querySelectorAll(s))};
function get(k){try{return JSON.parse(localStorage.getItem(k)||"[]")}catch(e){return[]}}
function set(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}

/* theme + mobile menu */
var tb=$("#theme");if(tb)tb.addEventListener("click",function(){var n=d.documentElement.dataset.theme==="dark"?"light":"dark";d.documentElement.dataset.theme=n;try{localStorage.setItem("theme",n)}catch(e){}});
var mb=$("#menu"),side=$("#side");if(mb)mb.addEventListener("click",function(){side.classList.toggle("open")});
d.addEventListener("click",function(e){if(side&&side.classList.contains("open")&&!side.contains(e.target)&&e.target!==mb)side.classList.remove("open")});

/* animated bars */
$$(".bar i[data-w]").forEach(function(i){var w=i.getAttribute("data-w");i.style.width="0";requestAnimationFrame(function(){requestAnimationFrame(function(){i.style.width=w+"%"})})});

/* activity heartbeat: counts time only while the tab is visible and the user was active in the last minute */
(function(){var last=Date.now();["mousemove","keydown","scroll","click","touchstart"].forEach(function(ev){d.addEventListener(ev,function(){last=Date.now()},{passive:true})});
  function set(id,v){var e=$("#"+id);if(e&&v!==undefined)e.textContent=v}
  setInterval(function(){if(d.visibilityState!=="visible"||Date.now()-last>60000)return;
    fetch("/track/ping",{method:"POST",credentials:"same-origin"}).then(function(r){return r.ok?r.json():null}).then(function(a){if(!a)return;set("act-visitors",a.visitors);set("act-visits",a.visits);set("act-time",a.time);set("act-this",a.this_visit)}).catch(function(){})},15000)})();

var cards=$$(".nc"),q=$("#qlive");
/* global search box: filters cards on this page, otherwise opens Daily News search */
if(q){q.addEventListener("keydown",function(e){if(e.key==="Enter"&&!cards.length&&q.value.trim()){location.href="/news?q="+encodeURIComponent(q.value.trim())}})}
d.addEventListener("keydown",function(e){var t=e.target.tagName;if(t==="INPUT"||t==="TEXTAREA"||t==="SELECT")return;
  if(e.key==="/"&&q){e.preventDefault();q.focus()}
  if((e.key==="j"||e.key==="k")&&cards.length){var vis=cards.filter(function(c){return!c.classList.contains("hide")});if(!vis.length)return;
    var cur=vis.findIndex(function(c){var r=c.getBoundingClientRect();return r.top>=70});if(cur<0)cur=vis.length-1;
    var idx=e.key==="j"?Math.min(cur+(vis[cur].getBoundingClientRect().top>80?0:1),vis.length-1):Math.max(cur-1,0);
    vis[idx].scrollIntoView({behavior:"smooth",block:"start"})}});
if(!cards.length)return;

/* reveal on scroll */
if("IntersectionObserver"in window){var io=new IntersectionObserver(function(es){es.forEach(function(x){if(x.isIntersecting){x.target.classList.add("in");io.unobserve(x.target)}})},{rootMargin:"0px 0px -5% 0px"});cards.forEach(function(c){io.observe(c)})}else{cards.forEach(function(c){c.classList.add("in")})}

/* read / saved / fold (stored in this browser only) */
var read=get("hub_read"),saved=get("hub_saved"),onlyUnread=false,onlySaved=false;
function mark(c){var id=c.getAttribute("data-id");c.classList.toggle("read",read.indexOf(id)>-1);
  var r=$('[data-act="read"]',c),s=$('[data-act="save"]',c);if(r)r.classList.toggle("active",read.indexOf(id)>-1);if(s)s.classList.toggle("active",saved.indexOf(id)>-1)}
function toggle(list,id){var i=list.indexOf(id);if(i>-1)list.splice(i,1);else list.push(id)}
function update(){var term=q?q.value.trim().toLowerCase():"";var shown=0;
  cards.forEach(function(c){var id=c.getAttribute("data-id");var ok=(!term||c.textContent.toLowerCase().indexOf(term)>-1)&&(!onlyUnread||read.indexOf(id)<0)&&(!onlySaved||saved.indexOf(id)>-1);c.classList.toggle("hide",!ok);if(ok)shown++});
  /* hide section headings with no visible cards */
  $$("h2.bsec").forEach(function(h2){var any=false,n=h2.nextElementSibling;while(n&&!n.matches("h2.bsec")){if(n.matches(".nc")&&!n.classList.contains("hide"))any=true;n=n.nextElementSibling}h2.classList.toggle("hide",!any);
    var sub=h2.nextElementSibling;while(sub&&!sub.matches("h2.bsec")){if(sub.matches("h3.bsub2")){var a=false,m=sub.nextElementSibling;while(m&&!m.matches("h3.bsub2,h2.bsec")){if(m.matches(".nc")&&!m.classList.contains("hide"))a=true;m=m.nextElementSibling}sub.classList.toggle("hide",!a)}sub=sub.nextElementSibling}});
  var done=cards.filter(function(c){return read.indexOf(c.getAttribute("data-id"))>-1}).length,pt=$("#ptext"),pb=$("#pbar");
  if(pt)pt.textContent=done+" of "+cards.length+" read"+(shown!==cards.length?" · "+shown+" shown":"");if(pb)pb.style.width=(cards.length?Math.round(done/cards.length*100):0)+"%"}
cards.forEach(mark);update();
if(q)q.addEventListener("input",update);
var fu=$("#f-unread"),fs=$("#f-saved");
if(fu)fu.addEventListener("click",function(){onlyUnread=!onlyUnread;fu.classList.toggle("active",onlyUnread);update()});
if(fs)fs.addEventListener("click",function(){onlySaved=!onlySaved;fs.classList.toggle("active",onlySaved);update()});
d.addEventListener("click",function(e){var b=e.target.closest("[data-act]");if(!b)return;var c=b.closest(".nc");if(!c)return;var id=c.getAttribute("data-id"),a=b.getAttribute("data-act");
  if(a==="read"){toggle(read,id);set("hub_read",read)}else if(a==="save"){toggle(saved,id);set("hub_saved",saved)}else if(a==="fold"){c.classList.toggle("folded");return}
  mark(c);update()});
})();
