// No browser/network: Hub spacing must retain image/source/identity validation.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context={window:{document:{readyState:'loading',addEventListener(){}}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/../ui/hero-carousel.js','utf8'),context);
const validate=context.window.JejuHero.validateConfig;
const base={schema_version:1,interval_ms:5000,autoplay:true,slides:[{id:'osulloc',name:'오설록 티뮤지엄',caption:'오설록 티뮤지엄',region_label:'안덕 서부',image:'/assets/osulloc.jpg',source_id:'visitjeju_CONT_000000000500457',href:'#destinations',focal_x:50,focal_y:50}]};
const copy=()=>JSON.parse(JSON.stringify(base));
assert.equal(validate(base).slides[0].name,'오설록 티뮤지엄');
assert.equal(validate(base).slides[0].caption,'오설록 티뮤지엄');
for(const [key,value] of [['id','unknown'],['image','https://untrusted.example/photo.jpg'],['image','/assets/seongsan.jpg'],['source_id','wrong'],['region_label','동부'],['href','https://untrusted.example/']]){
 const data=copy();data.slides[0][key]=value;assert.throws(()=>validate(data),key);
}
for(const name of ['다른 장소','', ' '.repeat(61),'오설록<티뮤지엄>','오설록\n티뮤지엄','오설록티뮤지엄'+' '.repeat(61)]){
 const data=copy();data.slides[0].name=name;assert.throws(()=>validate(data),name);
}
const old=copy();old.slides[0].name='오설록 티 뮤지엄';assert.equal(validate(old).slides[0].name,'오설록 티 뮤지엄');
const duplicate=copy();duplicate.slides.push({...duplicate.slides[0]});assert.throws(()=>validate(duplicate));
const fast=copy();fast.interval_ms=4999;assert.throws(()=>validate(fast));
console.log(JSON.stringify({pass:true,groups:5,checks:'Hub display name, original name, bounded identity-equivalent names, photo/source/anchor rejection, timing/duplicates'}));
