import json
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from .streams import parse_feed,newsnow_items,StreamError,clean
from .models import *
from . import services as svc

def atom(body='品牌星河发生包装破损',summary='普通摘要'):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom"><title>Feed</title><entry><id>stable-1</id><title>本周行业动态</title><link href="https://example.com/a"/><updated>2026-10-17T10:20:00+08:00</updated><author><name>作者甲</name></author><summary>{summary}</summary><content type="html">&lt;p&gt;{body}&lt;/p&gt;</content></entry></feed>'''.encode()

class StreamTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=User.objects.create_user('streamowner');cls.ws=Workspace.objects.create(name='流测试');Membership.objects.create(user=cls.user,workspace=cls.ws)
        cls.project=Project.objects.create(workspace=cls.ws,name='星河')
        cls.source=Source.objects.create(project=cls.project,name='订阅',url='https://example.com/feed')
    def setUp(self):self.client.force_login(self.user)
    def test_atom_prefers_content_over_summary_and_matches_body(self):
        items=parse_feed(atom());self.assertEqual(items[0]['level'],'fulltext');self.assertEqual(items[0]['summary'],'普通摘要');self.assertEqual(items[0]['author'],'作者甲')
        self.assertEqual(items[0]['published_at'].hour,2)
        svc.ingest(self.source,items);content=Content.objects.get();svc.analyze(content)
        self.assertTrue(content.relevant);content.refresh_from_db();self.assertEqual(content.sentiment,'负面线索')
        self.assertEqual(content.text_origin,'rss_content')
    def test_content_encoded_rss(self):
        xml=b'''<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>Feed</title><item><guid>one</guid><title>Title</title><description>Short</description><content:encoded><![CDATA[<p>Long body</p><p>Second paragraph</p>]]></content:encoded></item></channel></rss>'''
        row=parse_feed(xml)[0];self.assertIn('Long body\nSecond paragraph',row['text']);self.assertIn('Short',row['text']);self.assertEqual(row['level'],'fulltext')
    def test_json_feed_content_and_authors(self):
        data={'version':'https://jsonfeed.org/version/1.1','items':[{'id':'a','content_text':'星河有新动态','summary':'摘要','date_published':'2026-10-17T12:00:00+08:00','authors':[{'name':'作者乙'}],'url':'/article'}]}
        row=parse_feed(json.dumps(data).encode(),'https://example.com/feed')[0]
        self.assertEqual(row['url'],'https://example.com/article');self.assertEqual(row['author'],'作者乙');self.assertEqual(row['text_origin'],'json_content')
        self.assertIn('星河',row['title'])
    def test_summary_only_and_title_only_not_mislabeled(self):
        data={'version':'https://jsonfeed.org/version/1','items':[{'id':'a','title':'Title','summary':'Summary'},{'id':'b','title':'Title only'}]}
        rows=parse_feed(json.dumps(data).encode());self.assertEqual([r['level'] for r in rows],['summary','title'])
    def test_reject_unrelated_json_xml_entities_and_unsafe_link(self):
        for data in [b'{"items":[]}',b'{broken',b'<!DOCTYPE rss [<!ENTITY a SYSTEM "file:///secret">]><rss/>']:
            with self.assertRaises(StreamError):parse_feed(data)
        data={'version':'https://jsonfeed.org/version/1.1','items':[{'title':'x','url':'javascript:alert(1)'}]}
        self.assertEqual(parse_feed(json.dumps(data).encode())[0]['url'],'')
        self.assertEqual(clean('<script>malicious</script><p>Safe &amp; text</p>'),'Safe & text')
    def test_refresh_same_guid_updates_once_and_preserves_manual_feedback(self):
        svc.ingest(self.source,parse_feed(atom(body='普通内容')));content=Content.objects.get();content.feedback='无关';content.save()
        stats={};self.assertEqual(svc.ingest(self.source,parse_feed(atom()),stats=stats),0);self.assertEqual(stats['updated'],1)
        content.refresh_from_db();self.assertEqual(content.revision,2);self.assertEqual(content.feedback,'无关')
        svc.ingest(self.source,parse_feed(atom()),stats=stats);self.assertEqual(stats['updated'],0);self.assertEqual(Job.objects.filter(kind='analyze').count(),2)
    def test_shorter_evidence_does_not_erase_body(self):
        svc.ingest(self.source,parse_feed(atom()));content=Content.objects.get()
        svc.ingest(self.source,[{'external_id':'stable-1','title':content.title,'text':'short','level':'summary'}])
        content.refresh_from_db();self.assertIn('星河',content.text);self.assertEqual(content.level,'fulltext')
    def test_ranks_and_cache_dedup(self):
        source=Source.objects.create(project=self.project,name='榜单',kind='newsnow',url='https://example.com/api')
        payload={'status':'cache','updatedTime':1792200000000,'items':[{'id':'other','title':'Other','url':'https://example.com/other'},{'id':'brand','title':'星河动态','url':'https://example.com/brand'}]}
        rows=newsnow_items(json.dumps(payload).encode());svc.ingest(source,rows);svc.ingest(source,rows)
        content=Content.objects.get(title='星河动态');self.assertEqual(content.observations.count(),1);self.assertEqual(content.observations.first().rank,2)
        payload['updatedTime']+=1000;payload['items'].reverse();svc.ingest(source,newsnow_items(json.dumps(payload).encode()))
        self.assertEqual(list(content.observations.values_list('rank',flat=True)),[1,2]);self.assertEqual(Content.objects.filter(source=source).count(),2)
    def test_snapshot_without_timestamp_uses_payload_hash(self):
        payload={'status':'success','items':[{'id':1,'title':'One','url':'https://example.com/a'}]}
        first=newsnow_items(json.dumps(payload).encode());second=newsnow_items(json.dumps(payload).encode())
        self.assertEqual(first[0]['snapshot_key'],second[0]['snapshot_key']);self.assertIsNone(first[0]['upstream_at'])
    def test_full_read_ignores_conditional_headers_and_counts_update(self):
        self.source.etag='old';self.source.save()
        with patch('core.services.remote',return_value=(200,{},atom())) as remote:
            svc.collect(self.source,force=True);self.assertNotIn('If-None-Match',remote.call_args.kwargs['headers'])
        with patch('core.services.remote',return_value=(200,{},atom(body='星河内容更新'))):svc.collect(self.source)
        self.assertEqual(SourceRun.objects.latest('pk').updated,1)
    def test_detail_filter_and_workspace_isolation(self):
        svc.ingest(self.source,parse_feed(atom()));content=Content.objects.get()
        self.assertContains(self.client.get(f'/contents/{content.pk}/'),'订阅源提供的正文')
        self.assertContains(self.client.get('/contents/?stream=rss&level=fulltext'),'品牌星河')
        self.assertNotContains(self.client.get('/contents/?stream=newsnow'),'本周行业动态')
        other=User.objects.create_user('otherstream');ws=Workspace.objects.create(name='other');Membership.objects.create(user=other,workspace=ws);self.client.force_login(other)
        self.assertEqual(self.client.get(f'/contents/{content.pk}/').status_code,404)
    def test_changed_content_requires_new_review(self):
        svc.ingest(self.source,parse_feed(atom()));content=Content.objects.get();svc.analyze(content);event=Event.objects.get();event.review_status='审核通过';event.save()
        svc.ingest(self.source,parse_feed(atom(body='星河更新，仍有包装破损')));event.refresh_from_db();self.assertEqual(event.review_status,'待审核')
    def test_returning_to_old_digest_still_enqueues(self):
        svc.ingest(self.source,parse_feed(atom(body='版本甲')));svc.ingest(self.source,parse_feed(atom(body='版本乙')));svc.ingest(self.source,parse_feed(atom(body='版本甲')))
        self.assertEqual(Job.objects.filter(kind='analyze').count(),3)
    def test_ai_excerpt_retains_late_mentions(self):
        content=Content(source=self.source,title='标题没有品牌',text='普通资讯。'*2000+'星河发生包装破损，需要核实。'+'背景。'*2000)
        excerpt=svc.analysis_excerpt(content)
        self.assertIn('星河发生包装破损',excerpt);self.assertLessEqual(len(excerpt),8000)
