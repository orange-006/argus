const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),base=process.env.ARGUS_TEST_URL||'http://127.0.0.1:8767';
const data=process.env.ARGUS_TEST_DATA_DIR;if(!data)throw Error('Use a dedicated fresh ARGUS_TEST_DATA_DIR');
const output=path.join(root,'test-results','v1.1');fs.mkdirSync(output,{recursive:true});
const checks=[],errors=[];const brand='初次体验未被报道品牌'+Date.now();
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.ARGUS_CHROME?{executablePath:process.env.ARGUS_CHROME}:{})});try{
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=500)errors.push('HTTP '+r.status()+' '+new URL(r.url()).pathname);});
 const token=fs.readFileSync(path.join(data,'.setup-token'),'ascii').trim();
 await page.goto(base+'/welcome/?token='+encodeURIComponent(token));assert.equal(page.url(),base+'/welcome/');
 await page.locator('[name=username]').fill('beginner');await page.locator('[name=workspace_name]').fill('第一次使用的品牌空间');await page.locator('[name=password]').fill('BeginnerSafePassword22!');await page.locator('[name=confirm]').fill('BeginnerSafePassword22!');
 await Promise.all([page.waitForURL(base+'/onboarding/'),page.getByRole('button',{name:'创建账号，开始设置 →'}).click()]);assert.ok(!fs.existsSync(path.join(data,'首次登录.txt')));checks.push('新装直接创建账号，无密码文件');
 await page.screenshot({path:path.join(output,'onboarding-step-one.png'),fullPage:true});
 await page.locator('[name=industry]').selectOption('consumer');await page.locator('[name=name]').fill(brand);await page.getByRole('button',{name:'下一步：选择信息来源 →'}).click();
 assert.match(await page.locator('#setup-coverage').innerText(),/消费品牌覆盖可能有限/);assert.ok(await page.locator('.source-choice').count()>=4);
 for(const checkbox of await page.locator('[name=presets]').all())await checkbox.uncheck();await page.getByRole('button',{name:'下一步：确认设置 →'}).click();assert.match(await page.locator('#setup-source-error').innerText(),/至少勾选一个来源/);
 await page.locator('.source-choice').filter({hasText:'中国新闻网'}).locator('input').check();checks.push('真实来源库、覆盖提示、必选校验');
 await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(output,'onboarding-source-selection.png'),fullPage:true});
 await page.getByRole('button',{name:'下一步：确认设置 →'}).click();assert.match(await page.locator('#setup-summary-name').innerText(),new RegExp(brand));
 await page.getByRole('button',{name:'确认，开始我的监测 →'}).click();assert.match(page.url(),/first-results\/\d+\//);const resultPath=new URL(page.url()).pathname;
 const initial=await page.request.get(base+resultPath+'status/');assert.ok(['collecting','analyzing','no_matches'].includes((await initial.json()).stage));checks.push('向导自动创建项目与真实采集任务');
 let summary;
 for(let i=0;i<90;i++){summary=await (await page.request.get(base+resultPath+'status/')).json();if(summary.finished&&summary.report_id)break;await page.waitForTimeout(1000);}
 assert.equal(summary.stage,'no_matches');assert.ok(summary.total>0);assert.equal(summary.matches,0);assert.ok(summary.report_id);checks.push('真实来源内容与零品牌命中分开，首次报告自动生成');
 await page.reload();assert.match(await page.locator('#first-title').innerText(),/暂未发现相关提及/);await page.screenshot({path:path.join(output,'first-results-real-no-match.png'),fullPage:true});
 await page.goto(base+'/reports/'+summary.report_id+'/');assert.match(await page.locator('main').innerText(),/相关提及 0 条/);assert.ok(!await page.locator('main').innerText().then(t=>t.includes('本报告包含')));
 await page.goto(base+'/onboarding/');await page.getByRole('button',{name:'进入独立体验空间 →'}).click();assert.match(await page.locator('.experience-banner').innerText(),/独立体验空间/);await page.screenshot({path:path.join(output,'isolated-experience.png'),fullPage:true});
 await page.goto(base+'/contents/');assert.match(await page.locator('main').innerText(),/青禾饮品瓶盖/);await page.getByRole('button',{name:'退出体验，返回我的空间 →'}).click();await page.goto(base+'/contents/');assert.ok(!(await page.locator('main').innerText()).includes('青禾饮品瓶盖'));checks.push('进入和退出独立体验，真实数据不混入样例');
 const routes=['/','/onboarding/','/source-library/',resultPath,'/contents/','/events/','/notifications/','/reports/','/settings/','/sources/'];
 for(const width of [1440,1024,390,320]){await page.setViewportSize({width,height:1000});for(const route of routes){await page.goto(base+route);if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))errors.push('Overflow '+width+' '+route);}}
 await page.goto(base+'/onboarding/');await page.screenshot({path:path.join(output,'onboarding-mobile.png'),fullPage:true});checks.push('10 页面 × 4 种宽度检查');
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(output,'onboarding-results.json'),JSON.stringify({passed:true,checks,errors,first_results:summary},null,2));console.log(JSON.stringify({passed:true,checks,errors,real_source_items:summary.total,brand_mentions:summary.matches}));
 }finally{await browser.close();}})().catch(e=>{fs.writeFileSync(path.join(output,'onboarding-results.json'),JSON.stringify({passed:false,error:e.message,checks,errors},null,2));console.error(e);process.exitCode=1;});
