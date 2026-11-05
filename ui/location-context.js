(function () {
  'use strict';
  // One tab-only origin for exploration and chat. Coordinates are never persisted.
  let origin=null,service=null,version=0,pending=null;
  const inJeju=(latitude,longitude)=>latitude>=32.9&&latitude<=33.8&&longitude>=126&&longitude<=127.05;
  function point(raw,source){
    const coords=raw?.coords||raw;
    if(!coords||typeof coords.latitude!=='number'||typeof coords.longitude!=='number'||!Number.isFinite(coords.latitude)||!Number.isFinite(coords.longitude)||!inJeju(coords.latitude,coords.longitude))return null;
    const result={latitude:coords.latitude,longitude:coords.longitude,source};
    const accuracy=coords.accuracy_m??coords.accuracy;
    if(typeof accuracy==='number'&&Number.isFinite(accuracy)&&accuracy>=0)result.accuracy_m=accuracy;
    const label=raw?.label||raw?.name;
    if(typeof label==='string'&&label.trim())result.label=label.trim().slice(0,100);
    return result;
  }
  function get(){return origin?{...origin}:null;}
  function emit(reason){window.dispatchEvent(new CustomEvent('jeju:locationchange',{detail:{location:get(),reason}}));}
  function clear(reason='cleared',{cancelRequest=true}={}){
    if(cancelRequest){version++;service?.cancel?.(reason);pending=null;}origin=null;emit(reason);
  }
  function cancel(reason='cancelled'){
    version++;service?.cancel?.(reason,{preserveLocation:origin?.source==='device'});pending=null;
  }
  function setDevice(raw){
    origin=point(raw,'device');emit(origin?'device':'outside-jeju');return Boolean(origin);
  }
  function setManual(raw){
    version++;service?.cancel?.('manual');pending=null;origin=point(raw,'manual');emit(origin?'manual':'cleared');return Boolean(origin);
  }
  function bind(next){
    if(service&&service!==next)service.cancel?.('replaced');service=next||null;
  }
  function request(){
    if(pending)return pending;
    if(!service||typeof service.request!=='function')return Promise.resolve({status:'unavailable',reason:'not-mounted'});
    const ticket=version;
    const active=service.request();
    const flight=Promise.resolve(active).then(result=>{
      if(ticket!==version)return {status:'cancelled',reason:'origin-changed'};
      if(result?.status!=='success')return {status:result?.status||'error',reason:result?.reason||'request-failed'};
      if(result.inJeju===false){origin=null;emit('outside-jeju');return {status:'outside-jeju'};}
      if(!setDevice(result.position))return {status:'outside-jeju'};
      return {status:'success',location:get()};
    },()=>({status:'error',reason:'request-failed'})).finally(()=>{if(pending===flight)pending=null;});
    pending=flight;return flight;
  }
  window.addEventListener('jeju:reset',()=>clear('reset'));
  window.addEventListener('pagehide',()=>clear('pagehide'));
  window.JejuLocationContext={get,setDevice,setManual,clear,cancel,bind,request};
}());
