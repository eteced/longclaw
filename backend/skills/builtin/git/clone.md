---
name: git_clone
category: git
description: 如何从 GitHub 克隆仓库和拉取文件
---

# Git 克隆和文件拉取

## When to Use
当需要从 GitHub 获取代码或文件时使用此 Skill。

## Procedures
1. 使用 `git clone <repo_url>` 克隆整个仓库
2. 使用 `git pull` 拉取最新代码
3. 使用 `gh repo clone <owner/repo>` 通过 GitHub CLI 克隆

## Examples
```bash
git clone https://github.com/owner/repo.git
gh repo clone owner/repo -- --depth 1
```

## URL 格式
- HTTPS: `https://github.com/owner/repo`
- SSH: `git@github.com:owner/repo.git`

## 单文件下载
使用 GitHub 的 raw 服务或 `gh api` 获取单个文件：
```bash
curl -L https://raw.githubusercontent.com/owner/repo/branch/path/to/file
```
