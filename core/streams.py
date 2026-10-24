"""Independent feed parsers; content returned by feeds is never executed."""
import hashlib,json,re
from datetime import datetime,timezone
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit
import feedparser

class StreamError(ValueError):pass

class TextReader(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.ignored=0
    def handle_starttag(self,tag,attrs):
        if tag in ['script','style','noscript','iframe','object','svg']:self.ignored+=1
        if not self.ignored and tag in ['p','div','li','br','h1','h2','h3','section','article']:self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ['script','style','noscript','iframe','object','svg']:self.ignored=max(0,self.ignored-1)
        if not self.ignored and tag in ['p','div','li','h1','h2','h3','section','article']:self.parts.append('\n')
    def handle_data(self,data):
        if not self.ignored:self.parts.append(data)

def clean(value,limit=20000):
    if not isinstance(value,str):return ''
    parser=TextReader()
    try:parser.feed(value)
    except Exception:raise StreamError('无法清理订阅文本')
    return '\n'.join(line for raw in ''.join(parser.parts).splitlines() if (line:=re.sub(r'\s+',' ',raw).strip()))[:limit]

def safe_link(value,base=''):
    if not isinstance(value,str):return ''
    value=urljoin(base,value.strip()) if value.strip() else ''
    try:
        p=urlsplit(value)
        return value[:2000] if p.scheme in ['http','https'] and p.hostname and not p.username and not p.password else ''
    except ValueError:return ''

def combined_text(body,summary):
    if body and summary and summary not in body:return (summary+'\n\n'+body)[:20000]
    return body or summary

def parse_feed(data,feed_url=''):
    if data.lstrip().startswith(b'{'):
        try:feed=json.loads(data)
        except (ValueError,UnicodeDecodeError):raise StreamError('JSON Feed 格式错误')
        if not isinstance(feed,dict) or feed.get('version') not in ['https://jsonfeed.org/version/1','https://jsonfeed.org/version/1.1'] or not isinstance(feed.get('items'),list):raise StreamError('来源不是有效 JSON Feed')
        rows=[]
        for entry in feed['items'][:300]:
            if not isinstance(entry,dict):continue
            summary=clean(entry.get('summary',''))
            plain=entry.get('content_text')
            body=plain.strip()[:20000] if isinstance(plain,str) else clean(entry.get('content_html',''))
            text=combined_text(body,summary)
            title=clean(entry.get('title',''),1000) or (text[:80]+'…' if text else '')
            if not title:continue
            authors=entry.get('authors',[]) or ([entry['author']] if isinstance(entry.get('author'),dict) else [])
            author=', '.join(clean(a.get('name',''),100) for a in authors if isinstance(a,dict)) if isinstance(authors,list) else ''
            url=safe_link(entry.get('url') or entry.get('external_url'),feed_url)
            rows.append({'external_id':entry.get('id') or url or title,'title':title,'text':text,'summary':summary,'author':author[:300],'url':url,'published_at':entry.get('date_published') or entry.get('date_modified'),'level':'fulltext' if body else ('summary' if text else 'title'),'text_origin':'json_content' if body else ('json_summary' if text else '')})
        return rows
    if re.search(br'<!\s*(DOCTYPE|ENTITY)',data,re.I):raise StreamError('订阅含不允许的 XML 声明')
    feed=feedparser.parse(data)
    if not feed.version and not feed.entries:raise StreamError('来源不是有效 RSS/Atom/JSON Feed')
    rows=[]
    for entry in feed.entries[:300]:
        summary=clean(entry.get('summary') or entry.get('description',''))
        content=entry.get('content',[])
        body='\n'.join(clean(part.get('value','')) for part in content if isinstance(part,dict) and part.get('type','text/html') in ['text/html','text/plain','application/xhtml+xml'])[:20000] if isinstance(content,list) else ''
        text=combined_text(body,summary)
        title=clean(entry.get('title',''),1000) or (text[:80]+'…' if text else '')
        if not title:continue
        url=safe_link(entry.get('link'),feed_url)
        if not url:
            url=next((link for part in entry.get('links',[]) if part.get('rel','alternate')=='alternate' and (link:=safe_link(part.get('href'),feed_url))), '')
        published=entry.get('published') or entry.get('updated')
        parsed=entry.get('published_parsed') or entry.get('updated_parsed')
        if parsed:
            try:published=datetime(*parsed[:6],tzinfo=timezone.utc)
            except (ValueError,TypeError):pass
        author=clean(entry.get('author') or entry.get('dc_creator',''),300)
        rows.append({'external_id':entry.get('id') or url or title,'title':title,'text':text,'summary':summary,'author':author,'url':url,'published_at':published,'level':'fulltext' if body else ('summary' if text else 'title'),'text_origin':'rss_content' if body else ('rss_summary' if text else '')})
    return rows

def newsnow_items(data):
    try:payload=json.loads(data)
    except (ValueError,UnicodeDecodeError):raise StreamError('来源不是有效 JSON')
    if not isinstance(payload,dict) or payload.get('status') not in ['success','cache'] or not isinstance(payload.get('items'),list):raise StreamError('聚合来源返回异常或不可用状态')
    valid=[]
    for position,entry in enumerate(payload['items'][:300],1):
        if not isinstance(entry,dict):continue
        title=clean(entry.get('title',''),1000);url=safe_link(entry.get('url'))
        if not title or not url:continue
        valid.append({'external_id':str(entry.get('id') or url),'title':title,'text':'','url':url,'level':'title','rank':position})
    updated=payload.get('updatedTime');upstream=None
    if isinstance(updated,(float,int)) and not isinstance(updated,bool):
        try:upstream=datetime.fromtimestamp(updated/1000,tz=timezone.utc)
        except (ValueError,OverflowError,OSError):pass
    key=hashlib.sha256(json.dumps({'at':upstream.isoformat() if upstream else None,'rows':valid},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    for item in valid:item.update(snapshot_key=key,upstream_at=upstream)
    return valid
