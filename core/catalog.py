"""Release-verified metadata. Recheck on connection, never assume availability."""
from datetime import date
import json
from pathlib import Path
from .models import SourcePreset
PRESETS=[
 {'key':'chinanews','name':'中国新闻网 · 滚动新闻','url':'https://www.chinanews.com.cn/rss/scroll-news.xml','category':'综合资讯','description':'公开滚动新闻订阅，适合观察社会与行业公开报道。','coverage':'新闻网站公开资讯；不包含社交平台帖子、视频或用户评论。'},
 {'key':'ithome','name':'IT之家 · 科技资讯','url':'https://www.ithome.com/rss/','category':'科技与互联网','description':'科技产品、数码与互联网相关资讯，更新较频繁。','coverage':'科技新闻报道；品牌出现取决于来源是否报道，不能按需全网搜索。'},
 {'key':'solidot','name':'Solidot · 科技观察','url':'https://www.solidot.org/index.rss','category':'科技与互联网','description':'开源、科学、互联网与科技话题。','coverage':'科技主题公开资讯，不提供消费品牌评论或投诉数据。'},
 {'key':'ruanyifeng','name':'阮一峰的网络日志','url':'https://www.ruanyifeng.com/blog/atom.xml','category':'科技与互联网','description':'技术文章与科技爱好者周刊，适合行业资讯补充。','coverage':'个人博客公开文章，更新频率较低，仅保留订阅中可获得的条目。','interval_minutes':180},
]

# Registry snapshot from NewsNow (MIT), aliases removed; no upstream crawler code.
registry=json.loads(Path(__file__).with_name('newsnow_sources.json').read_text(encoding='utf-8-sig'))
categories={'china':'国内热点','tech':'科技与互联网','finance':'财经商业','world':'国际资讯','sports':'体育'}
for source_id, meta in registry.items():
    if meta.get('redirect'):continue
    PRESETS.append({'key':'newsnow-'+source_id,'kind':'newsnow','name':meta['name']+' · '+meta.get('title','热点资讯'),
      'url':'https://newsnow.busiyi.world/api/s?id='+source_id,'category':categories.get(meta.get('column'),'其他资讯'),
      'description':'NewsNow 聚合目录中的公开榜单或资讯。'+meta.get('desc',''),
      'coverage':'仅当前聚合条目的标题和原文链接；不是关键词搜索，不含完整评论或历史全量数据。',
      'content_level':'标题与链接','interval_minutes':60,
      'usage_note':'依赖第三方 NewsNow 服务，可能限流或失效。聚合程序 MIT 许可不等于原始内容商用授权。上游标记：'+str(meta.get('disable','无'))})
PRESETS.extend([
 {'key':'hn-frontpage','name':'Hacker News · 首页订阅','url':'https://hnrss.org/frontpage','category':'科技与互联网','description':'TrendRadar 配置中列出的 Hacker News RSS。','coverage':'首页文章标题与摘要，不包含完整讨论。'},
 {'key':'yahoo-finance','name':'Yahoo Finance · 财经新闻','url':'https://finance.yahoo.com/news/rssindex','category':'财经商业','description':'TrendRadar 配置中列出的 Yahoo 财经 RSS。','coverage':'英文财经资讯标题与摘要。'},
])

def seed_catalog():
    checks_path=Path(__file__).with_name('source_checks.json')
    checks=json.loads(checks_path.read_text(encoding='utf-8')) if checks_path.exists() else {}
    for item in PRESETS:
        check=checks.get(item['key'])
        defaults={**item,'interval_minutes':item.get('interval_minutes',60),'verified_date':date(2026,10,17) if check or item['key'] in ['chinanews','ithome','solidot','ruanyifeng'] else None,
          'check_status':check['status'] if check else ('发布前连接检查通过' if item.get('kind','rss')=='rss' and item['key'] not in ['hn-frontpage','yahoo-finance'] else '待首次连接检查')}
        defaults.pop('key')
        SourcePreset.objects.get_or_create(key=item['key'],defaults=defaults)
