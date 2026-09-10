#!/usr/bin/env python3
"""临时校验脚本：实测「大字·清晰版」三档切换是否真的改变了各界面的计算字号。

用法：python3 scripts/check_font_scale.py
依赖：本机 Chrome（channel='chrome'），预览服务需已在 127.0.0.1:5001 运行。
"""
from playwright.sync_api import sync_playwright

URL = 'http://127.0.0.1:5001/'

# 各界面要抽样的元素：(说明, CSS 选择器, 所在视图)
TARGETS = [
    ('首页问候语', '.greeting-line2', 'home'),
    ('首页区块标题', '.section-title', 'home'),
    ('快捷入口标题', '.quick-card-title', 'home'),
    ('快捷入口描述', '.quick-card-desc', 'home'),
    ('热门问题标签', '.hot-tag', 'home'),
    ('资讯卡片标题', '.news-card-title', 'home'),
    ('资讯卡片摘要', '.news-card-summary', 'home'),
    ('底部导航文字', '.nav-item span', 'home'),
    ('产品页标题', '.memory-title', 'products'),
    ('产品分类标题', '.product-category-title', 'products'),
    ('产品标签', '.product-cloud span, .product-cloud button', 'products'),
    ('聊天输入框', '#message-input', 'chat'),
    ('聊天消息气泡', '.msg-bubble', 'chat'),
    ('产品详情名称', '#tsize-probe .product-detail-name', 'detail'),
    ('产品详情摘要', '#tsize-probe .product-detail-summary', 'detail'),
    ('产品详情正文', '#tsize-probe .product-detail-content', 'detail'),
    ('资讯详情正文', '#tsize-probe .news-detail-body', 'detail'),
]


def measure(page, label):
    out = {}
    for desc, sel, _view in TARGETS:
        try:
            el = page.query_selector(sel)
            if not el:
                out[desc] = None
                continue
            out[desc] = round(float(page.evaluate(
                'e => parseFloat(getComputedStyle(e).fontSize)', el)), 1)
        except Exception:
            out[desc] = None
    print(f'\n--- {label} ---')
    for desc, val in out.items():
        print(f'  {desc:14s} {val if val else "(未找到)"}')
    return out


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome')
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        page.goto(URL, wait_until='networkidle')

        # 进门：选团队 + 姓名
        page.select_option('#team-select', index=1)
        page.fill('#member-name-input', '测试用户')
        page.click('.btn-primary')
        page.wait_for_timeout(1500)

        # 触发产品页渲染（产品内容按需加载，不切过去 DOM 里没有）
        page.evaluate("switchView('products')")
        page.wait_for_timeout(1800)
        # 注入一条模拟聊天消息，用于测量问答气泡字号（不必真发消息）
        page.evaluate("""() => {
            const c = document.querySelector('#chat-messages');
            if (c && !c.querySelector('.msg-bubble')) {
                c.insertAdjacentHTML('beforeend',
                    '<div class="msg"><div class="msg-avatar">AI</div>' +
                    '<div class="msg-body"><div class="msg-bubble">示例回答内容</div></div></div>');
            }
        }""")
        page.evaluate("""() => {
            const host = document.querySelector('#app-container');
            if (host && !document.querySelector('#tsize-probe')) {
                host.insertAdjacentHTML('beforeend',
                    '<div id="tsize-probe" style="display:none">' +
                    '<div class="product-detail-name">产品名称</div>' +
                    '<div class="product-detail-summary">产品摘要</div>' +
                    '<div class="product-detail-content rich-text"><p>产品详情正文</p></div>' +
                    '<div class="news-detail-body rich-text"><p>资讯详情正文</p></div>' +
                    '</div>');
            }
        }""")
        page.evaluate("switchView('home')")
        page.wait_for_timeout(600)

        standard = measure(page, '标准档 1.0')

        # 切到「大」档
        page.evaluate("selectTextSize('l')")
        page.wait_for_timeout(400)
        large = measure(page, '大字档 1.3')

        # 切到「超大」档
        page.evaluate("selectTextSize('xl')")
        page.wait_for_timeout(400)
        xlarge = measure(page, '超大档 1.55')

        print('\n=== 变化检查（标准 → 大）===')
        bad = []
        for desc in standard:
            a, b = standard[desc], large[desc]
            if a is None:
                print(f'  ?? {desc}: 页面未找到该元素')
                continue
            if b is None:
                continue
            ratio = b / a if a else 0
            flag = 'OK ' if ratio > 1.15 else '未变'
            if ratio <= 1.15:
                bad.append(desc)
            print(f'  {flag} {desc:14s} {a}px → {b}px  (×{ratio:.2f})')

        print('\n=== 超大档绝对值 ===')
        for desc, v in xlarge.items():
            if v:
                print(f'  {desc:14s} {v}px')

        print(f'\n未随档位放大的元素: {bad if bad else "无"}')
        browser.close()


if __name__ == '__main__':
    main()
