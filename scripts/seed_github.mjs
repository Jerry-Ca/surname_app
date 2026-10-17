#!/usr/bin/env node
/**
 * 一次性创建 GitHub 上的标签、里程碑与 30 张任务卡。
 *
 *   node scripts/seed_github.mjs            干跑：只打印将要创建的内容
 *   node scripts/seed_github.mjs --apply    实际创建（需要 gh 已登录）
 *
 * 幂等：已存在的标签会被更新颜色与描述；已存在的里程碑与 issue 会跳过（按标题匹配）。
 * 全部通过 gh api + stdin JSON 调用，避免中文参数在 Windows 上的编码问题。
 */

import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const APPLY = process.argv.includes('--apply')
const DRY_RUN = !APPLY

const team = JSON.parse(readFileSync(join(ROOT, 'docs', 'collaboration', 'team.json'), 'utf8'))
const { milestones, tasks } = JSON.parse(readFileSync(join(ROOT, 'docs', 'collaboration', 'tasks.json'), 'utf8'))
const { labels } = JSON.parse(readFileSync(join(ROOT, 'docs', 'collaboration', 'labels.json'), 'utf8'))

const REPO = team.repo

function gh(args, { input } = {}) {
  const result = execFileSync('gh', args, {
    encoding: 'utf8',
    input,
    stdio: input === undefined ? ['ignore', 'pipe', 'pipe'] : ['pipe', 'pipe', 'pipe'],
    maxBuffer: 32 * 1024 * 1024,
  })
  return (result ?? '').trim()
}

function ghJson(path) {
  const raw = gh(['api', path])
  return raw ? JSON.parse(raw) : null
}

function ghWrite(method, path, payload) {
  return gh(['api', '--method', method, path, '--input', '-'], { input: JSON.stringify(payload) })
}

function handleFor(role) {
  const member = team.members.find((m) => m.role === role)
  const handle = (member?.github || '').replace(/^@/, '').trim()
  return handle || team.fallback_handle
}

/** issue 正文 = 七段式的可执行版本（AGENTS.md 第三节） */
function issueBody(task) {
  const files = (task.files ?? []).map((f) => `- \`${f}\``).join('\n')
  const dod = (task.dod ?? []).map((d) => `- [ ] ${d}`).join('\n')
  const deps = (task.depends_on ?? []).length
    ? task.depends_on.map((d) => `\`${d}\``).join('、')
    : '无'

  return `## 任务 ${task.id} · ${task.title}

| 项目 | 内容 |
| --- | --- |
| 主责人 | ${task.owner}（${team.members.find((m) => m.role === task.owner)?.title ?? ''}） |
| 冲刺日 | Day${task.day} |
| 优先级 | ${task.priority} |
| 交付物 | \`${task.deliverable}\` |
| 依赖 | ${deps} |

### 允许修改的文件范围

${files}

超出以上范围请开 issue 请对应主责人修改，不要顺手改别的模块。

### 验收标准（正常 / 空结果 / 异常 / 数据真实性）

${dod}

### 七段式 Prompt（交给 AI 助手时直接复制）

\`\`\`
背景：项目是姓氏郡望与家族迁徙寻根系统，所有历史事实必须有可核验来源。
目标：${task.title}（交付物：${task.deliverable}）
允许修改的文件：${(task.files ?? []).join('、')}
输入和输出：见 docs/api-contract.md 与 docs/data-dictionary.md 对应章节。
验收标准：${(task.dod ?? []).join('；')}
禁止事项：不得编造来源，不得把 API Key 写入前端，不得删除已有数据，不得跨模块改动。
运行方式：见 AGENTS.md 第四节；完成后运行 pytest / npm run build / validate_data.py 并贴出结果。
最终输出：修改文件清单、已完成内容、测试结果、遗留问题。
\`\`\`

### 禁止事项（红线）

- 不得编造古籍、卷次、年代、原文、地点或迁徙事件（[AGENTS.md](https://github.com/${REPO}/blob/main/AGENTS.md)）
- 前端任务不得直接调用模型 API；密钥只走环境变量
- 数据变更必须通过导入脚本或迁移完成，不手工改库

---
契约文档：[api-contract.md](https://github.com/${REPO}/blob/main/docs/api-contract.md) ·
数据字典：[data-dictionary.md](https://github.com/${REPO}/blob/main/docs/data-dictionary.md) ·
验收步骤：[acceptance.md](https://github.com/${REPO}/blob/main/docs/acceptance.md)`
}

function main() {
  console.log(`仓库：${REPO}`)
  console.log(`模式：${DRY_RUN ? '干跑（不会修改任何远程内容）' : '实际创建'}`)
  console.log('')

  const existingLabels = new Set((ghJson(`repos/${REPO}/labels?per_page=100`) ?? []).map((l) => l.name))
  const existingMilestones = ghJson(`repos/${REPO}/milestones?state=all&per_page=100`) ?? []
  const existingIssues = new Set(
    gh(['api', `repos/${REPO}/issues?state=all&per_page=100`, '--paginate', '--jq', '.[].title'])
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
  )

  const summary = { labels: 0, milestones: 0, issues: 0, skipped: 0 }

  // ---- 标签 ----
  for (const label of labels) {
    const exists = existingLabels.has(label.name)
    if (!exists) summary.labels += 1
    console.log(`${exists ? '更新' : '创建'}标签  ${label.name.padEnd(22)} ${label.description}`)
    if (!DRY_RUN) {
      if (exists) ghWrite('PATCH', `repos/${REPO}/labels/${encodeURIComponent(label.name)}`, label)
      else ghWrite('POST', `repos/${REPO}/labels`, label)
    }
  }

  // ---- 里程碑 ----
  const milestoneNumber = {}
  for (const milestone of milestones) {
    const found = existingMilestones.find((m) => m.title === milestone.title)
    milestoneNumber[milestone.title] = found?.number ?? null
    console.log(`${found ? '跳过' : '创建'}里程碑  ${milestone.title}`)
    if (!found) {
      summary.milestones += 1
      if (!DRY_RUN) {
        const created = JSON.parse(
          ghWrite('POST', `repos/${REPO}/milestones`, { title: milestone.title, description: milestone.description }),
        )
        milestoneNumber[milestone.title] = created.number
      }
    }
  }

  // ---- 任务卡 ----
  for (const task of tasks) {
    const title = `[${task.id}] ${task.title}`
    if (existingIssues.has(title)) {
      summary.skipped += 1
      console.log(`跳过 issue   ${title}`)
      continue
    }
    summary.issues += 1
    console.log(`创建 issue   ${title}  → ${handleFor(task.owner)} / ${task.milestone}`)
    if (!DRY_RUN) {
      const payload = {
        title,
        body: issueBody(task),
        labels: [task.type, `owner/${task.owner}`, `day/${task.day}`, `prio/${task.priority}`],
        assignees: [handleFor(task.owner)],
      }
      if (milestoneNumber[task.milestone]) payload.milestone = milestoneNumber[task.milestone]
      ghWrite('POST', `repos/${REPO}/issues`, payload)
    }
  }

  console.log('')
  console.log(
    DRY_RUN
      ? `干跑完成：将创建标签 ${summary.labels}、里程碑 ${summary.milestones}、issue ${summary.issues}（已存在跳过 ${summary.skipped}）`
      : `完成：新建标签 ${summary.labels}、里程碑 ${summary.milestones}、issue ${summary.issues}（跳过已存在 ${summary.skipped}）`,
  )
  if (DRY_RUN) {
    console.log('确认无误后运行：node scripts/seed_github.mjs --apply')
  }
}

main()