const fs=require('fs');
const path=require('path');
const assert=require('assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..');
const base=process.env.ARGUS_TEST_URL||'http://127.0.0.1:8765';
const output=path.join(root,'test-results');fs.mkdirSync(output,{recursive:true});
const credentialPath=path.join(root,'data','首次登录.txt');const credentialFile=fs.existsSync(credentialPath)?fs.readFileSync(credentialPath,'utf8'):'';
const password=process.env.ARGUS_TEST_PASSWORD||credentialFile.match(/密码：([^\r\n]+)/)?.[1];
const username=process.env.ARGUS_TEST_USER||'admin';
if(!password)throw Error('Set ARGUS_TEST_PASSWORD or initialize a dedicated test instance');
const stamp=Date.now().toString();
const brand='Argus测试品牌'+stamp;
const errors=[];const checks=[];
async function login(page,user,pass){await page.goto(base+'/login/');await page.locator('[name=username]').fill(user);await page.locator('[name=password]').fill(pass);await Promise.all([page.waitForURL(url=>url.href===base+'/'||url.href===base+'/onboarding/'),page.getByRole('button',{name:'登录 Argus →'}).click()]);}
async function waitFor(page,url,condition,label){for(let i=0;i<30;i++){await page.goto(base+url);if(await condition())return;await page.waitForTimeout(1000);}throw Error('Timed out: '+label);}
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.ARGUS_CHROME?{executablePath:process.env.ARGUS_CHROME}:{})});
 try{
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=500)errors.push(r.status()+' '+new URL(r.url()).pathname);});
 page.on('dialog',d=>d.accept());
 await login(page,username,password);checks.push('登录');
 await page.goto(base+'/projects/new/');await page.locator('[name=name]').fill(brand);await page.locator('[name=aliases]').fill('测试产品'+stamp);await page.locator('[name=excludes]').fill('同名社区');await page.getByRole('button',{name:'保存并继续'}).click();assert.match(await page.locator('main').innerText(),new RegExp(brand));checks.push('创建监测项目');
 await page.goto(base+'/import/');
 const projectId=await page.locator('[name=project] option').evaluateAll((options,brand)=>options.find(x=>x.textContent===brand)?.value,brand);assert.ok(projectId);
 await page.locator('[name=project]').selectOption(projectId);await page.locator('[name=source_name]').fill('E2E自动化导入');
 const title=brand+'包装漏液需要售后核实';
 const csv='title,text,external_id\n'+title+','+brand+'包装漏液需要售后核实。,one\n'+title+','+brand+'包装漏液需要售后核实。,two\n同名社区活动,与品牌无关。,three\n';
 await page.locator('[type=file]').setInputFiles({name:'argus-e2e.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});await page.getByRole('button',{name:'保存并继续'}).click();assert.match(await page.locator('main').innerText(),/新增 3 条/);checks.push('真实 CSV 上传及入库');
 await waitFor(page,'/events/',async()=>await page.getByRole('link',{name:new RegExp(title)}).count()>0,'后台分析事件');
 await page.getByRole('link',{name:new RegExp(title)}).first().click();const eventPath=new URL(page.url()).pathname;
 assert.match(await page.locator('main').innerText(),/原始证据 · 2 条/);checks.push('后台任务分析与相近线索归并');
 await page.locator('[name=risk]').selectOption('需要关注');await page.getByRole('button',{name:'审核通过，检查通知规则'}).click();assert.match(await page.locator('main').innerText(),/审核通过/);checks.push('风险审核与通知排队');
 await page.locator('[name=note]').fill('自动化测试：核实证据后完成处置');await page.getByRole('button',{name:'标记已处理',exact:true}).click();assert.match(await page.locator('main').innerText(),/已处理/);checks.push('处置备注与审计');
 await page.screenshot({path:path.join(output,'event-desktop.png'),fullPage:true});
 await page.goto(base+'/reports/');await page.locator('[name=project]').selectOption(projectId);await page.getByRole('button',{name:'生成今日日报'}).click();
 await waitFor(page,'/reports/',async()=>await page.getByRole('link',{name:new RegExp(brand)}).count()>0,'生成日报');await page.getByRole('link',{name:new RegExp(brand)}).first().click();const reportPath=new URL(page.url()).pathname;assert.match(await page.locator('main').innerText(),/相关提及 2 条/);checks.push('日报不可变快照');
 const downloadPromise=page.waitForEvent('download');await page.getByRole('link',{name:'导出 CSV ↓'}).click();const download=await downloadPromise;const csvPath=path.join(output,'report.csv');await download.saveAs(csvPath);assert.ok(fs.readFileSync(csvPath,'utf8').includes(brand));checks.push('CSV 导出');
 await page.goto(base+'/notifications/');await page.locator('[name=group_name]').fill('E2E未连接测试群');await page.locator('[name=enabled]').uncheck();await page.getByRole('button',{name:'保存通知设置'}).click();assert.match(await page.locator('main').innerText(),/配置已保存/);checks.push('通知配置（不发送真实消息）');
 await page.goto(base+'/settings/');const viewer='viewer'+stamp,viewerPassword='ArgusViewerTest-17!';await page.locator('[name=username]').fill(viewer);await page.locator('[name=password]').fill(viewerPassword);await page.locator('[name=role]').selectOption('viewer');await page.getByRole('button',{name:'创建账号',exact:true}).click();assert.match(await page.locator('main').innerText(),/成员已创建/);
 const viewerContext=await browser.newContext();const viewerPage=await viewerContext.newPage();await login(viewerPage,viewer,viewerPassword);await viewerPage.goto(base+eventPath);assert.equal(await viewerPage.getByRole('button',{name:'审核通过，检查通知规则'}).count(),0);const denied=await viewerContext.request.get(base+'/settings/');assert.equal(denied.status(),403);await viewerContext.close();checks.push('只读成员权限');
 const routes=['/','/projects/','/contents/','/events/','/review/','/sources/','/notifications/','/settings/','/operations/',eventPath,reportPath];
 for(const width of [1440,1024,390,320]){
   await page.setViewportSize({width,height:1000});
   for(const route of routes){await page.goto(base+route);if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))errors.push('Overflow '+width+' '+route);}
 }
 checks.push('11 页面 × 4 屏幕宽度布局');
 await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/');await page.screenshot({path:path.join(output,'dashboard-desktop.png'),fullPage:true});
 await page.goto(base+'/notifications/');await page.screenshot({path:path.join(output,'notifications-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.goto(base+eventPath);await page.screenshot({path:path.join(output,'event-mobile.png'),fullPage:true});
 assert.equal(errors.length,0,errors.join('\n'));
 fs.writeFileSync(path.join(output,'e2e-results.json'),JSON.stringify({passed:true,date:new Date().toISOString(),checks,errors,brand},null,2));
 console.log(JSON.stringify({passed:true,checks,errors}));
 await context.close();
 }finally{await browser.close();}
})().catch(error=>{fs.writeFileSync(path.join(output,'e2e-results.json'),JSON.stringify({passed:false,error:error.message,checks,errors},null,2));console.error(error);process.exitCode=1;});
