const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),base=process.env.ARGUS_TEST_URL||'http://127.0.0.1:8765';
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.ARGUS_CHROME?{executablePath:process.env.ARGUS_CHROME}:{})});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const password=fs.readFileSync(path.join(root,'data','首次登录.txt'),'utf8').match(/密码：([^\r\n]+)/)[1];
 await page.goto(base+'/login/');await page.locator('[name=username]').fill('admin');await page.locator('[name=password]').fill(password);await Promise.all([page.waitForURL(url=>url.href===base+'/'||url.href===base+'/onboarding/'),page.getByRole('button',{name:'登录 Argus →'}).click()]);
 for(const route of ['/','/projects/','/sources/','/contents/','/events/','/review/','/notifications/','/reports/','/settings/','/operations/']){const response=await page.goto(base+route);assert.equal(response.status(),200,route);}
 const health=await page.request.get(base+'/health/');assert.equal((await health.json()).application,'Argus');
 await page.goto(base+'/');assert.equal(await page.getByText('后台任务尚未就绪或已停止。',{exact:false}).count(),0);
 fs.mkdirSync(path.join(root,'test-results'),{recursive:true});await page.screenshot({path:path.join(root,'test-results','release-dashboard.png'),fullPage:true});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,pages:10,worker:'healthy',errors}));
 }finally{await browser.close();}})().catch(e=>{console.error(e.message);process.exitCode=1;});
