/* 仅测试使用：冻结的前端基线，不随产品展示模块改动。 */
const fs = require('node:fs');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const source = execFileSync('git', ['show', '497fd1c:src/mi_fitness_mcp/web_assets/static/js/health-views.js'], {encoding:'utf8'});
const context = {module:{exports:{}}};
vm.runInNewContext(source, context);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const model = context.module.exports.build(input.kind, input.rows, input.range);
process.stdout.write(JSON.stringify({cards:model.cards.map(c=>c.raw ?? null), points:model.points,
  references:Object.fromEntries(model.references.map(r=>[r.key,r.value])), coverage:model.coverage, stride:model.stride, count:model.records.length}));
