// Regenerates the README screenshots from the running app (http://127.0.0.1:8020). Needs Chrome and a local model.
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
fs.mkdirSync('evidence/screens',{recursive:true});
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const b=await puppeteer.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const p=await b.newPage();await p.setViewport({width:1280,height:900});
 await p.goto('http://127.0.0.1:8020/#curriculum',{waitUntil:'networkidle0'});await p.waitForSelector('[data-feature]');
 await p.click('[data-feature]');await wait(2500);await p.click('nav [data-tab="curriculum"]');await wait(1500);
 await (await p.$('.curriculum-atlas')).screenshot({path:'evidence/screens/constellation-cross-subject-route.png'});
 await p.click('nav [data-tab="map"]');await p.waitForNetworkIdle({idleTime:500});
 await (await p.$('.map-layout')).screenshot({path:'evidence/screens/why-this-next.png'});
 await p.click('nav [data-tab="curriculum"]');await p.type('#curriculum-search','Scatter Graphs');await wait(1500);
 await p.click('#curriculum-grid [data-goal]');await wait(2500);await p.click('nav [data-tab="map"]');await p.waitForNetworkIdle({idleTime:500});
 await (await p.$('#map-view')).screenshot({path:'evidence/screens/focused-120-concept-route.png'});
 await p.click('nav [data-tab="compare"]');await p.waitForSelector('.comparison-card');await wait(1500);
 await (await p.$('#compare')).screenshot({path:'evidence/screens/two-learners.png'});
 await p.click('nav [data-tab="curriculum"]');await p.click('[data-feature]');await wait(2500);
 await p.goto('http://127.0.0.1:8020/#lab',{waitUntil:'networkidle0'});
 await p.evaluate(()=>fetch('/api/goal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({concept_id:'mt_Qkewo5M3_c'})}));await p.reload({waitUntil:'networkidle0'});
 await p.waitForFunction(()=>!document.querySelector('#agent').disabled);
 await p.click('#agent');await p.waitForSelector('[data-choice]',{timeout:180000});await wait(800);
 await (await p.$('.room')).screenshot({path:'evidence/screens/guide-investigation-trail.png'});
 await p.setViewport({width:390,height:844,isMobile:true});await p.goto('http://127.0.0.1:8020/#curriculum',{waitUntil:'networkidle0'});await wait(1500);
 await p.screenshot({path:'evidence/screens/mobile-curriculum.png'});
 console.log('screens written to evidence/screens');
}finally{await b.close();}
