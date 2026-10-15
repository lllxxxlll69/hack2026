// Independent, optional UI motion. Never affects requests or authorization.
(() => {
  const preference=matchMedia('(prefers-reduced-motion: reduce)');
  const running=new Set(), messages=new Set();
  let frame=0;
  const reduced=()=>{try{return preference.matches||localStorage.getItem('dean-reduced-motion')==='1';}catch{return preference.matches;}};
  function enter(element,delay=0){
    if(reduced()||!element?.animate)return;
    const animation=element.animate([{opacity:.35,transform:'translateY(7px)'},{opacity:1,transform:'translateY(0)'}],
      {duration:220,delay,easing:'cubic-bezier(.2,.7,.3,1)',fill:'backwards'});
    running.add(animation);
    animation.finished.catch(()=>{}).finally(()=>running.delete(animation));
  }
  function refresh(){
    frame=0;
    const content=document.querySelector('#content');
    for(const message of content.querySelectorAll('[data-message-id]')){
      const key=message.dataset.messageId;
      if(!messages.has(key)){messages.add(key);enter(message);}
    }
  }
  const observer=new MutationObserver(records=>{
    if(records.some(r=>r.target.id==='content')){
      const blocks=document.querySelectorAll('#content>.section-head,#content>.hero,#content>.panel,#content>.home-grid>.panel,#content>.settings-grid>.panel,#content>.knowledge-layout>.panel');
      [...blocks].slice(0,7).forEach((element,index)=>enter(element,index*25));
    }
    if(!frame)frame=requestAnimationFrame(refresh);
  });
  observer.observe(document.querySelector('#content'),{childList:true,subtree:true});
  document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('toggle',()=>{if(dialog.open)enter(dialog);}));
  function apply(){
    document.documentElement.dataset.reducedMotion=String(reduced());
    if(reduced())for(const animation of running)animation.cancel();
  }
  preference.addEventListener('change',apply);
  window.addEventListener('dean-motion-preference',apply);
  apply();
})();
