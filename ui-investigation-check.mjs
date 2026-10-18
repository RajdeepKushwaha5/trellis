// Real rendered investigation states, created with synthetic controller fixtures, not a model replay.
import puppeteer from 'puppeteer-core';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
const python=process.cwd()+'/.venv/Scripts/python.exe';
const fixtures=JSON.parse(execFileSync(python,['-m','backend.tutor.ui_fixture','create'],{encoding:'utf8'}));
const browser=await puppeteer.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const assert=(v,m)=>{if(!v)throw Error(m);};
try{
 const p=await browser.newPage(),errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.setViewport({width:1440,height:1050});
 for(const mode of ['probe','strategy']){
  await p.setCookie({name:'trellis_session',value:fixtures[mode],url:'http://127.0.0.1:8020',httpOnly:true,sameSite:'Strict'});
  await p.goto('http://127.0.0.1:8020/#lab',{waitUntil:'networkidle0'});
  await p.waitForSelector('#check-answer');
  assert(await p.$('#investigation-panel .investigation-card'),'Evidence explanation missing');
  await p.click('#investigation-panel summary');
  assert(await p.$eval('#investigation-panel',x=>x.textContent.includes('not diagnoses')),'Hypothesis boundary missing');
  if(mode==='probe'){
   assert(await p.$eval('#task',x=>x.textContent.includes('NOT A SUPPORT CHECK')),'Probe not distinguished');
   assert(!await p.$('#hint'),'Probe offers hints');
   await p.click('#fraction-work [data-choice="0"]');await p.click('#check-answer');
   await p.waitForSelector('#feedback .feedback');
   assert(await p.$eval('#feedback',x=>x.textContent.includes('Not counted towards support')),'Probe counted as support');
  }else{
   assert(await p.$eval('.strategy-card',x=>x.textContent.includes('Walk the gaps from zero')),'Selected strategy not rendered');
   assert(await p.$eval('.strategy-card',x=>x.textContent.includes('Count equal jumps')),'Strategy instruction missing');
  }
  await p.screenshot({path:`artifacts/investigation-${mode}.png`,fullPage:true});
  await p.setViewport({width:390,height:844,isMobile:true});
  assert(!await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),'Mobile overflow '+mode);
  await p.screenshot({path:`artifacts/investigation-${mode}-mobile.png`,fullPage:true});
  await p.setViewport({width:1440,height:1050});
 }
 assert(!errors.length,errors.join('; '));console.log('PASS: probe is separate from support, strategy text, evidence/hypothesis panel, mobile and browser errors. Synthetic controller fixtures, no model claim.');
}finally{
 await browser.close();execFileSync(python,['-m','backend.tutor.ui_fixture','delete',JSON.stringify(fixtures)]);
}
