import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
fs.mkdirSync('artifacts',{recursive:true});
const browser=await puppeteer.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const assert=(v,m)=>{if(!v)throw Error(m);};
try{
 const p=await browser.newPage(),errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.setViewport({width:1440,height:1050});await p.goto('http://127.0.0.1:8020/#curriculum',{waitUntil:'networkidle0'});
 await p.waitForSelector('.curriculum-card');assert(await p.$eval('#curriculum-count',e=>e.textContent.includes('1,590')),'Full curriculum count missing');
 await p.screenshot({path:'artifacts/curriculum-desktop.png',fullPage:true});
 await p.click('[data-subject="Mathematics"]');await p.type('#curriculum-search','fractions');await p.waitForFunction(()=>document.querySelector('#curriculum-count').textContent.includes('53 matching'));
 const goal=await p.$eval('#curriculum-grid [data-goal]',e=>e.dataset.goal);await p.click(`#curriculum-grid [data-goal="${goal}"]`);
 await p.waitForFunction(()=>!document.querySelector('#lab').hidden&&document.querySelector('#goal-title').textContent.includes('Fractions'));
 assert(await p.$eval('#water-demo',e=>e.hidden),'Unrelated water demo shown for fractions');
 // Fraction routes open the tutor; parent checks stay available, and labelled, from the concept field notes.
 await p.waitForFunction(()=>!document.querySelector('#tutor-studio').hidden&&document.querySelector('.role-strip'));
 await p.click('nav [data-tab="map"]');await p.waitForNetworkIdle({idleTime:600});await p.waitForSelector('#map-view .graph-node');
 const node=await p.$eval('#map-view .graph-node',e=>e.dataset.concept);await p.click(`#map-view [data-concept="${node}"]`);await p.waitForSelector('#preview');await p.click('#preview');await p.waitForSelector('#preview-result .feedback');
 await p.click('#concept-inspector [data-recheck]');await p.waitForSelector('#task [data-choice]');assert(await p.$eval('#task',e=>e.textContent.includes('PARENT-REPORTED')),'Parent check unlabelled');
 await p.click('#task [data-choice="0"]');await p.waitForSelector('#task .feedback');assert(await p.$eval('#task .feedback',e=>e.textContent.includes('not a graded')),'Report appears graded');
 await p.click('nav [data-tab="map"]');await p.waitForNetworkIdle({idleTime:600});
 await p.screenshot({path:'artifacts/prerequisite-graph.png',fullPage:true});
 await p.click('nav [data-tab="compare"]');await p.click('#compare-start');await p.waitForSelector('.comparison-card');
 await p.waitForFunction(()=>document.querySelectorAll('.comparison-card .compare-moves .trail-step').length>=2,{timeout:60000});
 const moves=await p.$$eval('.comparison-card .compare-moves b',els=>els.map(e=>e.textContent));assert(moves.length===2&&moves[0]!==moves[1],'Different mistakes did not lead to different moves');
 const box='#compare-task-0';
 if(await p.$(box+' [data-choice]'))await p.click(box+' [data-choice="0"]');else if(await p.$(box+' .tick'))await (await p.$$(box+' .tick'))[1].click();else await (await p.$$(box+' .part'))[0].click();
 await p.click(box+' #check-answer');await p.waitForSelector(box+' .feedback');
 await p.screenshot({path:'artifacts/two-learners.png',fullPage:true});
 await p.click('nav [data-tab="notes"]');await p.waitForSelector('#learning-route h3');assert(await p.$eval('#parent-observations',e=>e.textContent.includes('parent-reported')),'Parent evidence absent');
 await p.setViewport({width:390,height:844,isMobile:true});
 for(const name of ['curriculum','map','compare','notes','lab']){await p.click(`nav [data-tab="${name}"]`);assert(!await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),'Mobile overflow: '+name);}
 await p.screenshot({path:'artifacts/expanded-mobile.png',fullPage:true});
 assert(!errors.length,errors.join('; '));console.log('PASS: curriculum selection, parent reporting, SVG graph, preview, two learners with different mistakes and a live answer, route notes, all five mobile views, no browser errors.');
}finally{await browser.close();}
