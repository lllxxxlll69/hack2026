// Isolated frontend render checks: no browser credentials or production writes.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const nodes = new Map();
function node(selector) {
  if (!nodes.has(selector)) nodes.set(selector, {
    innerHTML: '', textContent: '', value: '', dataset: {}, style: {},
    classList: {add(){},remove(){},toggle(){}},
    setAttribute(){},removeAttribute(){},focus(){},
    showModal(){this.open=true;},close(){this.open=false;},reset(){},
  });
  return nodes.get(selector);
}
const ctx=vm.createContext({
  document:{querySelector:node,querySelectorAll:()=>[],body:{dataset:{}}},
  setTimeout:()=>0,clearTimeout(){},setInterval(){},
  fetch:async path=>{
    assert.equal(path,'/api/knowledge');
    return {ok:true,status:200,json:async()=>[{title:'Test rule',text:'Source text'}]};
  }, FormData:class{},URL,console,
});
const source=fs.readFileSync(new URL('../web/app.js',import.meta.url),'utf8')
  .replace(/^init\(\)\.catch.*$/m,'');
vm.runInContext(source,ctx);
vm.runInContext("user={name:'Test <student>',username:'preview',email:'',active:true,must_change:false,role:'student'}; types={}; conversations=[]; home();",ctx);
assert.match(node('#content').innerHTML,/panel abilities/);
assert.match(node('#content').innerHTML,/Здесь появится история/);
assert.match(node('#content').innerHTML,/aria-label="Прикрепить документ"/);
vm.runInContext('history()',ctx);
assert.match(node('#content').innerHTML,/Пока нет обращений/);
await vm.runInContext("page='documents'; documents()",ctx);
assert.match(node('#content').innerHTML,/Добавьте первый документ/);
await vm.runInContext("page='knowledge'; knowledge()",ctx);
assert.equal(node('#rule-text').textContent,'Source text');
vm.runInContext('settingsPage()',ctx);
assert.match(node('#content').innerHTML,/Test &lt;student&gt;/);
assert.doesNotMatch(node('#content').innerHTML,/account-verify|Код подтверждения/);
vm.runInContext("user.must_change=true; showPage('home')",ctx);
assert.match(node('#content').innerHTML,/Смените временный пароль/);
node('#registration-info').onclick();
assert.equal(node('#registration-dialog').open,true);
node('#close-registration').onclick();
assert.equal(node('#registration-dialog').open,false);
console.log('Frontend render checks passed: home, empty documents/history, rules, settings, registration help, password gate.');
