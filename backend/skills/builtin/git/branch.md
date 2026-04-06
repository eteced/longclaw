---
name: git_branch
category: git
description: Git 分支操作指南
---

# Git 分支操作

## When to Use
当需要创建、切换、合并或删除 Git 分支时使用此 Skill。

## Procedures

### 查看分支
```bash
git branch              # 本地分支
git branch -a           # 所有分支（包括远程）
git branch -r           # 远程分支
```

### 创建分支
```bash
git branch <branch_name>           # 创建新分支
git checkout -b <branch_name>       # 创建并切换
git switch -c <branch_name>        # 现代方式创建并切换
```

### 切换分支
```bash
git checkout <branch_name>
git switch <branch_name>
```

### 合并分支
```bash
git checkout <target_branch>
git merge <source_branch>
```

### 删除分支
```bash
git branch -d <branch_name>        # 安全删除
git branch -D <branch_name>        # 强制删除
git push origin --delete <branch>  # 删除远程分支
```

### 更新分支
```bash
git fetch --all
git pull origin <branch_name>
```
