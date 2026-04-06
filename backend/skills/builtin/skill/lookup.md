---
name: skill_lookup
category: skill
description: 如何使用 skill_lookup 工具检索 Skill 知识库
---

# Skill 检索指南

## When to Use
当你不确定如何执行某个操作时，先使用 `skill_lookup` 工具检索 Skill 获取操作指南。

## 使用场景

### 操作前检索
- 不确定如何执行 Git 操作 → 先 `skill_lookup: git`
- 需要从 GitHub 下载文件 → 先 `skill_lookup: github clone`
- 需要批量处理文件 → 先 `skill_lookup: find grep`
- 执行危险删除操作前 → 先 `skill_lookup: dangerous`

### 问题诊断
- 遇到陌生错误信息 → 搜索相关 Skill
- 不确定命令参数 → 检索对应 Skill

## 使用方法

使用 `skill_lookup` 工具进行检索：
```
skill_lookup: github clone
```

系统会返回相关的 Skill 列表及其描述，帮助你找到最佳操作方式。

## 检索策略

1. **关键词要简洁**: "git clone" 比 "如何从 GitHub 克隆仓库" 更有效
2. **使用英文**: 很多 Skill 使用英文关键词
3. **组合搜索**: 如 "web search" 可以找到搜索相关 Skill
4. **分类检索**: "shell dangerous" 找到危险命令警告

## 可用 Skill 分类

| 分类 | 包含内容 |
|------|----------|
| git | clone, branch, commit, merge |
| shell | find, grep, sed, awk, dangerous |
| web | search, fetch, API 调用 |
| python | pip, venv, package |
| skill | 如何使用 skill_lookup |

## 工作流示例

```
用户: 帮我从 GitHub 下载这个仓库的代码
↓
Agent: 使用 skill_lookup("github clone")
↓
返回: git_clone skill 的使用方法
↓
Agent: 根据 skill 内容执行 git clone
```
