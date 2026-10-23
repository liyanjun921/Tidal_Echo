/* Run through run_e2e.py; fixtures, never live credentials. */
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.LUNE_TEST_CHROMIUM?{executablePath:process.env.LUNE_TEST_CHROMIUM,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--no-zygote','--single-process']}: {})});
 const errors=[];const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true});
 const page=await context.newPage();page.on('pageerror',e=>{errors.push(e.message);console.error('UI ERROR',e.message)});page.on('response',async r=>{if(r.status()>=400)console.error('HTTP',r.status(),new URL(r.url()).pathname,(await r.text()).slice(0,400))});
 const url='http://127.0.0.1:8089/';await page.goto(url);
 await page.locator('#quickThemeButton').click();await page.locator('#relaySecret').fill('fixture-owner-secret');await page.locator('#connectionForm').evaluate(f=>f.requestSubmit());
 await page.waitForFunction(()=>document.querySelector('#settingsStatus').textContent.includes('连接成功'));
 for(const name of ['gpt','claude']){
  const form=page.locator('#agent-'+name);await form.locator('..').locator('summary').click();
  await form.locator('[name=protocol]').selectOption(name==='gpt'?'openai':'anthropic');
  await form.locator('[name=url]').fill('http://127.0.0.1:8766/v1');await form.locator('[name=model]').fill('fixture-'+name);await form.locator('[name=key]').fill('not-a-real-key-'+name);
  await form.evaluate(f=>f.requestSubmit());await page.waitForFunction(name=>document.querySelector('#settingsStatus').textContent.includes(name.toUpperCase()+' 设置已保存'),name);
  assert.equal(await form.locator('[name=key]').inputValue(),'');
 }
 await page.getByText('MCP 工具',{exact:true}).click();await page.locator('#mcpForm [name=serverName]').fill('fixture');await page.locator('#mcpForm [name=url]').fill('http://127.0.0.1:8767/mcp');await page.locator('#mcpForm').evaluate(f=>f.requestSubmit());await page.waitForFunction(()=>document.querySelector('#toolStatus').textContent.includes('online'));
 await page.locator('#closeConnection').click();await page.locator('#homeChats .home-conversation').first().click();
 await page.locator('#messageInput').fill('PRIVATE_UI_MARKER');await page.locator('#chatForm').evaluate(f=>f.requestSubmit());
 await page.waitForTimeout(1200);
 if((await page.locator('#chatStream').innerText()).includes('⚠️'))throw new Error('fixture model failed');
 await page.waitForFunction(()=>document.querySelector('#chatStream').textContent.includes('TEST_GPT')&&!document.querySelector('#runStatus').textContent.includes('正在'));
 await page.getByRole('button',{name:'记住这句话',exact:true}).click();await page.locator('#memoryForm [name=title]').fill('私聊来源');await page.locator('#memoryForm').evaluate(f=>f.requestSubmit());
 await page.waitForFunction(()=>document.querySelector('#modalOverlay').hidden);
 await page.locator('#backToHome').click();await page.locator('#homeChats .home-conversation').nth(2).click();
 await page.locator('#messageInput').fill('GROUP_UI_MARKER');await page.locator('#chatForm').evaluate(f=>f.requestSubmit());
 await page.waitForFunction(()=>document.querySelector('#chatStream').textContent.includes('TEST_CLAUDE')&&!document.querySelector('#runStatus').textContent.includes('正在'));
 assert.equal(await page.locator('.message-bubble').filter({hasText:'GROUP_UI_MARKER'}).count(),1);
 await page.reload();await page.locator('#homeChats .home-conversation').nth(2).click();await page.waitForFunction(()=>document.querySelector('#chatStream').textContent.includes('TEST_CLAUDE'));
 assert.equal(await page.locator('.message-bubble').filter({hasText:'GROUP_UI_MARKER'}).count(),1);
 await page.locator('#attachmentInput').setInputFiles({name:'note.txt',mimeType:'text/plain',buffer:Buffer.from('ATTACHMENT_BODY_MARKER')});await page.waitForFunction(()=>document.querySelector('#pendingFiles').textContent.includes('note.txt'));
 await page.locator('#messageInput').fill('@GPT 请读附件');await page.locator('#chatForm').evaluate(f=>f.requestSubmit());
 await page.waitForFunction(()=>document.querySelector('#chatStream').textContent.includes('note.txt')&&!document.querySelector('#runStatus').textContent.includes('正在'));
 await page.locator('#messageInput').fill('@GPT TOOL_UI_MARKER');await page.locator('#chatForm').evaluate(f=>f.requestSubmit());await page.waitForFunction(()=>document.querySelector('#chatStream').textContent.includes('TOOL_RESULT_MARKER')&&!document.querySelector('#runStatus').textContent.includes('正在'));assert.ok(await page.getByText('工具执行记录',{exact:true}).count());
 await page.evaluate(()=>navigator.serviceWorker.ready);await context.setOffline(true);await page.reload();await page.locator('#homeChats .home-conversation').nth(2).click();await page.waitForFunction(()=>document.querySelector('#chatStream').textContent.includes('TEST_GPT'));
 await page.locator('#messageInput').fill('@GPT OFFLINE_RETRY_MARKER');await page.locator('#chatForm').evaluate(f=>f.requestSubmit());await page.getByRole('button',{name:'核对并重试发送'}).waitFor();
 await page.reload();await page.locator('#homeChats .home-conversation').nth(2).click();await page.getByRole('button',{name:'核对并重试发送'}).waitFor();await context.setOffline(false);await page.getByRole('button',{name:'核对并重试发送'}).click();
 await page.waitForFunction(()=>document.querySelector('#chatStream').textContent.includes('OFFLINE_RETRY_MARKER')&&!document.querySelector('#chatStream').textContent.includes('核对并重试发送')&&!document.querySelector('#runStatus').textContent.includes('正在'));
 assert.equal(await page.locator('.message-bubble').filter({hasText:'OFFLINE_RETRY_MARKER'}).count(),1);
 for(const width of [320,390,1440]){
  await page.setViewportSize({width,height:844});await page.waitForTimeout(150);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'horizontal overflow at '+width);
  await page.screenshot({path:process.env.LUNE_TEST_OUTPUT+'/lune-'+width+'.png',fullPage:true});
 }
 await page.setViewportSize({width:390,height:844});await page.locator('#quickThemeButton').click();
 assert.ok(await page.evaluate(()=>document.querySelector('#connectionDialog').scrollWidth<=document.querySelector('#connectionDialog').clientWidth+1),'settings overflow');
 assert.deepEqual(errors,[]);console.log(JSON.stringify({browser:'chromium',widths:[320,390,1440],uiErrors:errors,flow:'connection → private chat → sourced memory → group → reload → attachment → MCP → offline restart → retry'}));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
