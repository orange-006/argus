# 第三方依赖

Argus 没有复制 TrendRadar、BettaFish、MediaCrawler 或 RSSHub 源码。本项目使用通用开源依赖，自行实现品牌监测应用逻辑。

主要直接依赖：Django（BSD-3-Clause）、requests（Apache-2.0）、feedparser（BSD-2-Clause）、cryptography（Apache-2.0 或 BSD-3-Clause）、defusedxml（PSF）、waitress（ZPL-2.1）。传递依赖与准确版本以 requirements-lock.txt 和安装发行包内 LICENSE 为准；浏览器开发测试使用 Playwright（Apache-2.0）。

软件依赖许可不授予任何平台数据访问、商业展示或再分发权。接入来源由使用者核验允许用途。最终商业发布应对锁定依赖进行完整许可证与漏洞审查。
