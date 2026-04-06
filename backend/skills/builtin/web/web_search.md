---
name: web_search
category: web
description: web_search 和 web_fetch 使用指南
---

# Web 搜索和使用指南

## When to Use
当需要搜索互联网信息或获取网页内容时使用此 Skill。

## web_search 工具

### 使用场景
- 搜索最新新闻或资讯
- 查找技术文档或教程
- 获取市场价格、统计数据
- 搜索解决方案或答案

### 使用方法
使用 `web_search` 工具，输入搜索关键词：
```
web_search: Python 异步编程教程
```

### 搜索技巧
1. **使用精确关键词**: "Python asyncio tutorial" 比 "Python" 更好
2. **限定范围**: "site:github.com Python" 搜索 GitHub
3. **排除词**: "-广告" 可以排除推广内容
4. **时间限定**: "2024 Python new features" 获取最新内容

## web_fetch 工具

### 使用场景
- 获取特定网页的完整内容
- 提取网页中的图片、文件
- 阅读长文章或文档

### 使用方法
使用 `web_fetch` 工具，输入完整 URL：
```
web_fetch: https://docs.python.org/3/library/asyncio.html
```

### URL 格式
- 标准: `https://example.com/page`
- 带参数: `https://example.com/search?q=keyword`
- 中文 URL: 需要 URL 编码

## 常见问题

### 搜索结果不准确
- 尝试不同的关键词组合
- 使用更具体的术语
- 添加地点或时间限定

### 网页获取失败
- 检查 URL 是否正确
- 确认网站是否可访问
- 尝试使用 http:// 而非 https://

### 内容被截断
- 长文章会被截断，可分段获取
- 关注关键段落，必要时手动访问

## 示例工作流

1. 搜索问题: `web_search: Python asyncio best practices`
2. 获取详情: `web_fetch: <找到的相关文章URL>`
3. 综合回答用户问题
