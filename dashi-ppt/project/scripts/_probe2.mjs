import { listLayouts, contentShapeFromPresentation } from './workflow/layout-query.mjs';

const THEME = 'theme11';
const ROLES = ['cover','statement','breakdown','transition','context','metrics','trend','comparison','distribution','relationship','case','image','process','risks','observation','ambient','actions','result','team','closing'];

function shapeForItemCount(n) {
  const items = [];
  for (let i = 0; i < n; i++) {
    items.push({ label: `item${i+1}`, value: i + 1, displayValue: String(i + 1), unit: '个' });
  }
  const presentation = {
    title: '测试标题',
    titleShort: '测试',
    summary: '摘要',
    takeaway: '要点',
    items,
  };
  return contentShapeFromPresentation(presentation);
}

const report = [];
for (const role of ROLES) {
  let maxFit = 0;
  let bestLayouts = [];
  let detail = [];
  for (let n = 1; n <= 16; n++) {
    const shape = shapeForItemCount(n);
    let cands = [];
    try {
      cands = listLayouts({ theme: THEME, role, contentShape: shape, limit: 80 });
    } catch (e) {
      cands = [];
    }
    if (cands.length > 0) {
      maxFit = n;
      bestLayouts = cands.map(c => c.layout);
      detail = cands.map(c => {
        const arr = (c.arrayMeta || []).find(a => a.role === 'item' || a.role === 'stat' || a.role === 'point');
        return `${c.layout}(max=${arr?.maxCount ?? '?'})`;
      });
    } else {
      break;
    }
  }
  report.push({ role, maxItemFit: maxFit, layouts: [...new Set(bestLayouts)], detail });
}

console.log(JSON.stringify(report, null, 2));
