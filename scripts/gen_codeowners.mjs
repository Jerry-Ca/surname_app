#!/usr/bin/env node
/**
 * 从 docs/collaboration/team.json 生成 .github/CODEOWNERS。
 *
 * 用法：node scripts/gen_codeowners.mjs [--check]
 *   --check  只校验生成结果是否与当前文件一致（CI 用），不写文件
 *
 * 注意：CODEOWNERS 里同一路径多条规则时**最后一条生效**，
 * 因此本脚本按路径层级从浅到深输出，保证最具体的规则胜出。
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const TEAM_FILE = join(ROOT, 'docs', 'collaboration', 'team.json')
const TARGET = join(ROOT, '.github', 'CODEOWNERS')

const team = JSON.parse(readFileSync(TEAM_FILE, 'utf8'))
const fallback = team.fallback_handle

function handleFor(member) {
  const handle = (member.github || '').replace(/^@/, '').trim()
  return handle ? `@${handle}` : `@${fallback}`
}

/** docs/** → /docs/ ；README.md → /README.md */
function toPattern(glob) {
  if (glob.endsWith('/**')) return `/${glob.slice(0, -3)}/`
  return `/${glob}`
}

const rules = []
for (const member of team.members) {
  for (const glob of member.paths ?? []) {
    rules.push({ glob, pattern: toPattern(glob), owner: handleFor(member), role: member.role })
  }
}
// 浅路径在前，深路径在后（后者覆盖前者）
rules.sort((a, b) => a.pattern.split('/').length - b.pattern.split('/').length)

const missingHandles = team.members.filter((m) => !(m.github || '').trim())

const lines = [
  '# 由 scripts/gen_codeowners.mjs 从 docs/collaboration/team.json 生成，请勿手改。',
  '# 修改归属：先改 team.json，再运行 node scripts/gen_codeowners.mjs',
  '#',
  `# 团队成员尚未填写 GitHub 账号：${missingHandles.map((m) => m.role).join('、') || '（全部已填写）'}`,
  `# 未填写的角色，其目录暂时由 @${fallback} 代为评审。`,
  '',
  `*  @${fallback}`,
  '',
]

for (const rule of rules) {
  lines.push(`${rule.pattern.padEnd(34)} ${rule.owner}   # ${rule.role} · ${rule.glob}`)
}
lines.push('')

const content = lines.join('\n')
const current = existsSync(TARGET) ? readFileSync(TARGET, 'utf8') : null

if (process.argv.includes('--check')) {
  if (current !== content) {
    console.error('CODEOWNERS 与 team.json 不一致：请运行 node scripts/gen_codeowners.mjs 后提交。')
    process.exit(1)
  }
  console.log('CODEOWNERS 与 team.json 一致。')
  process.exit(0)
}

writeFileSync(TARGET, content, 'utf8')
console.log(`已生成 ${TARGET}`)
console.log(`规则 ${rules.length} 条；未填写 GitHub 账号的角色：${missingHandles.map((m) => m.role).join('、') || '无'}`)
if (missingHandles.length) {
  console.log('提示：附录二要求收集 5 人 Git 账号。填进 team.json 后重新运行本脚本即可。')
}