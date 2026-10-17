# scripts/ — 脚本与工具

主责：见下表。跨模块脚本改动请在 PR 中 @ 对应主责人。

| 脚本 | 用途 | 主责 | 谁会用 |
| --- | --- | --- | --- |
| `validate_data.py` | 数据校验（编号规则、必填字段、状态枚举、年份合法性） | A | B 交付前自检；CI 的 `data-check` 作业 |
| `import_data.py` | 导入 `data/verified/` 的已核对数据；先本地校验再调 `POST /api/admin/import` | C | B 交付数据、C 在服务器导入 |
| `backup_db.py` | PostgreSQL 备份（带时间戳 + sha256 校验和） | C | C 每天备份、E 部署时配置定时任务 |
| `restore_db.py` | 从 dump 恢复并输出行数统计 | C | C 验证可维护性、演示前兜底 |
| `dev.sh` | 本地一键启动（数据自检 → 后端 → 前端） | A | 全员 |
| `seed_github.mjs` | 创建/更新标签、里程碑与 30 张任务卡 | A | A 在 Day1 执行一次 |
| `gen_codeowners.mjs` | 从 `docs/collaboration/team.json` 生成 `.github/CODEOWNERS` | A | 收集到成员账号后执行 |
| `setup_repo.sh` | 合并策略 + `main` 分支保护 + 调用上面两个脚本 | A | A 在 Day1 执行一次 |

## 常用命令

```bash
python scripts/validate_data.py --path data                 # 数据自检（CI 同款）
python scripts/import_data.py --file data/verified/evidences.csv --operator B     # 导入前干跑
node scripts/seed_github.mjs                                # GitHub 看板干跑
node scripts/gen_codeowners.mjs                             # 重新生成 CODEOWNERS
bash scripts/dev.sh                                         # 本地一键启动
```

## 约束

- `validate_data.py` 必须只依赖 Python 标准库：CI 的 `data-check` 作业不安装第三方包。
- 导入数据只能通过 `import_data.py`（它内部调用契约中的管理接口），不允许写第二个写库入口。
- 脚本里不得出现任何密钥；连接信息一律来自环境变量或 `.env`。
- 新增脚本请同步更新本表，并在 `docs/collaboration/tasks.json` 对应任务的交付物中登记。