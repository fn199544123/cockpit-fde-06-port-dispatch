#!/usr/bin/env python3
"""真实 Chromium 验收；隔离浏览器上下文，不改变用户浏览器数据。"""
import argparse, csv, hashlib, io, json, time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('--url',default='http://127.0.0.1:18086/')
args=parser.parse_args()
results=[]
def check(name, fn):
    fn()
    results.append({'name':name,'passed':True})
def require(cond, msg='断言失败'):
    assert cond,msg
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    context=browser.new_context(viewport={'width':1440,'height':1100},accept_downloads=True)
    page=context.new_page()
    errors=[]; external=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:external.append(r.url) if not r.url.startswith(args.url) and not r.url.startswith('data:') else None)
    response=page.goto(args.url)
    check('宿主机 HTTP 200 与初始台账',lambda: require(response.status==200 and page.locator('[data-row]').count()==3))
    def snapshot():return page.evaluate('JSON.stringify(state)')
    def rejected(expr, part):
        before=snapshot()
        msg=page.evaluate('(expression)=>{try{eval(expression);return "NOT_REJECTED"}catch(e){return e.message}}',expr)
        require(part in msg,msg)
        require(snapshot()==before,'拒绝后数据不应变化')
    def create_ui():
        page.locator('#new-task').click()
        for k,v in {'id':'ZY-910','name':'演示验收船卸船入场','qty':'7','start':'2026-09-28T08:00','end':'2026-09-28T09:00'}.items():page.locator(f'[name="{k}"]').fill(v)
        page.locator('[name="yard"]').select_option('CW-002')
        page.locator('#form button[type=submit]').click()
        require(page.locator('[data-row="ZY-910"]').count()==1)
    check('通过界面新增作业任务',create_ui)
    check('待派发不能直接完成',lambda:rejected("advance('ZY-910','已完成')",'非法状态'))
    def edit_ui():
        page.locator('[data-row="ZY-910"] [data-action=edit]').click()
        page.locator('[name="qty"]').fill('9')
        page.locator('#form button[type=submit]').click()
        require(page.evaluate("item('tasks','ZY-910').qty")==9)
    check('编辑任务更新箱量',edit_ui)
    def dispatch_ui():
        page.locator('[data-row="ZY-910"] [data-action=dispatch]').click()
        page.locator('[name="berth"]').select_option('BW-002')
        page.locator('[name="vehicle"]').select_option('JC-002')
        page.locator('#form button[type=submit]').click()
        require(page.evaluate("item('tasks','ZY-910').status")=='已派发')
        require('1 / 3' in page.locator('[data-stat="0"]').inner_text())
        require('1 / 3' in page.locator('[data-stat="1"]').inner_text())
        require(page.evaluate("reserved('CW-002')")==9)
    check('界面指定空闲泊位车辆派发，统计及堆场预留联动',dispatch_ui)
    check('已派发不能重复派发',lambda:rejected("dispatch('ZY-910','BW-003','JC-003')",'仅待派发'))
    check('占用泊位拒绝重复使用',lambda:rejected("dispatch('ZY-002','BW-002','JC-003')",'泊位已占用'))
    check('占用车辆拒绝重复使用',lambda:rejected("dispatch('ZY-002','BW-003','JC-002')",'车辆已占用'))
    check('已派发不能跳过执行直接完成',lambda:rejected("advance('ZY-910','已完成')",'非法状态'))
    check('已派发任务禁止编辑绕过占用',lambda:rejected("saveRecord('tasks','ZY-910',{})",'禁止修改'))
    def complete_ui():
        page.locator('[data-row="ZY-910"] [data-action=start]').click()
        require(page.evaluate("item('tasks','ZY-910').status")=='执行中')
        page.locator('[data-row="ZY-910"] [data-action=finish]').click()
        require(page.evaluate("item('tasks','ZY-910').status")=='已完成')
        require(page.evaluate("item('yards','CW-002').used")==29)
        require(page.evaluate("reserved('CW-002')")==0)
        require('2 / 3' in page.locator('[data-stat="0"]').inner_text())
        require('2 / 3' in page.locator('[data-stat="1"]').inner_text())
        require('1 / 4' in page.locator('[data-stat="3"]').inner_text())
    check('界面执行及完成：资源释放、库存入账、完成统计联动',complete_ui)
    check('完成不可重复入库',lambda:rejected("advance('ZY-910','已完成')",'非法状态'))
    def new_task(id,start,end,qty=1):
        return page.evaluate('v=>saveRecord("tasks","",v)',dict(id=id,name='演示冲突验收',qty=qty,yard='CW-002',start=start,end=end))
    new_task('ZY-911','2026-09-28T08:30','2026-09-28T10:00')
    check('空闲泊位历史排班重叠被拒绝',lambda:rejected("dispatch('ZY-911','BW-002','JC-003')",'排班时间重叠'))
    check('空闲车辆历史排班重叠被拒绝',lambda:rejected("dispatch('ZY-911','BW-003','JC-002')",'排班时间重叠'))
    def adjacent():
        new_task('ZY-912','2026-09-28T09:00','2026-09-28T10:00')
        page.evaluate("dispatch('ZY-912','BW-002','JC-002')")
        require(page.evaluate("item('tasks','ZY-912').status")=='已派发')
    check('前后相接的排班允许派发',adjacent)
    new_task('ZY-913','2026-09-29T09:00','2026-09-29T10:00',1000)
    check('超出堆场容量拒绝派发',lambda:rejected("dispatch('ZY-913','BW-003','JC-003')",'容量不足'))
    check('缩减货位容量不能侵占预留',lambda:rejected("saveRecord('yards','CW-002',{name:'西区货位',capacity:29,used:29})",'容量不足'))
    check('拒绝倒置排班时间',lambda:rejected("saveRecord('tasks','',{id:'ZY-914',name:'演示',qty:1,yard:'CW-002',start:'2026-09-29T10:00',end:'2026-09-29T09:00'})",'结束时间'))
    check('拒绝重复编号',lambda:rejected("saveRecord('berths','',{id:'BW-001',name:'演示泊位'})",'编号已存在'))
    check('拒绝负数箱量',lambda:rejected("saveRecord('tasks','',{id:'ZY-914',name:'演示',qty:-1,yard:'CW-002',start:'2026-09-29T09:00',end:'2026-09-29T10:00'})",'整数'))
    def resources_ui():
        for tab,id in [('berths','BW-910'),('yards','CW-910'),('vehicles','JC-910')]:
            page.locator(f'[data-tab={tab}]').click();page.locator('#add').click()
            page.locator('[name=id]').fill(id);page.locator('[name=name]').fill('演示新增资源')
            page.locator('#form button[type=submit]').click()
            page.locator(f'[data-row="{id}"] [data-action=edit]').click()
            page.locator('[name=name]').fill('演示修改资源');page.locator('#form button[type=submit]').click()
            require('演示修改资源' in page.locator(f'[data-row="{id}"]').inner_text())
            page.locator('#search').fill(id)
            require(page.locator('[data-row]').count()==1)
            with page.expect_download() as d:page.locator('#export').click()
            rows=list(csv.reader(io.StringIO(Path(d.value.path()).read_text('utf-8-sig'))))
            require(len(rows)==2 and rows[1][0]==id)
    check('泊位、货位、车辆分别新增编辑筛选与CSV导出',resources_ui)
    def persistence():
        before=snapshot();page.reload();require(snapshot()==before)
        require(page.evaluate("Object.keys(localStorage).every(k=>k.startsWith('development-6-'))"))
    check('刷新保持全部数据，localStorage键使用指定前缀',persistence)
    def export_task():
        page.locator('#search').fill('ZY-910');page.locator('#filter').select_option('已完成')
        require(page.locator('[data-row]').count()==1)
        with page.expect_download() as d:page.locator('#export').click()
        rows=list(csv.reader(io.StringIO(Path(d.value.path()).read_text('utf-8-sig'))))
        require(len(rows)==2 and rows[1][0]=='ZY-910' and rows[1][2]=='9')
    check('任务组合筛选与实际下载CSV内容一致',export_task)
    def reset():
        before=snapshot();page.locator('#reset').click();page.locator('#reset-cancel').click();require(snapshot()==before)
        page.locator('#reset').click();page.locator('#reset-confirm').click()
        require(page.evaluate('state.tasks.length')==3 and page.evaluate('state.yards[1].used')==20)
        page.reload();require(page.evaluate('state.tasks.length')==3)
    check('重置取消保留；确认恢复样例并持久化',reset)
    page.screenshot(path=str(ROOT/'acceptance-desktop.png'),full_page=True)
    def mobile():
        page.set_viewport_size({'width':390,'height':844})
        require(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'手机页面横向溢出')
        page.locator('#new-task').click()
        require(page.locator('#editor').is_visible())
        require(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        page.locator('#cancel').click()
        page.screenshot(path=str(ROOT/'acceptance-mobile.png'),full_page=True)
    check('390px手机无整页横向溢出，新增弹窗可操作',mobile)
    check('无浏览器脚本错误，无页面外部请求',lambda: require(not errors and not external,str(errors+external)))
    browser.close()
report={'passed':True,'browser':'Playwright Chromium headless','runtime':'GPU 宿主机 fangnangpu，共享同路径','url':args.url,'timestamp':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'html_sha256':hashlib.sha256((ROOT/'index.html').read_bytes()).hexdigest(),'checks':results,'screenshots':['acceptance-desktop.png','acceptance-mobile.png']}
(ROOT/'acceptance-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':True,'count':len(results),'url':args.url},ensure_ascii=False))
