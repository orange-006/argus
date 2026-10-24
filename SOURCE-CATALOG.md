# 来源目录扩充

新增 NewsNow 全部 52 个非重定向来源，保留上游受部署环境限制的来源并显示实际连接检查结果；14 个别名不重复展示。原 4 个 RSS 加入 TrendRadar 配置中的 Hacker News 和 Yahoo Finance，共 58 个可选择预设。

目录来源：https://github.com/newsnext/newsnow/blob/main/shared/sources.json 。目录数据按 MIT 使用；仅使用元数据，采集解析独立实现。TrendRadar 配置作为调研参考，没有复制 GPL 程序。第三方服务和原站内容的授权范围应分别确认。

连接快照在 core/source_checks.json；通过仅代表发布检查时成功。每次真实采集仍重新验证 HTTP 状态与数据结构。失败来源允许手动选择重试；不会将它的失败视为“没有舆情”。新增预设不自动添加到客户项目，用户选择后才采集，避免默认启用全部来源产生大量无关内容。

来源库支持搜索（包含分类名称）、选中当前显示来源与清空。调度、首次结果、立即采集、启停、去重和后续分析均覆盖 RSS 与 NewsNow。

## 其他已调研项目的边界

- RSSHub：是路由生成器，不是固定订阅清单。账号、栏目、关键词和部署地址不同会产生无限路由，不能把所有路由变成开箱可用来源。已支持在来源管理添加可用的 RSSHub 订阅 URL；需要 Cookie 的路由必须由运营方配置。
- Harken / OpenMagpie：HN 已覆盖；Bluesky 关键词检索、Stack Overflow 标签检索、Mastodon 实例、Reddit、YouTube、X 均涉及用户范围或授权配置，不冒充固定免费来源。本轮未实现这些定向采集器。
- BettaFish：主要提供分析流程，不额外产生可预设的公开内容源。
- MediaCrawler：未引入其限制商用的代码，未把登录爬虫当作免费来源。
- changedetection.io / MediaCloud：分别需要目标网页或 API 账户，不存在可直接照搬的通用来源目录。

抖音、微博等榜单只包含上榜话题标题与原文链接，不是全站搜索、定向品牌评论采集，也不能证明全网覆盖。NewsNow 公共服务故障或限流会同时影响多个榜单；长期商用应部署自有聚合服务并确认内容许可。
