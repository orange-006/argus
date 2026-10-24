const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.ARGUS_CHROME});try{
const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
const password=fs.readFileSync(path.resolve(__dirname,'../data/首次登录.txt'),'utf8').match(/密码：([^\r\n]+)/)[1];
await page.goto('http://127.0.0.1:8765/login/');await page.locator('[name=username]').fill('admin');await page.locator('[name=password]').fill(password);await page.getByRole('button',{name:'登录 Argus →'}).click();await page.waitForURL(url=>!url.pathname.includes('login'));
await page.goto('http://127.0.0.1:8765/onboarding/');assert.equal(await page.locator('[data-source-card]').count(),58);
await page.locator('[name=name]').fill('来源界面检查');await page.locator('[data-next]').first().click();
await page.locator('[data-source-search]').fill('微博');assert.equal(await page.locator('[data-source-card]:visible').count(),1);
await page.locator('[data-source-clear]').click();await page.locator('[data-source-select]').click();assert.equal(await page.locator('[name=presets]:checked').count(),1);
await page.locator('[data-source-search]').fill('');
for(const width of [390,768,1440]){await page.setViewportSize({width,height:950});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Horizontal overflow '+width);}
assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,presets:58,search:true,bulkSelection:true,widths:[390,768,1440]}));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
