#!/usr/bin/env node
/**
 * 一次性创建 GitHub 上的标签、里程碑与 30 张任务卡。
 *
 *   node scripts/seed_github.mjs                        干跑：只打印将要创建的内容
 *   node scripts/seed_github.mjs --apply                实际创建（需要 gh 已登录）
 *   node scripts/seed_github.mjs --apply --reassign     已存在的 issue 也更新指派与标签
 *
 * 幂等：已存在的标签会被更新颜色与描述；已存在的里程碑与 issue 默认跳过（按标题匹配）。
 * 团队成员的 GitHub 账号填进 team.json 后，用 --reassign 一次把指派改回正确的人。
 * 未填账号的角色（如当前的 A/D/E）不指派，也不会落到兜底账号上——兜底只用于 CODEOWNERS。
 * 全部通过 gh api + stdin JSON 调用，避免中文参数在 Windows 上的编码问题。
 */

import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const APPLY = process.argv.includes('--apply')
const REASSIGN = process.argv.includes('--reassign')
const DRY_RUN = !APPLY

const team = JSON.parse(readFileSync(join(ROOT, 'docs', 'collaboration', 'team.json'), 'utf8'))
const { milestones, tasks } = JSON.parse(readFileSync(join(ROOT, 'docs', 'collaboration', 'tasks.json'), 'utf8'))
const { labels } = JSON.parse(readFileSync(join(ROOT, 'docs', 'collaboration', 'labels.json'), 'utf8'))

const REPO = team.repo

// 在 main() 里填充：已接受的协作者 / 待接受的邀请
let collaborators = new Set()
let pendingInvites = new Set()

function gh(args, { input } = {}) {
  try {
    const result = execFileSync('gh', args, {
      encoding: 'utf8',
      input,
      stdio: input === undefined ? ['ignore', 'pipe', 'pipe'] : ['pipe', 'pipe', 'pipe'],
      maxBuffer: 32 * 1024 * 1024,
    })
    return (result ?? '').trim()
  } catch (error) {
    const stderr = (error.stderr ?? '').toString().trim()
    const stdout = (error.stdout ?? '').toString().trim()
    // gh 把 API 的具体校验原因写在 stdout 的 JSON 里，两个都要留下
    throw new Error([stderr, stdout].filter(Boolean).join('\n').slice(0, 1200) || error.message)
  }
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
  return handle || null
}

/** 未填账号的角色不指派（不落到兜底账号上，避免把 18 张卡指派给并非该角色的人） */
function assigneesFor(role) {
  const handle = handleFor(role)
  if (!handle) return []
  // 未接受协作者邀请的账号无法被指派（GitHub 会返回 422），此时保持未指派
  if (!collaborators.has(handle)) return []
  return [handle]
}

function ownerLabel(role) {
  const handle = handleFor(role)
  if (!handle) return '（账号待定，暂不指派）'
  if (!collaborators.has(handle)) {
    return pendingInvites.has(handle) ? `（@${handle} 邀请待接受，暂不指派）` : `（@${handle} 不是仓库协作者，暂不指派）`
  }
  return `@${handle}`
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
  // 标题 → issue 编号，用于跳过已存在与 --reassign 回填指派
  const existingIssues = new Map()
  for (const line of gh(['api', `repos/${REPO}/issues?state=all&per_page=100`, '--paginate', '--jq', '.[] | [.number, .title] | @tsv']).split('\n')) {
    const [number, ...title] = line.split('\t')
    if (number && title.length) existingIssues.set(title.join('\t').trim(), Number(number))
  }

  // 已接受的协作者与待接受的邀请（未接受邀请的账号不能被指派，否则 422）
  collaborators = new Set(
    gh(['api', `repos/${REPO}/collaborators?per_page=100`, '--jq', '.[].login']).split('\n').map((s) => s.trim()).filter(Boolean),
  )
  pendingInvites = new Set(
    gh(['api', `repos/${REPO}/invitations?per_page=100`, '--jq', '.[].invitee.login']).split('\n').map((s) => s.trim()).filter(Boolean),
  )
  if (pendingInvites.size) {
    console.log(`待接受的协作者邀请：${[...pendingInvites].map((h) => '@' + h).join('、')}（接受后才能被指派）`)
  }

  const summary = { labels: 0, milestones: 0, issues: 0, skipped: 0, updated: 0 }

  // ---- 标签 ----
  for (const label of labels) {
    const exists = existingLabels.has(label.name)
    if (!exists) summary.labels += 1
    console.log(`${exists ? '更新' : '创建'}标签  ${label.name.padEnd(22)} ${label.description}`)
    if (!DRY_RUN) {
      // label 名字里的斜杠必须保持未编码：GitHub 对 %2F 会返回 404（2026-10-17 实测）
      if (exists) ghWrite('PATCH', `repos/${REPO}/labels/${label.name}`, label)
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
    const payload = {
      title,
      body: issueBody(task),
      labels: [task.type, `owner/${task.owner}`, `day/${task.day}`, `prio/${task.priority}`],
      assignees: assigneesFor(task.owner),
    }
    if (milestoneNumber[task.milestone]) payload.milestone = milestoneNumber[task.milestone]

    const existingNumber = existingIssues.get(title)
    if (existingNumber) {
      if (!REASSIGN) {
        summary.skipped += 1
        console.log(`跳过 issue   ${title}（#${existingNumber}）`)
        continue
      }
      summary.updated += 1
      console.log(`更新 issue   ${title}  → ${ownerLabel(task.owner)} / ${task.milestone}`)
      if (!DRY_RUN) ghWrite('PATCH', `repos/${REPO}/issues/${existingNumber}`, payload)
      continue
    }

    summary.issues += 1
    console.log(`创建 issue   ${title}  → ${ownerLabel(task.owner)} / ${task.milestone}`)
    if (!DRY_RUN) ghWrite('POST', `repos/${REPO}/issues`, payload)
  }

  console.log('')
  if (DRY_RUN) {
    console.log(
      `干跑完成：将创建标签 ${summary.labels}、里程碑 ${summary.milestones}、issue ${summary.issues}` +
        `（已存在跳过 ${summary.skipped}${REASSIGN ? `，将更新 ${summary.updated}` : ''}）`,
    )
    console.log('确认无误后运行：node scripts/seed_github.mjs --apply')
  } else {
    console.log(
      `完成：新建标签 ${summary.labels}、里程碑 ${summary.milestones}、issue ${summary.issues}` +
        `（跳过已存在 ${summary.skipped}，更新 ${summary.updated}）`,
    )
  }
}

main()