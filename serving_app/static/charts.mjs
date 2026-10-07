import {escapeHTML as h, segments, addDays} from './client.mjs';
const number = v => Number(v).toLocaleString('ko-KR', {maximumFractionDigits: 2});
export function renderChart(target, observations, forecasts, from, to) {
  if (!observations.length && !forecasts.length) { target.innerHTML = '<div class="empty">선택한 기간에 표시할 관측·예측 자료가 없습니다.</div>'; return; }
  const W = Math.max(340, target.clientWidth - 26), left = 62, right = W - 22, top = 36, bottom = 222, rainTop = 282, rainBottom = 342;
  const values = [...observations.map(o => o.groundwater_depth_cm), ...forecasts.map(f => f.predicted_depth_cm)];
  const low = Math.min(...values), high = Math.max(...values), padding = Math.max((high - low) * .18, 2);
  const min = Math.max(0, low - padding), max = high + padding;
  const start = Date.parse(from), span = Math.max(86400000, Date.parse(to) - start);
  const x = date => left + (Date.parse(date) - start) / span * (right - left);
  // Depth is measured downward from the surface: larger values appear lower.
  const y = value => top + (value - min) / (max - min) * (bottom - top);
  const maxRain = Math.max(1, ...observations.map(o => o.rainfall_mm));
  const modelGroups = new Map();
  forecasts.forEach(f => { if (!modelGroups.has(f.model.id)) modelGroups.set(f.model.id, []); modelGroups.get(f.model.id).push(f); });
  const colors = ['#9aadff', '#edb8e4', '#f0bc73', '#b8d58a'];
  let svg = `<svg viewBox="0 0 ${W} 381" role="img" aria-label="지하수 깊이와 강수량. 깊이는 아래로 증가합니다. 날짜별 값은 표 보기를 이용하세요."><text x="${left}" y="15" fill="#a2adc0" font-size="11">지표면 기준 깊이 (cm) ↓</text>`;
  for (let i = 0; i <= 4; i++) {
    const value = min + (max - min) * i / 4, py = y(value);
    svg += `<line x1="${left}" y1="${py}" x2="${right}" y2="${py}" stroke="#252e3b" stroke-dasharray="3 5"/><text x="${left - 12}" y="${py + 4}" text-anchor="end" fill="#a2adc0" font-size="10">${number(value)}</text>`;
  }
  svg += `<text x="${left}" y="265" fill="#a2adc0" font-size="11">일 강수량 (mm)</text><line x1="${left}" y1="${rainBottom}" x2="${right}" y2="${rainBottom}" stroke="#30394a"/><text x="${left-12}" y="${rainTop+5}" text-anchor="end" fill="#a2adc0" font-size="10">${number(maxRain)}</text><text x="${left-12}" y="${rainBottom+4}" text-anchor="end" fill="#a2adc0" font-size="10">0</text>`;
  const tickCount = W < 480 ? 3 : 5;
  for (let i = 0; i <= tickCount; i++) {
    const date = addDays(from, Math.round((Date.parse(to) - start) / 86400000 * i / tickCount));
    svg += `<text x="${x(date)}" y="369" text-anchor="middle" fill="#a2adc0" font-size="10">${h(date.slice(5).replace('-', '.'))}</text>`;
  }
  const draw = (rows, key, valueKey, color, dashed = false) => {
    let output = '';
    for (const segment of segments(rows, key)) {
      output += `<polyline points="${segment.map(r => `${x(r[key])},${y(r[valueKey])}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2" ${dashed ? 'stroke-dasharray="6 5"' : ''}/>`;
    }
    rows.forEach(r => {
      const detail = dashed ? `${r[key]} · 예측 ${number(r[valueKey])} cm · 모델 ${r.model.registry_name} v${r.model.registry_version}` : `${r[key]} · 관측 ${number(r[valueKey])} cm · 강수 ${number(r.rainfall_mm)} mm`;
      output += `<circle cx="${x(r[key])}" cy="${y(r[valueKey])}" r="${rows.length > 100 ? 2 : 3}" fill="${color}"/><circle cx="${x(r[key])}" cy="${y(r[valueKey])}" r="9" fill="transparent" data-tooltip="${h(detail)}"><title>${h(detail)}</title></circle>`;
    });
    return output;
  };
  const barWidth = Math.max(1, Math.min(10, (right-left)/(span/86400000+1)*.6));
  observations.forEach(o => {
    const height = o.rainfall_mm/maxRain*(rainBottom-rainTop);
    svg += `<rect x="${x(o.observed_date)-barWidth/2}" y="${rainBottom-height}" width="${barWidth}" height="${height}" rx="1" fill="#556fa8" data-tooltip="${h(o.observed_date)} · 강수 ${number(o.rainfall_mm)} mm"><title>${h(o.observed_date)} · ${number(o.rainfall_mm)} mm</title></rect>`;
  });
  svg += draw(observations, 'observed_date', 'groundwater_depth_cm', '#69cecb');
  let modelIndex = 0;
  for (const group of modelGroups.values()) svg += draw(group, 'target_date', 'predicted_depth_cm', colors[modelIndex++ % colors.length], true);
  target.innerHTML = svg + '</svg><div class="chart-tooltip" aria-live="polite"></div>' + (modelGroups.size ? `<div class="legend" style="padding:0 10px 12px">${[...modelGroups.values()].map((g,i) => `<span><i class="forecast" style="border-color:${colors[i%colors.length]}"></i>${h(g[0].model.registry_name)} v${h(g[0].model.registry_version)}</span>`).join('')}</div>` : '');
  target.onpointerover = event => { const point = event.target.closest('[data-tooltip]'); if (point) target.querySelector('.chart-tooltip').textContent = point.dataset.tooltip; };
}
