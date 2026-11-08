'use strict';
// Explicit user actions with mocked tools; no location permission or network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
function fragment(file,start,end){const source=fs.readFileSync(__dirname+'/../ui/'+file,'utf8');const a=source.indexOf(start),b=source.indexOf(end,a+start.length);assert(a>=0&&b>a);return source.slice(a,b);}
function fixture(){
  const nodes=new Map(),messages=[],opened=[];let cleared=0,updated=0;
  const $=selector=>{if(!nodes.has(selector))nodes.set(selector,{checked:false,disabled:false,value:'',hidden:false});return nodes.get(selector);};
  $('#route-mode-saved').checked=true;
  const state={$: $,saved:new Set(),notify:x=>messages.push(x),clearPlannerResult(){cleared++;},
    updatePlanningMode(){updated++;},showPlannerInputs:(message,target)=>opened.push({message,target})};
  vm.createContext(state);vm.runInContext(fragment('app.js','function beginGuidedPlan(','function showPlannerInputs('),state);
  return {state,$,messages,opened,cleared:()=>cleared,updated:()=>updated};
}
{
 const f=fixture();f.$('[name=start_lat]').value='33.1';f.$('[name=budget_krw]').value='55000';
 assert.equal(f.state.beginGuidedPlan('automatic'),true);
 assert.equal(f.$('#route-mode-auto').checked,true);assert.equal(f.$('#route-mode-saved').checked,false);
 assert.equal(f.cleared(),1);assert.equal(f.opened[0].target,'#auto-route-region');
 assert.equal(f.$('[name=start_lat]').value,'33.1');assert.equal(f.$('[name=budget_krw]').value,'55000','do not overwrite chosen conditions or confirm an origin');
 assert.equal(f.state.beginGuidedPlan('automatic'),true);assert.equal(f.cleared(),1,'reopening the same mode preserves an existing route');
 assert.equal(f.state.beginGuidedPlan('bad'),false);assert.equal(f.cleared(),1);
 f.$('#create-trip').disabled=true;assert.equal(f.state.beginGuidedPlan('saved'),false);assert.equal(f.$('#route-mode-auto').checked,true);assert(f.messages[0].includes('계산'));
 f.$('#create-trip').disabled=false;assert.equal(f.state.beginGuidedPlan('saved'),true);assert(f.opened.at(-1).message.includes('담아'));
}
{
 const nodes=new Map(),calls=[];let loads=0;
 const $=selector=>{if(!nodes.has(selector))nodes.set(selector,{value:'',dataset:{}});return nodes.get(selector);};
 $('#discovery-region').value='north';
 const state={$: $,tourismRequest:10,setTab:type=>calls.push(['tab',type]),discover(){loads++;},reveal:(target,opts)=>calls.push(['reveal',opts.block])};
 vm.createContext(state);vm.runInContext(fragment('discovery.js','  function searchFoodFromQuery(','  window.JejuExplore='),state);
 assert.equal(loads,0);assert.equal(state.searchFoodFromQuery(' 커피 '),true);assert.equal(loads,1);
 assert.equal($('#food-wish').value,'커피');assert.equal($('#discovery-region').value,'north','preserve chosen region when none is supplied');
 assert.equal(state.tourismRequest,11,'late tourism response cannot replace the explicit food task');
 assert.equal(state.searchFoodFromQuery('한식','east'),true);assert.equal($('#discovery-region').value,'east');
 const before=loads;assert.equal(state.searchFoodFromQuery(''),false);assert.equal(state.searchFoodFromQuery('x'.repeat(101)),false);assert.equal(state.searchFoodFromQuery('커피','outside'),false);assert.equal(loads,before);
 assert.deepEqual(calls[0],['tab','food']);assert(calls.some(v=>v[0]==='reveal'));
}
console.log('PASS explicit planner modes preserve conditions and existing results; food actions preserve region and never request location or auto-submit a trip');
