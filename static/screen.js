(()=>{
const $=id=>document.getElementById(id),node=(tag,text,className)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;};
function render(d){
 $('workspace').textContent=d.workspace+(d.demo?' · 演示数据':' · 真实监测空间');
 $('worker').textContent=d.worker?'● 后台任务在线':'● 后台任务待检查';$('worker').style.color=d.worker?'#42d9db':'#ffbd66';
 $('updated').textContent='数据更新：'+d.updated;
 for(const [key,value] of Object.entries(d.metrics))$(key).textContent=Number(value).toLocaleString('zh-CN');
 const max=Math.max(1,...d.trend.map(x=>x.total));$('trend').replaceChildren();
 for(const point of d.trend){const col=node('div',undefined,'column'),bars=node('div',undefined,'columns');col.append(node('em',String(point.total)));for(const key of ['total','negative']){const b=node('div',undefined,'bar'+(key==='negative'?' negative':''));b.style.height=(point[key]/max*100)+'%';b.title=key==='negative'?'负面线索 '+point[key]:'相关提及 '+point[key];bars.append(b);}col.append(bars,node('small',point.date));$('trend').append(col);}
 const pct=d.sources.total?Math.round(d.sources.healthy/d.sources.total*100):0;
 $('source-total').textContent=d.sources.total+' 个已启用来源';$('health-rate').textContent=d.sources.total?pct+'%':'—';$('health-ring').style.background=`conic-gradient(#42d9db ${pct*3.6}deg,#21364c 0deg)`;
 $('health').replaceChildren();for(const [key,label]of [['healthy','正常'],['failed','失败'],['waiting','待检 / 超期']]){const e=node('div');e.append(node('strong',String(d.sources[key])),node('span',label));$('health').append(e);}
 $('distribution').replaceChildren();const peak=Math.max(1,...d.distribution.map(x=>x.count));
 for(const row of d.distribution){const e=node('div',undefined,'row'),head=node('div',undefined,'row-head'),track=node('div',undefined,'track'),fill=node('div');head.append(node('span',row.name),node('b',String(row.count)));fill.style.width=row.count/peak*100+'%';track.append(fill);e.append(head,track);$('distribution').append(e);}
 if(!d.distribution.length)$('distribution').append(node('div','今日暂无相关提及','empty'));
 $('events').replaceChildren();for(const event of d.events){const e=node('article',undefined,'event'),info=node('div'),link=node('a',event.title);link.href=event.url;info.append(link,node('p',event.project+' · '+event.status));e.append(node('span',event.risk,'badge'),info,node('time',event.time));$('events').append(e);}if(!d.events.length)$('events').append(node('div','暂无监测事件，接入来源后开始检索','empty'));
}
render(JSON.parse($('screen-data').textContent));let loading=false;
async function refresh(){if(loading)return;loading=true;try{const r=await fetch('/screen/status/'+window.location.search,{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw Error();render(await r.json());}catch{$('updated').textContent='更新失败，保留上次结果；请检查登录与服务状态';}finally{loading=false;}}
$('refresh').addEventListener('click',refresh);$('fullscreen').addEventListener('click',()=>{const action=document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen?.();action?.catch(()=>{});});
setInterval(refresh,30000);setInterval(()=>{$('clock').textContent=new Date().toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+' 北京时间';},1000);
})();
