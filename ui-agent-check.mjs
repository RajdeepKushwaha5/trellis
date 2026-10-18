import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
const browser=await puppeteer.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const assert=(x,m)=>{if(!x)throw Error(m);};
try{
 const p=await browser.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto('http://127.0.0.1:8020/#lab',{waitUntil:'networkidle0'});
 // This check covers the original investigation guide, which runs on the water route.
 await p.evaluate(()=>fetch('/api/goal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({concept_id:'mt_Qkewo5M3_c'})}));
 await p.reload({waitUntil:'networkidle0'});
 await p.waitForFunction(()=>!document.querySelector('#agent').disabled);
 await p.click('#agent');await p.waitForSelector('[data-choice]',{timeout:180000});
 await p.click('[data-choice="0"]');await p.waitForFunction(()=>document.querySelector('#continue')?.textContent.includes('Your next check is ready'),{timeout:180000});
 const notebook=await p.evaluate(async()=>await(await fetch('/api/notebook')).json());
 assert(notebook.decisions.length===2,'Automatic response did not record a second agent investigation');
 assert(notebook.decisions[0].action.revision+1===notebook.decisions[1].action.revision,'Second decision did not use revised evidence');
 assert(notebook.decisions.every(d=>d.trace.some(t=>t.tool==='rank_checks')&&d.trace.some(t=>t.tool==='launch_diagnostic')),'MCP investigation incomplete');
 await p.click('#continue');await p.waitForSelector('[data-choice]');
 await p.click('nav [data-tab="notes"]');await p.waitForSelector('.tool');
 fs.mkdirSync('artifacts',{recursive:true});fs.writeFileSync('artifacts/browser-agent-loop.json',JSON.stringify(notebook,null,2));
 await p.screenshot({path:'artifacts/agent-field-notes.png',fullPage:true});
 assert(errors.length===0,errors.join('; '));console.log('PASS actual browser response -> automatic MCP investigation at next revision -> prepared next check -> recorded field notes.');
}finally{await browser.close();}
